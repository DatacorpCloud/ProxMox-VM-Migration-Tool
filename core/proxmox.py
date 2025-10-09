from typing import Optional, Tuple, List
import re

from .ssh_client import SSHClient
from typing import Callable


def qm_create(ssh: SSHClient, vmid: int, name: str, memory: int, cores: int, net0: str):
    cmd = f"qm create {vmid} --name {name} --memory {memory} --cores {cores} --net0 {net0}"
    return ssh.run(cmd)


def qm_importdisk(ssh: SSHClient, vmid: int, vmdk_path: str, storage: str):
    cmd = f"qm importdisk {vmid} \"{vmdk_path}\" {storage}"
    return ssh.run(cmd)


def qm_importdisk_with_progress(
    ssh: SSHClient,
    vmid: int,
    vmdk_path: str,
    storage: str,
    progress_cb: Callable[[float, str], None] | None = None,
):
    """
    Esegue qm importdisk con streaming e parsing delle righe di avanzamento.
    Aggiorna progress_cb quando l'output contiene "(NN.NN%)" o il messaggio
    di completamento "successfully imported disk".
    """
    cmd = f"qm importdisk {vmid} \"{vmdk_path}\" {storage}"
    # Inoltra il parsing al client SSH e rilancia il messaggio con prefisso "Import"
    def _relay(pct: float, msg: str):
        if progress_cb:
            progress_cb(pct, f"Import: {msg}")
    return ssh.run_streaming_with_parser(cmd, parse_cb=_relay)


def qm_set_scsi(ssh: SSHClient, vmid: int, disk_id: str, scsihw: str = "virtio-scsi-pci"):
    # Esempio disk_id: "QNAP-IMAGES:vm-120-disk-0"
    cmd = f"qm set {vmid} --scsihw {scsihw} --scsi0 {disk_id}"
    return ssh.run(cmd)


def qm_attach_scsi(ssh: SSHClient, vmid: int, disk_id: str, index: int = 0, scsihw: str = "virtio-scsi-pci"):
    slot = f"scsi{index}"
    cmd = f"qm set {vmid} --scsihw {scsihw} --{slot} {disk_id}"
    return ssh.run(cmd)


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
    # imposta macchina q35, bios ovmf e crea efidisk
    code1, out1, err1 = ssh.run(f"qm set {vmid} --machine q35 --bios ovmf")
    code2, out2, err2 = ssh.run(f"qm set {vmid} --efidisk0 {storage}:0,pre-enrolled-keys=1")
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