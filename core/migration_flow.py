from typing import Dict, Any, List, Optional, Callable
import time

from .ssh_client import SSHClient
from .proxmox import (
    qm_create,
    qm_importdisk,
    qm_importdisk_with_progress,
    qm_set_scsi,
    qm_set_boot,
    qm_start,
    qm_set_uefi,
    parse_importdisk_disk_id,
    qm_attach_scsi,
    qm_attach_disk,
)
from .transfer import (
    compute_dest_dir,
    copy_vmdk_from_esxi,
    copy_vmdk_flat_with_progress,
    guess_vmdk_data_rel,
    resolve_vmdk_data_rel,
    qemu_img_convert,
)
from .esxi_import import (
    write_esxi_password_file,
    esxi_find_vmid_by_vmx,
    esxi_create_snapshot,
    esxi_find_snapshot_id_by_name,
    esxi_remove_snapshot,
    esxi_get_vm_firmware,
    esxi_get_vm_guestos,
    map_guestos_to_proxmox,
)


def compose_plan(vmid: int, name: str, memory: int, cores: int, net0: str, vmdk_path: str, storage: str) -> List[str]:
    """Restituisce l'elenco dei comandi che verranno eseguiti su Proxmox."""
    return [
        f"qm create {vmid} --name {name} --memory {memory} --cores {cores} --net0 {net0}",
        f"qm importdisk {vmid} \"{vmdk_path}\" {storage}",
        # Nota: dopo importdisk, l'identificatore del disco dipende dall'output (es. {storage}:vm-{vmid}-disk-0)
        f"qm set {vmid} --scsihw virtio-scsi-pci --scsi0 {storage}:vm-{vmid}-disk-0",
        f"qm set {vmid} --boot order=scsi0",
        f"qm start {vmid}",
    ]


def execute_plan(ssh: SSHClient, vmid: int, name: str, memory: int, cores: int, net0: str, vmdk_path: str, storage: str) -> List[str]:
    """Esegue i comandi su Proxmox nell'ordine previsto. Ritorna log dei comandi eseguiti."""
    logs: List[str] = []
    code, out, err = qm_create(ssh, vmid, name, memory, cores, net0)
    logs.append(f"qm create -> code={code}\n{out}\n{err}")
    code, out, err = qm_importdisk(ssh, vmid, vmdk_path, storage)
    logs.append(f"qm importdisk -> code={code}\n{out}\n{err}")
    # Assunzione: disco sarà {storage}:vm-{vmid}-disk-0 (verificare dall'output reale)
    disk_id = parse_importdisk_disk_id(out) or f"{storage}:vm-{vmid}-disk-0"
    code, out, err = qm_set_scsi(ssh, vmid, disk_id)
    logs.append(f"qm set --scsi0 -> code={code}\n{out}\n{err}")
    code, out, err = qm_set_boot(ssh, vmid, "scsi0")
    logs.append(f"qm set --boot -> code={code}\n{out}\n{err}")
    code, out, err = qm_start(ssh, vmid)
    logs.append(f"qm start -> code={code}\n{out}\n{err}")
    return logs


def execute_full_migration(
    ssh: SSHClient,
    esxi_host: str,
    esxi_user: str,
    esxi_pass: str,
    selected_vm_info: Dict[str, Any],
    vmid: int,
    name: str,
    memory: int,
    cores: int,
    net0: str,
    storage: str,
    custom_dest: Optional[str],
    use_uefi: bool,
    selected_disk_indexes: Optional[List[int]] = None,
    use_convert: bool = False,
    convert_fmt: str = "qcow2",
    use_esxi_snapshot: bool = False,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    guest_os: Optional[str] = None,
    windows_link_down: bool = False,
) -> List[str]:
    logs: List[str] = []
    # 1) Copia VMDK su Proxmox
    disks = selected_vm_info.get("disks", [])
    if not disks:
        raise RuntimeError("Nessun disco disponibile per la VM selezionata")
    # selezione multipla
    if selected_disk_indexes:
        disk_list = [disks[i] for i in selected_disk_indexes if 0 <= i < len(disks)]
    else:
        disk_list = [disks[0]]
    dest_dir = compute_dest_dir(ssh, storage, name, custom_dest)
    logs.append(f"Destinazione: {dest_dir}")

    # Assicura che il file password ESXi sia scritto su Proxmox per evitare password inline
    try:
        write_esxi_password_file(ssh, esxi_pass)
        logs.append("Password ESXi scritta su /root/esxi_pass.txt (Proxmox)")
    except Exception as e:
        logs.append(f"Errore scrittura password ESXi: {e}")

    power = str(selected_vm_info.get("power", "") or "")
    if power == "poweredOn" and not use_esxi_snapshot:
        raise RuntimeError("VM accesa su ESXi: abilita Snapshot oppure spegni la VM prima di migrare")

    # ---- Rilevamento OS guest e profilo Proxmox ----
    # Se guest_os non fornito, prova a leggerlo dal .vmx ESXi.
    if not guest_os:
        cfg = selected_vm_info.get("config", {}) if isinstance(selected_vm_info, dict) else {}
        cfg_ds = (cfg.get("datastore") or "").strip()
        cfg_vmx = (cfg.get("path") or "").strip()
        if cfg_ds and cfg_vmx:
            try:
                guest_os = esxi_get_vm_guestos(
                    ssh, esxi_host, esxi_user, "/root/esxi_pass.txt", cfg_ds, cfg_vmx
                )
                logs.append(f"guestOS rilevato dal .vmx ESXi: '{guest_os or '(vuoto)'}'")
            except Exception as e:
                logs.append(f"Impossibile leggere guestOS dal .vmx: {e}")
                guest_os = ""

    profile = map_guestos_to_proxmox(guest_os or "")
    is_windows = bool(profile.get("is_windows"))
    nic_model = profile.get("nic_model", "virtio")
    bus = profile.get("bus", "scsi")
    ostype = profile.get("ostype", "other")
    machine = profile.get("machine") if use_uefi else None  # q35 solo per UEFI
    scsihw = profile.get("scsihw", "virtio-scsi-single")
    bios = "ovmf" if use_uefi else None
    logs.append(
        f"Profilo VM: ostype={ostype} bus={bus} nic={nic_model} "
        f"machine={machine or 'default'} bios={bios or 'default'} "
        f"is_windows={is_windows}"
    )

    # Adatta net0: sostituisci modello se l'utente ha passato 'virtio' ma il
    # profilo richiede e1000 (Windows al primo boot, niente driver netkvm).
    net0_final = net0 or ""
    if is_windows and net0_final.lower().startswith("virtio"):
        net0_final = "e1000" + net0_final[len("virtio"):]
        logs.append(f"NIC: virtio → e1000 (Windows primo boot)")
    if is_windows and windows_link_down and "link_down" not in net0_final:
        # link_down=1 utile per evitare conflitti AD/DC al primo boot
        sep = "," if "," in net0_final else ","
        net0_final = net0_final + f"{sep}link_down=1"
        logs.append("NIC: link_down=1 (Windows DC isolato)")

    snapshot_vmid: Optional[int] = None
    snapshot_id: Optional[int] = None
    snapshot_name: Optional[str] = None

    if use_esxi_snapshot:
        cfg = selected_vm_info.get("config", {}) if isinstance(selected_vm_info, dict) else {}
        cfg_ds = (cfg.get("datastore") or "").strip()
        cfg_vmx = (cfg.get("path") or "").strip()
        if not cfg_ds or not cfg_vmx:
            raise RuntimeError("Dati VMX non disponibili: impossibile creare snapshot ESXi")
        snapshot_vmid = esxi_find_vmid_by_vmx(ssh, esxi_host, esxi_user, "/root/esxi_pass.txt", cfg_ds, cfg_vmx)
        if snapshot_vmid is None:
            raise RuntimeError(f"Impossibile trovare VMID ESXi per VMX {cfg_ds}/{cfg_vmx}")
        snapshot_name = f"vm-migration-tool-{snapshot_vmid}-{int(time.time())}"
        if progress_cb:
            try:
                progress_cb(0.0, "Snapshot: creazione snapshot ESXi…")
            except Exception:
                pass
        try:
            esxi_create_snapshot(
                ssh,
                esxi_host,
                esxi_user,
                "/root/esxi_pass.txt",
                snapshot_vmid,
                snapshot_name,
                "Snapshot temporanea per migrazione",
                quiesce=True,
                memory=False,
            )
        except Exception as e:
            logs.append(f"Snapshot ESXi con quiesce fallita, retry senza quiesce: {e}")
            esxi_create_snapshot(
                ssh,
                esxi_host,
                esxi_user,
                "/root/esxi_pass.txt",
                snapshot_vmid,
                snapshot_name,
                "Snapshot temporanea per migrazione",
                quiesce=False,
                memory=False,
            )
        snapshot_id = esxi_find_snapshot_id_by_name(
            ssh, esxi_host, esxi_user, "/root/esxi_pass.txt", snapshot_vmid, snapshot_name
        )
        if snapshot_id is None:
            raise RuntimeError("Snapshot creata ma Snapshot Id non trovato (non posso fare cleanup in sicurezza)")
        logs.append(f"Snapshot ESXi creata: vmid={snapshot_vmid} snapshot_id={snapshot_id} name={snapshot_name}")

    # 2) Creazione VM su Proxmox (con ostype/machine/bios/scsihw già al create)
    code, out, err = qm_create(
        ssh,
        vmid,
        name,
        memory,
        cores,
        net0_final,
        ostype=ostype,
        machine=machine,
        bios=bios,
        cpu="host",
        scsihw=scsihw,
    )
    logs.append(f"qm create -> code={code}\n{out}\n{err}")
    if code != 0:
        # Interrompi il flusso se la creazione VM fallisce (evita importdisk/set su VM inesistente)
        raise RuntimeError(f"Creazione VM fallita (code={code}): {err or out}")
    else:
        # Feedback immediato in UI dopo creazione VM
        if progress_cb:
            try:
                progress_cb(0.0, f"Creazione VM {vmid} completata, preparo fasi successive…")
            except Exception:
                pass

    # 2b) UEFI subito dopo create (così l'efidisk si crea su VM già configurata
    # con bios=ovmf e abbiamo i certificati 2023k pre-enrollati).
    if use_uefi:
        code_u, out_u, err_u = qm_set_uefi(ssh, vmid, storage)
        logs.append(f"qm set UEFI -> code={code_u}\n{out_u}\n{err_u}")
        if code_u != 0:
            logs.append(f"AVVISO: configurazione UEFI fallita (code={code_u})")

    copied_disks: List[dict] = []

    # 3) Copia dischi su Proxmox (con snapshot ESXi attiva, se abilitata)
    for idx, d in enumerate(disk_list):
        vmdk_relpath = d.get("path", "")
        datastore = d.get("datastore", "")
        capacity = int(d.get("capacity", 0))
        # calcolo nome del file dati reale su ESXi (flat, delta o sesparse)
        flat_rel = resolve_vmdk_data_rel(ssh, esxi_host, esxi_user, "/root/esxi_pass.txt", datastore, vmdk_relpath)
        # copia con progress
        dest_flat = copy_vmdk_flat_with_progress(
            ssh,
            esxi_host,
            esxi_user,
            esxi_pass,
            datastore,
            flat_rel,
            dest_dir,
            capacity,
            progress_cb,
        )
        logs.append(f"Copia flat completata: {dest_flat}")
        # copia descriptor (piccolo)
        copy_vmdk_from_esxi(ssh, esxi_host, esxi_user, esxi_pass, datastore, vmdk_relpath, dest_dir)
        vmdk_local = f"{dest_dir}/" + vmdk_relpath.split("/")[-1]
        copied_disks.append({"idx": idx, "vmdk_local": vmdk_local})

    if snapshot_vmid is not None and snapshot_id is not None:
        if progress_cb:
            try:
                progress_cb(0.0, "Snapshot: rimozione snapshot ESXi…")
            except Exception:
                pass
        esxi_remove_snapshot(ssh, esxi_host, esxi_user, "/root/esxi_pass.txt", snapshot_vmid, snapshot_id)
        logs.append("Snapshot ESXi rimossa")

    from .proxmox import storage_supports_images
    if not storage_supports_images(ssh, storage):
        raise RuntimeError(
            f"Lo storage '{storage}' non supporta il contenuto 'images'. Seleziona uno storage idoneo (es. 'local-lvm') o abilita 'images' nelle impostazioni dello storage."
        )

    # 4) Conversione/import/attach
    for item in copied_disks:
        idx = int(item["idx"])
        vmdk_local = str(item["vmdk_local"])
        import_source = vmdk_local
        if use_convert:
            if progress_cb:
                try:
                    progress_cb(0.0, f"Convert: avvio conversione {vmdk_local} → {convert_fmt}")
                except Exception:
                    pass
            out_img = f"{dest_dir}/{name}-disk{idx}.{convert_fmt}"
            code_c, out_c, err_c = qemu_img_convert(ssh, vmdk_local, out_img, fmt=convert_fmt, compress=True, progress_cb=progress_cb)
            logs.append(f"qemu-img convert -> code={code_c}\n{out_c}\n{err_c}")
            if code_c == 0:
                import_source = out_img

        if progress_cb:
            try:
                progress_cb(0.0, f"Import: avvio importdisk su storage '{storage}' (formato {convert_fmt})")
            except Exception:
                pass
            start_ts = time.time()

            def _fmt_t(sec: float) -> str:
                s = int(sec)
                return f"{s//60:02d}:{s%60:02d}"

            def _relay(pct: float, msg: str):
                elapsed = max(0.001, time.time() - start_ts)
                eta = 0.0
                if pct > 0.0 and pct < 100.0:
                    eta = elapsed * (100.0 - pct) / pct
                progress_cb(pct, f"{msg} — elapsed {_fmt_t(elapsed)} — ETA {_fmt_t(eta)}")

            code, out, err = qm_importdisk_with_progress(
                ssh, vmid, import_source, storage, _relay, fmt=convert_fmt
            )
        else:
            code, out, err = qm_importdisk(ssh, vmid, import_source, storage, fmt=convert_fmt)
        logs.append(f"qm importdisk (disk {idx}) -> code={code}\n{out}\n{err}")
        disk_id = parse_importdisk_disk_id(out) or f"{storage}:vm-{vmid}-disk-{idx}"
        # Aggancia bus-aware: SATA per Windows (driver nativo), SCSI VirtIO per il resto.
        # Per Linux/altri: discard=on + iothread=1 (richiede virtio-scsi-single).
        code, out, err = qm_attach_disk(
            ssh,
            vmid,
            disk_id,
            index=idx,
            bus=bus,
            scsihw=scsihw,
            discard=True,
            iothread=(bus == "scsi"),
        )
        logs.append(f"qm set --{bus}{idx} -> code={code}\n{out}\n{err}")

    # 5) Pulizia file temporanei (VMDK copiati + eventuale file convertito)
    if progress_cb:
        try:
            progress_cb(0.0, "Cleanup: rimozione file temporanei…")
        except Exception:
            pass
    for item in copied_disks:
        vmdk_local = str(item["vmdk_local"])
        # descriptor .vmdk
        ssh.run(f"rm -f '{vmdk_local}' 2>/dev/null || true")
        # flat/delta (stesso nome base + -flat.vmdk o -delta.vmdk)
        flat_name = guess_vmdk_data_rel(vmdk_local.split("/")[-1])
        flat_path = f"{dest_dir}/{flat_name}"
        ssh.run(f"rm -f '{flat_path}' 2>/dev/null || true")
        # file convertito (se presente)
        idx = int(item["idx"])
        converted = f"{dest_dir}/{name}-disk{idx}.{convert_fmt}"
        ssh.run(f"rm -f '{converted}' 2>/dev/null || true")
        logs.append(f"Cleanup tmp: rimossi file in {dest_dir}")

    # UEFI già configurato prima dell'import (vedi step 2b).
    # Lasciamo questa chiamata come no-op idempotente solo se per qualche motivo
    # use_uefi è True ma il primo tentativo è fallito; non ripetiamo l'enroll
    # certificati per evitare di toccare un efidisk già valido.

    # Boot order coerente col bus scelto (sata0 per Windows, scsi0 per il resto)
    boot_dev = f"{bus}0"
    code, out, err = qm_set_boot(ssh, vmid, boot_dev)
    logs.append(f"qm set --boot order={boot_dev} -> code={code}\n{out}\n{err}")

    # Per VM Windows: monta automaticamente l'ISO virtio-win se presente in
    # local:iso (fallback silenzioso se non c'è). Utile per installare i driver
    # dopo il primo boot.
    if is_windows:
        code_iso, out_iso, err_iso = ssh.run(
            "test -f /var/lib/vz/template/iso/virtio-win.iso && "
            f"qm set {vmid} --ide2 local:iso/virtio-win.iso,media=cdrom || true"
        )
        if "update VM" in (out_iso or ""):
            logs.append(f"ISO virtio-win montata su ide2 -> {out_iso.strip()}")

    code, out, err = qm_start(ssh, vmid)
    logs.append(f"qm start -> code={code}\n{out}\n{err}")
    if progress_cb:
        try:
            # Conclude con progress al 100%
            pct_end = 100.0 if code == 0 else 0.0
            msg_end = "Avvio VM completato" if code == 0 else f"Avvio VM fallito (code={code})"
            progress_cb(pct_end, msg_end)
        except Exception:
            pass
    return logs
