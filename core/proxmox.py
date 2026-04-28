from typing import Optional, Tuple, List
import re

from .ssh_client import SSHClient
from typing import Callable


def qm_create(
    ssh: SSHClient,
    vmid: int,
    name: str,
    memory: int,
    cores: int,
    net0: str,
    ostype: Optional[str] = None,
    machine: Optional[str] = None,
    bios: Optional[str] = None,
    cpu: Optional[str] = None,
    scsihw: Optional[str] = None,
):
    """
    Crea una VM su Proxmox. Tutti i campi opzionali (ostype, machine, bios, cpu,
    scsihw) sono passati come flag se valorizzati. Impostarli al create evita
    qm set successivi e permette a Proxmox di applicare i default OS-aware.
    """
    parts = [
        f"qm create {vmid}",
        f"--name {name}",
        f"--memory {memory}",
        f"--cores {cores}",
        f"--net0 {net0}",
    ]
    if ostype:
        parts.append(f"--ostype {ostype}")
    if machine:
        parts.append(f"--machine {machine}")
    if bios:
        parts.append(f"--bios {bios}")
    if cpu:
        parts.append(f"--cpu {cpu}")
    if scsihw:
        parts.append(f"--scsihw {scsihw}")
    return ssh.run(" ".join(parts))


def qm_importdisk(
    ssh: SSHClient,
    vmid: int,
    vmdk_path: str,
    storage: str,
    fmt: str = "qcow2",
):
    """
    Importa un disco. Forza il formato di destinazione (default qcow2) per
    evitare che lo storage scriva in raw quando supporta entrambi i formati.
    """
    fmt_flag = f" --format {fmt}" if fmt else ""
    cmd = f"qm importdisk {vmid} \"{vmdk_path}\" {storage}{fmt_flag}"
    return ssh.run(cmd)


def qm_importdisk_with_progress(
    ssh: SSHClient,
    vmid: int,
    vmdk_path: str,
    storage: str,
    progress_cb: Callable[[float, str], None] | None = None,
    fmt: str = "qcow2",
):
    """
    Esegue qm importdisk con streaming e parsing delle righe di avanzamento.
    Usa stdbuf -oL per forzare line-buffering (qm importdisk emette progress
    su stdout, ma su pipe il buffering di default ritarda l'output).
    Aggiorna progress_cb quando l'output contiene "(NN.NN%)" o il messaggio
    di completamento "successfully imported disk".
    """
    fmt_flag = f" --format {fmt}" if fmt else ""
    cmd = f"stdbuf -oL -eL qm importdisk {vmid} \"{vmdk_path}\" {storage}{fmt_flag}"

    def _relay(pct: float, msg: str):
        if progress_cb:
            progress_cb(pct, f"Import: {msg}")

    return ssh.run_streaming_with_parser(cmd, parse_cb=_relay)


def qm_set_scsi(ssh: SSHClient, vmid: int, disk_id: str, scsihw: str = "virtio-scsi-pci"):
    # Esempio disk_id: "QNAP-IMAGES:vm-120-disk-0"
    cmd = f"qm set {vmid} --scsihw {scsihw} --scsi0 {disk_id}"
    return ssh.run(cmd)


def qm_attach_scsi(ssh: SSHClient, vmid: int, disk_id: str, index: int = 0, scsihw: str = "virtio-scsi-pci"):
    """Mantenuto per retrocompatibilità. Per nuovo codice usare qm_attach_disk."""
    slot = f"scsi{index}"
    cmd = f"qm set {vmid} --scsihw {scsihw} --{slot} {disk_id}"
    return ssh.run(cmd)


def qm_attach_disk(
    ssh: SSHClient,
    vmid: int,
    disk_id: str,
    index: int = 0,
    bus: str = "scsi",
    scsihw: str = "virtio-scsi-single",
    discard: bool = True,
    iothread: bool = True,
):
    """
    Aggancia un disco in modo bus-aware:
    - bus="scsi" → --scsiN (con virtio-scsi-single per supportare iothread)
    - bus="sata" → --sataN (consigliato per Windows al primo boot)
    - bus="ide"  → --ideN
    - bus="virtio" → --virtioN
    Aggiunge discard=on (TRIM) e iothread=1 (solo se SCSI VirtIO single).
    """
    slot = f"{bus}{index}"
    opts: List[str] = []
    if discard:
        opts.append("discard=on")
    # iothread valido solo con virtio-scsi-single (o virtio block device)
    if iothread and (
        (bus == "scsi" and scsihw == "virtio-scsi-single") or bus == "virtio"
    ):
        opts.append("iothread=1")
    opts_str = ("," + ",".join(opts)) if opts else ""

    parts = [f"qm set {vmid}"]
    # scsihw va impostato solo per dischi SCSI; per SATA/IDE/VirtIO è inerte
    if bus == "scsi":
        parts.append(f"--scsihw {scsihw}")
    parts.append(f"--{slot} {disk_id}{opts_str}")
    return ssh.run(" ".join(parts))


def list_storages(ssh: SSHClient) -> List[str]:
    # Usa pvesm status per elencare nomi storage
    code, out, err = ssh.run("pvesm status --verbose || pvesm status")
    names: List[str] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("name"):
            continue
        parts = line.split()
        if parts:
            names.append(parts[0])
    return sorted(set(names))


def list_bridges(ssh: SSHClient) -> List[str]:
    # Elenca interfacce, filtra vmbr*
    code, out, err = ssh.run("ls /sys/class/net")
    bridges = [n for n in out.split() if n.startswith("vmbr")]
    return sorted(set(bridges))


def get_next_vmid(ssh: SSHClient) -> Optional[int]:
    # Usa pvesh se disponibile, altrimenti None
    code, out, err = ssh.run("pvesh get /cluster/nextid 2>/dev/null || echo")
    try:
        return int(out.strip()) if out.strip() else None
    except Exception:
        return None

def storage_supports_images(ssh: SSHClient, storage: str) -> bool:
    """Verifica se lo storage indicato supporta il contenuto 'images'."""
    cmd = (
        f"if awk '/^.*: {storage}$/,/^$/' /etc/pve/storage.cfg | grep -i '^\\s*content' | grep -qi 'images'; then "
        f"  echo YES; "
        f"elif pvesh get /storage/{storage} 2>/dev/null | grep -i 'content' | grep -qi 'images'; then "
        f"  echo YES; "
        f"else echo NO; fi"
    )
    code, out, err = ssh.run(cmd)
    return "YES" in out


def qm_set_boot(ssh: SSHClient, vmid: int, order: str = "scsi0"):
    cmd = f"qm set {vmid} --boot order={order}"
    return ssh.run(cmd)


def qm_start(ssh: SSHClient, vmid: int):
    cmd = f"qm start {vmid}"
    return ssh.run(cmd)


def qm_set_uefi(ssh: SSHClient, vmid: int, storage: str) -> Tuple[int, str, str]:
    """
    Configura UEFI/OVMF: machine=q35, bios=ovmf, efidisk con certificati 2023k.
    Il flag ms-cert=2023k pre-enrolla i certificati Microsoft 2023, evitando
    il warning "UEFI 2011 certificates expire June 2026" su Proxmox >= 8.4.
    """
    code1, out1, err1 = ssh.run(f"qm set {vmid} --machine q35 --bios ovmf")
    efidisk_opts = "efitype=4m,pre-enrolled-keys=1,ms-cert=2023k"
    code2, out2, err2 = ssh.run(f"qm set {vmid} --efidisk0 {storage}:0,{efidisk_opts}")
    # Ritorna lo stato combinato
    return code2 or code1, out1 + out2, err1 + err2


def parse_importdisk_disk_id(output: str) -> Optional[str]:
    """
    Tenta di estrarre l'identificatore del disco creato da qm importdisk.
    Supporta sia storage LVM/Ceph (es. "QNAP-IMAGES:vm-120-disk-0") che storage
    directory (es. "QNAP-IMAGES:120/vm-120-disk-0.raw").
    """
    # Caso esplicito da output qm: "Successfully imported disk as '<VOL>'"
    m = re.search(r"imported\s+disk\s+as\s+'([^']+)'", output, re.IGNORECASE)
    if m:
        return m.group(1)
    # LVM/Ceph: <storage>:vm-<id>-disk-<n>
    m2 = re.search(r"([\w-]+:vm-\d+-disk-\d+)", output)
    if m2:
        return m2.group(1)
    # Directory: <storage>:<id>/vm-<id>-disk-<n>.<ext>
    m3 = re.search(r"([\w-]+:\d+/vm-\d+-disk-\d+\.[A-Za-z0-9]+)", output)
    if m3:
        return m3.group(1)
    return None