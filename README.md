VM Migration: ESXi → Proxmox

Overview

- Desktop tool to migrate VMs from VMware ESXi to Proxmox VE.
- Copies VMDK from ESXi, converts with `qemu-img`, imports to target storage, and configures VM (including optional UEFI/OVMF).
- Progress bars and a dedicated progress log file for visibility.

Key Features

- ESXi copy via SCP with `sshpass` using a password file on Proxmox (no plaintext in commands).
- Conversion and import to Proxmox storage (`images`, `dir`, etc.).
- Optional UEFI/OVMF config (`q35`, `ovmf`, `efidisk0` with pre-enrolled keys).
- UI flow: Connect & Scan → Options & Migration.

Requirements

- Python 3.9+
- Proxmox VE reachable via SSH.
- ESXi host reachable via SSH (user with read access to datastore).

Quick Start

- Install deps: `pip install -r vm-migration-tool/requirements.txt`
- Run app: `python vm-migration-tool/main.py`
- In the UI:
  - Enter Proxmox and ESXi credentials.
  - Scan ESXi and choose a VM.
  - Pick Proxmox storage and options (UEFI/OVMF if original VM uses UEFI).
  - Start migration and monitor progress.

Web UI (Backup & Restore)

This project also includes a lightweight web interface (Flask) that exposes:

- Resource management (Proxmox / ESXi credentials stored locally in SQLite)
- Repository storage management (NFS / iSCSI / Windows mounted paths)
- Backup workflows (ESXi and Proxmox)
- Restore workflows:
  - Simple restore (auto-detect backup platform, optional VM name, start on/off)
  - Cross-platform restore (Proxmox ⇄ VMware) using a Proxmox worker when needed
- Jobs view and real-time job events (progress and logs)
- Home dashboard metrics (backups count, total GB, VMs in backup, migrated VMs)

Run the Web UI

- Install deps: `pip install -r vm-migration-tool/requirements.txt`
- Start server: `python vm-migration-tool/main.py --web --host localhost --port 8080`
- Open: http://localhost:8080

Notes

- MVP limitation: one job at a time (backup/restore/migration) to keep runs deterministic.
- Repo storages can be tested from the UI ("Test" button) to validate access before using them.
- Minimal runtime set for web-only deployments:
  - `vm-migration-tool/main.py`
  - `vm-migration-tool/ui/web_app.py`
  - `vm-migration-tool/core/*`
  - `vm-migration-tool/requirements.txt`
  - Optional for persistence: `vm-migration-tool/app.sqlite3`, `vm-migration-tool/repository/`

Security & Logging

- Password sanitization in application logs; sensitive values are redacted.
- ESXi password is written to `/root/esxi_pass.txt` on Proxmox (restricted permissions) and used via `sshpass -f`.
- Progress entries are also written to `vm-migration-tool/logs/progress-*.log`.
- Project files exclude secrets by design.

Usage Notes

- Enable UEFI/OVMF only if the original VM uses UEFI/EFI firmware; keep BIOS legacy otherwise.
- After a migration completes, you can select another VM and repeat without restarting the app.

Roadmap

- See [ROADMAP.en.md](ROADMAP.en.md) for planned features (multi-VM concurrent migration, improved transfer resilience, CI, and more).

Operational Instructions (Options & Migration)

- Uncheck `Dry-run (show plan, do not execute)` to actually run the migration.
- Check `Convert with qemu-img` to convert VMDK to the target format (default: `qcow2`).
- Select a Proxmox storage that supports `images` content (in Proxmox: Datacenter → Storage → your storage should include "Disk image").
  - If the storage does NOT support `images`, the app will warn and block the import.
- Field `Destination file (on Proxmox)`:
  - If the storage is mounted under `/mnt/pve/<storage>`, the suggested path is `/mnt/pve/<storage>/tmp/<vmName>`.
  - For non-mounted storages (e.g., `local-lvm`), the fallback is `/root/tmp/<vmName>`.
  - Use `Browse…` to set a custom path if needed.
- UEFI/OVMF: enable only if the original VM uses UEFI/EFI firmware; keep disabled for legacy BIOS.
- Press `Prepare/Run Migration` and follow the progress bars (copy and import/conversion).

Screenshots

1. Project Creation
   ![Project Creation](docs/screenshots/projct.PNG)
2. Connection and Scan
   ![Connection and Scan](docs/screenshots/connection_scan.PNG)
3. Options and Migration
   ![Options and Migration](docs/screenshots/options_migration.png)

Web UI Screenshots

1. Home
   ![Home](docs/screenshots/home.png)
2. Resources • Storage
   ![Storage](docs/screenshots/storage.png)
3. Jobs
   ![Job](docs/screenshots/job.png)
4. Resources • Virtualizers (list)
   ![Virtualizers List](docs/screenshots/elen-virtualizzatori.png)
5. Resources • Virtualizers (add)
   ![Add Virtualizer](docs/screenshots/virtualizzatore.png)
6. Backup
   ![Backup](docs/screenshots/backup.png)
7. Cross-platform restore
   ![Restore Cross-platform](docs/screenshots/restorecrossplat.png)
8. Live cross migration
   ![Live Cross Migration](docs/screenshots/livecrossmigration.png)
