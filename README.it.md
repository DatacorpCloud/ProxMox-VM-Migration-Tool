Migrazione VM: ESXi → Proxmox

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
- Premi `Prepara/Esegui Migrazione` e segui le barre di avanzamento (copia e import/conversione).

Screenshot (esempio)

![Opzioni & Migrazione](docs/screenshots/options_migration.png)