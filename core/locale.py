"""
Modulo di localizzazione per supportare più lingue nell'applicazione.
"""

# Dizionario delle stringhe localizzate
STRINGS = {
    "en": {
        # Titoli finestre e tabs
        "app_title": "VM Migration: ESXi → Proxmox",
        "tab_project": "Project",
        "tab_connection": "Connection and Scan",
        "tab_migration": "Options & Migration",
        
        # Etichette credenziali
        "credentials": "Credentials",
        "host_ip": "Host/IP",
        "user": "User",
        "password": "Password",
        
        # Etichette progetto
        "project": "Project",
        "project_name": "Project name",
        "existing_projects": "Existing",
        
        # Etichette scansione
        "scan": "Scan",
        "available_vms": "Available VMs (select one)",
        "vms_found_on_esxi": "VMs found on ESXi",
        "vm_name": "VM Name",
        "datastore": "Datastore",
        "disk_path": "Disk Path",
        "capacity": "Capacity (GB)",
        "power_state": "Power",
        
        # Etichette opzioni
        "options": "Options",
        "storage": "Storage",
        "network": "Network",
        "new_vmid": "New VMID",
        "new_name": "New VM Name",
        "ram_mb": "RAM (MB)",
        "vcpu": "vCPU",
        "destination": "Destination files (on Proxmox)",
        "browse": "Browse...",
        "dry_run": "Dry-run (show plan, don't execute)",
        "uefi_ovmf": "UEFI/OVMF",
        "vlan_aware": "VLAN-aware (show command)",
        "convert_qemu": "Convert with qemu-img",
        "format": "Format",
        
        # Etichette dischi
        "selected_vm_disks": "Selected VM disks (multiple selection)",
        
        # Etichette log e progresso
        "log": "Log",
        "copy_progress": "Copy progress",
        "conversion_import": "Conversion / Import / Start",
        
        # Pulsanti
        "save": "Save",
        "load": "Load",
        "new": "New",
        "refresh_list": "Refresh list",
        "connect_and_scan": "Connect Proxmox & Scan ESXi",
        "prepare_execute_migration": "Prepare/Execute Migration",
        "cleanup_esxi_credentials": "Cleanup ESXi credentials",
        "scan_button": "Scan ESXi & Proxmox",
        "migrate": "Migrate",
        "select": "Select",
        
        # Messaggi
        "project_saved": "Project '{0}' saved: {1}",
        "save_error": "Save error",
        "project_loaded": "Project '{0}' loaded",
        "load_error": "Load error",
        "scan_complete": "Scan completed",
        "scan_error": "Scan error: {0}",
        "migration_complete": "Migration completed (check output/log)",
        "migration_error": "Migration error: {0}",
        "log_file": "Log file: {0}",
        "detected_storages": "Detected storages: {0}",
        "detected_bridges": "Detected bridges: {0}",
        "suggested_vmid": "Suggested next VMID: {0}",
        "browse_error": "Remote browse error: {0}",
    },
    "it": {
        # Titoli finestre e tabs
        "app_title": "Migrazione VM: ESXi → Proxmox",
        "tab_project": "Progetto",
        "tab_connection": "Connessione e Scansione",
        "tab_migration": "Opzioni & Migrazione",
        
        # Etichette credenziali
        "credentials": "Credenziali",
        "host_ip": "Host/IP",
        "user": "User",
        "password": "Password",
        
        # Etichette progetto
        "project": "Progetto",
        "project_name": "Nome progetto",
        "existing_projects": "Esistenti",
        
        # Etichette scansione
        "scan": "Scansione",
        "available_vms": "VM disponibili (seleziona una)",
        "vms_found_on_esxi": "VM trovate su ESXi",
        "vm_name": "Nome VM",
        "datastore": "Datastore",
        "disk_path": "Path Disco",
        "capacity": "Capacità (GB)",
        "power_state": "Power",
        
        # Etichette opzioni
        "options": "Opzioni",
        "storage": "Storage",
        "network": "Rete",
        "new_vmid": "Nuovo VMID",
        "new_name": "Nuovo Nome VM",
        "ram_mb": "RAM (MB)",
        "vcpu": "vCPU",
        "destination": "Destinazione file (su Proxmox)",
        "browse": "Sfoglia...",
        "dry_run": "Dry-run (mostra piano, non esegue)",
        "uefi_ovmf": "UEFI/OVMF",
        "vlan_aware": "VLAN-aware (mostra comando)",
        "convert_qemu": "Converti con qemu-img",
        "format": "Formato",
        
        # Etichette dischi
        "selected_vm_disks": "Dischi della VM selezionata (selezione multipla)",
        
        # Etichette log e progresso
        "log": "Log",
        "copy_progress": "Avanzamento copia",
        "conversion_import": "Conversione / Import / Avvio",
        
        # Pulsanti
        "save": "Salva",
        "load": "Carica",
        "new": "Nuovo",
        "refresh_list": "Aggiorna elenco",
        "connect_and_scan": "Connetti Proxmox e Scansiona ESXi",
        "prepare_execute_migration": "Prepara/Esegui Migrazione",
        "cleanup_esxi_credentials": "Cleanup credenziali ESXi",
        "scan_button": "Scansione ESXi & Proxmox",
        "migrate": "Migra",
        "select": "Seleziona",
        
        # Messaggi
        "project_saved": "Progetto '{0}' salvato: {1}",
        "save_error": "Errore salvataggio",
        "project_loaded": "Progetto '{0}' caricato",
        "load_error": "Errore caricamento",
        "scan_complete": "Scansione completata",
        "scan_error": "Errore scansione: {0}",
        "migration_complete": "Migrazione eseguita (verifica output/log)",
        "migration_error": "Errore migrazione: {0}",
        "log_file": "File di log: {0}",
        "detected_storages": "Storage rilevati: {0}",
        "detected_bridges": "Bridge rilevati: {0}",
        "suggested_vmid": "Prossimo VMID suggerito: {0}",
        "browse_error": "Errore sfoglia remota: {0}",
    }
}

# Lingua predefinita
DEFAULT_LANGUAGE = "it"
current_language = DEFAULT_LANGUAGE

# Carica la lingua dalle impostazioni se esiste
try:
    import os
    config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
    os.makedirs(config_dir, exist_ok=True)
    lang_file = os.path.join(config_dir, "language.txt")
    if os.path.exists(lang_file):
        with open(lang_file, "r") as f:
            saved_lang = f.read().strip()
            if saved_lang in STRINGS:
                current_language = saved_lang
except Exception:
    pass

def set_language(lang_code):
    """
    Imposta la lingua corrente.
    
    Args:
        lang_code (str): Codice lingua ('it' o 'en')
    """
    global current_language
    if lang_code in STRINGS:
        current_language = lang_code
        # Salva la lingua nelle impostazioni
        try:
            import os
            config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
            os.makedirs(config_dir, exist_ok=True)
            lang_file = os.path.join(config_dir, "language.txt")
            with open(lang_file, "w") as f:
                f.write(lang_code)
        except Exception:
            pass
    else:
        current_language = DEFAULT_LANGUAGE

def get_string(key):
    """
    Ottiene una stringa localizzata.
    
    Args:
        key (str): Chiave della stringa
        
    Returns:
        str: Stringa localizzata o la chiave stessa se non trovata
    """
    if key in STRINGS[current_language]:
        return STRINGS[current_language][key]
    elif key in STRINGS["en"]:  # Fallback all'inglese
        return STRINGS["en"][key]
    return key  # Fallback alla chiave stessa

# Alias più breve per get_string
_ = get_string