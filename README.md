# 🧩 ProxMox VM Migration Tool  
_Migrate your virtual machines seamlessly from VMware ESXi to Proxmox VE_

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-green.svg)]()
[![Platform](https://img.shields.io/badge/Platform-Proxmox%20%7C%20ESXi-orange.svg)]()

---

## 🚀 Overview

**ProxMox VM Migration Tool** is a desktop utility to migrate virtual machines from **VMware ESXi** to **Proxmox VE**.  
It copies VMDK disks from ESXi, converts them using `qemu-img`, and imports them to target storage with automatic VM configuration — including optional UEFI/OVMF setup.

### ✨ Key Features
- Secure SCP transfer from ESXi via `sshpass` (password file, no plaintext).
- Conversion and import into any Proxmox storage (`images`, `dir`, etc.).
- Optional **UEFI/OVMF** configuration (`q35`, `efidisk0` with pre-enrolled keys).
- UI workflow: **Connect & Scan → Options → Migration**.
- Progress bars + detailed log file for transparency.

---

## ⚙️ Requirements
- Python **3.9+**
- Proxmox VE reachable via SSH
- ESXi host reachable via SSH (user with read access to datastore)

---

## 🧭 Quick Start

```bash
# Install dependencies
pip install -r vm-migration-tool/requirements.txt

# Run the application
python vm-migration-tool/main.py
