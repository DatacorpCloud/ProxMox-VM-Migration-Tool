import json
from typing import Dict, Any

from .ssh_client import SSHClient


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