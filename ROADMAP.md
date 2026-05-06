Roadmap

Funzionalità ancora da implementare. Per ciò che è già stato consegnato vedi il [CHANGELOG](CHANGELOG.md).

## Migrazione multi-VM concorrente

- Selezione multipla VM dalla scansione con coda di esecuzione
- Limite di concorrenza configurabile (es. 2–3 job paralleli) e priorità per VM
- Aggregazione progressi per singola VM + totale batch
- Cancellazione/pausa di un singolo job senza interrompere gli altri

## Robustezza trasferimenti

- Resume di una copia interrotta (riprende dal byte raggiunto invece di rifare daccapo)
- Retry automatico con backoff esponenziale su errori transienti di rete
- Validazione post-copia con checksum opzionale (sha256 sul file flat)
- Health-check pre-volo: verifica spazio disco, raggiungibilità ESXi/Proxmox, permessi storage

## Helper post-migrazione (nuovo, dall'esperienza sul campo)

Automatizzare i passi che oggi sono manuali e spiegati nel README:

- **Linux**: rilevamento e disabilitazione automatica della gestione rete di cloud-init per rendere persistente il netplan post-migrazione. Possibile injection del netplan giusto via SSH dentro la VM al primo boot.
- **Windows**: helper guidato per la "danza VirtIO" (dummy disk → reboot → arming `viostor`/`vioscsi` via registro → swap a SCSI VirtIO) con conferma utente tra i passaggi.
- Aggiornamento certificati UEFI 2023k automatico per VM migrate prima del fix.

## Reportistica

- Export del report di migrazione in JSON/CSV (timing per fase, dimensioni, esito)
- Metriche aggregate sul Dashboard Home (durata media, MB/s effettivi, tasso di successo)
- Audit log persistente delle migrazioni completate

## Conversione / Import

- Supporto storage Proxmox aggiuntivi: ZFS, Ceph RBD, LVM-thin
- Preset di compressione `qemu-img` (zstd dove supportato, livelli configurabili)
- Conversione streaming via pipe SSH (eliminando il file intermedio sul Proxmox)

## Configurazione & progetti

- Template di progetto (preset di mappature storage/bridge/profilo OS) riusabili
- Import/export delle impostazioni non sensibili
- Validazione preventiva del progetto prima del run

## Qualità & CI

- Workflow GitHub Actions: esecuzione test suite + lint su ogni PR
- Linter/formatter (black + ruff) con configurazione condivisa
- Estensione test suite ai flussi di backup/restore (oggi coperti solo i blocchi core)

## Sicurezza

- Autenticazione SSH a chiave invece di password (sia per Proxmox che per ESXi)
- Gestione secret via variabili d'ambiente o file dedicato (alternativa a SQLite locale)
- Hardening della sessione SSH: known_hosts pinning, disable di algoritmi deboli
- Rotazione automatica delle credenziali CHAP iSCSI dopo recovery
