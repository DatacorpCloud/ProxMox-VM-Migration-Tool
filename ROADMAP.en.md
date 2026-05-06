Roadmap

Features still to be implemented. For what has already been delivered, see the [CHANGELOG](CHANGELOG.md).

## Multi-VM concurrent migration

- Multiple VM selection from scan with execution queue
- Configurable concurrency limit (e.g., 2–3 parallel jobs) and per-VM priority
- Progress aggregation per single VM + batch total
- Cancel/pause of a single job without interrupting the others

## Transfer resilience

- Resume of an interrupted copy (resumes from current byte instead of starting over)
- Automatic retry with exponential backoff on transient network errors
- Post-copy validation with optional checksum (sha256 on the flat file)
- Pre-flight health check: disk space, ESXi/Proxmox reachability, storage permissions

## Post-migration helpers (new, from real-world experience)

Automate the steps that are currently manual and documented in the README:

- **Linux**: detect and automatically disable cloud-init's network management to make the post-migration netplan persistent. Possible injection of the right netplan via SSH inside the VM at first boot.
- **Windows**: guided helper for the "VirtIO dance" (dummy disk → reboot → arm `viostor`/`vioscsi` via registry → swap to SCSI VirtIO) with user confirmation between steps.
- Automatic UEFI 2023k certificate update for VMs migrated before the fix.

## Reporting

- Export migration report in JSON/CSV (timing per phase, sizes, outcome)
- Aggregate metrics on the Home Dashboard (average duration, effective MB/s, success rate)
- Persistent audit log of completed migrations

## Conversion / Import

- Additional Proxmox storage support: ZFS, Ceph RBD, LVM-thin
- `qemu-img` compression presets (zstd where supported, configurable levels)
- Streaming conversion via SSH pipe (eliminating the intermediate file on Proxmox)

## Configuration & projects

- Reusable project templates (preset mappings for storage/bridge/OS profile)
- Import/export of non-sensitive settings
- Preventive project validation before run

## Quality & CI

- GitHub Actions workflow: run test suite + lint on every PR
- Linter/formatter (black + ruff) with shared configuration
- Extend test suite to backup/restore flows (today only the core blocks are covered)

## Security

- SSH key-based authentication instead of password (for both Proxmox and ESXi)
- Secret management via environment variables or dedicated file (alternative to local SQLite)
- SSH session hardening: known_hosts pinning, disable weak algorithms
- Automatic rotation of iSCSI CHAP credentials after recovery
