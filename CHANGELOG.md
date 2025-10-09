Changelog

2025-10-09

- Added MIT LICENSE.
- Implemented password redaction in SSHClient logs.
- Switched ESXi transfers to `sshpass -f /root/esxi_pass.txt`.
- Ensured ESXi password file creation in `execute_full_migration`.
- Added dedicated progress log channel in the UI.
- Created `.gitignore` for logs, projects, and Python caches.
- Cleaned existing logs and recreated `logs/` folder.
- Added bilingual documentation (`README.it.md`, `README.en.md`).
- Added `docs/` with screenshot conventions.
- Added `ROADMAP.md` and `ROADMAP.en.md` (English roadmap).