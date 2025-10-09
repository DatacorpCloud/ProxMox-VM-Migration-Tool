import os
import json
from typing import Dict, Any, List


def _base_dir() -> str:
    # Base: cartella del progetto (una sopra 'core')
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def projects_dir() -> str:
    d = os.path.join(_base_dir(), "projects")
    os.makedirs(d, exist_ok=True)
    return d


def project_path(name: str) -> str:
    safe = "".join(c for c in name if (c.isalnum() or c in ("-", "_")))
    if not safe:
        safe = "project"
    return os.path.join(projects_dir(), f"{safe}.json")


EXCLUDE_KEYS = {"pmx_pass", "esxi_pass", "password", "proxmox_pass"}


def _sanitize(data: Dict[str, Any]) -> Dict[str, Any]:
    # Rimuove automaticamente chiavi sensibili (qualsiasi chiave che contiene 'pass')
    clean: Dict[str, Any] = {}
    for k, v in data.items():
        if k in EXCLUDE_KEYS or ("pass" in k.lower()):
            continue
        clean[k] = v
    return clean


def save_project(name: str, data: Dict[str, Any]) -> str:
    """
    Salva un progetto come JSON, escludendo password/secret. Ritorna il percorso.
    """
    path = project_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_sanitize(data), f, indent=2, ensure_ascii=False)
    return path


def load_project(name: str) -> Dict[str, Any]:
    path = project_path(name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Progetto non trovato: {name}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_projects() -> List[str]:
    d = projects_dir()
    items = []
    for fn in os.listdir(d):
        if fn.endswith(".json"):
            items.append(os.path.splitext(fn)[0])
    return sorted(items)


def project_exists(name: str) -> bool:
    return os.path.exists(project_path(name))