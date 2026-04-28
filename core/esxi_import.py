import json
import re
import shlex
from typing import Dict, Any, Optional, Tuple

from .ssh_client import SSHClient
from .transfer import ensure_sshpass


def write_esxi_password_file(proxmox_ssh: SSHClient, password: str, path: str = "/root/esxi_pass.txt"):
    proxmox_ssh.write_file(path, password)
    # Imposta permessi restrittivi
    proxmox_ssh.run(f"chmod 600 {path}")


def list_vms(proxmox_ssh: SSHClient, esxi_host: str, esxi_user: str, pass_file: str = "/root/esxi_pass.txt", skip_cert: bool = True) -> Dict[str, Any]:
    flag = "--skip-cert-verification" if skip_cert else ""
    cmd = f"python3 /usr/libexec/pve-esxi-import-tools/listvms.py {flag} {esxi_host} {esxi_user} {pass_file}"
    # Usa streaming per vedere l'avanzamento di listvms.py in tempo reale
    code, out, err = proxmox_ssh.run_streaming(cmd, timeout=180)
    if code != 0:
        raise RuntimeError(f"Errore listvms.py (code={code}): {err}\nOutput: {out}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        # Alcuni ambienti possono stampare log extra: prova a trovare la prima { ... } JSON
        start = out.find("{")
        end = out.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(out[start : end + 1])
        else:
            raise
    # Normalizza struttura: ritorna direttamente la mappa { vm_name: info }
    # Formati attesi:
    # { "ha-datacenter": { "vms": { ... } } }
    # oppure { "vms": { ... } }
    # oppure direttamente { vm_name: {config, disks, power} }
    if isinstance(data, dict):
        if "ha-datacenter" in data and isinstance(data["ha-datacenter"], dict):
            inner = data["ha-datacenter"].get("vms")
            if isinstance(inner, dict):
                return inner
        if "vms" in data and isinstance(data["vms"], dict):
            return data["vms"]
        # Se le chiavi sembrano essere nomi VM (contengono dict con 'config'/'disks')
        sample = next(iter(data.values()), None)
        if isinstance(sample, dict) and ("config" in sample or "disks" in sample):
            return data
    # Fallback: restituisci ciò che è stato parsato
    return data


def esxi_run_cmd(
    proxmox_ssh: SSHClient,
    esxi_host: str,
    esxi_user: str,
    pass_file: str,
    remote_cmd: str,
    timeout: Optional[int] = None,
) -> Tuple[int, str, str]:
    ensure_sshpass(proxmox_ssh)
    cmd = (
        f"sshpass -f {shlex.quote(pass_file)} ssh "
        f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
        f"{shlex.quote(esxi_user)}@{shlex.quote(esxi_host)} {shlex.quote(remote_cmd)}"
    )
    return proxmox_ssh.run(cmd, timeout=timeout)


def esxi_find_vmid_by_vmx(
    proxmox_ssh: SSHClient,
    esxi_host: str,
    esxi_user: str,
    pass_file: str,
    vmx_datastore: str,
    vmx_relpath: str,
) -> Optional[int]:
    expected = f"[{vmx_datastore}] {vmx_relpath}"
    code, out, err = esxi_run_cmd(proxmox_ssh, esxi_host, esxi_user, pass_file, "vim-cmd vmsvc/getallvms", timeout=60)
    if code != 0:
        raise RuntimeError(f"Errore getallvms (code={code}): {err or out}")
    for line in out.splitlines():
        if expected in line:
            m = re.match(r"\s*(\d+)\s+", line)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
    return None


def esxi_create_snapshot(
    proxmox_ssh: SSHClient,
    esxi_host: str,
    esxi_user: str,
    pass_file: str,
    vmid: int,
    name: str,
    description: str,
    quiesce: bool = True,
    memory: bool = False,
) -> None:
    mem_flag = "1" if memory else "0"
    quiesce_flag = "1" if quiesce else "0"
    remote = f"vim-cmd vmsvc/snapshot.create {vmid} {shlex.quote(name)} {shlex.quote(description)} {mem_flag} {quiesce_flag}"
    code, out, err = esxi_run_cmd(proxmox_ssh, esxi_host, esxi_user, pass_file, remote, timeout=120)
    if code != 0:
        raise RuntimeError(f"Creazione snapshot fallita (code={code}): {err or out}")


def esxi_find_snapshot_id_by_name(
    proxmox_ssh: SSHClient,
    esxi_host: str,
    esxi_user: str,
    pass_file: str,
    vmid: int,
    snapshot_name: str,
) -> Optional[int]:
    code, out, err = esxi_run_cmd(
        proxmox_ssh, esxi_host, esxi_user, pass_file, f"vim-cmd vmsvc/snapshot.get {vmid}", timeout=60
    )
    if code != 0:
        return None
    last_name: Optional[str] = None
    for line in out.splitlines():
        m_name = re.search(r"Snapshot\s+Name\s*:\s*(.+)\s*$", line)
        if m_name:
            last_name = m_name.group(1).strip()
            continue
        m_id = re.search(r"Snapshot\s+Id\s*:\s*(\d+)\s*$", line)
        if m_id and last_name == snapshot_name:
            try:
                return int(m_id.group(1))
            except Exception:
                return None
    return None


def esxi_create_snapshot_direct(
    esxi_ssh: SSHClient,
    vmid: int,
    name: str,
    description: str,
    quiesce: bool = True,
    memory: bool = False,
) -> None:
    mem_flag = "1" if memory else "0"
    quiesce_flag = "1" if quiesce else "0"
    remote = f"vim-cmd vmsvc/snapshot.create {vmid} {shlex.quote(name)} {shlex.quote(description)} {mem_flag} {quiesce_flag}"
    code, out, err = esxi_run_cmd_direct(esxi_ssh, remote, timeout=120)
    if code != 0:
        raise RuntimeError(f"Creazione snapshot fallita (code={code}): {err or out}")


def esxi_find_snapshot_id_by_name_direct(esxi_ssh: SSHClient, vmid: int, snapshot_name: str) -> Optional[int]:
    code, out, err = esxi_run_cmd_direct(esxi_ssh, f"vim-cmd vmsvc/snapshot.get {vmid}", timeout=60)
    if code != 0:
        return None
    last_name: Optional[str] = None
    for line in out.splitlines():
        m_name = re.search(r"Snapshot\s+Name\s*:\s*(.+)\s*$", line)
        if m_name:
            last_name = m_name.group(1).strip()
            continue
        m_id = re.search(r"Snapshot\s+Id\s*:\s*(\d+)\s*$", line)
        if m_id and last_name == snapshot_name:
            try:
                return int(m_id.group(1))
            except Exception:
                return None
    return None


def esxi_remove_snapshot(
    proxmox_ssh: SSHClient,
    esxi_host: str,
    esxi_user: str,
    pass_file: str,
    vmid: int,
    snapshot_id: int,
) -> None:
    remote = f"vim-cmd vmsvc/snapshot.remove {vmid} {snapshot_id} 0"
    code, out, err = esxi_run_cmd(proxmox_ssh, esxi_host, esxi_user, pass_file, remote, timeout=300)
    if code != 0:
        raise RuntimeError(f"Rimozione snapshot fallita (code={code}): {err or out}")


def esxi_run_cmd_direct(esxi_ssh: SSHClient, remote_cmd: str, timeout: Optional[int] = None) -> Tuple[int, str, str]:
    return esxi_ssh.run(remote_cmd, timeout=timeout)


def _parse_getallvms_output(out: str) -> Dict[str, Any]:
    vms: Dict[str, Any] = {}
    for line in out.splitlines():
        t = line.rstrip()
        if not t:
            continue
        if t.lower().lstrip().startswith("vmid"):
            continue
        m = re.match(r"^\s*(\d+)\s+(.+?)\s+(\[[^\]]+\]\s+.+?\.vmx)\s", t)
        if not m:
            m2 = re.match(r"^\s*(\d+)\s+(.+?)\s+(\[[^\]]+\]\s+.+?\.vmx)\s*$", t)
            if not m2:
                continue
            vmid_s, name, file_col = m2.group(1), m2.group(2), m2.group(3)
        else:
            vmid_s, name, file_col = m.group(1), m.group(2), m.group(3)
        try:
            vmid = int(vmid_s)
        except Exception:
            continue
        ds_m = re.match(r"^\[([^\]]+)\]\s+(.+)$", file_col.strip())
        datastore = ds_m.group(1).strip() if ds_m else ""
        relpath = ds_m.group(2).strip() if ds_m else file_col.strip()
        vms[str(vmid)] = {"name": name.strip(), "config": {"datastore": datastore, "path": relpath}}
    return vms


def list_vms_direct(esxi_ssh: SSHClient) -> Dict[str, Any]:
    code, out, err = esxi_run_cmd_direct(esxi_ssh, "vim-cmd vmsvc/getallvms", timeout=90)
    if code != 0:
        raise RuntimeError(f"Errore getallvms (code={code}): {err or out}")
    return _parse_getallvms_output(out)


def esxi_power_state_direct(esxi_ssh: SSHClient, vmid: int) -> str:
    code, out, err = esxi_run_cmd_direct(esxi_ssh, f"vim-cmd vmsvc/power.getstate {vmid}", timeout=30)
    if code != 0:
        return ""
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    return lines[-1] if lines else ""


def esxi_get_summary_direct(esxi_ssh: SSHClient, vmid: int) -> str:
    code, out, err = esxi_run_cmd_direct(esxi_ssh, f"vim-cmd vmsvc/get.summary {vmid}", timeout=60)
    if code != 0:
        raise RuntimeError(err or out)
    return out


def esxi_get_config_direct(esxi_ssh: SSHClient, vmid: int) -> str:
    code, out, err = esxi_run_cmd_direct(esxi_ssh, f"vim-cmd vmsvc/get.config {vmid}", timeout=60)
    if code != 0:
        raise RuntimeError(err or out)
    return out


def esxi_get_filelayout_direct(esxi_ssh: SSHClient, vmid: int) -> str:
    code, out, err = esxi_run_cmd_direct(esxi_ssh, f"vim-cmd vmsvc/get.filelayout {vmid}", timeout=60)
    if code != 0:
        raise RuntimeError(err or out)
    return out


def esxi_get_devices_direct(esxi_ssh: SSHClient, vmid: int) -> str:
    code, out, err = esxi_run_cmd_direct(esxi_ssh, f"vim-cmd vmsvc/device.getdevices {vmid}", timeout=60)
    if code != 0:
        raise RuntimeError(err or out)
    return out


def esxi_get_vm_firmware(
    proxmox_ssh: SSHClient,
    esxi_host: str,
    esxi_user: str,
    pass_file: str,
    datastore: str,
    vmx_relpath: str,
) -> str:
    """
    Legge il campo 'firmware' dal file .vmx della VM su ESXi.
    Ritorna 'efi' se UEFI, 'bios' altrimenti.
    """
    vmx_path = f"/vmfs/volumes/{datastore}/{vmx_relpath}"
    cmd = (
        f"sshpass -f {shlex.quote(pass_file)} ssh "
        f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
        f"{shlex.quote(esxi_user)}@{shlex.quote(esxi_host)} "
        f"\"grep -i '^firmware' {shlex.quote(vmx_path)} 2>/dev/null || echo ''\""
    )
    code, out, err = proxmox_ssh.run(cmd, timeout=20)
    line = (out or "").strip().lower()
    if "efi" in line:
        return "efi"
    return "bios"


def esxi_get_vm_guestos(
    proxmox_ssh: SSHClient,
    esxi_host: str,
    esxi_user: str,
    pass_file: str,
    datastore: str,
    vmx_relpath: str,
) -> str:
    """
    Legge il campo 'guestOS' dal file .vmx della VM su ESXi.
    Ritorna stringa lowercase (es. 'windows9srv-64', 'ubuntu-64', 'freebsd13-64').
    Stringa vuota se non trovata.
    """
    vmx_path = f"/vmfs/volumes/{datastore}/{vmx_relpath}"
    cmd = (
        f"sshpass -f {shlex.quote(pass_file)} ssh "
        f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
        f"{shlex.quote(esxi_user)}@{shlex.quote(esxi_host)} "
        f"\"grep -i '^guestOS' {shlex.quote(vmx_path)} 2>/dev/null || echo ''\""
    )
    code, out, err = proxmox_ssh.run(cmd, timeout=20)
    m = re.search(r'guestos\s*=\s*"([^"]+)"', (out or "").lower())
    return m.group(1).strip() if m else ""


def map_guestos_to_proxmox(esxi_guestos: str) -> Dict[str, Any]:
    """
    Mappa il guestOS ESXi al profilo di configurazione Proxmox raccomandato.

    Ritorna un dict con:
        ostype     : valore per --ostype (win10/win11/l26/other/...)
        is_windows : True se la VM è Windows (richiede SATA + e1000 al primo boot)
        nic_model  : 'e1000' per Windows, 'virtio' altrimenti
        bus        : 'sata' per Windows (driver nativo), 'scsi' altrimenti
        machine    : 'q35' raccomandato per UEFI, None per lasciare default
        scsihw     : 'virtio-scsi-single' per supportare iothread per disco
    """
    g = (esxi_guestos or "").lower()
    profile: Dict[str, Any] = {
        "ostype": "other",
        "is_windows": False,
        "nic_model": "virtio",
        "bus": "scsi",
        "machine": "q35",
        "scsihw": "virtio-scsi-single",
    }

    if "windows" in g:
        # win10 copre Server 2016/2019/2022 e Win 10. win11 per Win 11 / Server 2025.
        if "11" in g or "2025" in g:
            profile["ostype"] = "win11"
        else:
            profile["ostype"] = "win10"
        profile["is_windows"] = True
        profile["nic_model"] = "e1000"
        profile["bus"] = "sata"
        return profile

    if any(
        x in g
        for x in (
            "ubuntu",
            "debian",
            "centos",
            "rhel",
            "fedora",
            "linux",
            "suse",
            "arch",
            "rocky",
            "alma",
            "oracle",
        )
    ):
        profile["ostype"] = "l26"
        return profile

    if "freebsd" in g or "pfsense" in g or "opnsense" in g:
        # FreeBSD / pfSense: kernel BSD ha driver vtnet/virtio_blk nativi
        profile["ostype"] = "other"
        return profile

    if "solaris" in g:
        profile["ostype"] = "solaris"
        return profile

    return profile
