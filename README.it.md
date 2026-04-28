[![View on GitHub](https://img.shields.io/badge/View%20on-GitHub-black?logo=github)](https://github.com/DatacorpCloud/ProxMox-VM-Migration-Tool)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Proxmox%20%7C%20ESXi%20%7C%20Windows-orange.svg)](https://github.com/DatacorpCloud/ProxMox-VM-Migration-Tool)

VM Backup & Migration Tool (Proxmox ⇄ ESXi)

Interfaccia Web (Backup & Restore)

Interfaccia web (Flask) orientata alle operazioni quotidiane di backup/restore:

- Gestione risorse (credenziali Proxmox / ESXi salvate localmente in SQLite)
- Gestione storage repository (NFS / iSCSI / percorsi Windows montati, es. `Z:\...`)
- Flussi di backup (ESXi e Proxmox)
- Flussi di restore:
  - Restore “semplice” (auto-rileva la piattaforma del backup, nome VM opzionale, avvio acceso/spento)
  - Restore “multi‑piattaforma” (Proxmox ⇄ VMware) usando un worker Proxmox quando serve
- Vista Job e streaming eventi (progress + log)
- Metriche Home (numero backup, GB totali, VM in backup, VM migrate)

Avvio Web

- Installa dipendenze: `pip install -r vm-migration-tool/requirements.txt`
- Avvia server: `python vm-migration-tool/main.py --web --host localhost --port 8080`
- Apri: http://localhost:8080

Note

- Limite MVP: un job alla volta (backup/restore/migrazione).
- Gli storage repository possono essere verificati dalla UI (pulsante “Test”) per validare l’accesso prima dell’uso.
- Set minimo per deploy solo web:
  - `vm-migration-tool/main.py`
  - `vm-migration-tool/ui/web_app.py`
  - `vm-migration-tool/core/*`
  - `vm-migration-tool/requirements.txt`
  - Opzionali per persistenza: `vm-migration-tool/app.sqlite3`, `vm-migration-tool/repository/`

Screenshot Web UI

1. Home
   ![Home](docs/screenshots/home.png)
2. Risorse • Storage
   ![Storage](docs/screenshots/storage.png)
3. Job
   ![Job](docs/screenshots/job.png)
4. Risorse • Virtualizzatori (elenco)
   ![Elenco virtualizzatori](docs/screenshots/elen-virtualizzatori.png)
5. Risorse • Virtualizzatori (Add virtualizzatore)
   ![Add virtualizzatore](docs/screenshots/virtualizzatore.png)
6. Backup
   ![Backup](docs/screenshots/backup.png)
7. Restore multi‑piattaforma
   ![Restore cross-platform](docs/screenshots/restorecrossplat.png)
8. Live Cross Migration
   ![Live cross migration](docs/screenshots/livecrossmigration.png)

Interfaccia Desktop (legacy: migrazione ESXi → Proxmox)

Panoramica

- Strumento desktop per migrare VM da VMware ESXi a Proxmox VE.
- Copia i VMDK da ESXi, converte con `qemu-img`, importa sullo storage di destinazione e configura la VM (incluso UEFI/OVMF opzionale).
- Barre di avanzamento e file di log dedicato al progresso per visibilità.

Funzionalità principali

- Copia da ESXi via SCP usando `sshpass` con file password su Proxmox (niente password in chiaro).
- Conversione e import su storage Proxmox (`images`, `dir`, ecc.).
- Configurazione UEFI/OVMF opzionale (`q35`, `ovmf`, `efidisk0` con chiavi pre-enrollate).
- Flusso UI: Connessione & Scansione → Opzioni & Migrazione.

Requisiti

- Python 3.9+
- Proxmox VE raggiungibile via SSH.
- Host ESXi raggiungibile via SSH (utente con accesso in lettura al datastore).

Avvio rapido

- Installa dipendenze: `pip install -r vm-migration-tool/requirements.txt`
- Avvia app: `python vm-migration-tool/main.py`
- Nella UI:
  - Inserisci le credenziali di Proxmox ed ESXi.
  - Scansiona ESXi e scegli una VM.
  - Seleziona storage Proxmox e opzioni (UEFI/OVMF se la VM originale usa UEFI).
  - Avvia la migrazione e monitora l’avanzamento.

Sicurezza e log

- Redazione automatica dei segreti nei log applicativi; le password non compaiono in chiaro.
- La password ESXi viene scritta su `/root/esxi_pass.txt` in Proxmox (permessi restrittivi) e usata tramite `sshpass -f`.
- Gli avanzamenti sono scritti anche in `vm-migration-tool/logs/progress-*.log`.
- I file di progetto escludono le informazioni sensibili.

Note d’uso

- Abilita UEFI/OVMF solo se la VM originale usa firmware UEFI/EFI; mantieni BIOS legacy altrimenti.
- Dopo una migrazione puoi sceglierne un’altra e ripetere senza riavviare l’app.

Profilo di migrazione OS-aware (dal 2026-04)

Il tool legge `guestOS` dal `.vmx` sorgente e applica un profilo adatto al primo boot su Proxmox:

| OS guest sorgente              | Bus disco | NIC    | ostype  | Note                                                                  |
| ------------------------------ | --------- | ------ | ------- | --------------------------------------------------------------------- |
| Windows Server 2016/2019/2022  | `sata0`   | e1000  | `win10` | Windows ha driver SATA + e1000 nativi: niente BSOD `viostor`.         |
| Windows 11 / Server 2025       | `sata0`   | e1000  | `win11` | Idem.                                                                 |
| Linux (Ubuntu/Debian/RHEL/…)   | `scsi0`   | virtio | `l26`   | SCSI VirtIO + `discard=on` + `iothread=1` (massime performance).      |
| FreeBSD / pfSense / OPNsense   | `scsi0`   | virtio | `other` | Driver virtio nativi nel kernel BSD (`vtnet`, `virtio_blk`).          |
| Altro / Sconosciuto            | `scsi0`   | virtio | `other` | Default sicuri.                                                       |

Dopo un primo boot Windows riuscito puoi migrare manualmente a SCSI VirtIO con la procedura "dummy disk" (collega un disco SCSI VirtIO piccolo → riavvia → verifica in Device Manager che `viostor` sia caricato come boot driver → sposta il disco reale su SCSI). Il tool NON lo fa in automatico perché richiede conferma utente tra i passaggi.

Web UI: nel form di migrazione il campo **"Profilo OS guest"** è impostato di default su `Auto (da .vmx)`. Forza un valore solo se il `.vmx` non contiene `guestOS` o se vuoi imporre un profilo diverso. Il campo read-only **"Hint profilo rilevato"** mostra il profilo risolto (bus / nic / ostype) prima di lanciare il job.

UEFI: quando attivo, `efidisk0` viene creato con `pre-enrolled-keys=1` e `ms-cert=2023k`, evitando il warning *"UEFI 2011 certificates expire June 2026"* su Proxmox ≥ 8.4.

Formato disco: `qm importdisk` viene invocato con `--format qcow2` per garantire che il disco di destinazione sia qcow2 anche quando il default dello storage sarebbe raw. Questo ripristina le funzionalità di snapshot/backup tipiche di qcow2.

Roadmap

- Vedi [ROADMAP.md](ROADMAP.md) per le funzionalità pianificate (migrazione multi-VM concorrente, robustezza trasferimenti, CI, e altro).

Istruzioni operative (Opzioni & Migrazione)

- Rimuovi la spunta da `Dry-run (mostra piano, non esegue)` per avviare davvero la migrazione.
- Metti la spunta su `Converti con qemu-img` per convertire il VMDK nel formato di destinazione (default: `qcow2`).
- Seleziona uno storage Proxmox che supporti il contenuto `images` (in Proxmox: Datacenter → Storage → il tuo storage deve avere "Disk image").
  - Se lo storage NON supporta `images`, l’app lo segnalerà e bloccherà l’import.
- Campo `Destinazione file (su Proxmox)`:
  - Se lo storage è montato in `/mnt/pve/<storage>`, viene suggerito ` /mnt/pve/<storage>/tmp/<nomeVM>`.
  - Per storage non montati (es. `local-lvm`), il fallback è `/root/tmp/<nomeVM>`.
  - Usa `Sfoglia…` se vuoi impostare un percorso personalizzato.
- UEFI/OVMF: abilitalo solo se la VM originale usa firmware UEFI/EFI; tieni disabilitato per BIOS legacy.
- **Profilo OS (Auto)**: il form rileva automaticamente la famiglia OS dal `.vmx` sorgente. Per Windows configura la VM su SATA + e1000 (primo boot sicuro). Per Linux/FreeBSD usa SCSI VirtIO con discard + iothread.
- **Isolamento DC Windows**: spunta *"Windows: link giù primo boot"* quando migri un Domain Controller che non vuoi parli con i peer al primo boot.
- Premi `Prepara/Esegui Migrazione` e segui le barre di avanzamento (copia e import/conversione). Entrambe le barre ora si aggiornano in tempo reale (progress di `qemu-img` e `qm importdisk`).

Test

Una piccola test suite copre i punti più soggetti a regressione:

```
python -m unittest discover -s tests -v
```

Test inclusi:
- `tests/test_guestos_mapping.py` — mapping guestOS → profilo Proxmox (`map_guestos_to_proxmox`).
- `tests/test_progress_parser.py` — bug fix del parser `(NN.NN/100%)` di `qemu-img`.
- `tests/test_proxmox_commands.py` — forma dei comandi `qm` generati (formato importdisk, bus attach, certificati UEFI).

Screenshot Desktop UI

1. Creazione progetto
   ![Project Creation](docs/screenshots/projct.PNG)
2. Connessione e scansione
   ![Connection and Scan](docs/screenshots/connection_scan.PNG)
3. Opzioni & Migrazione
   ![Opzioni & Migrazione](docs/screenshots/options_migration.png)
