Roadmap

- Multi-VM concurrent migration
  - Multiple VM selection from scan with a safe parallel queue
  - Configurable concurrency limit (e.g., 2–3 jobs) and prioritization
  - Progress aggregation per VM and for the whole batch

- Transfer resilience
  - Resume on interrupted copy (rsync/scp + size verification)
  - Error detection and automatic retry with backoff
  - Post-copy validation with optional checksums

- UX & logging
  - Separate progress log channel (implemented)
  - Export migration reports to JSON/CSV
  - Log filters and automatic secret redaction (implemented)

- Conversion/Import
  - Advanced `qemu-img` compression and compatibility options
  - Support additional storages and content types (images, rootdir, dir, zfs)

- Configuration & projects
  - Save only non-sensitive settings (passwords excluded by design)
  - Project templates and validation

- Quality & CI
  - Unit tests for parsing/progress
  - Linting/formatting and a GitHub Actions CI workflow

- Security
  - Secret management via files/environment variables
  - SSH hardening and key management