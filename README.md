[![View on GitHub](https://img.shields.io/badge/View%20on-GitHub-black?logo=github)](https://github.com/DatacorpCloud/ProxMox-VM-Migration-Tool)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Proxmox%20%7C%20ESXi%20%7C%20Windows-orange.svg)](https://github.com/DatacorpCloud/ProxMox-VM-Migration-Tool)

VM Backup & Migration Tool (Proxmox ⇄ ESXi)

Web UI (Backup & Restore)

Lightweight web interface (Flask) focused on day-to-day backup/restore operations:

- Resource management (Proxmox / ESXi credentials stored locally in SQLite)
- Repository storage management (NFS / iSCSI / Windows mounted paths)
- Backup workflows (ESXi and Proxmox)
- Restore workflows:
  - Simple restore (auto-detect backup platform, optional VM name, start on/off)
  - Cross-platform restore (Proxmox ⇄ VMware) using a Proxmox worker when needed
- Jobs view and real-time job events (progress and logs)
- Home dashboard metrics (backups count, total GB, VMs in backup, migrated VMs)

Run the Web UI

- Install deps: `pip install -r requirements.txt`
- Start server: `python main.py --web --host 0.0.0.0 --port 8080`
- Open: http://localhost:8080

> Run on the Proxmox host itself (faster, works on local files) or on any Linux/Windows machine that can reach via SSH both Proxmox and the source ESXi.

Notes

- MVP limitation: one job at a time (backup/restore/migration).
- Repo storages can be tested from the UI ("Test" button) to validate access before using them.
- Minimal runtime set for web-only deployments:
  - `main.py`
  - `ui/web_app.py`
  - `core/*`
  - `requirements.txt`
  - Optional for persistence: `app.sqlite3`, `repository/`

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

Desktop UI (legacy: ESXi → Proxmox migration)

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

- Install deps: `pip install -r requirements.txt`
- Run app: `python main.py`
- In the UI:
  - Enter Proxmox and ESXi credentials.
  - Scan ESXi and choose a VM.
  - Pick Proxmox storage and options (UEFI/OVMF if original VM uses UEFI).
  - Start migration and monitor progress.

Security & Logging

- Password sanitization in application logs; sensitive values are redacted.
- ESXi password is written to `/root/esxi_pass.txt` on Proxmox (restricted permissions) and used via `sshpass -f`.
- Progress entries are also written to `vm-migration-tool/logs/progress-*.log`.
- Project files exclude secrets by design.

Usage Notes

- Enable UEFI/OVMF only if the original VM uses UEFI/EFI firmware; keep BIOS legacy otherwise.
- After a migration completes, you can select another VM and repeat without restarting the app.

OS-aware migration profile (since 2026-04)

The tool now reads `guestOS` from the source `.vmx` and applies a profile suited for the first boot on Proxmox:

| Source guest OS              | Disk bus    | NIC    | ostype  | Notes                                                          |
| ---------------------------- | ----------- | ------ | ------- | -------------------------------------------------------------- |
| Windows Server 2016/2019/2022| `sata0`     | e1000  | `win10` | Windows has native SATA + e1000 drivers, no `viostor` BSOD.    |
| Windows 11 / Server 2025     | `sata0`     | e1000  | `win11` | Same as above.                                                 |
| Linux (Ubuntu/Debian/RHEL/…) | `scsi0`     | virtio | `l26`   | SCSI VirtIO + `discard=on` + `iothread=1` (best performance).  |
| FreeBSD / pfSense / OPNsense | `scsi0`     | virtio | `other` | Native FreeBSD virtio drivers (`vtnet`, `virtio_blk`).         |
| Other / Unknown              | `scsi0`     | virtio | `other` | Safe defaults.                                                 |

After a successful Windows boot you can manually migrate to SCSI VirtIO using the "dummy disk" pattern (attach a small SCSI VirtIO disk → reboot → confirm `viostor` is loaded as boot driver → swap real disk to SCSI). The tool intentionally does NOT do this automatically because it requires user confirmation between steps.

Web UI: in the Migration form, the field **"Profilo OS guest"** defaults to `Auto (da .vmx)`. Override only when the `.vmx` lacks `guestOS` or you want to force a specific profile. The **"Hint profilo rilevato"** read-only field shows the resolved profile (bus / nic / ostype) before you start the job.

UEFI: when enabled, `efidisk0` is created with `pre-enrolled-keys=1` and `ms-cert=2023k`, which avoids the warning *"UEFI 2011 certificates expire June 2026"* on Proxmox ≥ 8.4.

Disk format: `qm importdisk` is invoked with `--format qcow2` to ensure the destination disk is qcow2 even when the storage default would be raw. This restores snapshot/backup capabilities expected from qcow2.

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
- **OS profile (Auto)**: the form auto-detects the OS family from the source `.vmx`. For Windows it prepares the VM on SATA + e1000 (first boot safe). For Linux/FreeBSD it uses SCSI VirtIO with discard + iothread.
- **Windows DC isolation**: tick *"Windows: link giù primo boot"* when migrating a Domain Controller you don't want to talk to its peers immediately at first boot.
- Press `Prepare/Run Migration` and follow the progress bars (copy and import/conversion). Both bars now update in real time (qemu-img and qm importdisk progress).

Post-migration tasks

When a VM boots on Proxmox for the first time, the guest OS may need small adjustments to fully restore network and performance.

### Linux (Ubuntu/Debian with netplan + cloud-init)

The network interface name changes (on Proxmox VirtIO the first NIC is `ens18`). Also, if cloud-init is enabled, it **regenerates network config at every boot** and overrides your manual netplan: to make it persistent, you must disable cloud-init's network management.

```bash
# 1. (on the VM) check the actual interface name
ip -br link

# 2. write /etc/netplan/00-network.yaml
sudo tee /etc/netplan/00-network.yaml >/dev/null <<'EOF'
network:
  version: 2
  renderer: networkd
  ethernets:
    ens18:
      dhcp4: false
      dhcp6: false
      addresses:
        - 192.168.1.50/24
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
        search: []
      routes:
        - to: default
          via: 192.168.1.1
EOF

sudo chmod 600 /etc/netplan/00-network.yaml

# 3. disable cloud-init network (KEY!)
echo 'network: {config: disabled}' | \
    sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg

# 4. remove the netplan generated by cloud-init
sudo rm -f /etc/netplan/50-cloud-init.yaml

# 5. clean cloud-init state and apply
sudo cloud-init clean --logs
sudo netplan generate
sudo netplan apply

# 6. reboot test (the real persistence judge)
sudo reboot
```

### Windows Server / Windows 10/11

The tool configures the VM on **SATA + e1000** at first boot to avoid BSOD. Once inside Windows, you have two optional steps:

**a) Install VirtIO drivers and Guest Agent** (always recommended):
1. From the `virtio-win.iso` mounted on `ide2`, run `virtio-win-gt-x64.msi` (full driver set) and `guest-agent\qemu-ga-x86_64.msi` (Guest Agent).
2. Reboot.

**b) Migrate disk to SCSI VirtIO** (better performance, optional):
1. From the Proxmox host, attach a dummy SCSI VirtIO disk: `qm set <VMID> --scsi0 <storage>:1,format=qcow2`
2. Reboot the VM. In **Device Manager → Storage controllers** verify that `Red Hat VirtIO SCSI controller` appears without errors.
3. From admin CMD on the VM, **arm `viostor` as a boot driver** (key step, prevents BSOD `INACCESSIBLE_BOOT_DEVICE` at next boot):
   ```cmd
   reg add "HKLM\SYSTEM\CurrentControlSet\Services\viostor"  /v Start /t REG_DWORD /d 0 /f
   reg add "HKLM\SYSTEM\CurrentControlSet\Services\vioscsi"  /v Start /t REG_DWORD /d 0 /f
   ```
4. Shutdown VM, swap disk from SATA to SCSI VirtIO + change NIC from e1000 to virtio:
   ```bash
   qm shutdown <VMID>
   qm set <VMID> --delete sata0 --delete scsi0
   qm set <VMID> --scsi0 <storage>:<vmid>/vm-<vmid>-disk-X.qcow2,discard=on,iothread=1
   qm set <VMID> --boot order=scsi0
   qm set <VMID> --net0 virtio=<MAC-OLD>,bridge=vmbr0
   qm start <VMID>
   ```

**c) Update UEFI 2023 certificates** (for VMs migrated before 2026-04 or to force):
```bash
qm shutdown <VMID>
qm enroll-efi-keys <VMID>     # do this with VM stopped
qm start <VMID>
```
If the VM has BitLocker active, suspend protectors first:
```powershell
manage-bde -protectors -disable C: -RebootCount 1
```

Troubleshooting

| Symptom | Diagnosis | Fix |
|---|---|---|
| BSOD `INACCESSIBLE_BOOT_DEVICE` (0x7B) just after Windows boot | `viostor` not armed as boot driver, or disk attached to SCSI VirtIO without driver present | Reattach disk on `sata0` with `qm set --delete scsi0 --sata0 ...,discard=on`, boot, apply the `reg add` above, then redo the swap |
| Windows boot stuck at "Start boot option" / OVMF logo | Corrupt EFI NVRAM or wrong boot order | `qm set <VMID> --boot order=sata0`. If it persists: ESC during OVMF logo → Boot Manager → Boot from File → `EFI\Microsoft\Boot\bootmgfw.efi` |
| Linux loses IP config after each reboot | cloud-init regenerates the netplan | Disable cloud-init network (see Linux post-migration section) |
| Linux: interface name different from `ens18` | NIC at unexpected PCI slot or UEFI vs BIOS difference | Edit the netplan key; the real name is in `ip -br link` |
| Disk lands as `raw` instead of `qcow2` on NFS | Tool version < 2026-04, missing `--format qcow2` fix | Update the tool, or manually: `qemu-img convert -O qcow2 vm-N-disk-X.raw vm-N-disk-X.qcow2` then `qm set --scsi0 ...qcow2` |
| "Conversion/Import" progress bar stuck at 0% then jumps to 100% | Tool version < 2026-04 (regex parser bug + buffering) | Update the tool: now uses `stdbuf -oL` and correct regex on `(NN.NN/100%)` |
| Warning "UEFI 2011 certificates expire June 2026" | `efidisk0` created without `ms-cert=2023k` | `qm enroll-efi-keys <VMID>` with VM stopped |
| Migrated Windows DC fights with the original DC still alive | Same AD identity active simultaneously | Migrate with NIC `link_down=1` (UI toggle), then power off the original DC before bringing the link up |
| Source ESXi has unconsolidated snapshots | The `-000001-sesparse.vmdk` chain is followed by `qemu-img convert` but it's slow and fragile | Consolidate snapshots on ESXi before migration: `vim-cmd vmsvc/snapshot.removeall <VMID>` |

Tests

A small test suite covers the regression-prone bits:

```
python -m unittest discover -s tests -v
```

Tests included:
- `tests/test_guestos_mapping.py` — guestOS → Proxmox profile (`map_guestos_to_proxmox`).
- `tests/test_progress_parser.py` — fixes the qemu-img `(NN.NN/100%)` parser bug.
- `tests/test_proxmox_commands.py` — generated `qm` command shape (importdisk format, attach bus, UEFI cert).

Desktop UI Screenshots

1. Project Creation
   ![Project Creation](docs/screenshots/projct.PNG)
2. Connection and Scan
   ![Connection and Scan](docs/screenshots/connection_scan.PNG)
3. Options and Migration
   ![Options and Migration](docs/screenshots/options_migration.png)
