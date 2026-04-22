from typing import Tuple, Optional, Callable
import time

from .ssh_client import SSHClient


def ensure_sshpass(ssh: SSHClient) -> None:
    code, out, err = ssh.run("which sshpass || echo MISSING")
    if "MISSING" in out or code != 0:
        ssh.run("apt-get update -y || apt update -y")
        ssh.run("apt-get install -y sshpass")


def storage_mount_exists(ssh: SSHClient, storage: str) -> bool:
    code, out, err = ssh.run(f"test -d /mnt/pve/{storage} && echo OK || echo NO")
    return "OK" in out


def compute_dest_dir(ssh: SSHClient, storage: str, vm_name: str, custom: str | None) -> str:
    if custom and custom.strip():
        return custom.strip()
    if storage_mount_exists(ssh, storage):
        return f"/mnt/pve/{storage}/tmp/{vm_name}"
    # fallback per storage non montati (es. local-lvm)
    return f"/root/tmp/{vm_name}"


def ensure_dir(ssh: SSHClient, path: str) -> None:
    ssh.run(f"mkdir -p '{path}'")


def guess_vmdk_data_rel(vmdk_relpath: str) -> str:
    """
    Determina il nome del file dati associato al descriptor VMDK.
    - Per un descriptor base "disk.vmdk" → "disk-flat.vmdk"
    - Per uno snapshot "disk-000001.vmdk" → "disk-000001-delta.vmdk"
    Nota: su alcuni ambienti VMFS può essere "-sesparse.vmdk" al posto di "-delta".
    In prima istanza restituiamo "-delta" per gli snapshot; il codice di copia
    gestirà eventuali fallback.
    """
    rel = vmdk_relpath
    if rel.lower().endswith(".vmdk"):
        base = rel[:-5]
        # Rileva pattern snapshot -000001.vmdk
        if "-000" in base:
            return base + "-delta.vmdk"
        return base + "-flat.vmdk"
    # Se non termina con .vmdk, prova comunque ad aggiungere -flat
    return rel + "-flat.vmdk"


def copy_vmdk_from_esxi(
    ssh: SSHClient,
    esxi_host: str,
    esxi_user: str,
    esxi_pass: str,
    datastore: str,
    vmdk_relpath: str,
    dest_dir: str,
) -> Tuple[str, str]:
    """
    Copia SOLO il file descriptor .vmdk da ESXi verso Proxmox.
    Il file dati (flat/delta) viene già gestito da copy_vmdk_flat_with_progress,
    quindi qui evitiamo un secondo trasferimento bloccante senza avanzamento.
    Ritorna il percorso del descriptor e il percorso atteso del file dati in Proxmox.
    """
    ensure_sshpass(ssh)
    ensure_dir(ssh, dest_dir)

    # Percorsi ESXi
    src_desc = f"/vmfs/volumes/{datastore}/{vmdk_relpath}"
    # calcola il file dati (snapshot → -delta, base → -flat) solo per comporre il path di ritorno
    data_rel = guess_vmdk_data_rel(vmdk_relpath)

    # Comandi SCP con sshpass usando file password (evita password inline nei log)
    base_scp = (
        f"sshpass -f /root/esxi_pass.txt scp -o StrictHostKeyChecking=no "
        f"{esxi_user}@{esxi_host}:'{{src}}' '{dest_dir}/'"
    )
    ssh.run(base_scp.format(src=src_desc))

    return f"{dest_dir}/" + vmdk_relpath.split("/")[-1], f"{dest_dir}/" + data_rel.split("/")[-1]


def copy_file_from_esxi(
    ssh: SSHClient,
    esxi_host: str,
    esxi_user: str,
    datastore: str,
    relpath: str,
    dest_dir: str,
) -> str:
    ensure_sshpass(ssh)
    ensure_dir(ssh, dest_dir)
    src = f"/vmfs/volumes/{datastore}/{relpath}"
    base_scp = (
        f"sshpass -f /root/esxi_pass.txt scp -o StrictHostKeyChecking=no "
        f"{esxi_user}@{esxi_host}:'{{src}}' '{dest_dir}/'"
    )
    ssh.run(base_scp.format(src=src))
    return f"{dest_dir}/" + relpath.split("/")[-1]


def start_scp_background(ssh: SSHClient, esxi_host: str, esxi_user: str, esxi_pass: str, src: str, dest_dir: str) -> int:
    ensure_sshpass(ssh)
    ensure_dir(ssh, dest_dir)
    # Avvia scp in background e prova a leggere il PID dal contesto corrente.
    # Usiamo printf per evitare edge case con echo su shell non interattive.
    cmd = (
        "bash -lc \""
        "nohup sshpass -f /root/esxi_pass.txt scp -o StrictHostKeyChecking=no "
        + esxi_user
        + "@"
        + esxi_host
        + ":'"
        + src
        + "' '"
        + dest_dir
        + "/' > /tmp/scp_copy.log 2>&1 & "
        "pid=$!; printf '%s\\n' \"$pid\"\""
    )
    code, out, err = ssh.run(cmd)
    if code != 0:
        raise RuntimeError(f"Impossibile avviare scp: {err}")
    out_pid = out.strip()
    # Se il PID non è stato catturato, effettua un fallback usando pgrep sul comando scp appena avviato
    if not out_pid:
        # Attendi un attimo per permettere al processo di apparire nella tabella
        ssh.run("sleep 1")
        # Cerca l'ultimo processo scp correlato al file sorgente (match sul nome file)
        src_name = src.split("/")[-1]
        code2, out2, err2 = ssh.run(f"pgrep -n -f 'sshpass.*scp.*{src_name}' 2>/dev/null || echo 0")
        out_pid = out2.strip()
    try:
        pid = int(out_pid)
    except Exception:
        raise RuntimeError(f"PID non valido per scp: {out_pid}")
    return pid


def is_process_running(ssh: SSHClient, pid: int) -> bool:
    code, out, err = ssh.run(f"kill -0 {pid} >/dev/null 2>&1 && echo RUN || echo STOP")
    return "RUN" in out


def file_size_bytes(ssh: SSHClient, path: str) -> int:
    code, out, err = ssh.run(f"stat -c %s '{path}' 2>/dev/null || echo 0")
    try:
        return int(out.strip())
    except Exception:
        return 0


def resolve_vmdk_data_rel(
    ssh: SSHClient,
    esxi_host: str,
    esxi_user: str,
    pass_file: str,
    datastore: str,
    vmdk_relpath: str,
) -> str:
    """
    Determina il nome reale del file dati associato al descriptor VMDK su ESXi.
    Prova in ordine: -flat.vmdk, -delta.vmdk, -sesparse.vmdk.
    Ritorna il primo che esiste, altrimenti ritorna il guess di default.
    """
    rel = vmdk_relpath
    candidates = []
    if rel.lower().endswith(".vmdk"):
        base = rel[:-5]
        if "-000" in base:
            # Snapshot VMFS6: prova delta poi sesparse
            candidates = [base + "-delta.vmdk", base + "-sesparse.vmdk"]
        else:
            candidates = [base + "-flat.vmdk"]
    else:
        candidates = [rel + "-flat.vmdk"]

    for candidate in candidates:
        vmx_path = f"/vmfs/volumes/{datastore}/{candidate}"
        cmd = (
            f"sshpass -f {pass_file} ssh "
            f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            f"{esxi_user}@{esxi_host} "
            f"\"test -f '{vmx_path}' && echo EXISTS || echo MISSING\""
        )
        code, out, err = ssh.run(cmd, timeout=15)
        if "EXISTS" in (out or ""):
            return candidate

    # Fallback al guess standard
    return guess_vmdk_data_rel(vmdk_relpath)


def copy_vmdk_flat_with_progress(
    ssh: SSHClient,
    esxi_host: str,
    esxi_user: str,
    esxi_pass: str,
    datastore: str,
    flat_rel: str,
    dest_dir: str,
    capacity_bytes: int,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    # Interpreta flat_rel come "file dati" generico (flat o delta)
    src_data = f"/vmfs/volumes/{datastore}/{flat_rel}"
    pid = start_scp_background(ssh, esxi_host, esxi_user, esxi_pass, src_data, dest_dir)
    dest_data = f"{dest_dir}/" + flat_rel.split("/")[-1]
    src_name = flat_rel.split("/")[-1]
    start_ts = time.time()
    last_size = -1
    last_change_ts = start_ts
    STALL_TIMEOUT = 120.0  # secondi senza progressi prima di abortire
    # Poll progress (robusto: segue crescita file e verifica processo)
    while True:
        transferred = file_size_bytes(ssh, dest_data)
        if transferred != last_size:
            last_size = transferred
            last_change_ts = time.time()
        now = time.time()
        stall_secs = now - last_change_ts
        pct = 0.0
        if capacity_bytes > 0:
            pct = min(100.0, transferred * 100.0 / capacity_bytes)
        if progress_cb:
            elapsed = max(0.001, now - start_ts)
            rate_bps = transferred / elapsed if elapsed > 0 else 0.0
            rate_mibs = rate_bps / (1024 * 1024)
            eta_sec = 0.0
            if rate_bps > 0 and capacity_bytes > transferred:
                eta_sec = (capacity_bytes - transferred) / rate_bps
            def _fmt_t(sec: float) -> str:
                s = int(sec)
                return f"{s//60:02d}:{s%60:02d}"
            msg = (
                f"Copia in corso: {transferred}/{capacity_bytes} bytes — "
                f"velocità {rate_mibs:.1f} MiB/s — elapsed {_fmt_t(elapsed)} — ETA {_fmt_t(eta_sec)}"
            )
            progress_cb(pct, msg)
        # Se ha raggiunto (o superato) la dimensione attesa, termina
        if capacity_bytes > 0 and transferred >= capacity_bytes:
            break
        # Verifica stato processo; se non RUN e nessuna crescita recente, termina
        code_run, out_run, _ = ssh.run(
            f"pgrep -n -f 'sshpass.*scp.*{src_name}' >/dev/null && echo RUN || echo STOP"
        )
        is_run = "RUN" in out_run
        if not is_run and stall_secs > 3.0:
            break
        # Timeout di stallo: processo in esecuzione ma nessun byte trasferito per troppo tempo
        if stall_secs > STALL_TIMEOUT:
            # legge il log SCP per includere il motivo nel messaggio di errore
            _, scp_log, _ = ssh.run("cat /tmp/scp_copy.log 2>/dev/null | tail -n 5")
            hint = f" Log SCP: {scp_log.strip()}" if (scp_log or "").strip() else " Controlla /tmp/scp_copy.log su Proxmox."
            raise RuntimeError(
                f"Trasferimento bloccato: 0 byte copiati in {int(stall_secs)}s. "
                f"Verifica che ESXi ({src_data}) sia raggiungibile via SSH/SCP da Proxmox.{hint}"
            )
        # piccolo sleep via remoto per ridurre chiamate
        ssh.run("sleep 1")
    # Aggiornamento finale coerente con dimensione attuale
    if progress_cb:
        transferred = file_size_bytes(ssh, dest_data)
        elapsed = max(0.001, time.time() - start_ts)
        def _fmt_t(sec: float) -> str:
            s = int(sec)
            return f"{s//60:02d}:{s%60:02d}"
        final_pct = min(100.0, transferred * 100.0 / capacity_bytes) if capacity_bytes > 0 else 0.0
        progress_cb(final_pct, f"Copia completata: {transferred} bytes — elapsed {_fmt_t(elapsed)}")
    # Se la copia ha fallito e il file è assente/vuoto, segnala errore chiaro
    final_size = file_size_bytes(ssh, dest_data)
    if final_size <= 0:
        raise RuntimeError(
            f"Copia fallita: nessun byte copiato. Verifica che '{src_data}' esista su ESXi"
        )
    return dest_data


def qemu_img_convert(
    ssh: SSHClient,
    src_image: str,
    dest_image: str,
    fmt: str = "qcow2",
    compress: bool = True,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> Tuple[int, str, str]:
    """Esegue qemu-img convert con progress (-p) e inoltra avanzamento alla UI."""
    flag_c = "-c" if compress and fmt == "qcow2" else ""
    cmd = f"qemu-img convert -p -O {fmt} {flag_c} '{src_image}' '{dest_image}'"
    # Usa streaming con parser: riconosce sia (NN.NN%) sia NN.NN%
    def _relay(pct: float, msg: str):
        if progress_cb:
            progress_cb(pct, f"Convert: {msg}")
    return ssh.run_streaming_with_parser(cmd, parse_cb=_relay)
