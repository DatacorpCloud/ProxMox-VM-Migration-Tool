Roadmap

- Migrazione multi-VM contemporanea
  - Selezione multipla VM dalla scansione con coda/esecuzione parallela sicura
  - Limite di concorrenza configurabile (es. 2–3 job) e priorità
  - Aggregazione progressi per VM e totale batch

- Robustezza trasferimenti
  - Resume su copia interrotta (rsync/scp + verifica dimensione)
  - Rilevamento errori e retry con backoff
  - Validazione post-copia con checksum opzionale

- UX & logging
  - Canale log progresso separato (implementato)
  - Esportazione report migrazione in JSON/CSV
  - Filtri log e redazione automatica segreti (implementato)

- Conversione/Import
  - Opzioni di compressione e compatibilità `qemu-img` avanzate
  - Supporto storage aggiuntivi e contenuti (images, rootdir, dir, zfs)

- Configurazione e progetti
  - Salvataggio impostazioni non sensibili (già senza password)
  - Template di progetto e validazione

- Qualità e CI
  - Test unitari per parsing/progress
  - Linting/formatting e workflow CI GitHub Actions

- Sicurezza
  - Gestione secret via file/variabili d’ambiente
  - Hardening SSH e gestione chiavi