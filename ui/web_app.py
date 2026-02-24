import json
import queue
import threading
import time
import uuid
import os
import tempfile
import shutil
import sqlite3
import subprocess
import re
import shlex
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List, Tuple
from flask import Flask, Response, jsonify, request

from core.ssh_client import SSHClient
from core.esxi_import import (
    write_esxi_password_file,
    list_vms,
    list_vms_direct,
    esxi_power_state_direct,
    esxi_get_summary_direct,
    esxi_get_config_direct,
    esxi_get_devices_direct,
    esxi_get_filelayout_direct,
    esxi_find_vmid_by_vmx,
    esxi_create_snapshot,
    esxi_create_snapshot_direct,
    esxi_find_snapshot_id_by_name,
    esxi_find_snapshot_id_by_name_direct,
    esxi_remove_snapshot,
)
from core.migration_flow import execute_full_migration
from core.proxmox import (
    list_storages,
    list_bridges,
    get_next_vmid,
    qm_create,
    qm_importdisk,
    qm_importdisk_with_progress,
    qm_attach_scsi,
    qm_set_boot,
    qm_start,
    qm_set_uefi,
    parse_importdisk_disk_id,
    storage_supports_images,
)
from core.transfer import (
    ensure_dir,
    guess_vmdk_data_rel,
    copy_vmdk_flat_with_progress,
    copy_vmdk_from_esxi,
    copy_file_from_esxi,
)


INDEX_HTML = """<!doctype html>
<html lang="it">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>VM Backup & Migration Tool</title>
    <style>
      :root {
        --bg: #0b1020;
        --panel: #0f172a;
        --panel2: #111b33;
        --text: #e5e7eb;
        --muted: #94a3b8;
        --border: rgba(148, 163, 184, 0.20);
        --accent: #22c55e;
        --accent2: #3b82f6;
        --danger: #ef4444;
        --shadow: 0 8px 28px rgba(0,0,0,.35);
        color-scheme: dark;
      }
      * { box-sizing: border-box; }
      body {
        font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
        margin: 0;
        background: radial-gradient(1200px 800px at 20% -10%, rgba(34, 197, 94, 0.20), transparent 60%),
                    radial-gradient(900px 700px at 90% 10%, rgba(59, 130, 246, 0.22), transparent 55%),
                    var(--bg);
        color: var(--text);
      }
      input, select, button { padding: 8px 10px; font-size: 14px; }
      input, select {
        width: 100%;
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid var(--border);
        color: var(--text);
        border-radius: 10px;
        outline: none;
      }
      select { color-scheme: dark; }
      select option, select optgroup {
        background: var(--panel);
        color: var(--text);
      }
      input::placeholder { color: rgba(148, 163, 184, 0.65); }
      button {
        border: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.04);
        color: var(--text);
        border-radius: 10px;
        cursor: pointer;
        transition: transform 0.08s ease, background 0.12s ease, border-color 0.12s ease;
      }
      button:active { transform: translateY(1px); }
      button:hover { background: rgba(255, 255, 255, 0.07); border-color: rgba(148, 163, 184, 0.35); }
      button.primary { background: rgba(34, 197, 94, 0.16); border-color: rgba(34, 197, 94, 0.35); }
      button.danger { background: rgba(239, 68, 68, 0.14); border-color: rgba(239, 68, 68, 0.35); }
      button.secondary { opacity: 0.8; }
      button:disabled { opacity: 0.45; cursor: not-allowed; transform: none; }

      .app { display: grid; grid-template-columns: 270px 1fr; min-height: 100vh; }
      .sidebar {
        border-right: 1px solid var(--border);
        background: rgba(15, 23, 42, 0.75);
        backdrop-filter: blur(10px);
        padding: 14px 12px;
      }
      .brand { padding: 10px 10px 14px 10px; }
      .brandTitle { font-size: 14px; letter-spacing: 0.3px; font-weight: 700; }
      .brandSub { font-size: 12px; color: var(--muted); margin-top: 2px; }
      .navCol { display: flex; flex-direction: column; gap: 8px; }
      .navGroupTitle { margin-top: 10px; font-size: 11px; color: rgba(148, 163, 184, 0.85); text-transform: uppercase; letter-spacing: 0.08em; padding: 0 10px; }
      .navCol button { text-align: left; padding: 10px 10px; }
      .navCol button.active { background: rgba(59, 130, 246, 0.16); border-color: rgba(59, 130, 246, 0.35); opacity: 1; }

      .main { padding: 18px; }
      .topbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 12px 14px;
        border: 1px solid var(--border);
        border-radius: 14px;
        background: rgba(15, 23, 42, 0.60);
        backdrop-filter: blur(10px);
        box-shadow: var(--shadow);
      }
      #pageTitle { font-weight: 700; letter-spacing: 0.2px; }
      .content { margin-top: 14px; }
      .card {
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 14px;
        background: rgba(15, 23, 42, 0.60);
        backdrop-filter: blur(10px);
        box-shadow: var(--shadow);
      }
      .hidden { display: none !important; }
      .muted { color: var(--muted); font-size: 12px; }
      .row { margin: 14px 0; }
      .grid { display: grid; grid-template-columns: 260px 1fr; gap: 10px 12px; align-items: center; }
      .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
      .toolbar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; justify-content: space-between; }
      .toolbarLeft { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }

      .dash { display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 12px; margin-top: 12px; }
      .dashCard { border: 1px solid var(--border); background: rgba(255,255,255,0.03); border-radius: 14px; padding: 12px; }
      .dashLabel { font-size: 12px; color: var(--muted); }
      .dashValue { font-size: 22px; font-weight: 800; margin-top: 6px; }

      .bar { height: 16px; background: rgba(255,255,255,0.07); border-radius: 10px; overflow: hidden; border: 1px solid var(--border); }
      .bar > div { height: 100%; width: 0%; background: var(--accent2); transition: width 0.15s; }
      .bar.ops > div { background: var(--accent); }

      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: 10px; border-bottom: 1px solid var(--border); font-size: 13px; }
      th { color: rgba(229, 231, 235, 0.90); font-weight: 650; }
      tbody tr { cursor: pointer; }
      tbody tr:hover { background: rgba(255,255,255,0.03); }
      tbody tr.sel { background: rgba(59, 130, 246, 0.12); }

      pre { background: rgba(2, 6, 23, 0.78); color: #e5e7eb; padding: 12px; border-radius: 12px; border: 1px solid var(--border); height: 260px; overflow: auto; }

      .modal {
        position: fixed;
        inset: 0;
        background: rgba(2, 6, 23, 0.70);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 16px;
        z-index: 50;
      }
      .modalCard {
        width: min(860px, 100%);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 14px;
        background: rgba(15, 23, 42, 0.92);
        box-shadow: var(--shadow);
      }
      .modalTop { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
      .modalTitle { font-weight: 750; }
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: 10px; border-bottom: 1px solid var(--border); font-size: 13px; }
    </style>
  </head>
  <body>
    <div class="app">
      <aside class="sidebar">
        <div class="brand">
          <div class="brandTitle">VM Backup & Migration Tool</div>
          <div class="brandSub">Home • Job • Risorse • VM Backup • Sistema</div>
        </div>
        <div class="navCol">
          <button id="navHome">Home</button>
          <button id="navJobs" class="secondary">Job</button>

          <div class="navGroupTitle">Risorse</div>
          <button id="navResources" class="secondary">Virtualizzatori</button>
          <button id="navStorage" class="secondary">Storage</button>

          <div class="navGroupTitle">VM Backup</div>
          <button id="navBackup" class="secondary">Backup</button>
          <button id="navRestore" class="secondary">Restore</button>
          <button id="navCross" class="secondary">Cross Migration</button>

          <div class="navGroupTitle">Sistema</div>
          <button id="navSystem" class="secondary">Log</button>
        </div>
      </aside>

      <main class="main">
        <div class="topbar">
          <div id="pageTitle">Home</div>
          <div class="muted">MVP: risorse (SQLite) • inventario • repo backup • migrazione</div>
        </div>

        <div class="content">
          <div id="pageHome" class="card">
            <h2>Home</h2>
            <div class="muted">Panoramica rapida</div>
            <div class="row grid">
              <div>Repository (backup)</div>
              <select id="homeRepoStorage" disabled></select>
            </div>
            <div class="dash">
              <div class="dashCard">
                <div class="dashLabel">Backup eseguiti</div>
                <div id="homeBackupsTotal" class="dashValue">0</div>
              </div>
              <div class="dashCard">
                <div class="dashLabel">Totale GB in backup</div>
                <div id="homeBackupsGb" class="dashValue">0</div>
              </div>
              <div class="dashCard">
                <div class="dashLabel">VM sotto backup</div>
                <div id="homeVmsBackedUp" class="dashValue">0</div>
              </div>
              <div class="dashCard">
                <div class="dashLabel">VM migrate piattaforma</div>
                <div id="homeVmsMigrated" class="dashValue">0</div>
              </div>
            </div>
          </div>

    <div id="pageBackup" class="card hidden">
      <h2>Backup</h2>
      <div class="muted">Seleziona infrastruttura, scegli una VM e avvia il backup</div>
      <div class="row grid">
        <div>Virtualizzatore</div>
        <select id="backupVirt">
          <option value="esxi" selected>ESXi</option>
          <option value="proxmox">Proxmox</option>
        </select>
      </div>
      <div class="row grid" id="rowBackupPmx">
        <div>Proxmox (risorsa)</div><select id="infraPmx" disabled></select>
      </div>
      <div class="row grid" id="rowBackupEsxi">
        <div>ESXi (risorsa)</div><select id="infraEsxi" disabled></select>
      </div>
      <div class="row grid">
        <div>Nome backup</div><input id="backupLabel" placeholder="es. Win10-test-2026-02-17" />
        <div></div><div></div>
      </div>
      <div class="row grid">
        <div>Storage (repo)</div><select id="backupRepoStorage" disabled></select>
      </div>
      <div class="row grid">
        <div>Downtime</div>
        <label style="display:flex; gap:8px; align-items:center;">
          <input id="allowPowerOff" type="checkbox" />
          <span>Se necessario spegni la VM per copiare i dischi</span>
        </label>
        <div></div><div></div>
      </div>
      <div class="row grid">
        <div>Snapshot</div>
        <label style="display:flex; gap:8px; align-items:center;">
          <input id="removeSnapshotAfter" type="checkbox" checked />
          <span>Rimuovi snapshot dopo backup</span>
        </label>
        <div></div><div></div>
      </div>
      <div class="row actions">
        <button id="btnInfraPmx" disabled>Lista VM Proxmox</button>
        <button id="btnInfraEsxi" disabled>Lista VM ESXi</button>
        <button id="btnBackupRun" disabled>Avvia backup</button>
        <span class="muted" id="infraStatus"></span>
      </div>
      <div class="row">
        <table>
          <thead><tr><th>Fonte</th><th>ID/Name</th><th>Stato</th><th>Dettagli</th></tr></thead>
          <tbody id="infraTable"></tbody>
        </table>
      </div>
      <div class="row">
        <div class="muted">Impostazioni VM (seleziona una riga)</div>
        <pre id="infraDetails"></pre>
      </div>
    </div>

    <div id="pageJobs" class="card hidden">
      <h2>Job</h2>
      <div class="muted">Elenco attività (1 job alla volta per i test)</div>
      <div class="row actions">
        <button id="btnJobsRefresh">Aggiorna</button>
        <button id="btnJobStart" disabled>Avvia job</button>
        <span class="muted" id="jobsStatus"></span>
      </div>
      <div class="row">
        <table>
          <thead><tr><th>Data</th><th>VM</th><th>GB</th><th>Stato</th><th>Copia%</th><th>Ops%</th><th>MB/s</th><th>Tipo</th><th>ID</th><th>Errore</th></tr></thead>
          <tbody id="jobsTable"></tbody>
        </table>
      </div>
      <div class="row">
        <div class="muted">Dettaglio job (click su una riga)</div>
        <pre id="jobDetails"></pre>
      </div>
    </div>

    <div id="pageRestore" class="card hidden">
      <h2>Restore</h2>
      <div class="muted">Seleziona un backup dal repository e ripristina la VM</div>

      <div class="row actions">
        <button id="btnRestoreTabSimple" class="primary">Ripristino</button>
        <button id="btnRestoreTabXplat" class="secondary">Ripristino multi‑piattaforma</button>
        <span class="muted" id="repoStatus"></span>
      </div>

      <div class="row grid">
        <div>Storage (repo)</div><select id="restoreRepoStorage" disabled></select>
        <div>Backup (repo)</div><select id="backupSelect" disabled></select>
      </div>

      <div id="restoreSimple">
        <div class="row grid">
          <div>Piattaforma backup</div><input id="restoreDetectedPlatform" value="" disabled />
          <div>Ripristina su</div><input id="restoreTargetPlatform" value="" disabled />
        </div>
        <div class="row grid" id="restoreSimplePmx">
          <div>Proxmox (dest.)</div><select id="restorePmxDest" disabled></select>
          <div>Storage (Proxmox)</div><select id="restorePmxStorage" disabled></select>
          <div>Bridge</div><select id="restorePmxBridge" disabled></select>
          <div>VMID (opz.)</div><input id="restorePmxVmid" value="" />
        </div>
        <div class="row grid hidden" id="restoreSimpleEsxi">
          <div>ESXi (dest.)</div><select id="restoreEsxiDest" disabled></select>
          <div>Datastore (ESXi)</div><select id="restoreEsxiDatastore" disabled></select>
        </div>
        <div class="row grid">
          <div>Nome VM ripristinata (opz.)</div><input id="restoreVmName" value="" />
          <div>Avvio</div>
          <label style="display:flex; gap:8px; align-items:center;">
            <input id="restoreStartVm" type="checkbox" checked />
            <span>Avvia dopo ripristino</span>
          </label>
        </div>
        <div class="row grid">
          <div>RAM (MB)</div><input id="restoreMem" value="4096" />
          <div>vCPU</div><input id="restoreCores" value="2" />
          <div>UEFI/OVMF</div>
          <select id="restoreUefi">
            <option value="false" selected>Disabilitato</option>
            <option value="true">Abilitato</option>
          </select>
        </div>
        <div class="row actions">
          <button id="btnRestoreSimple" disabled>Avvia ripristino</button>
          <span class="muted" id="restoreSimpleStatus"></span>
        </div>
      </div>

      <div id="restoreXplat" class="hidden">
        <div class="muted">Ripristino su altra piattaforma (Proxmox ⇄ VMware)</div>
        <div class="row grid">
          <div>Origine</div><input id="migOrigin" value="" disabled />
          <div>Destinazione</div><input id="migDest" value="" disabled />
          <div>Proxmox (dest.)</div><select id="repoPmx" disabled></select>
          <div>Proxmox (worker)</div><select id="repoPmxWorker" disabled></select>
          <div>Storage temp (worker)</div><select id="repoPmxWorkerTmp" disabled></select>
          <div>ESXi (dest.)</div><select id="repoEsxi" disabled></select>
          <div>Datastore (ESXi)</div><select id="repoEsxiDatastore" disabled></select>
        </div>
        <div class="row actions">
          <button id="btnRefreshBackups">Aggiorna elenco backup</button>
          <button id="btnRestore" disabled>Importa su Proxmox</button>
          <button id="btnImportVmware" disabled>Importa su VMware</button>
        </div>
      </div>

      <div class="row actions">
        <button id="btnRefreshBackups2">Aggiorna elenco backup</button>
      </div>
      <div class="row">
        <table>
          <thead><tr><th>Data</th><th>Backup</th><th>Fonte</th><th>VM</th></tr></thead>
          <tbody id="backupsTable"></tbody>
        </table>
      </div>
    </div>

    <div id="pageCross" class="card hidden">
      <h2>Cross Migration</h2>
      <div class="muted">Migrazione diretta ESXi ⇄ Proxmox e cattura backup</div>
      <div class="row grid">
        <div>Proxmox (risorsa)</div><select id="pmxSel" disabled></select>
        <div>ESXi (risorsa)</div><select id="esxiSel" disabled></select>
      </div>
      <div class="row actions">
        <button id="btnScan" disabled>Scansiona ESXi + Proxmox</button>
        <span class="muted" id="scanStatus"></span>
      </div>

      <div class="row grid">
        <div>VM (da ESXi)</div><select id="vmSelect" disabled></select>
        <div>Storage (Proxmox)</div><select id="storageSelect" disabled></select>
        <div>Bridge (Proxmox)</div><select id="bridgeSelect" disabled></select>
        <div>VMID</div><input id="vmid" value="" />
        <div>Nome VM</div><input id="vmname" value="" />
        <div>RAM (MB)</div><input id="mem" value="4096" />
        <div>vCPU</div><input id="cores" value="2" />
        <div>UEFI/OVMF</div>
        <select id="uefi">
          <option value="false" selected>Disabilitato</option>
          <option value="true">Abilitato</option>
        </select>
        <div>Snapshot ESXi (hot)</div>
        <select id="snapshot">
          <option value="true" selected>Sì</option>
          <option value="false">No</option>
        </select>
        <div>Converti con qemu-img</div>
        <select id="convert">
          <option value="false" selected>No</option>
          <option value="true">Sì</option>
        </select>
        <div>Formato</div>
        <select id="format">
          <option value="qcow2" selected>qcow2</option>
          <option value="raw">raw</option>
          <option value="vmdk">vmdk</option>
        </select>
        <div>Dest dir (opz.)</div><input id="destDir" placeholder="/mnt/pve/<storage>/tmp/<vm>" />
      </div>

      <div class="row actions">
        <button id="btnStart" disabled>Avvia migrazione</button>
        <button id="btnCapture" disabled>Cattura backup (repo)</button>
        <span class="muted" id="jobStatus"></span>
      </div>

      <div class="row">
        <div class="muted">Copia</div>
        <div class="bar"><div id="barCopy"></div></div>
        <div class="muted" id="msgCopy"></div>
      </div>
      <div class="row">
        <div class="muted">Conversione / Import / Avvio</div>
        <div class="bar ops"><div id="barOps"></div></div>
        <div class="muted" id="msgOps"></div>
      </div>
    </div>

    <div id="pageResources" class="card hidden">
      <h2>Risorse • Virtualizzatori</h2>
      <div class="muted">Add / Edit / Delete (credenziali salvate in SQLite locale)</div>
      <div class="row toolbar">
        <div class="toolbarLeft">
          <button id="btnResCreate" class="primary">Add</button>
          <button id="btnResEdit" class="secondary" disabled>Edit</button>
          <button id="btnResDelete" class="danger" disabled>Delete</button>
        </div>
        <span class="muted" id="resStatus"></span>
      </div>
      <div class="row">
        <table>
          <thead><tr><th>Tipo</th><th>Nome</th><th>Host</th><th>User</th><th>Porta</th></tr></thead>
          <tbody id="resTable"></tbody>
        </table>
      </div>
    </div>

    <div id="pageStorage" class="card hidden">
      <h2>Risorse • Storage</h2>
      <div class="muted">NFS / iSCSI</div>
      <div class="row toolbar">
        <div class="toolbarLeft">
          <button id="btnStoCreate" class="primary">Add</button>
          <button id="btnStoEdit" class="secondary" disabled>Edit</button>
          <button id="btnStoDelete" class="danger" disabled>Delete</button>
          <button id="btnStoTest" class="secondary" disabled>Test</button>
        </div>
        <span class="muted" id="stoStatus"></span>
      </div>
      <div class="row">
        <table>
          <thead><tr><th>Tipo</th><th>Nome</th><th>Host</th><th>Percorso/Target</th><th>User</th><th>Porta</th></tr></thead>
          <tbody id="stoTable"></tbody>
        </table>
      </div>
    </div>

    <div id="pageSystem" class="card hidden">
      <h2>Sistema • Log</h2>
      <div class="muted">Log runtime dell'interfaccia e dei job</div>
      <div class="row grid">
        <div>Repository locale</div><input id="repoPath" placeholder="C:\\backup\\vm-migration-tool" />
        <div></div><button id="btnRepoPathSave" class="primary">Salva</button>
      </div>
      <div class="row">
        <span class="muted" id="sysStatus"></span>
      </div>
      <div class="row">
        <pre id="log"></pre>
      </div>
    </div>

    <div id="resModal" class="modal hidden">
      <div class="modalCard">
        <div class="modalTop">
          <div class="modalTitle" id="resModalTitle">Risorsa</div>
          <button id="btnResModalClose" class="secondary">Chiudi</button>
        </div>
        <div class="row grid">
          <div>Tipo</div>
          <select id="resKind">
            <option value="proxmox" selected>Proxmox</option>
            <option value="esxi">VMware / ESXi</option>
          </select>
          <div>Nome</div><input id="resName" placeholder="es. PVE-DC1" />
          <div>Host/IP</div><input id="resHost" placeholder="10.0.0.10" />
          <div>User</div><input id="resUser" placeholder="root@pam" />
          <div>Password</div><input id="resPass" type="password" />
          <div>Porta</div><input id="resPort" value="22" />
        </div>
        <div class="row actions">
          <button id="btnResAdd" class="primary">Salva</button>
          <button id="btnResClear" class="secondary">Pulisci</button>
        </div>
      </div>
    </div>

    <div id="stoModal" class="modal hidden">
      <div class="modalCard">
        <div class="modalTop">
          <div class="modalTitle" id="stoModalTitle">Storage</div>
          <button id="btnStoModalClose" class="secondary">Chiudi</button>
        </div>
        <div class="row grid">
          <div>Tipo</div>
          <select id="stoKind">
            <option value="nfs" selected>NFS</option>
            <option value="iscsi">iSCSI</option>
          </select>
          <div>Nome</div><input id="stoName" placeholder="es. NAS-01" />
          <div>Host/IP</div><input id="stoHost" placeholder="10.0.0.20" />
          <div>Percorso/Target</div><input id="stoPath" placeholder="Z:\\backup oppure \\\\nas\\share\\backup oppure /export/backup" />
          <div>User</div><input id="stoUser" placeholder="opzionale" />
          <div>Password</div><input id="stoPass" type="password" />
          <div>Porta</div><input id="stoPort" value="2049" />
        </div>
        <div class="row actions">
          <button id="btnStoSave" class="primary">Salva</button>
          <button id="btnStoClear" class="secondary">Pulisci</button>
        </div>
      </div>
    </div>

    <script>
      const el = (id) => document.getElementById(id);
      const logEl = el("log");
      function log(line) {
        logEl.textContent += line + "\\n";
        logEl.scrollTop = logEl.scrollHeight;
      }

      let scanId = null;
      let eventSource = null;
      let jobsEventSource = null;
      let selectedResourceId = null;
      let selectedInfraEsxiVmid = null;
      let selectedInfraPmxVmid = null;
      let selectedJobId = null;
      let selectedJobData = null;
      let selectedJobLogs = [];
      let resources = [];
      let storages = [];
      let selectedStorageId = null;
      let backupsCache = [];

      function setPageTitle(pageId) {
        const titles = {
          pageHome: "Home",
          pageJobs: "Job",
          pageResources: "Risorse • Virtualizzatori",
          pageStorage: "Risorse • Storage",
          pageBackup: "VM Backup • Backup",
          pageRestore: "VM Backup • Restore",
          pageCross: "VM Backup • Cross Migration",
          pageSystem: "Sistema • Log"
        };
        if (el("pageTitle")) el("pageTitle").textContent = titles[pageId] || "VM Backup & Migration Tool";
      }

      function setProgress(copyPct, copyMsg, opsPct, opsMsg) {
        if (typeof copyPct === "number") el("barCopy").style.width = Math.max(0, Math.min(100, copyPct)) + "%";
        if (typeof opsPct === "number") el("barOps").style.width = Math.max(0, Math.min(100, opsPct)) + "%";
        if (typeof copyMsg === "string") el("msgCopy").textContent = copyMsg;
        if (typeof opsMsg === "string") el("msgOps").textContent = opsMsg;
      }

      async function api(path, payload) {
        const res = await fetch(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const msg = data && data.error ? data.error : ("HTTP " + res.status);
          throw new Error(msg);
        }
        return data;
      }

      async function apiGet(path) {
        const res = await fetch(path, { method: "GET" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const msg = data && data.error ? data.error : ("HTTP " + res.status);
          throw new Error(msg);
        }
        return data;
      }

      function fillSelect(selectEl, items, getLabel) {
        selectEl.innerHTML = "";
        for (const it of items) {
          const opt = document.createElement("option");
          opt.value = it.value;
          opt.textContent = getLabel(it);
          selectEl.appendChild(opt);
        }
        selectEl.disabled = items.length === 0;
      }

      function updateInfraButtons() {
        const virt = (el("backupVirt").value || "esxi").trim();
        const hasPmx = !!(el("infraPmx").value || "").trim();
        const hasEsxi = !!(el("infraEsxi").value || "").trim();
        el("btnInfraPmx").disabled = !hasPmx;
        el("btnInfraEsxi").disabled = !hasEsxi;
        if (virt !== "esxi") selectedInfraEsxiVmid = null;
        if (virt !== "proxmox") selectedInfraPmxVmid = null;
        el("btnBackupRun").disabled = !(
          (virt === "esxi" && hasEsxi && selectedInfraEsxiVmid) ||
          (virt === "proxmox" && hasPmx && selectedInfraPmxVmid)
        );
        el("btnInfraPmx").style.display = virt === "proxmox" ? "" : "none";
        el("btnInfraEsxi").style.display = virt === "esxi" ? "" : "none";
        if (virt === "proxmox") {
          el("infraStatus").textContent = hasPmx ? "Lista VM Proxmox" : "Seleziona una risorsa Proxmox";
        } else {
          el("infraStatus").textContent = hasEsxi ? "" : "Seleziona una risorsa ESXi";
        }
      }

      function updateBackupVirtUI() {
        const virt = (el("backupVirt").value || "esxi").trim();
        if (el("rowBackupPmx")) el("rowBackupPmx").style.display = virt === "proxmox" ? "" : "none";
        if (el("rowBackupEsxi")) el("rowBackupEsxi").style.display = virt === "esxi" ? "" : "none";
        const tbody = el("infraTable");
        if (tbody) tbody.innerHTML = "";
        if (el("infraDetails")) el("infraDetails").textContent = "";
        updateInfraButtons();
      }

      function showPage(pageId) {
        const pages = ["pageHome", "pageResources", "pageStorage", "pageBackup", "pageRestore", "pageCross", "pageJobs", "pageSystem"];
        for (const p of pages) {
          const node = el(p);
          if (!node) continue;
          node.classList.toggle("hidden", p !== pageId);
        }
        const navMap = {
          pageHome: "navHome",
          pageJobs: "navJobs",
          pageResources: "navResources",
          pageStorage: "navStorage",
          pageBackup: "navBackup",
          pageRestore: "navRestore",
          pageCross: "navCross",
          pageSystem: "navSystem"
        };
        for (const [p, navId] of Object.entries(navMap)) {
          const btn = el(navId);
          if (!btn) continue;
          const active = p === pageId;
          btn.classList.toggle("active", active);
          btn.classList.toggle("secondary", !active);
        }
        setPageTitle(pageId);
        if (pageId !== "pageJobs" && jobsEventSource) {
          try { jobsEventSource.close(); } catch (_) {}
          jobsEventSource = null;
        }
      }

      function fmtDate(ms) {
        try {
          const d = new Date(Number(ms || 0));
          if (!isFinite(d.getTime())) return "";
          const pad = (n) => String(n).padStart(2, "0");
          return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
        } catch (_) {
          return "";
        }
      }

      function updateMigrationSelection() {
        const backupId = (el("backupSelect") ? el("backupSelect").value : "") || "";
        const b = (backupsCache || []).find(x => x.backup_id === backupId) || null;
        const st = (b && b.source_type ? String(b.source_type) : "").trim();
        let origin = "VMware";
        let dest = "Proxmox";
        if (st === "proxmox-vzdump") {
          origin = "Proxmox";
          dest = "VMware";
        }
        if (el("migOrigin")) el("migOrigin").value = origin;
        if (el("migDest")) el("migDest").value = dest;
        const hasBackup = !!backupId;
        const hasPmx = !!((el("repoPmx") && el("repoPmx").value) || "").trim();
        const hasEsxi = !!((el("repoEsxi") && el("repoEsxi").value) || "").trim();
        const hasWorker = !!((el("repoPmxWorker") && el("repoPmxWorker").value) || "").trim();
        const hasEsxiDs = !!((el("repoEsxiDatastore") && el("repoEsxiDatastore").value) || "").trim();

        if (el("repoPmx")) el("repoPmx").disabled = !(dest === "Proxmox");
        if (el("repoPmxWorker")) el("repoPmxWorker").disabled = !(dest === "VMware");
        if (el("repoPmxWorkerTmp")) el("repoPmxWorkerTmp").disabled = !(dest === "VMware" && hasWorker);
        if (el("repoEsxi")) el("repoEsxi").disabled = !(dest === "VMware");
        if (el("repoEsxiDatastore")) el("repoEsxiDatastore").disabled = !(dest === "VMware" && hasEsxi);

        if (el("btnRestore")) el("btnRestore").disabled = !(hasBackup && hasPmx && dest === "Proxmox");
        if (el("btnImportVmware")) el("btnImportVmware").disabled = !(hasBackup && dest === "VMware" && hasWorker && hasEsxi && hasEsxiDs);
      }

      let restoreTab = "simple";

      function setRestoreTab(tab) {
        restoreTab = (tab === "xplat") ? "xplat" : "simple";
        if (el("restoreSimple")) el("restoreSimple").classList.toggle("hidden", restoreTab !== "simple");
        if (el("restoreXplat")) el("restoreXplat").classList.toggle("hidden", restoreTab !== "xplat");
        if (el("btnRestoreTabSimple")) el("btnRestoreTabSimple").classList.toggle("secondary", restoreTab !== "simple");
        if (el("btnRestoreTabXplat")) el("btnRestoreTabXplat").classList.toggle("secondary", restoreTab !== "xplat");
        if (el("btnRestoreTabSimple")) el("btnRestoreTabSimple").classList.toggle("primary", restoreTab === "simple");
        if (el("btnRestoreTabXplat")) el("btnRestoreTabXplat").classList.toggle("primary", restoreTab === "xplat");
        updateRestoreSimpleSelection();
        updateMigrationSelection();
      }

      function updateRestoreSimpleSelection() {
        const backupId = (el("backupSelect") ? el("backupSelect").value : "") || "";
        const b = (backupsCache || []).find(x => x.backup_id === backupId) || null;
        const st = (b && b.source_type ? String(b.source_type) : "").trim();
        const isPmx = st === "proxmox-vzdump";
        const isEsxiDirect = st === "esxi-direct";

        if (el("restoreDetectedPlatform")) el("restoreDetectedPlatform").value = isPmx ? "Proxmox" : (isEsxiDirect ? "VMware" : "");
        if (el("restoreTargetPlatform")) el("restoreTargetPlatform").value = isPmx ? "Proxmox" : (isEsxiDirect ? "VMware" : "");

        if (el("restoreSimplePmx")) el("restoreSimplePmx").classList.toggle("hidden", !isPmx);
        if (el("restoreSimpleEsxi")) el("restoreSimpleEsxi").classList.toggle("hidden", !isEsxiDirect);

        const hasBackup = !!backupId;
        const vmNameEl = el("restoreVmName");
        if (vmNameEl && hasBackup && !(vmNameEl.value || "").trim()) {
          const suggested = (b && (b.vm_name || b.label_user || b.label)) ? String(b.vm_name || b.label_user || b.label).trim() : "";
          if (suggested) vmNameEl.value = suggested;
        }

        const pmxOk = isPmx
          && !!((el("restorePmxDest")?.value || "").trim())
          && !!((el("restorePmxStorage")?.value || "").trim())
          && !!((el("restorePmxBridge")?.value || "").trim());
        const esxiOk = isEsxiDirect
          && !!((el("restoreEsxiDest")?.value || "").trim())
          && !!((el("restoreEsxiDatastore")?.value || "").trim());

        if (el("btnRestoreSimple")) {
          el("btnRestoreSimple").disabled = !(hasBackup && (pmxOk || esxiOk));
        }
      }

      function renderBackupsTable() {
        const tbody = el("backupsTable");
        if (!tbody) return;
        tbody.innerHTML = "";
        for (const b of (backupsCache || [])) {
          const tr = document.createElement("tr");
          tr.style.cursor = "pointer";
          tr.addEventListener("click", () => {
            if (el("backupSelect")) el("backupSelect").value = b.backup_id;
            updateMigrationSelection();
            updateRestoreSimpleSelection();
          });
          const tdDate = document.createElement("td");
          tdDate.textContent = fmtDate(b.created_ms || 0);
          const tdLabel = document.createElement("td");
          tdLabel.textContent = b.label || b.backup_id;
          const tdSrc = document.createElement("td");
          tdSrc.textContent = b.source_type || "";
          const tdVm = document.createElement("td");
          tdVm.textContent = (b.vm_key || b.vmid || "") + ((b.vm_name && (b.vm_key || b.vmid)) ? (" / " + b.vm_name) : (b.vm_name || ""));
          tr.appendChild(tdDate);
          tr.appendChild(tdLabel);
          tr.appendChild(tdSrc);
          tr.appendChild(tdVm);
          tbody.appendChild(tr);
        }
      }

      async function loadResources() {
        const data = await apiGet("/api/resources");
        resources = data.resources || [];
        const labelRes = (r) => {
          const n = (r && r.name ? String(r.name).trim() : "");
          const h = (r && r.host ? String(r.host).trim() : "");
          const u = (r && r.username ? String(r.username).trim() : "");
          if (n) return n + (h ? (" (" + h + ")") : "") + (u ? (" — " + u) : "");
          return (h ? h : "") + (u ? (" (" + u + ")") : "");
        };
        const pmx = resources.filter(r => r.kind === "proxmox").map(r => ({ value: r.id, label: labelRes(r) }));
        const esxi = resources
          .filter(r => (r.kind === "esxi" || r.kind === "vmware"))
          .map(r => ({ value: r.id, label: labelRes(r) }));
        fillSelect(el("pmxSel"), pmx, it => it.label);
        fillSelect(el("esxiSel"), esxi, it => it.label);
        fillSelect(el("repoPmx"), pmx, it => it.label);
        fillSelect(el("repoPmxWorker"), pmx, it => it.label);
        fillSelect(el("repoEsxi"), esxi, it => it.label);
        fillSelect(el("restorePmxDest"), pmx, it => it.label);
        fillSelect(el("restoreEsxiDest"), esxi, it => it.label);
        fillSelect(el("infraPmx"), pmx, it => it.label);
        fillSelect(el("infraEsxi"), esxi, it => it.label);
        el("btnScan").disabled = (pmx.length === 0 || esxi.length === 0);
        updateInfraButtons();
      }

      async function loadRepoPath() {
        try {
          const data = await apiGet("/api/settings/repo");
          if (data && data.path && el("repoPath")) el("repoPath").value = data.path;
        } catch (e) {}
      }

      async function refreshStoragesTable() {
        const data = await apiGet("/api/storages");
        storages = data.storages || [];
        const tbody = el("stoTable");
        if (!tbody) return;
        tbody.innerHTML = "";
        for (const s of storages) {
          const tr = document.createElement("tr");
          tr.addEventListener("click", () => {
            selectedStorageId = s.id;
            for (const row of Array.from(tbody.querySelectorAll("tr"))) row.classList.remove("sel");
            tr.classList.add("sel");
            updateStorageActions();
          });
          const tdKind = document.createElement("td");
          tdKind.textContent = s.kind || "";
          const tdName = document.createElement("td");
          tdName.textContent = s.name || "";
          const tdHost = document.createElement("td");
          tdHost.textContent = s.host || "";
          const tdPath = document.createElement("td");
          tdPath.textContent = s.path || "";
          const tdUser = document.createElement("td");
          tdUser.textContent = s.username || "";
          const tdPort = document.createElement("td");
          tdPort.textContent = String(s.port || "");
          tr.appendChild(tdKind);
          tr.appendChild(tdName);
          tr.appendChild(tdHost);
          tr.appendChild(tdPath);
          tr.appendChild(tdUser);
          tr.appendChild(tdPort);
          tbody.appendChild(tr);
        }
        updateStorageActions();
      }

      function updateStorageActions() {
        if (el("btnStoEdit")) el("btnStoEdit").disabled = !(selectedStorageId || "").trim();
        if (el("btnStoDelete")) el("btnStoDelete").disabled = !(selectedStorageId || "").trim();
        if (el("btnStoTest")) el("btnStoTest").disabled = !(selectedStorageId || "").trim();
      }

      function openStoModal(mode) {
        const modal = el("stoModal");
        if (!modal) return;
        if (el("stoModalTitle")) el("stoModalTitle").textContent = mode === "edit" ? "Edit storage" : "Add storage";
        if (mode === "new") {
          selectedStorageId = null;
          el("stoKind").value = "nfs";
          el("stoName").value = "";
          el("stoHost").value = "";
          el("stoPath").value = "";
          el("stoUser").value = "";
          el("stoPass").value = "";
          el("stoPort").value = "2049";
        } else {
          const s = (storages || []).find(x => x.id === selectedStorageId) || null;
          if (s) {
            el("stoKind").value = s.kind || "nfs";
            el("stoName").value = s.name || "";
            el("stoHost").value = s.host || "";
            el("stoPath").value = s.path || "";
            el("stoUser").value = s.username || "";
            el("stoPass").value = "";
            el("stoPort").value = String(s.port || "");
          }
        }
        modal.classList.remove("hidden");
        el("stoName")?.focus?.();
      }

      function closeStoModal() {
        const modal = el("stoModal");
        if (!modal) return;
        modal.classList.add("hidden");
      }

      async function refreshResourcesTable() {
        const data = await apiGet("/api/resources");
        resources = data.resources || [];
        const tbody = el("resTable");
        tbody.innerHTML = "";
        for (const r of resources) {
          const tr = document.createElement("tr");
          tr.addEventListener("click", () => {
            selectedResourceId = r.id;
            for (const row of Array.from(tbody.querySelectorAll("tr"))) row.classList.remove("sel");
            tr.classList.add("sel");
            updateResourceActions();
          });
          const tdKind = document.createElement("td");
          tdKind.textContent = r.kind;
          const tdName = document.createElement("td");
          tdName.textContent = r.name || "";
          const tdHost = document.createElement("td");
          tdHost.textContent = r.host;
          const tdUser = document.createElement("td");
          tdUser.textContent = r.username;
          const tdPort = document.createElement("td");
          tdPort.textContent = String(r.port || 22);
          tr.appendChild(tdKind);
          tr.appendChild(tdName);
          tr.appendChild(tdHost);
          tr.appendChild(tdUser);
          tr.appendChild(tdPort);
          tbody.appendChild(tr);
        }
        updateResourceActions();
      }

      function updateResourceActions() {
        if (el("btnResEdit")) el("btnResEdit").disabled = !(selectedResourceId || "").trim();
        if (el("btnResDelete")) el("btnResDelete").disabled = !(selectedResourceId || "").trim();
      }

      function openResModal(mode) {
        const modal = el("resModal");
        if (!modal) return;
        if (el("resModalTitle")) el("resModalTitle").textContent = mode === "edit" ? "Edit risorsa" : "Add risorsa";
        if (mode === "new") {
          selectedResourceId = null;
          el("resKind").value = "proxmox";
          el("resName").value = "";
          el("resHost").value = "";
          el("resUser").value = "";
          el("resPass").value = "";
          el("resPort").value = "22";
        } else {
          const r = (resources || []).find(x => x.id === selectedResourceId) || null;
          if (r) {
            el("resKind").value = r.kind || "proxmox";
            el("resName").value = r.name || "";
            el("resHost").value = r.host || "";
            el("resUser").value = r.username || "";
            el("resPass").value = "";
            el("resPort").value = String(r.port || 22);
          }
        }
        modal.classList.remove("hidden");
        el("resName")?.focus?.();
      }

      function closeResModal() {
        const modal = el("resModal");
        if (!modal) return;
        modal.classList.add("hidden");
      }

      async function refreshBackups() {
        el("repoStatus").textContent = "Caricamento…";
        try {
          const sid = (el("restoreRepoStorage") ? (el("restoreRepoStorage").value || "").trim() : "");
          const qs = sid ? ("?repo_storage_id=" + encodeURIComponent(sid)) : "";
          const data = await apiGet("/api/backups" + qs);
          backupsCache = data.backups || [];
          const items = backupsCache.map(b => ({ value: b.backup_id, label: (b.label || b.backup_id) }));
          fillSelect(el("backupSelect"), items, it => it.label);
          renderBackupsTable();
          updateMigrationSelection();
          updateRestoreSimpleSelection();
          el("repoStatus").textContent = "OK (" + items.length + ")";
        } catch (e) {
          el("repoStatus").textContent = "Errore: " + e.message;
        }
      }

      if (el("navHome")) el("navHome").addEventListener("click", async () => {
        showPage("pageHome");
        try { await refreshHome(); } catch (e) {}
      });
      if (el("navResources")) el("navResources").addEventListener("click", async () => {
        showPage("pageResources");
        await refreshResourcesTable();
      });
      if (el("navStorage")) el("navStorage").addEventListener("click", async () => {
        showPage("pageStorage");
        try { await refreshStoragesTable(); } catch (e) {}
      });
      if (el("navBackup")) el("navBackup").addEventListener("click", async () => {
        showPage("pageBackup");
        try { await loadResources(); } catch (e) {}
        try { await loadRepoStorages(); } catch (e) {}
        try { await loadRepoPath(); } catch (e) {}
        try { updateBackupVirtUI(); } catch (e) {}
        updateInfraButtons();
      });
      if (el("navRestore")) el("navRestore").addEventListener("click", async () => {
        showPage("pageRestore");
        setRestoreTab("simple");
        try { await loadResources(); } catch (e) {}
        try { await loadRepoStorages(); } catch (e) {}
        try { await refreshPmxWorkerTmpDirs(); } catch (e) {}
        try { await refreshEsxiDatastores(); } catch (e) {}
        try { await prefillProxmoxTargetRestore(); } catch (e) {}
        try { await refreshEsxiDatastoresRestore(); } catch (e) {}
        try { await refreshBackups(); } catch (e) {}
        updateMigrationSelection();
      });
      if (el("navCross")) el("navCross").addEventListener("click", async () => {
        showPage("pageCross");
        try { await loadResources(); } catch (e) {}
      });
      if (el("navJobs")) el("navJobs").addEventListener("click", async () => {
        showPage("pageJobs");
        await refreshJobs();
      });
      if (el("navSystem")) el("navSystem").addEventListener("click", async () => {
        showPage("pageSystem");
        try { await loadRepoPath(); } catch (e) {}
      });

      el("infraPmx").addEventListener("change", updateInfraButtons);
      el("infraEsxi").addEventListener("change", updateInfraButtons);
      el("backupVirt").addEventListener("change", updateInfraButtons);
      el("backupSelect").addEventListener("change", () => {
        updateMigrationSelection();
        updateRestoreSimpleSelection();
      });
      el("repoPmx").addEventListener("change", async () => {
        try {
          await prefillProxmoxTarget();
        } catch (e) {}
        updateMigrationSelection();
      });
      el("repoPmxWorker").addEventListener("change", () => updateMigrationSelection());
      el("repoPmxWorker").addEventListener("change", async () => {
        try { await refreshPmxWorkerTmpDirs(); } catch (e) {}
      });
      el("repoPmxWorkerTmp").addEventListener("change", () => updateMigrationSelection());
      el("repoEsxi").addEventListener("change", async () => {
        try {
          await refreshEsxiDatastores();
        } catch (e) {}
        updateMigrationSelection();
      });
      el("repoEsxiDatastore").addEventListener("change", () => updateMigrationSelection());

      el("btnRepoPathSave").addEventListener("click", async () => {
        const p = (el("repoPath").value || "").trim();
        if (el("sysStatus")) el("sysStatus").textContent = "Salvataggio…";
        try {
          await api("/api/settings/repo", { path: p });
          if (el("sysStatus")) el("sysStatus").textContent = "Percorso salvato";
        } catch (e) {
          if (el("sysStatus")) el("sysStatus").textContent = "Errore: " + e.message;
        }
      });

      el("btnResClear").addEventListener("click", () => {
        el("resKind").value = "proxmox";
        el("resName").value = "";
        el("resHost").value = "";
        el("resUser").value = "";
        el("resPass").value = "";
        el("resPort").value = "22";
      });

      if (el("btnResModalClose")) el("btnResModalClose").addEventListener("click", closeResModal);
      if (el("btnResCreate")) el("btnResCreate").addEventListener("click", () => openResModal("new"));
      if (el("btnResEdit")) el("btnResEdit").addEventListener("click", () => openResModal("edit"));
      if (el("btnResDelete")) el("btnResDelete").addEventListener("click", async () => {
        const rid = (selectedResourceId || "").trim();
        if (!rid) return;
        el("resStatus").textContent = "Eliminazione…";
        try {
          await fetch("/api/resources/" + encodeURIComponent(rid), { method: "DELETE" });
          selectedResourceId = null;
          await refreshResourcesTable();
          await loadResources();
          el("resStatus").textContent = "Eliminato";
        } catch (e) {
          el("resStatus").textContent = "Errore: " + (e && e.message ? e.message : String(e));
        }
      });

      el("btnResAdd").addEventListener("click", async () => {
        el("resStatus").textContent = "Salvataggio…";
        try {
          const payload = {
            id: selectedResourceId,
            kind: el("resKind").value,
            name: el("resName").value,
            host: el("resHost").value,
            username: el("resUser").value,
            password: el("resPass").value,
            port: el("resPort").value
          };
          await api("/api/resources", payload);
          el("resStatus").textContent = "OK";
          closeResModal();
          el("resPass").value = "";
          await refreshResourcesTable();
          await loadResources();
        } catch (e) {
          el("resStatus").textContent = "Errore: " + e.message;
        }
      });

      if (el("stoKind")) el("stoKind").addEventListener("change", () => {
        const k = (el("stoKind").value || "").trim().toLowerCase();
        if (k === "iscsi") el("stoPort").value = "3260";
        if (k === "nfs") el("stoPort").value = "2049";
      });
      if (el("btnStoModalClose")) el("btnStoModalClose").addEventListener("click", closeStoModal);
      if (el("btnStoCreate")) el("btnStoCreate").addEventListener("click", () => openStoModal("new"));
      if (el("btnStoEdit")) el("btnStoEdit").addEventListener("click", () => openStoModal("edit"));
      if (el("btnStoDelete")) el("btnStoDelete").addEventListener("click", async () => {
        const sid = (selectedStorageId || "").trim();
        if (!sid) return;
        if (el("stoStatus")) el("stoStatus").textContent = "Eliminazione…";
        try {
          await fetch("/api/storages/" + encodeURIComponent(sid), { method: "DELETE" });
          selectedStorageId = null;
          await refreshStoragesTable();
          if (el("stoStatus")) el("stoStatus").textContent = "Eliminato";
        } catch (e) {
          if (el("stoStatus")) el("stoStatus").textContent = "Errore: " + (e && e.message ? e.message : String(e));
        }
      });
      if (el("btnStoTest")) el("btnStoTest").addEventListener("click", async () => {
        const sid = (selectedStorageId || "").trim();
        if (!sid) return;
        if (el("stoStatus")) el("stoStatus").textContent = "Test…";
        try {
          const data = await api("/api/storages/" + encodeURIComponent(sid) + "/check", {});
          if (data && data.ok) {
            const p = (data.path || "").trim();
            const note = (data.note || "").trim();
            if (el("stoStatus")) el("stoStatus").textContent = "OK" + (p ? (" • " + p) : "") + (note ? (" • " + note) : "");
          } else {
            if (el("stoStatus")) el("stoStatus").textContent = "Errore: " + ((data && data.error) ? data.error : "test fallito");
          }
        } catch (e) {
          if (el("stoStatus")) el("stoStatus").textContent = "Errore: " + e.message;
        }
      });
      if (el("btnStoClear")) el("btnStoClear").addEventListener("click", () => {
        el("stoKind").value = "nfs";
        el("stoName").value = "";
        el("stoHost").value = "";
        el("stoPath").value = "";
        el("stoUser").value = "";
        el("stoPass").value = "";
        el("stoPort").value = "2049";
      });
      if (el("btnStoSave")) el("btnStoSave").addEventListener("click", async () => {
        if (el("stoStatus")) el("stoStatus").textContent = "Salvataggio…";
        try {
          const payload = {
            id: selectedStorageId,
            kind: el("stoKind").value,
            name: el("stoName").value,
            host: el("stoHost").value,
            path: el("stoPath").value,
            username: el("stoUser").value,
            password: el("stoPass").value,
            port: el("stoPort").value
          };
          await api("/api/storages", payload);
          if (el("stoStatus")) el("stoStatus").textContent = "OK";
          closeStoModal();
          el("stoPass").value = "";
          await refreshStoragesTable();
        } catch (e) {
          if (el("stoStatus")) el("stoStatus").textContent = "Errore: " + e.message;
        }
      });

      async function refreshHome() {
        try {
          const sid = (el("homeRepoStorage") ? (el("homeRepoStorage").value || "").trim() : "");
          const qs = sid ? ("?repo_storage_id=" + encodeURIComponent(sid)) : "";
          const m = await apiGet("/api/metrics" + qs);
          if (el("homeBackupsTotal")) el("homeBackupsTotal").textContent = String(m.backups_total || 0);
          if (el("homeBackupsGb")) el("homeBackupsGb").textContent = (typeof m.backup_gb_total === "number" ? m.backup_gb_total.toFixed(2) : "0");
          if (el("homeVmsBackedUp")) el("homeVmsBackedUp").textContent = String(m.vms_in_backup_total || 0);
          if (el("homeVmsMigrated")) el("homeVmsMigrated").textContent = String(m.vms_migrated_total || 0);
        } catch (e) {}
      }

      async function loadRepoStorages() {
        const data = await apiGet("/api/storages");
        const items = (data.storages || []).map(s => ({ value: s.id, label: (s.name || s.host || s.id) + " • " + (s.kind || "") }));
        const withLocal = [{ value: "", label: "Locale (repo)" }, ...items];
        if (el("backupRepoStorage")) {
          fillSelect(el("backupRepoStorage"), withLocal, it => it.label);
          el("backupRepoStorage").disabled = false;
        }
        if (el("restoreRepoStorage")) {
          fillSelect(el("restoreRepoStorage"), withLocal, it => it.label);
          el("restoreRepoStorage").disabled = false;
        }
        if (el("homeRepoStorage")) {
          fillSelect(el("homeRepoStorage"), withLocal, it => it.label);
          el("homeRepoStorage").disabled = false;
        }
      }

      if (el("homeRepoStorage")) el("homeRepoStorage").addEventListener("change", async () => {
        try { await refreshHome(); } catch (e) {}
      });
      if (el("restoreRepoStorage")) el("restoreRepoStorage").addEventListener("change", async () => {
        try { await refreshBackups(); } catch (e) {}
      });

      async function prefillProxmoxTarget() {
        const pmxId = (el("repoPmx").value || "").trim();
        if (!pmxId) return;
        const data = await api("/api/infrastructure/proxmox/prefill", { pmx_id: pmxId });
        const storages = (data.storages || []).map(s => ({ value: s, label: s }));
        const bridges = (data.bridges || []).map(b => ({ value: b, label: b }));
        fillSelect(el("storageSelect"), storages, it => it.label);
        fillSelect(el("bridgeSelect"), bridges, it => it.label);
        if (data.next_vmid && !String(el("vmid").value || "").trim()) {
          el("vmid").value = String(data.next_vmid);
        }
      }

      async function prefillProxmoxTargetRestore() {
        const pmxId = (el("restorePmxDest")?.value || "").trim();
        if (!pmxId) {
          fillSelect(el("restorePmxStorage"), [], it => it.label);
          fillSelect(el("restorePmxBridge"), [], it => it.label);
          return;
        }
        const data = await api("/api/infrastructure/proxmox/prefill", { pmx_id: pmxId });
        const storages = (data.storages || []).map(s => ({ value: s, label: s }));
        const bridges = (data.bridges || []).map(b => ({ value: b, label: b }));
        fillSelect(el("restorePmxStorage"), storages, it => it.label);
        fillSelect(el("restorePmxBridge"), bridges, it => it.label);
        if (data.next_vmid && !String(el("restorePmxVmid")?.value || "").trim()) {
          el("restorePmxVmid").value = String(data.next_vmid);
        }
      }

      async function refreshEsxiDatastores() {
        const esxiId = (el("repoEsxi").value || "").trim();
        if (!esxiId) {
          fillSelect(el("repoEsxiDatastore"), [], it => it.label);
          return;
        }
        const data = await api("/api/infrastructure/esxi/datastores", { esxi_id: esxiId });
        const dss = (data.datastores || []).map(d => ({ value: d, label: d }));
        fillSelect(el("repoEsxiDatastore"), dss, it => it.label);
      }

      async function refreshEsxiDatastoresRestore() {
        const esxiId = (el("restoreEsxiDest")?.value || "").trim();
        if (!esxiId) {
          fillSelect(el("restoreEsxiDatastore"), [], it => it.label);
          return;
        }
        const data = await api("/api/infrastructure/esxi/datastores", { esxi_id: esxiId });
        const dss = (data.datastores || []).map(d => ({ value: d, label: d }));
        fillSelect(el("restoreEsxiDatastore"), dss, it => it.label);
      }

      async function refreshPmxWorkerTmpDirs() {
        const pmxId = (el("repoPmxWorker").value || "").trim();
        if (!pmxId) {
          fillSelect(el("repoPmxWorkerTmp"), [], it => it.label);
          return;
        }
        const data = await api("/api/infrastructure/proxmox/tmpdirs", { pmx_id: pmxId });
        const items = (data.items || []).map(it => ({ value: it.value, label: it.label }));
        fillSelect(el("repoPmxWorkerTmp"), items, it => it.label);
      }

      if (el("btnRestoreTabSimple")) el("btnRestoreTabSimple").addEventListener("click", () => setRestoreTab("simple"));
      if (el("btnRestoreTabXplat")) el("btnRestoreTabXplat").addEventListener("click", () => setRestoreTab("xplat"));

      if (el("btnRefreshBackups2")) el("btnRefreshBackups2").addEventListener("click", () => refreshBackups());

      if (el("restorePmxDest")) el("restorePmxDest").addEventListener("change", async () => {
        try { await prefillProxmoxTargetRestore(); } catch (e) {}
        updateRestoreSimpleSelection();
      });
      if (el("restorePmxStorage")) el("restorePmxStorage").addEventListener("change", () => updateRestoreSimpleSelection());
      if (el("restorePmxBridge")) el("restorePmxBridge").addEventListener("change", () => updateRestoreSimpleSelection());
      if (el("restoreEsxiDest")) el("restoreEsxiDest").addEventListener("change", async () => {
        try { await refreshEsxiDatastoresRestore(); } catch (e) {}
        updateRestoreSimpleSelection();
      });
      if (el("restoreEsxiDatastore")) el("restoreEsxiDatastore").addEventListener("change", () => updateRestoreSimpleSelection());
      if (el("restoreVmName")) el("restoreVmName").addEventListener("input", () => updateRestoreSimpleSelection());

      if (el("btnRestoreSimple")) el("btnRestoreSimple").addEventListener("click", async () => {
        const backupId = (el("backupSelect")?.value || "").trim();
        if (!backupId) return;
        const b = (backupsCache || []).find(x => x.backup_id === backupId) || null;
        const st = (b && b.source_type ? String(b.source_type) : "").trim();
        const repoStorageId = (el("restoreRepoStorage") ? (el("restoreRepoStorage").value || "").trim() : "");
        const payloadBase = {
          backup_id: backupId,
          name: (el("restoreVmName")?.value || "").trim(),
          mem: (el("restoreMem")?.value || "").trim(),
          cores: (el("restoreCores")?.value || "").trim(),
          uefi: (el("restoreUefi")?.value || "false") === "true",
          start_vm: !!el("restoreStartVm")?.checked,
          repo_storage_id: repoStorageId,
        };
        el("btnRestoreSimple").disabled = true;
        if (el("restoreSimpleStatus")) el("restoreSimpleStatus").textContent = "Avvio ripristino…";
        try {
          let data = null;
          if (st === "proxmox-vzdump") {
            data = await api("/api/backups/restore/proxmox", {
              ...payloadBase,
              pmx_id: (el("restorePmxDest")?.value || "").trim(),
              storage: (el("restorePmxStorage")?.value || "").trim(),
              bridge: (el("restorePmxBridge")?.value || "").trim(),
              vmid: (el("restorePmxVmid")?.value || "").trim(),
            });
          } else if (st === "esxi-direct") {
            data = await api("/api/backups/restore/esxi-direct", {
              ...payloadBase,
              esxi_id: (el("restoreEsxiDest")?.value || "").trim(),
              datastore: (el("restoreEsxiDatastore")?.value || "").trim(),
            });
          } else {
            throw new Error("Tipo backup non supportato");
          }
          const jobId = data.job_id;
          if (el("restoreSimpleStatus")) el("restoreSimpleStatus").textContent = "Job: " + jobId;
          if (eventSource) {
            try { eventSource.close(); } catch (_) {}
          }
          eventSource = new EventSource("/api/jobs/" + jobId + "/events");
          eventSource.addEventListener("message", (evt) => {
            try {
              const payload = JSON.parse(evt.data);
              if (payload.type === "status" && el("restoreSimpleStatus")) el("restoreSimpleStatus").textContent = payload.status || "";
              if (payload.type === "progress" && el("restoreSimpleStatus")) {
                const msg = (payload.ops_msg || payload.copy_msg || "").trim();
                if (msg) el("restoreSimpleStatus").textContent = msg;
              }
              if (payload.type === "log") log(payload.line);
            } catch (e) {}
          });
        } catch (e) {
          if (el("restoreSimpleStatus")) el("restoreSimpleStatus").textContent = "Errore: " + e.message;
          el("btnRestoreSimple").disabled = false;
        } finally {
          updateRestoreSimpleSelection();
        }
      });

      el("btnImportVmware").addEventListener("click", async () => {
        const backupId = el("backupSelect").value;
        if (!backupId) return;
        el("btnImportVmware").disabled = true;
        el("jobStatus").textContent = "Avvio import VMware…";
        setProgress(0, "", 0, "");
        log("");
        log("== Restore backup (repo → ESXi) ==");
        try {
          const tmpBase = (el("repoPmxWorkerTmp").value || "").trim();
          const repoStorageId = (el("restoreRepoStorage") ? (el("restoreRepoStorage").value || "").trim() : "");
          const data = await api("/api/backups/restore/esxi", {
            backup_id: backupId,
            pmx_id: el("repoPmxWorker").value,
            pmx_tmp_base: (tmpBase && tmpBase !== "auto") ? tmpBase : "",
            esxi_id: el("repoEsxi").value,
            datastore: el("repoEsxiDatastore").value,
            name: el("vmname").value,
            mem: el("mem").value,
            cores: el("cores").value,
            uefi: el("uefi").value === "true",
            repo_storage_id: repoStorageId,
          });
          const jobId = data.job_id;
          el("jobStatus").textContent = "Job: " + jobId;
          if (eventSource) {
            try { eventSource.close(); } catch (_) {}
          }
          eventSource = new EventSource("/api/jobs/" + jobId + "/events");
          eventSource.addEventListener("message", (evt) => {
            try {
              const payload = JSON.parse(evt.data);
              if (payload.type === "log") log(payload.line);
              if (payload.type === "progress") setProgress(payload.copy_pct, payload.copy_msg, payload.ops_pct, payload.ops_msg);
              if (payload.type === "status") el("jobStatus").textContent = payload.status;
            } catch (e) {
              log("Event parse error: " + e.message);
            }
          });
        } catch (e) {
          el("jobStatus").textContent = "Errore: " + e.message;
          log("Errore restore ESXi: " + e.message);
          el("btnImportVmware").disabled = false;
        } finally {
          updateMigrationSelection();
        }
      });

      el("btnScan").addEventListener("click", async () => {
        el("scanStatus").textContent = "Scansione in corso…";
        el("btnScan").disabled = true;
        el("btnStart").disabled = true;
        el("btnCapture").disabled = true;
        scanId = null;
        setProgress(0, "", 0, "");
        log("");
        log("== Scan ==");
        try {
          const data = await api("/api/scan", {
            pmx_id: el("pmxSel").value,
            esxi_id: el("esxiSel").value
          });
          scanId = data.scan_id;
          el("scanStatus").textContent = "OK";

          fillSelect(el("vmSelect"), data.vms.map(v => ({ value: v.key, label: v.label })), (it) => it.label);
          fillSelect(el("storageSelect"), data.storages.map(s => ({ value: s, label: s })), (it) => it.label);
          fillSelect(el("bridgeSelect"), data.bridges.map(s => ({ value: s, label: s })), (it) => it.label);

          if (data.next_vmid) el("vmid").value = data.next_vmid;
          if (data.vms.length > 0) el("vmname").value = data.vms[0].suggested_name || data.vms[0].label;
          el("btnStart").disabled = (data.vms.length === 0 || data.storages.length === 0 || data.bridges.length === 0);
          el("btnCapture").disabled = (data.vms.length === 0);

          log("VM trovate: " + data.vms.length);
          refreshBackups();
        } catch (e) {
          el("scanStatus").textContent = "Errore: " + e.message;
          log("Errore scan: " + e.message);
        } finally {
          el("btnScan").disabled = false;
        }
      });

      el("vmSelect").addEventListener("change", () => {
        const opt = el("vmSelect").selectedOptions[0];
        if (opt && opt.textContent) el("vmname").value = opt.textContent;
      });

      el("btnStart").addEventListener("click", async () => {
        if (!scanId) return;
        el("btnStart").disabled = true;
        el("jobStatus").textContent = "Avvio job…";
        setProgress(0, "", 0, "");
        log("");
        log("== Migration job ==");
        try {
          const data = await api("/api/jobs/start", {
            scan_id: scanId,
            vm_key: el("vmSelect").value,
            pmx_id: el("pmxSel").value,
            esxi_id: el("esxiSel").value,
            storage: el("storageSelect").value,
            bridge: el("bridgeSelect").value,
            vmid: el("vmid").value,
            name: el("vmname").value,
            mem: el("mem").value,
            cores: el("cores").value,
            uefi: el("uefi").value === "true",
            snapshot: el("snapshot").value === "true",
            convert: el("convert").value === "true",
            format: el("format").value,
            dest_dir: el("destDir").value
          });

          const jobId = data.job_id;
          el("jobStatus").textContent = "Job: " + jobId;
          if (eventSource) {
            try { eventSource.close(); } catch (_) {}
          }
          eventSource = new EventSource("/api/jobs/" + jobId + "/events");
          eventSource.addEventListener("message", (evt) => {
            try {
              const payload = JSON.parse(evt.data);
              if (payload.type === "log") log(payload.line);
              if (payload.type === "progress") setProgress(payload.copy_pct, payload.copy_msg, payload.ops_pct, payload.ops_msg);
              if (payload.type === "status") el("jobStatus").textContent = payload.status;
              if (payload.type === "backup") refreshBackups();
            } catch (e) {
              log("Event parse error: " + e.message);
            }
          });
          eventSource.addEventListener("error", () => {
            log("EventSource disconnected");
          });
        } catch (e) {
          el("jobStatus").textContent = "Errore: " + e.message;
          log("Errore start job: " + e.message);
          el("btnStart").disabled = false;
        }
      });

      el("btnCapture").addEventListener("click", async () => {
        if (!scanId) return;
        el("btnCapture").disabled = true;
        el("jobStatus").textContent = "Avvio capture…";
        setProgress(0, "", 0, "");
        log("");
        log("== Capture backup (repo) ==");
        try {
          const data = await api("/api/backups/capture/esxi", {
            scan_id: scanId,
            vm_key: el("vmSelect").value,
            pmx_id: el("pmxSel").value,
            esxi_id: el("esxiSel").value,
            snapshot: el("snapshot").value === "true",
          });
          const jobId = data.job_id;
          el("jobStatus").textContent = "Job: " + jobId;
          if (eventSource) {
            try { eventSource.close(); } catch (_) {}
          }
          eventSource = new EventSource("/api/jobs/" + jobId + "/events");
          eventSource.addEventListener("message", (evt) => {
            try {
              const payload = JSON.parse(evt.data);
              if (payload.type === "log") log(payload.line);
              if (payload.type === "progress") setProgress(payload.copy_pct, payload.copy_msg, payload.ops_pct, payload.ops_msg);
              if (payload.type === "status") el("jobStatus").textContent = payload.status;
              if (payload.type === "backup") refreshBackups();
            } catch (e) {
              log("Event parse error: " + e.message);
            }
          });
        } catch (e) {
          el("jobStatus").textContent = "Errore: " + e.message;
          log("Errore capture: " + e.message);
          el("btnCapture").disabled = false;
        }
      });

      el("btnRefreshBackups").addEventListener("click", () => refreshBackups());

      el("btnRestore").addEventListener("click", async () => {
        const backupId = el("backupSelect").value;
        if (!backupId) return;
        el("btnRestore").disabled = true;
        el("jobStatus").textContent = "Avvio restore…";
        setProgress(0, "", 0, "");
        log("");
        log("== Restore backup (repo → Proxmox) ==");
        try {
          const repoStorageId = (el("restoreRepoStorage") ? (el("restoreRepoStorage").value || "").trim() : "");
          const data = await api("/api/backups/restore/proxmox", {
            backup_id: backupId,
            pmx_id: el("repoPmx").value,
            storage: el("storageSelect").value,
            bridge: el("bridgeSelect").value,
            vmid: el("vmid").value,
            name: el("vmname").value,
            mem: el("mem").value,
            cores: el("cores").value,
            uefi: el("uefi").value === "true",
            repo_storage_id: repoStorageId,
          });
          const jobId = data.job_id;
          el("jobStatus").textContent = "Job: " + jobId;
          if (eventSource) {
            try { eventSource.close(); } catch (_) {}
          }
          eventSource = new EventSource("/api/jobs/" + jobId + "/events");
          eventSource.addEventListener("message", (evt) => {
            try {
              const payload = JSON.parse(evt.data);
              if (payload.type === "log") log(payload.line);
              if (payload.type === "progress") setProgress(payload.copy_pct, payload.copy_msg, payload.ops_pct, payload.ops_msg);
              if (payload.type === "status") el("jobStatus").textContent = payload.status;
              if (payload.type === "backup") refreshBackups();
            } catch (e) {
              log("Event parse error: " + e.message);
            }
          });
        } catch (e) {
          el("jobStatus").textContent = "Errore: " + e.message;
          log("Errore restore: " + e.message);
          el("btnRestore").disabled = false;
        }
      });

      function renderSelectedJob() {
        const job = selectedJobData;
        if (!job) {
          el("jobDetails").textContent = "";
          el("btnJobStart").disabled = true;
          return;
        }
        const fmtMb = (b) => (typeof b === "number" && isFinite(b) && b > 0) ? (b / 1000000.0) : 0;
        const fmtGb = (b) => (typeof b === "number" && isFinite(b) && b > 0) ? (b / 1000000000.0) : 0;
        const lines = [];
        lines.push("job_id: " + (job.job_id || ""));
        lines.push("kind: " + (job.kind || ""));
        lines.push("title: " + (job.title || ""));
        lines.push("status: " + (job.status || ""));
        if (job.created_ms) lines.push("created: " + new Date(job.created_ms).toLocaleString());
        if (job.updated_ms) lines.push("updated: " + new Date(job.updated_ms).toLocaleString());
        if (typeof job.bytes_done === "number" || typeof job.bytes_total === "number") {
          const doneGb = fmtGb(job.bytes_done || 0);
          const totalGb = fmtGb(job.bytes_total || 0);
          if (totalGb > 0) lines.push("bytes: " + doneGb.toFixed(2) + " / " + totalGb.toFixed(2) + " GB");
        }
        if (typeof job.rate_bps === "number" && isFinite(job.rate_bps) && job.rate_bps > 0) {
          lines.push("rate: " + fmtMb(job.rate_bps).toFixed(2) + " MB/s");
        }
        if (job.backup_id) lines.push("backup_id: " + job.backup_id);
        if (job.error) lines.push("error: " + job.error);
        lines.push("");
        const copyPct = (typeof job.copy_pct === "number") ? job.copy_pct : 0;
        const opsPct = (typeof job.ops_pct === "number") ? job.ops_pct : 0;
        lines.push("copy: " + String(copyPct) + "% " + (job.copy_msg || ""));
        lines.push("ops:  " + String(opsPct) + "% " + (job.ops_msg || ""));
        lines.push("");
        lines.push("== log ==");
        for (const l of (selectedJobLogs || [])) lines.push(l);
        el("jobDetails").textContent = lines.join("\\n");
        el("btnJobStart").disabled = (job.status || "") !== "queued";
      }

      async function loadJob(jobId) {
        selectedJobId = jobId;
        el("jobDetails").textContent = "Caricamento…";
        try {
          const data = await apiGet("/api/jobs/" + encodeURIComponent(jobId));
          selectedJobData = data || null;
          selectedJobLogs = Array.isArray(data.logs) ? data.logs.slice(-400) : (Array.isArray(data.log_tail) ? data.log_tail.slice(-400) : []);
          renderSelectedJob();
          if (jobsEventSource) {
            try { jobsEventSource.close(); } catch (_) {}
          }
          jobsEventSource = new EventSource("/api/jobs/" + encodeURIComponent(jobId) + "/events");
          jobsEventSource.addEventListener("message", (evt) => {
            try {
              const payload = JSON.parse(evt.data);
              if (!selectedJobData || selectedJobId !== jobId) return;
              if (payload.type === "log" && payload.line) {
                selectedJobLogs.push(payload.line);
                if (selectedJobLogs.length > 500) selectedJobLogs = selectedJobLogs.slice(-500);
              }
              if (payload.type === "progress") {
                selectedJobData.copy_pct = payload.copy_pct;
                selectedJobData.copy_msg = payload.copy_msg;
                selectedJobData.ops_pct = payload.ops_pct;
                selectedJobData.ops_msg = payload.ops_msg;
                if (typeof payload.bytes_total === "number") selectedJobData.bytes_total = payload.bytes_total;
                if (typeof payload.bytes_done === "number") selectedJobData.bytes_done = payload.bytes_done;
                if (typeof payload.rate_bps === "number") selectedJobData.rate_bps = payload.rate_bps;
              }
              if (payload.type === "status") {
                selectedJobData.status = payload.status;
                if (payload.error) selectedJobData.error = payload.error;
              }
              renderSelectedJob();
              if (payload.type === "status" && (payload.status === "done" || payload.status === "error")) refreshJobs();
              if (payload.type === "backup") refreshBackups();
            } catch (_) {}
          });
        } catch (e) {
          selectedJobData = null;
          selectedJobLogs = [];
          el("jobDetails").textContent = "Errore: " + e.message;
          el("btnJobStart").disabled = true;
        }
      }

      async function refreshJobs() {
        el("jobsStatus").textContent = "Caricamento…";
        try {
          const data = await apiGet("/api/jobs");
          const jobs = data.jobs || [];
          const fmtGb = (b) => (typeof b === "number" && isFinite(b) && b > 0) ? (b / 1000000000.0) : 0;
          const fmtMb = (b) => (typeof b === "number" && isFinite(b) && b > 0) ? (b / 1000000.0) : 0;
          const tbody = el("jobsTable");
          tbody.innerHTML = "";
          for (const j of jobs) {
            const tr = document.createElement("tr");
            tr.style.cursor = "pointer";
            tr.addEventListener("click", async () => {
              await loadJob(j.job_id);
            });
            const tdDate = document.createElement("td");
            tdDate.textContent = j.created_ms ? new Date(j.created_ms).toLocaleString() : "";
            const tdVm = document.createElement("td");
            tdVm.textContent = (j.vm_key || (j.vmid ? ("vmid=" + String(j.vmid)) : "")) || "";
            const tdGb = document.createElement("td");
            const gb = fmtGb(j.bytes_total || 0);
            tdGb.textContent = gb > 0 ? gb.toFixed(2) : "";
            const tdStatus = document.createElement("td");
            tdStatus.textContent = j.status || "";
            const tdCopy = document.createElement("td");
            tdCopy.textContent = (typeof j.copy_pct === "number") ? String(Math.round(j.copy_pct)) : "";
            const tdOps = document.createElement("td");
            tdOps.textContent = (typeof j.ops_pct === "number") ? String(Math.round(j.ops_pct)) : "";
            const tdRate = document.createElement("td");
            const mb = fmtMb(j.rate_bps || 0);
            tdRate.textContent = mb > 0 ? mb.toFixed(2) : "";
            const tdKind = document.createElement("td");
            tdKind.textContent = j.kind || "";
            const tdId = document.createElement("td");
            tdId.textContent = j.job_id || "";
            const tdErr = document.createElement("td");
            tdErr.textContent = j.error || "";
            tr.appendChild(tdDate);
            tr.appendChild(tdVm);
            tr.appendChild(tdGb);
            tr.appendChild(tdStatus);
            tr.appendChild(tdCopy);
            tr.appendChild(tdOps);
            tr.appendChild(tdRate);
            tr.appendChild(tdKind);
            tr.appendChild(tdId);
            tr.appendChild(tdErr);
            tbody.appendChild(tr);
          }
          el("jobsStatus").textContent = "OK (" + jobs.length + ")";
        } catch (e) {
          el("jobsStatus").textContent = "Errore: " + e.message;
        }
      }

      el("btnJobsRefresh").addEventListener("click", async () => {
        await refreshJobs();
      });

      el("btnJobStart").addEventListener("click", async () => {
        if (!selectedJobId) return;
        el("btnJobStart").disabled = true;
        el("jobsStatus").textContent = "Avvio job…";
        try {
          await api("/api/jobs/" + encodeURIComponent(selectedJobId) + "/start", {});
          el("jobsStatus").textContent = "Job avviato";
          await loadJob(selectedJobId);
          await refreshJobs();
        } catch (e) {
          el("jobsStatus").textContent = "Errore: " + e.message;
          await loadJob(selectedJobId);
        }
      });

      el("btnInfraPmx").addEventListener("click", async () => {
        el("infraStatus").textContent = "Caricamento…";
        const tbody = el("infraTable");
        tbody.innerHTML = "";
        el("infraDetails").textContent = "";
        selectedInfraPmxVmid = null;
        const pmxId = el("infraPmx").value;
        const pmxRes = (resources || []).find(r => r.id === pmxId);
        const pmxLabel = (pmxRes && (pmxRes.name || pmxRes.host)) ? String((pmxRes.name || pmxRes.host) || "").trim() : "Proxmox";
        try {
          const data = await api("/api/infrastructure/proxmox/list", { pmx_id: pmxId });
          const vms = data.vms || [];
          for (const v of vms) {
            const tr = document.createElement("tr");
            tr.style.cursor = "pointer";
            tr.addEventListener("click", async () => {
              el("infraDetails").textContent = "Carico configurazione…";
              try {
                selectedInfraPmxVmid = v.vmid;
                updateInfraButtons();
                const cfg = await api("/api/infrastructure/proxmox/config", { pmx_id: pmxId, vmid: v.vmid });
                el("infraDetails").textContent = cfg.text || "";
              } catch (e) {
                el("infraDetails").textContent = "Errore: " + e.message;
              }
            });
            const td1 = document.createElement("td");
            td1.textContent = pmxLabel;
            const td2 = document.createElement("td");
            td2.textContent = (v.vmid || "") + " / " + (v.name || "");
            const td3 = document.createElement("td");
            td3.textContent = v.status || "";
            const td4 = document.createElement("td");
            td4.textContent = "clicca per qm config";
            tr.appendChild(td1);
            tr.appendChild(td2);
            tr.appendChild(td3);
            tr.appendChild(td4);
            tbody.appendChild(tr);
          }
          el("infraStatus").textContent = "OK (" + vms.length + ")";
        } catch (e) {
          el("infraStatus").textContent = "Errore: " + e.message;
        }
      });

      el("btnInfraEsxi").addEventListener("click", async () => {
        el("infraStatus").textContent = "Caricamento…";
        const tbody = el("infraTable");
        tbody.innerHTML = "";
        el("infraDetails").textContent = "";
        selectedInfraEsxiVmid = null;
        const esxiId = el("infraEsxi").value;
        const esxiRes = (resources || []).find(r => r.id === esxiId);
        const esxiLabel = (esxiRes && (esxiRes.name || esxiRes.host)) ? String((esxiRes.name || esxiRes.host) || "").trim() : "ESXi";
        try {
          const data = await api("/api/infrastructure/esxi/list", { esxi_id: esxiId });
          const vms = data.vms || [];
          for (const v of vms) {
            const tr = document.createElement("tr");
            tr.style.cursor = "pointer";
            tr.addEventListener("click", async () => {
              el("infraDetails").textContent = "Carico dettagli…";
              try {
                selectedInfraEsxiVmid = v.vmid;
                updateInfraButtons();
                const det = await api("/api/infrastructure/esxi/details", { esxi_id: esxiId, vmid: v.vmid });
                const text =
                  (det && det.summary ? ("== summary ==\\n" + det.summary + "\\n\\n") : "") +
                  (det && det.config ? ("== config ==\\n" + det.config + "\\n\\n") : "") +
                  (det && det.devices ? ("== devices ==\\n" + det.devices + "\\n\\n") : "") +
                  (det && det.filelayout ? ("== filelayout ==\\n" + det.filelayout) : "");
                el("infraDetails").textContent = text || "";
              } catch (e) {
                el("infraDetails").textContent = "Errore: " + e.message;
              }
            });
            const td1 = document.createElement("td");
            td1.textContent = esxiLabel;
            const td2 = document.createElement("td");
            td2.textContent = (v.vmid || "") + " / " + (v.name || "");
            const td3 = document.createElement("td");
            td3.textContent = v.power || "";
            const td4 = document.createElement("td");
            td4.textContent = "clicca per summary/config";
            tr.appendChild(td1);
            tr.appendChild(td2);
            tr.appendChild(td3);
            tr.appendChild(td4);
            tbody.appendChild(tr);
          }
          el("infraStatus").textContent = "OK (" + vms.length + ")";
        } catch (e) {
          el("infraStatus").textContent = "Errore: " + e.message;
        }
      });

      el("btnBackupRun").addEventListener("click", async () => {
        const virt = (el("backupVirt").value || "esxi").trim();
        const repoStorageId = (el("backupRepoStorage") ? (el("backupRepoStorage").value || "").trim() : "");
        if (virt === "esxi") {
          const esxiId = el("infraEsxi").value;
          if (!esxiId || !selectedInfraEsxiVmid) return;
          el("btnBackupRun").disabled = true;
          el("infraStatus").textContent = "Avvio backup…";
          setProgress(0, "", 0, "");
          log("");
          log("== Avvio backup ESXi ==");
          try {
            const created = await api("/api/jobs/create/backup/esxi-direct", {
              esxi_id: esxiId,
              vmid: selectedInfraEsxiVmid,
              snapshot_name: null,
              allow_power_off: !!el("allowPowerOff").checked,
              remove_snapshot_after: !!el("removeSnapshotAfter").checked,
              backup_label: (el("backupLabel").value || "").trim(),
              repo_storage_id: repoStorageId
            });
            const jobId = created.job_id;
            await api("/api/jobs/" + encodeURIComponent(jobId) + "/start", {});
            el("infraStatus").textContent = "Job avviato: " + jobId;
            showPage("pageJobs");
            await refreshJobs();
            await loadJob(jobId);
          } catch (e) {
            el("infraStatus").textContent = "Errore backup: " + e.message;
            log("Errore backup: " + e.message);
            if ((e.message || "").toLowerCase().includes("già un job")) {
              try { showPage("pageJobs"); } catch (_) {}
              try { await refreshJobs(); } catch (_) {}
            }
          } finally {
            updateInfraButtons();
          }
          return;
        }
        if (virt === "proxmox") {
          const pmxId = el("infraPmx").value;
          if (!pmxId || !selectedInfraPmxVmid) return;
          el("btnBackupRun").disabled = true;
          el("infraStatus").textContent = "Avvio backup…";
          setProgress(0, "", 0, "");
          log("");
          log("== Avvio backup Proxmox ==");
          try {
            const created = await api("/api/jobs/create/backup/proxmox-vzdump", {
              pmx_id: pmxId,
              vmid: selectedInfraPmxVmid,
              allow_power_off: !!el("allowPowerOff").checked,
              remove_snapshot_after: !!el("removeSnapshotAfter").checked,
              backup_label: (el("backupLabel").value || "").trim(),
              repo_storage_id: repoStorageId
            });
            const jobId = created.job_id;
            await api("/api/jobs/" + encodeURIComponent(jobId) + "/start", {});
            el("infraStatus").textContent = "Job avviato: " + jobId;
            showPage("pageJobs");
            await refreshJobs();
            await loadJob(jobId);
          } catch (e) {
            el("infraStatus").textContent = "Errore backup: " + e.message;
            log("Errore backup: " + e.message);
            if ((e.message || "").toLowerCase().includes("già un job")) {
              try { showPage("pageJobs"); } catch (_) {}
              try { await refreshJobs(); } catch (_) {}
            }
          } finally {
            updateInfraButtons();
          }
          return;
        }
      });

      el("backupVirt").addEventListener("change", () => {
        try { updateBackupVirtUI(); } catch (_) {}
      });

      (async () => {
        showPage("pageHome");
        try { await loadResources(); } catch (e) {}
        try { await loadRepoStorages(); } catch (e) {}
        try { await loadRepoPath(); } catch (e) {}
        try { await refreshResourcesTable(); } catch (e) {}
        try { await refreshBackups(); } catch (e) {}
        try { await refreshHome(); } catch (e) {}
      })();
    </script>
        </div>
      </main>
    </div>
  </body>
</html>
"""


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class ScanResult:
    scan_id: str
    created_ms: int
    vms: Dict[str, Any]


@dataclass
class JobState:
    job_id: str
    created_ms: int
    updated_ms: int = 0
    kind: str = ""
    title: str = ""
    backup_id: Optional[str] = None
    vmid: Optional[int] = None
    vm_key: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    error: Optional[str] = None
    copy_pct: float = 0.0
    copy_msg: str = ""
    ops_pct: float = 0.0
    ops_msg: str = ""
    bytes_total: int = 0
    bytes_done: int = 0
    rate_bps: float = 0.0
    logs: List[str] = field(default_factory=list)
    events: "queue.Queue[dict]" = field(default_factory=queue.Queue)
    _rate_last_ms: int = 0
    _rate_last_bytes: int = 0
    _last_persist_ms: int = 0

    def __post_init__(self):
        if not self.updated_ms:
            self.updated_ms = int(self.created_ms or 0)

    def emit(self, payload: dict):
        try:
            if payload.get("type") == "log":
                line = payload.get("line")
                if isinstance(line, str) and line:
                    self.logs.append(line)
                    if len(self.logs) > 800:
                        self.logs = self.logs[-800:]
        except Exception:
            pass
        try:
            self.events.put_nowait(payload)
        except Exception:
            pass
        try:
            force = False
            if payload.get("type") == "status":
                force = payload.get("status") in ("done", "error")
            elif payload.get("type") in ("backup",):
                force = True
            _job_persist(self, force=force)
        except Exception:
            pass

    def update_transfer(self, bytes_done: int, bytes_total: int):
        try:
            bd = int(bytes_done or 0)
            bt = int(bytes_total or 0)
        except Exception:
            bd = 0
            bt = 0
        self.bytes_done = max(0, bd)
        self.bytes_total = max(0, bt)
        now = _now_ms()
        if self._rate_last_ms and now > self._rate_last_ms and self.bytes_done >= self._rate_last_bytes:
            dt = (now - self._rate_last_ms) / 1000.0
            if dt > 0:
                inst = (self.bytes_done - self._rate_last_bytes) / dt
                if self.rate_bps <= 0:
                    self.rate_bps = float(inst)
                else:
                    self.rate_bps = float(self.rate_bps * 0.75 + inst * 0.25)
        self._rate_last_ms = now
        self._rate_last_bytes = self.bytes_done


_scans: Dict[str, ScanResult] = {}
_jobs: Dict[str, JobState] = {}
_job_lock = threading.Lock()
_active_job_id: Optional[str] = None


def _job_to_dict(job: JobState) -> dict:
    return {
        "job_id": job.job_id,
        "created_ms": job.created_ms,
        "updated_ms": job.updated_ms,
        "kind": job.kind,
        "title": job.title,
        "backup_id": job.backup_id,
        "status": job.status,
        "error": job.error,
        "vmid": job.vmid,
        "vm_key": job.vm_key,
        "copy_pct": job.copy_pct,
        "copy_msg": job.copy_msg,
        "ops_pct": job.ops_pct,
        "ops_msg": job.ops_msg,
        "bytes_total": job.bytes_total,
        "bytes_done": job.bytes_done,
        "rate_bps": job.rate_bps,
        "log_tail": job.logs[-200:],
    }


def _base_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _db_path() -> str:
    return os.path.join(_base_dir(), "app.sqlite3")


def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _db_init() -> None:
    conn = _db_connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS resources (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              name TEXT NOT NULL,
              host TEXT NOT NULL,
              username TEXT NOT NULL,
              password TEXT NOT NULL,
              port INTEGER NOT NULL,
              created_ms INTEGER NOT NULL,
              updated_ms INTEGER NOT NULL
            )
            """
        )
        try:
            cols = [str(r[1]) for r in conn.execute("PRAGMA table_info(resources)").fetchall()]
            if "name" not in cols:
                conn.execute("ALTER TABLE resources ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS storages (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              name TEXT NOT NULL,
              host TEXT NOT NULL,
              path TEXT NOT NULL,
              username TEXT NOT NULL,
              password TEXT NOT NULL,
              port INTEGER NOT NULL,
              created_ms INTEGER NOT NULL,
              updated_ms INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              job_id TEXT PRIMARY KEY,
              created_ms INTEGER NOT NULL,
              updated_ms INTEGER NOT NULL,
              kind TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL,
              backup_id TEXT,
              vmid INTEGER,
              vm_key TEXT,
              error TEXT,
              bytes_total INTEGER NOT NULL,
              bytes_done INTEGER NOT NULL,
              rate_bps REAL NOT NULL,
              copy_pct REAL NOT NULL,
              copy_msg TEXT NOT NULL,
              ops_pct REAL NOT NULL,
              ops_msg TEXT NOT NULL,
              log_tail TEXT NOT NULL,
              payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_ms DESC)")
        conn.commit()
    finally:
        conn.close()


def _job_persist(job: JobState, force: bool = False) -> None:
    now = _now_ms()
    if not force and job._last_persist_ms and (now - job._last_persist_ms) < 1500:
        return
    job.updated_ms = now
    payload_json = "{}"
    try:
        payload_json = json.dumps(job.payload or {}, ensure_ascii=False)
    except Exception:
        payload_json = "{}"
    log_tail_text = ""
    try:
        log_tail_text = "\n".join((job.logs or [])[-200:])
    except Exception:
        log_tail_text = ""
    conn = _db_connect()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO jobs (
              job_id, created_ms, updated_ms, kind, title, status, backup_id, vmid, vm_key, error,
              bytes_total, bytes_done, rate_bps,
              copy_pct, copy_msg, ops_pct, ops_msg,
              log_tail, payload_json
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
              ?, ?, ?,
              ?, ?, ?, ?,
              ?, ?
            )
            """,
            (
                job.job_id,
                int(job.created_ms or 0),
                int(job.updated_ms or 0),
                str(job.kind or ""),
                str(job.title or ""),
                str(job.status or ""),
                job.backup_id,
                job.vmid,
                str(job.vm_key or ""),
                job.error,
                int(job.bytes_total or 0),
                int(job.bytes_done or 0),
                float(job.rate_bps or 0.0),
                float(job.copy_pct or 0.0),
                str(job.copy_msg or ""),
                float(job.ops_pct or 0.0),
                str(job.ops_msg or ""),
                log_tail_text,
                payload_json,
            ),
        )
        conn.commit()
        job._last_persist_ms = now
    finally:
        conn.close()


def _jobs_load_from_db(limit: int = 200) -> List[JobState]:
    conn = _db_connect()
    try:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_ms DESC LIMIT ?", (int(limit),)).fetchall()
        out: List[JobState] = []
        for r in rows:
            j = JobState(
                job_id=str(r["job_id"]),
                created_ms=int(r["created_ms"] or 0),
                updated_ms=int(r["updated_ms"] or 0),
                kind=str(r["kind"] or ""),
                title=str(r["title"] or ""),
                status=str(r["status"] or ""),
            )
            j.backup_id = (r["backup_id"] if r["backup_id"] is not None else None)
            try:
                j.vmid = int(r["vmid"]) if r["vmid"] is not None else None
            except Exception:
                j.vmid = None
            j.vm_key = str(r["vm_key"] or "")
            j.error = (r["error"] if r["error"] is not None else None)
            j.bytes_total = int(r["bytes_total"] or 0)
            j.bytes_done = int(r["bytes_done"] or 0)
            try:
                j.rate_bps = float(r["rate_bps"] or 0.0)
            except Exception:
                j.rate_bps = 0.0
            j.copy_pct = float(r["copy_pct"] or 0.0)
            j.copy_msg = str(r["copy_msg"] or "")
            j.ops_pct = float(r["ops_pct"] or 0.0)
            j.ops_msg = str(r["ops_msg"] or "")
            lt = str(r["log_tail"] or "")
            j.logs = [ln for ln in lt.splitlines() if ln.strip()]
            try:
                j.payload = json.loads(str(r["payload_json"] or "{}")) or {}
            except Exception:
                j.payload = {}
            out.append(j)
        return out
    finally:
        conn.close()


def _job_get_from_db(job_id: str) -> Optional[JobState]:
    conn = _db_connect()
    try:
        r = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not r:
            return None
        j = JobState(
            job_id=str(r["job_id"]),
            created_ms=int(r["created_ms"] or 0),
            updated_ms=int(r["updated_ms"] or 0),
            kind=str(r["kind"] or ""),
            title=str(r["title"] or ""),
            status=str(r["status"] or ""),
        )
        j.backup_id = (r["backup_id"] if r["backup_id"] is not None else None)
        try:
            j.vmid = int(r["vmid"]) if r["vmid"] is not None else None
        except Exception:
            j.vmid = None
        j.vm_key = str(r["vm_key"] or "")
        j.error = (r["error"] if r["error"] is not None else None)
        j.bytes_total = int(r["bytes_total"] or 0)
        j.bytes_done = int(r["bytes_done"] or 0)
        try:
            j.rate_bps = float(r["rate_bps"] or 0.0)
        except Exception:
            j.rate_bps = 0.0
        j.copy_pct = float(r["copy_pct"] or 0.0)
        j.copy_msg = str(r["copy_msg"] or "")
        j.ops_pct = float(r["ops_pct"] or 0.0)
        j.ops_msg = str(r["ops_msg"] or "")
        lt = str(r["log_tail"] or "")
        j.logs = [ln for ln in lt.splitlines() if ln.strip()]
        try:
            j.payload = json.loads(str(r["payload_json"] or "{}")) or {}
        except Exception:
            j.payload = {}
        return j
    finally:
        conn.close()


def _settings_get(key: str) -> Optional[str]:
    conn = _db_connect()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else None
    finally:
        conn.close()


def _settings_set(key: str, value: str) -> None:
    conn = _db_connect()
    try:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def _ensure_repo_writable(repo_dir: str) -> None:
    repo_dir = os.path.abspath(os.path.expanduser(repo_dir))
    os.makedirs(repo_dir, exist_ok=True)
    test_dir = os.path.join(repo_dir, f".vm-migration-tool-write-test-{uuid.uuid4()}")
    test_file = os.path.join(test_dir, "test.txt")
    os.makedirs(test_dir, exist_ok=True)
    try:
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("ok")
    finally:
        try:
            os.remove(test_file)
        except Exception:
            pass
        try:
            os.rmdir(test_dir)
        except Exception:
            pass


def _list_resources() -> List[dict]:
    conn = _db_connect()
    try:
        rows = conn.execute(
            "SELECT id, kind, name, host, username, port, created_ms, updated_ms FROM resources ORDER BY updated_ms DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_resource(resource_id: str) -> Optional[dict]:
    conn = _db_connect()
    try:
        row = conn.execute(
            "SELECT id, kind, name, host, username, password, port, created_ms, updated_ms FROM resources WHERE id=?",
            (resource_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _upsert_resource(payload: dict) -> str:
    rid = (payload.get("id") or "").strip() or str(uuid.uuid4())
    kind = (payload.get("kind") or "").strip().lower()
    if kind == "vmware":
        kind = "esxi"
    name = (payload.get("name") or "").strip()
    host = (payload.get("host") or "").strip()
    username = (payload.get("username") or "").strip()
    password = payload.get("password")
    port_raw = payload.get("port")
    try:
        port = int(str(port_raw or "22").strip())
    except Exception:
        port = 22
    now = _now_ms()

    if kind not in ("proxmox", "esxi"):
        raise RuntimeError("kind non valido (usa proxmox/esxi)")
    if not host or not username:
        raise RuntimeError("host/username mancanti")

    conn = _db_connect()
    try:
        existing = conn.execute("SELECT password, created_ms FROM resources WHERE id=?", (rid,)).fetchone()
        if existing and (password is None or str(password).strip() == ""):
            password = existing["password"]
        if password is None:
            password = ""
        if not str(password).strip():
            raise RuntimeError("password mancante")
        created_ms = int(existing["created_ms"]) if existing else now
        conn.execute(
            """
            INSERT INTO resources (id, kind, name, host, username, password, port, created_ms, updated_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              kind=excluded.kind,
              name=excluded.name,
              host=excluded.host,
              username=excluded.username,
              password=excluded.password,
              port=excluded.port,
              updated_ms=excluded.updated_ms
            """,
            (rid, kind, str(name or ""), host, username, str(password), port, created_ms, now),
        )
        conn.commit()
        return rid
    finally:
        conn.close()


def _delete_resource(resource_id: str) -> None:
    conn = _db_connect()
    try:
        conn.execute("DELETE FROM resources WHERE id=?", (resource_id,))
        conn.commit()
    finally:
        conn.close()


def _list_storages() -> List[dict]:
    conn = _db_connect()
    try:
        rows = conn.execute(
            "SELECT id, kind, name, host, path, username, port, created_ms, updated_ms FROM storages ORDER BY updated_ms DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_storage(storage_id: str) -> Optional[dict]:
    conn = _db_connect()
    try:
        row = conn.execute(
            "SELECT id, kind, name, host, path, username, password, port, created_ms, updated_ms FROM storages WHERE id=?",
            (storage_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _upsert_storage(payload: dict) -> str:
    sid = (payload.get("id") or "").strip() or str(uuid.uuid4())
    kind = (payload.get("kind") or "").strip().lower()
    name = (payload.get("name") or "").strip()
    host = (payload.get("host") or "").strip()
    path = (payload.get("path") or "").strip()
    username = (payload.get("username") or "").strip()
    password = payload.get("password")
    port_raw = payload.get("port")
    now = _now_ms()

    if kind not in ("nfs", "iscsi"):
        raise RuntimeError("kind non valido (usa nfs/iscsi)")
    if not path:
        raise RuntimeError("percorso/target mancante")
    if kind == "iscsi" and not host:
        raise RuntimeError("host mancante")
    if not host and os.name != "nt":
        raise RuntimeError("host mancante")

    if port_raw is None or str(port_raw).strip() == "":
        port = 3260 if kind == "iscsi" else 2049
    else:
        try:
            port = int(str(port_raw).strip())
        except Exception:
            port = 3260 if kind == "iscsi" else 2049

    conn = _db_connect()
    try:
        existing = conn.execute("SELECT password, created_ms FROM storages WHERE id=?", (sid,)).fetchone()
        if existing and (password is None or str(password).strip() == ""):
            password = existing["password"]
        if password is None:
            password = ""
        created_ms = int(existing["created_ms"]) if existing else now
        conn.execute(
            """
            INSERT INTO storages (id, kind, name, host, path, username, password, port, created_ms, updated_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              kind=excluded.kind,
              name=excluded.name,
              host=excluded.host,
              path=excluded.path,
              username=excluded.username,
              password=excluded.password,
              port=excluded.port,
              updated_ms=excluded.updated_ms
            """,
            (sid, kind, str(name or ""), host, path, str(username or ""), str(password or ""), port, created_ms, now),
        )
        conn.commit()
        return sid
    finally:
        conn.close()


def _delete_storage(storage_id: str) -> None:
    conn = _db_connect()
    try:
        conn.execute("DELETE FROM storages WHERE id=?", (storage_id,))
        conn.commit()
    finally:
        conn.close()


def _looks_like_windows_path(p: str) -> bool:
    p = (p or "").strip()
    if not p:
        return False
    if p.startswith("\\\\"):
        return True
    return re.match(r"^[A-Za-z]:[\\\\/]", p) is not None


def _storage_repo_effective_path(sto: dict) -> str:
    p = (sto.get("path") or "").strip()
    host = (sto.get("host") or "").strip()
    if os.name == "nt":
        if _looks_like_windows_path(p):
            return p
        if p.startswith("/") and host:
            return "\\\\" + host + "\\" + p.lstrip("/").replace("/", "\\")
    return p


def _unc_share_root(path: str) -> Optional[str]:
    p = (path or "").strip()
    if not p.startswith("\\\\"):
        return None
    parts = [x for x in p.strip("\\").split("\\") if x]
    if len(parts) < 2:
        return None
    return "\\\\" + parts[0] + "\\" + parts[1]


def _try_net_use_connect(unc_share: str, username: str, password: str) -> Tuple[bool, bool, str]:
    unc_share = (unc_share or "").strip()
    if not unc_share:
        return False, False, "Condivisione non valida"
    try:
        res0 = subprocess.run(["net", "use", unc_share], capture_output=True, text=True)
        if res0.returncode == 0:
            return True, False, "Già connessa"
    except Exception:
        pass

    if not username or not password:
        return False, False, "Credenziali mancanti"

    res = subprocess.run(["net", "use", unc_share, password, f"/user:{username}"], capture_output=True, text=True)
    if res.returncode == 0:
        return True, True, "Connessa con credenziali"
    out = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
    out = out.splitlines()[-1] if out else ""
    low = (out or "").lower()
    if "connessioni multiple" in low or "multiple connections" in low or "1219" in low:
        return False, False, "Condivisione già connessa con credenziali diverse (Windows)"
    return False, False, out or "Connessione fallita"


def _net_use_disconnect(unc_share: str) -> None:
    unc_share = (unc_share or "").strip()
    if not unc_share:
        return
    try:
        subprocess.run(["net", "use", unc_share, "/delete", "/y"], capture_output=True, text=True)
    except Exception:
        return


def _repo_root_dir() -> str:
    configured = (_settings_get("repo_path") or "").strip()
    preferred = os.path.abspath(os.path.expanduser(configured)) if configured else ""
    fallback = os.path.abspath(os.path.join(_base_dir(), "repository"))
    if preferred:
        try:
            _ensure_repo_writable(preferred)
            return preferred
        except Exception:
            pass
    _ensure_repo_writable(fallback)
    return fallback


def _repo_dir_for_storage(repo_storage_id: Optional[str]) -> str:
    sid = (repo_storage_id or "").strip()
    if not sid:
        return _repo_root_dir()
    sto = _get_storage(sid)
    if not sto:
        raise RuntimeError("Storage repository non trovato")
    p = _storage_repo_effective_path(sto)
    if not p:
        raise RuntimeError("Storage repository senza percorso/target")
    abs_p = os.path.abspath(os.path.expanduser(p))
    try:
        _ensure_repo_writable(abs_p)
        return abs_p
    except Exception:
        fallback = os.path.join(_repo_root_dir(), "storages", sid)
        _ensure_repo_writable(fallback)
        return fallback


def _load_backup_manifest(backup_id: str, repo_dir: Optional[str] = None) -> dict:
    repo_dir = repo_dir or _repo_root_dir()
    manifest_path = os.path.join(repo_dir, backup_id, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _list_backups(repo_dir: Optional[str] = None) -> List[dict]:
    repo_dir = repo_dir or _repo_root_dir()
    out: List[dict] = []
    try:
        for name in os.listdir(repo_dir):
            p = os.path.join(repo_dir, name)
            if not os.path.isdir(p):
                continue
            manifest_path = os.path.join(p, "manifest.json")
            if not os.path.isfile(manifest_path):
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    m = json.load(f)
                created_ms = int(m.get("created_ms") or 0)
                source = m.get("source") or {}
                source_type = str(source.get("type") or "").strip()
                vm_obj = m.get("vm") or {}
                vm_key = (vm_obj.get("key") or "").strip()
                vmid = str(vm_obj.get("vmid") or "").strip()
                vm_name = str(vm_obj.get("name") or "").strip()
                if not vm_name:
                    info = vm_obj.get("info") if isinstance(vm_obj, dict) else None
                    if isinstance(info, dict):
                        vm_name = str(info.get("name") or "").strip()
                label = (m.get("label") or "").strip()
                if not label:
                    if vm_key:
                        label = f"{name} — {vm_key}"
                    elif vmid or vm_name:
                        label = f"{name} — {vmid}{(' / ' + vm_name) if vm_name else ''}"
                    else:
                        label = f"{name} — vm"
                out.append(
                    {
                        "backup_id": name,
                        "created_ms": created_ms,
                        "source_type": source_type,
                        "vm_key": vm_key,
                        "vmid": vmid,
                        "vm_name": vm_name,
                        "label": label,
                    }
                )
            except Exception:
                continue
    except Exception:
        return []
    out.sort(key=lambda x: int(x.get("created_ms") or 0), reverse=True)
    return out


def create_app() -> Flask:
    app = Flask(__name__)
    _db_init()
    try:
        loaded = _jobs_load_from_db(limit=200)
        with _job_lock:
            for j in loaded:
                if j.status in ("queued", "running"):
                    j.status = "error"
                    j.error = "Interrotto: applicazione riavviata"
                    _job_persist(j, force=True)
                _jobs[j.job_id] = j
    except Exception:
        pass

    @app.get("/")
    def index():
        return Response(
            INDEX_HTML,
            mimetype="text/html; charset=utf-8",
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
            },
        )

    @app.get("/api/resources")
    def api_resources_list():
        return jsonify({"resources": _list_resources()})

    @app.post("/api/resources")
    def api_resources_upsert():
        body = request.get_json(force=True, silent=True) or {}
        try:
            rid = _upsert_resource(body)
            return jsonify({"id": rid})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.delete("/api/resources/<resource_id>")
    def api_resources_delete(resource_id: str):
        try:
            _delete_resource(resource_id)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.get("/api/storages")
    def api_storages_list():
        return jsonify({"storages": _list_storages()})

    @app.post("/api/storages")
    def api_storages_upsert():
        body = request.get_json(force=True, silent=True) or {}
        try:
            sid = _upsert_storage(body)
            return jsonify({"id": sid})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.delete("/api/storages/<storage_id>")
    def api_storages_delete(storage_id: str):
        try:
            _delete_storage(storage_id)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.post("/api/storages/<storage_id>/check")
    def api_storages_check(storage_id: str):
        sto = _get_storage(storage_id)
        if not sto:
            return jsonify({"error": "storage_id non trovato"}), 404
        effective = _storage_repo_effective_path(sto)
        abs_p = os.path.abspath(os.path.expanduser(effective))
        unc_root = _unc_share_root(effective) if os.name == "nt" else None
        created_conn = False
        note = ""
        try:
            try:
                _ensure_repo_writable(abs_p)
                return jsonify({"ok": True, "path": abs_p, "note": "Accessibile"})
            except Exception as first_err:
                if not unc_root:
                    return jsonify({"ok": False, "error": str(first_err), "path": abs_p}), 400
                ok, created_conn, msg = _try_net_use_connect(
                    unc_root, (sto.get("username") or "").strip(), (sto.get("password") or "").strip()
                )
                if not ok:
                    return jsonify({"ok": False, "error": msg, "path": abs_p}), 400
                note = msg
                _ensure_repo_writable(abs_p)
                return jsonify({"ok": True, "path": abs_p, "note": note})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e), "path": abs_p}), 400
        finally:
            if created_conn and unc_root:
                _net_use_disconnect(unc_root)

    @app.get("/api/settings/repo")
    def api_settings_repo_get():
        configured = (_settings_get("repo_path") or "").strip()
        effective = _repo_root_dir()
        warning = ""
        if configured:
            configured_abs = os.path.abspath(os.path.expanduser(configured))
            if os.path.normcase(configured_abs) != os.path.normcase(effective):
                warning = "Percorso configurato non scrivibile: uso fallback"
        return jsonify({"path": effective, "configured": configured, "warning": warning})

    @app.post("/api/settings/repo")
    def api_settings_repo_set():
        body = request.get_json(force=True, silent=True) or {}
        raw = str(body.get("path") or "").strip()
        if not raw:
            _settings_set("repo_path", "")
            return jsonify({"path": _repo_root_dir(), "configured": "", "warning": ""})
        repo_dir = os.path.abspath(os.path.expanduser(raw))
        try:
            _ensure_repo_writable(repo_dir)
        except Exception as e:
            return jsonify({"error": f"Percorso non scrivibile: {e}"}), 400
        _settings_set("repo_path", repo_dir)
        return jsonify({"path": _repo_root_dir(), "configured": repo_dir, "warning": ""})

    @app.get("/api/metrics")
    def api_metrics():
        sid = (request.args.get("repo_storage_id") or "").strip()
        try:
            repo_dir = _repo_dir_for_storage(sid) if sid else _repo_root_dir()
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        def _dir_size_bytes(root: str) -> int:
            total = 0
            try:
                for base, _dirs, files in os.walk(root):
                    for fn in files:
                        try:
                            fp = os.path.join(base, fn)
                            total += int(os.path.getsize(fp))
                        except Exception:
                            continue
            except Exception:
                return 0
            return int(total)

        backups = _list_backups(repo_dir=repo_dir)
        backups_total = int(len(backups))
        bytes_total = 0
        vm_ids: set[str] = set()
        for b in backups:
            bid = str(b.get("backup_id") or "").strip()
            if bid:
                bytes_total += _dir_size_bytes(os.path.join(repo_dir, bid))
            vm_key = str(b.get("vm_key") or "").strip()
            vmid = str(b.get("vmid") or "").strip()
            vm_name = str(b.get("vm_name") or "").strip()
            if vm_key:
                vm_ids.add(f"key:{vm_key}")
            elif vmid:
                vm_ids.add(f"vmid:{vmid}")
            elif vm_name:
                vm_ids.add(f"name:{vm_name}")
        vms_in_backup_total = int(len(vm_ids))

        migrated: set[str] = set()
        try:
            with _job_lock:
                jobs = list(_jobs.values())
            for j in jobs:
                if getattr(j, "kind", "") != "migration":
                    continue
                if getattr(j, "status", "") != "done":
                    continue
                vm_key = str(getattr(j, "vm_key", "") or "").strip()
                if not vm_key and isinstance(getattr(j, "payload", None), dict):
                    vm_key = str((j.payload or {}).get("vm_key") or "").strip()
                migrated.add(vm_key or str(getattr(j, "job_id", "") or ""))
        except Exception:
            migrated = set()

        return jsonify(
            {
                "backups_total": backups_total,
                "backup_bytes_total": int(bytes_total),
                "backup_gb_total": float(bytes_total) / 1000000000.0,
                "vms_in_backup_total": vms_in_backup_total,
                "vms_migrated_total": int(len(migrated)),
            }
        )

    def _resolve_pmx(body: dict) -> tuple[str, str, str]:
        pmx_id = (body.get("pmx_id") or "").strip()
        if pmx_id:
            r = _get_resource(pmx_id)
            if not r or r.get("kind") != "proxmox":
                raise RuntimeError("pmx_id non valido")
            return str(r["host"]), str(r["username"]), str(r["password"])
        host = (body.get("pmx_host") or "").strip()
        user = (body.get("pmx_user") or "").strip()
        pw = body.get("pmx_pass") or ""
        if not host or not user or not pw:
            raise RuntimeError("Credenziali Proxmox mancanti")
        return host, user, pw

    def _resolve_pmx_conn(body: dict) -> tuple[str, str, str, int]:
        pmx_id = (body.get("pmx_id") or "").strip()
        if pmx_id:
            r = _get_resource(pmx_id)
            if not r or r.get("kind") != "proxmox":
                raise RuntimeError("pmx_id non valido")
            port = 22
            try:
                port = int(r.get("port") or 22)
            except Exception:
                port = 22
            return str(r["host"]), str(r["username"]), str(r["password"]), port
        host = (body.get("pmx_host") or "").strip()
        user = (body.get("pmx_user") or "").strip()
        pw = body.get("pmx_pass") or ""
        port_raw = body.get("pmx_port")
        try:
            port = int(str(port_raw or "22").strip())
        except Exception:
            port = 22
        if not host or not user or not pw:
            raise RuntimeError("Credenziali Proxmox mancanti")
        return host, user, pw, port

    def _resolve_esxi(body: dict) -> tuple[str, str, str]:
        esxi_id = (body.get("esxi_id") or "").strip()
        if esxi_id:
            r = _get_resource(esxi_id)
            if not r or (r.get("kind") not in ("esxi", "vmware")):
                raise RuntimeError("esxi_id non valido")
            return str(r["host"]), str(r["username"]), str(r["password"])
        host = (body.get("esxi_host") or "").strip()
        user = (body.get("esxi_user") or "").strip()
        pw = body.get("esxi_pass") or ""
        if not host or not user or not pw:
            raise RuntimeError("Credenziali ESXi mancanti")
        return host, user, pw

    def _resolve_esxi_conn(body: dict) -> tuple[str, str, str, int]:
        esxi_id = (body.get("esxi_id") or "").strip()
        if esxi_id:
            r = _get_resource(esxi_id)
            if not r or (r.get("kind") not in ("esxi", "vmware")):
                raise RuntimeError("esxi_id non valido")
            port = 22
            try:
                port = int(r.get("port") or 22)
            except Exception:
                port = 22
            return str(r["host"]), str(r["username"]), str(r["password"]), port
        host = (body.get("esxi_host") or "").strip()
        user = (body.get("esxi_user") or "").strip()
        pw = body.get("esxi_pass") or ""
        port_raw = body.get("esxi_port")
        try:
            port = int(str(port_raw or "22").strip())
        except Exception:
            port = 22
        if not host or not user or not pw:
            raise RuntimeError("Credenziali ESXi mancanti")
        return host, user, pw, port

    @app.post("/api/scan")
    def api_scan():
        body = request.get_json(force=True, silent=True) or {}
        try:
            pmx_host, pmx_user, pmx_pass = _resolve_pmx(body)
            esxi_host, esxi_user, esxi_pass = _resolve_esxi(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        ssh = SSHClient(pmx_host, pmx_user, pmx_pass, log_cb=None)
        try:
            ssh.connect()
            storages = list_storages(ssh)
            bridges = list_bridges(ssh)
            nextid = get_next_vmid(ssh)

            write_esxi_password_file(ssh, esxi_pass)
            vms_map = list_vms(ssh, esxi_host, esxi_user, "/root/esxi_pass.txt", skip_cert=True)

            scan_id = str(uuid.uuid4())
            _scans[scan_id] = ScanResult(scan_id=scan_id, created_ms=_now_ms(), vms=vms_map)

            vms_list: List[dict] = []
            for key, info in vms_map.items():
                disks = info.get("disks", []) if isinstance(info, dict) else []
                label = key
                suggested = key
                if disks:
                    d0 = disks[0]
                    path = d0.get("path") or ""
                    if isinstance(path, str) and "/" in path:
                        suggested = path.split("/", 1)[0] or suggested
                        label = suggested
                vms_list.append({"key": key, "label": label, "suggested_name": suggested})

            return jsonify(
                {
                    "scan_id": scan_id,
                    "storages": storages,
                    "bridges": bridges,
                    "next_vmid": nextid,
                    "vms": vms_list,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            try:
                ssh.close()
            except Exception:
                pass

    @app.post("/api/jobs/start")
    def api_jobs_start():
        body = request.get_json(force=True, silent=True) or {}
        scan_id = (body.get("scan_id") or "").strip()
        vm_key = (body.get("vm_key") or "").strip()
        try:
            pmx_host, pmx_user, pmx_pass = _resolve_pmx(body)
            esxi_host, esxi_user, esxi_pass = _resolve_esxi(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        storage = (body.get("storage") or "").strip()
        bridge = (body.get("bridge") or "").strip()
        name = (body.get("name") or "").strip() or "vm"
        dest_dir = (body.get("dest_dir") or "").strip() or None

        try:
            vmid = int(str(body.get("vmid") or "").strip())
            mem = int(str(body.get("mem") or "").strip())
            cores = int(str(body.get("cores") or "").strip())
        except Exception:
            return jsonify({"error": "VMID/RAM/vCPU non validi"}), 400

        use_uefi = bool(body.get("uefi"))
        use_snapshot = bool(body.get("snapshot"))
        use_convert = bool(body.get("convert"))
        convert_fmt = (body.get("format") or "qcow2").strip() or "qcow2"

        if not scan_id or not vm_key:
            return jsonify({"error": "scan_id/vm_key mancanti"}), 400
        scan = _scans.get(scan_id)
        if not scan:
            return jsonify({"error": "scan_id non valido o scaduto"}), 400
        selected_vm_info = scan.vms.get(vm_key)
        if not isinstance(selected_vm_info, dict):
            return jsonify({"error": "VM selezionata non valida"}), 400

        if not storage or not bridge:
            return jsonify({"error": "Storage/Bridge mancanti"}), 400

        net0 = f"virtio,bridge={bridge}"

        with _job_lock:
            global _active_job_id
            if _active_job_id and _jobs.get(_active_job_id) and _jobs[_active_job_id].status in ("queued", "running"):
                return jsonify({"error": "C'è già un job in esecuzione (MVP: 1 job alla volta)"}), 409

            job_id = str(uuid.uuid4())
            job = JobState(job_id=job_id, created_ms=_now_ms(), status="queued", kind="migration", title=f"Migrazione {vm_key}")
            job.vm_key = str(vm_key or "")
            job.payload = {"vm_key": job.vm_key}
            try:
                disks = selected_vm_info.get("disks", []) if isinstance(selected_vm_info, dict) else []
                total = 0
                for d in disks:
                    try:
                        total += int(d.get("capacity") or 0)
                    except Exception:
                        continue
                if total > 0:
                    job.update_transfer(0, total)
            except Exception:
                pass
            _jobs[job_id] = job
            _active_job_id = job_id
            _job_persist(job, force=True)

        def _run_job():
            ssh: Optional[SSHClient] = None
            try:
                job.status = "running"
                job.emit({"type": "status", "status": "running"})
                ssh = SSHClient(pmx_host, pmx_user, pmx_pass, log_cb=None)
                ssh.connect()

                def progress_cb(pct: float, msg: str):
                    m = (msg or "")
                    is_copy = m.strip().lower().startswith("copia")
                    if is_copy:
                        job.copy_pct = float(pct or 0.0)
                        job.copy_msg = m
                    else:
                        job.ops_pct = float(pct or 0.0)
                        job.ops_msg = m
                    job.emit(
                        {
                            "type": "progress",
                            "copy_pct": job.copy_pct,
                            "copy_msg": job.copy_msg,
                            "ops_pct": job.ops_pct,
                            "ops_msg": job.ops_msg,
                            "bytes_total": job.bytes_total,
                            "bytes_done": job.bytes_done,
                            "rate_bps": job.rate_bps,
                        }
                    )
                    job.emit({"type": "log", "line": f"{pct:.1f}% — {m}"})

                logs = execute_full_migration(
                    ssh,
                    esxi_host,
                    esxi_user,
                    esxi_pass,
                    selected_vm_info,
                    vmid,
                    name,
                    mem,
                    cores,
                    net0,
                    storage,
                    dest_dir,
                    use_uefi,
                    selected_disk_indexes=None,
                    use_convert=use_convert,
                    convert_fmt=convert_fmt,
                    use_esxi_snapshot=use_snapshot,
                    progress_cb=progress_cb,
                )
                for line in logs:
                    job.emit({"type": "log", "line": line})

                job.status = "done"
                job.emit({"type": "status", "status": "done"})
            except Exception as e:
                job.status = "error"
                job.error = str(e)
                job.emit({"type": "log", "line": f"ERRORE: {job.error}"})
                job.emit({"type": "status", "status": "error"})
            finally:
                try:
                    if ssh:
                        try:
                            ssh.run("shred -u /root/esxi_pass.txt || rm -f /root/esxi_pass.txt")
                        except Exception:
                            pass
                finally:
                    try:
                        if ssh:
                            ssh.close()
                    except Exception:
                        pass
                with _job_lock:
                    global _active_job_id
                    if _active_job_id == job_id:
                        _active_job_id = None

        t = threading.Thread(target=_run_job, daemon=True)
        t.start()

        return jsonify({"job_id": job_id})

    @app.get("/api/backups")
    def api_backups_list():
        sid = (request.args.get("repo_storage_id") or "").strip()
        try:
            repo_dir = _repo_dir_for_storage(sid) if sid else _repo_root_dir()
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"backups": _list_backups(repo_dir=repo_dir)})

    @app.post("/api/backups/capture/esxi")
    def api_backups_capture_esxi():
        body = request.get_json(force=True, silent=True) or {}
        scan_id = (body.get("scan_id") or "").strip()
        vm_key = (body.get("vm_key") or "").strip()
        repo_storage_id = (body.get("repo_storage_id") or "").strip()
        try:
            pmx_host, pmx_user, pmx_pass = _resolve_pmx(body)
            esxi_host, esxi_user, esxi_pass = _resolve_esxi(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        use_snapshot = bool(body.get("snapshot"))

        if not scan_id or not vm_key:
            return jsonify({"error": "scan_id/vm_key mancanti"}), 400
        scan = _scans.get(scan_id)
        if not scan:
            return jsonify({"error": "scan_id non valido o scaduto"}), 400
        selected_vm_info = scan.vms.get(vm_key)
        if not isinstance(selected_vm_info, dict):
            return jsonify({"error": "VM selezionata non valida"}), 400

        with _job_lock:
            global _active_job_id
            if _active_job_id and _jobs.get(_active_job_id) and _jobs[_active_job_id].status in ("queued", "running"):
                return jsonify({"error": "C'è già un job in esecuzione (MVP: 1 job alla volta)"}), 409

            job_id = str(uuid.uuid4())
            job = JobState(job_id=job_id, created_ms=_now_ms(), status="queued", kind="backup_esxi_via_proxmox", title=f"Backup ESXi {vm_key}")
            job.vm_key = str(vm_key or "")
            job.payload = {"vm_key": job.vm_key}
            try:
                disks = selected_vm_info.get("disks", []) if isinstance(selected_vm_info, dict) else []
                total = 0
                for d in disks:
                    try:
                        total += int(d.get("capacity") or 0)
                    except Exception:
                        continue
                if total > 0:
                    job.update_transfer(0, total)
            except Exception:
                pass
            _jobs[job_id] = job
            _active_job_id = job_id
            _job_persist(job, force=True)

        backup_id = str(uuid.uuid4())
        job.backup_id = backup_id
        _job_persist(job, force=True)
        try:
            repo_dir = _repo_dir_for_storage(repo_storage_id) if repo_storage_id else _repo_root_dir()
        except Exception as e:
            return jsonify({"error": f"Repository non scrivibile: {e}"}), 400
        backup_dir = os.path.join(repo_dir, backup_id)
        os.makedirs(backup_dir, exist_ok=True)

        def _run_job():
            ssh: Optional[SSHClient] = None
            tmp_dir = f"/root/tmp/vm-migration-tool-capture/{backup_id}"
            snapshot_vmid: Optional[int] = None
            snapshot_id: Optional[int] = None
            snapshot_name: Optional[str] = None

            try:
                job.status = "running"
                job.emit({"type": "status", "status": "running"})
                ssh = SSHClient(pmx_host, pmx_user, pmx_pass, log_cb=None)
                ssh.connect()
                ensure_dir(ssh, tmp_dir)

                def progress_cb(pct: float, msg: str):
                    m = (msg or "")
                    is_copy = m.strip().lower().startswith("copia")
                    if is_copy:
                        job.copy_pct = float(pct or 0.0)
                        job.copy_msg = m
                    else:
                        job.ops_pct = float(pct or 0.0)
                        job.ops_msg = m
                    job.emit(
                        {
                            "type": "progress",
                            "copy_pct": job.copy_pct,
                            "copy_msg": job.copy_msg,
                            "ops_pct": job.ops_pct,
                            "ops_msg": job.ops_msg,
                            "bytes_total": job.bytes_total,
                            "bytes_done": job.bytes_done,
                            "rate_bps": job.rate_bps,
                        }
                    )
                    job.emit({"type": "log", "line": f"{pct:.1f}% — {m}"})

                write_esxi_password_file(ssh, esxi_pass)

                power = str(selected_vm_info.get("power", "") or "")
                if power == "poweredOn" and not use_snapshot:
                    raise RuntimeError("VM accesa su ESXi: abilita Snapshot per cattura hot")

                if use_snapshot:
                    cfg = selected_vm_info.get("config", {}) if isinstance(selected_vm_info, dict) else {}
                    cfg_ds = (cfg.get("datastore") or "").strip()
                    cfg_vmx = (cfg.get("path") or "").strip()
                    if not cfg_ds or not cfg_vmx:
                        raise RuntimeError("Dati VMX non disponibili: impossibile creare snapshot ESXi")
                    snapshot_vmid = esxi_find_vmid_by_vmx(ssh, esxi_host, esxi_user, "/root/esxi_pass.txt", cfg_ds, cfg_vmx)
                    if snapshot_vmid is None:
                        raise RuntimeError(f"Impossibile trovare VMID ESXi per VMX {cfg_ds}/{cfg_vmx}")
                    snapshot_name = f"vm-migration-tool-capture-{snapshot_vmid}-{int(time.time())}"
                    progress_cb(0.0, "Snapshot: creazione snapshot ESXi…")
                    try:
                        esxi_create_snapshot(
                            ssh,
                            esxi_host,
                            esxi_user,
                            "/root/esxi_pass.txt",
                            snapshot_vmid,
                            snapshot_name,
                            "Snapshot temporanea per backup",
                            quiesce=True,
                            memory=False,
                        )
                    except Exception as e:
                        job.emit({"type": "log", "line": f"Snapshot con quiesce fallita, retry senza quiesce: {e}"})
                        esxi_create_snapshot(
                            ssh,
                            esxi_host,
                            esxi_user,
                            "/root/esxi_pass.txt",
                            snapshot_vmid,
                            snapshot_name,
                            "Snapshot temporanea per backup",
                            quiesce=False,
                            memory=False,
                        )
                    snapshot_id = esxi_find_snapshot_id_by_name(
                        ssh, esxi_host, esxi_user, "/root/esxi_pass.txt", snapshot_vmid, snapshot_name
                    )
                    if snapshot_id is None:
                        raise RuntimeError("Snapshot creata ma Snapshot Id non trovato (non posso fare cleanup in sicurezza)")

                vm_cfg = selected_vm_info.get("config", {}) if isinstance(selected_vm_info, dict) else {}
                vmx_rel = (vm_cfg.get("path") or "").strip()
                vmx_ds = (vm_cfg.get("datastore") or "").strip()

                disks = selected_vm_info.get("disks", []) if isinstance(selected_vm_info, dict) else []
                if not disks:
                    raise RuntimeError("Nessun disco disponibile per la VM selezionata")

                files_disks: List[dict] = []

                for idx, d in enumerate(disks):
                    vmdk_relpath = (d.get("path") or "").strip()
                    datastore = (d.get("datastore") or "").strip()
                    capacity = int(d.get("capacity") or 0)
                    if not vmdk_relpath or not datastore:
                        raise RuntimeError("Disco non valido: path/datastore mancanti")
                    flat_rel = guess_vmdk_data_rel(vmdk_relpath)
                    dest_flat = copy_vmdk_flat_with_progress(
                        ssh, esxi_host, esxi_user, esxi_pass, datastore, flat_rel, tmp_dir, capacity, progress_cb
                    )
                    copy_vmdk_from_esxi(ssh, esxi_host, esxi_user, esxi_pass, datastore, vmdk_relpath, tmp_dir)
                    desc_name = vmdk_relpath.split("/")[-1]
                    data_name = flat_rel.split("/")[-1]
                    files_disks.append(
                        {
                            "idx": idx,
                            "descriptor": desc_name,
                            "data": data_name,
                            "remote_descriptor": f"{tmp_dir}/{desc_name}",
                            "remote_data": dest_flat,
                        }
                    )

                vmx_filename: Optional[str] = None
                vmx_remote: Optional[str] = None
                if vmx_rel and vmx_ds:
                    vmx_remote = copy_file_from_esxi(ssh, esxi_host, esxi_user, vmx_ds, vmx_rel, tmp_dir)
                    vmx_filename = vmx_rel.split("/")[-1]

                if snapshot_vmid is not None and snapshot_id is not None:
                    progress_cb(0.0, "Snapshot: rimozione snapshot ESXi…")
                    esxi_remove_snapshot(ssh, esxi_host, esxi_user, "/root/esxi_pass.txt", snapshot_vmid, snapshot_id)

                local_files: List[dict] = []

                completed_bytes = 0
                completed_total = 0

                def _download(remote_path: str, local_path: str, label: str):
                    nonlocal completed_bytes, completed_total
                    total = 0
                    try:
                        code, out, _ = ssh.run(f"stat -c %s '{remote_path}' 2>/dev/null || echo 0")
                        total = int((out or "0").strip().splitlines()[-1] or 0)
                    except Exception:
                        total = 0
                    if total > 0:
                        completed_total += total
                        job.update_transfer(completed_bytes, completed_total)

                    def _cb(transferred: int, _total: int):
                        tt = _total or total or 0
                        pct = 0.0
                        if tt > 0:
                            pct = min(100.0, transferred * 100.0 / tt)
                        if tt > 0:
                            job.update_transfer(completed_bytes + int(transferred or 0), completed_total)
                        job.ops_pct = float(pct)
                        job.ops_msg = f"Download: {label} ({transferred}/{tt} bytes)"
                        job.emit(
                            {
                                "type": "progress",
                                "copy_pct": job.copy_pct,
                                "copy_msg": job.copy_msg,
                                "ops_pct": job.ops_pct,
                                "ops_msg": job.ops_msg,
                                "bytes_total": job.bytes_total,
                                "bytes_done": job.bytes_done,
                                "rate_bps": job.rate_bps,
                            }
                        )

                    ssh.get_file(remote_path, local_path, progress_cb=_cb if total > 0 else None)
                    if total > 0:
                        completed_bytes += total
                        job.update_transfer(completed_bytes, completed_total)

                for d in files_disks:
                    local_desc = os.path.join(backup_dir, d["descriptor"])
                    local_data = os.path.join(backup_dir, d["data"])
                    _download(d["remote_descriptor"], local_desc, d["descriptor"])
                    _download(d["remote_data"], local_data, d["data"])
                    local_files.append({"idx": d["idx"], "descriptor": d["descriptor"], "data": d["data"]})

                if vmx_remote and vmx_filename:
                    local_vmx = os.path.join(backup_dir, vmx_filename)
                    _download(vmx_remote, local_vmx, vmx_filename)

                manifest = {
                    "backup_id": backup_id,
                    "created_ms": _now_ms(),
                    "label": f"{backup_id} — {vm_key}",
                    "source": {"type": "esxi", "host": esxi_host, "user": esxi_user},
                    "vm": {"key": vm_key, "info": selected_vm_info},
                    "files": {"vmx": vmx_filename, "disks": local_files},
                }
                with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)

                try:
                    ssh.run(f"rm -rf '{tmp_dir}'")
                except Exception:
                    pass

                job.status = "done"
                job.emit({"type": "backup", "backup_id": backup_id})
                job.emit({"type": "status", "status": "done"})
            except Exception as e:
                job.status = "error"
                job.error = str(e)
                job.emit({"type": "log", "line": f"ERRORE: {job.error}"})
                job.emit({"type": "status", "status": "error"})
                try:
                    if ssh:
                        ssh.run(f"rm -rf '{tmp_dir}'")
                except Exception:
                    pass
            finally:
                try:
                    if ssh:
                        try:
                            ssh.run("shred -u /root/esxi_pass.txt || rm -f /root/esxi_pass.txt")
                        except Exception:
                            pass
                finally:
                    try:
                        if ssh:
                            ssh.close()
                    except Exception:
                        pass
                with _job_lock:
                    global _active_job_id
                    if _active_job_id == job_id:
                        _active_job_id = None

        threading.Thread(target=_run_job, daemon=True).start()
        return jsonify({"job_id": job_id, "backup_id": backup_id})

    def _parse_datastore_url_map(config_text: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for m in re.finditer(r'name\s*=\s*"([^"]+)"\s*,\s*url\s*=\s*"([^"]+)"', config_text or "", flags=re.S):
            name = (m.group(1) or "").strip()
            url = (m.group(2) or "").strip()
            if name and url:
                out[name] = url
        return out

    def _split_bracket_path(bracket_path: str) -> Optional[tuple[str, str]]:
        m = re.match(r"^\[([^\]]+)\]\s+(.+)$", (bracket_path or "").strip())
        if not m:
            return None
        return (m.group(1).strip(), m.group(2).strip())

    def _abs_path_from_bracket(ds_url_map: Dict[str, str], bracket_path: str) -> str:
        t = (bracket_path or "").strip()
        if t.startswith("/vmfs/volumes/"):
            return t
        parts = _split_bracket_path(bracket_path)
        if not parts:
            raise RuntimeError("Path datastore non valido")
        ds, rel = parts
        url = (ds_url_map.get(ds) or "").strip()
        rel = rel.lstrip("/")
        if not url:
            return f"/vmfs/volumes/{ds}/{rel}"
        if not url.endswith("/"):
            url += "/"
        return url + rel

    def _parse_vmdk_candidates(filelayout_text: str) -> List[str]:
        found = re.findall(r"\[[^\]]+\]\s+[^\n,\"]+?\.vmdk", filelayout_text or "")
        found += re.findall(r"(/vmfs/volumes/[^\s,\"]+?\.vmdk)", filelayout_text or "")
        uniq: List[str] = []
        seen = set()
        for p in found:
            pp = (p or "").strip()
            if pp and pp not in seen:
                seen.add(pp)
                uniq.append(pp)
        return uniq

    def _parse_vmdk_candidates_from_config(config_text: str) -> List[str]:
        found = re.findall(r"\[[^\]]+\]\s+[^\n,\"]+?\.vmdk", config_text or "")
        found += re.findall(r"(/vmfs/volumes/[^\s,\"]+?\.vmdk)", config_text or "")
        uniq: List[str] = []
        seen = set()
        for p in found:
            pp = (p or "").strip()
            if pp and pp not in seen:
                seen.add(pp)
                uniq.append(pp)
        return uniq

    def _parse_vmdk_candidates_from_devices(devices_text: str) -> List[str]:
        found: List[str] = []
        found += re.findall(r'fileName\s*=\s*"(\[[^\]]+\]\s+[^"]+?\.vmdk)"', devices_text or "", flags=re.I)
        found += re.findall(r'fileName\s*=\s*"(/vmfs/volumes/[^"]+?\.vmdk)"', devices_text or "", flags=re.I)
        uniq: List[str] = []
        seen = set()
        for p in found:
            pp = (p or "").strip()
            if pp and pp not in seen:
                seen.add(pp)
                uniq.append(pp)
        return uniq

    def _derive_descriptor_rel(relpath: str) -> Optional[str]:
        rel = (relpath or "").strip()
        low = rel.lower()
        if low.endswith("-flat.vmdk"):
            return rel[: -len("-flat.vmdk")] + ".vmdk"
        if low.endswith("-delta.vmdk"):
            return rel[: -len("-delta.vmdk")] + ".vmdk"
        if low.endswith("-sesparse.vmdk"):
            return rel[: -len("-sesparse.vmdk")] + ".vmdk"
        return None

    def _split_abs_vmfs_path(abs_path: str) -> Optional[tuple[str, str]]:
        p = (abs_path or "").strip()
        if not p.startswith("/vmfs/volumes/"):
            return None
        rest = p[len("/vmfs/volumes/") :]
        if "/" not in rest:
            return None
        ds, rel = rest.split("/", 1)
        ds = (ds or "").strip()
        rel = (rel or "").strip()
        if not ds or not rel:
            return None
        return (ds, rel)

    def _split_candidate_path(p: str) -> Optional[tuple[str, str]]:
        t = (p or "").strip()
        if t.startswith("/vmfs/volumes/"):
            return _split_abs_vmfs_path(t)
        return _split_bracket_path(t)

    def _expand_vmdk_candidates(candidates: List[str]) -> List[str]:
        uniq: List[str] = []
        seen = set()
        for p in candidates or []:
            pp = (p or "").strip()
            if not pp or pp in seen:
                continue
            seen.add(pp)
            uniq.append(pp)
            if pp.startswith("/vmfs/volumes/"):
                parts_abs = _split_abs_vmfs_path(pp)
                if not parts_abs:
                    continue
                _, rel_abs = parts_abs
                derived_rel = _derive_descriptor_rel(rel_abs)
                if not derived_rel:
                    continue
                base_dir = pp.rsplit("/", 1)[0]
                d = base_dir + "/" + derived_rel.split("/")[-1]
                if d not in seen:
                    seen.add(d)
                    uniq.append(d)
            else:
                parts = _split_bracket_path(pp)
                if not parts:
                    continue
                ds, rel = parts
                derived_rel = _derive_descriptor_rel(rel)
                if not derived_rel:
                    continue
                d = f"[{ds}] {derived_rel}"
                if d not in seen:
                    seen.add(d)
                    uniq.append(d)
        return uniq

    def _is_vmdk_descriptor_abs(esxi_ssh: SSHClient, abs_path: str) -> bool:
        code, out, _ = esxi_ssh.run(f"head -n 200 {shlex.quote(abs_path)} 2>/dev/null || true", timeout=30)
        if code not in (0, 1):
            return False
        t = (out or "").lower()
        return (
            ("disk descriptorfile" in t)
            or ("extent description" in t)
            or ("ddb." in t)
            or ("createtype" in t)
            or ("parentcid" in t)
            or ("cid=" in t)
            or ("rw " in t and ".vmdk" in t)
        )

    def _base_vmdk_key(ds: str, relpath: str) -> str:
        rel = relpath.strip()
        m = re.match(r"^(.*)-000(\d+)\.vmdk$", rel, flags=re.I)
        if m:
            rel = m.group(1) + ".vmdk"
        return f"{ds}::{rel}"

    def _snapshot_seq(relpath: str) -> int:
        m = re.match(r"^.*-000(\d+)\.vmdk$", (relpath or "").strip(), flags=re.I)
        if not m:
            return -1
        try:
            return int(m.group(1))
        except Exception:
            return -1

    def _read_extent_filename(esxi_ssh: SSHClient, abs_descriptor_path: str) -> str:
        code, out, err = esxi_ssh.run(f"cat {shlex.quote(abs_descriptor_path)}", timeout=30)
        if code != 0:
            raise RuntimeError(err or out or "Impossibile leggere descriptor VMDK")
        m = re.search(r'RW\s+\d+\s+\S+\s+"([^"]+\.vmdk)"', out, flags=re.I)
        if m:
            return m.group(1)
        m2 = re.search(r'"([^"]+\.vmdk)"', out, flags=re.I)
        if m2:
            return m2.group(1)
        raise RuntimeError("Impossibile determinare file dati del VMDK (extent)")

    def _pick_latest_snapshot_descriptor_abs(esxi_ssh: SSHClient, base_descriptor_abs: str) -> Optional[str]:
        p = (base_descriptor_abs or "").strip()
        if not p or "/" not in p:
            return None
        d, fn = p.rsplit("/", 1)
        if not d or not fn:
            return None
        if "-000" in fn.lower():
            return None
        if not fn.lower().endswith(".vmdk"):
            return None
        base = fn[:-5]
        code, out, _ = esxi_ssh.run(f"ls -1 {shlex.quote(d)}/*.vmdk 2>/dev/null || true", timeout=30)
        if code not in (0, 1):
            return None
        best_seq = -1
        best_fn: Optional[str] = None
        for line in (out or "").splitlines():
            t = (line or "").strip()
            if not t:
                continue
            name = t.rsplit("/", 1)[-1]
            m = re.match(rf"^{re.escape(base)}-000(\d+)\.vmdk$", name, flags=re.I)
            if not m:
                continue
            try:
                seq = int(m.group(1))
            except Exception:
                continue
            if seq > best_seq:
                best_seq = seq
                best_fn = name
        if not best_fn:
            return None
        return d.rstrip("/") + "/" + best_fn

    def _clone_vmdk_for_download_abs(esxi_ssh: SSHClient, src_abs_desc: str, job: Any) -> Tuple[str, str]:
        p = (src_abs_desc or "").strip()
        if not p or "/" not in p or not p.lower().endswith(".vmdk"):
            raise RuntimeError("Percorso descriptor non valido per clone")
        desc_dir, fn = p.rsplit("/", 1)
        base = fn[:-5]
        clone_desc_abs = desc_dir.rstrip("/") + f"/{base}-vmmtclone-{int(time.time())}.vmdk"
        job.emit({"type": "log", "line": f"Clone ESXi (vmkfstools -i): {src_abs_desc} → {clone_desc_abs}"})
        esxi_ssh.run(f"rm -f {shlex.quote(clone_desc_abs)} 2>/dev/null || true", timeout=30)
        code, out, err = esxi_ssh.run(
            f"vmkfstools -i {shlex.quote(p)} {shlex.quote(clone_desc_abs)} -d thin",
            timeout=6 * 3600,
        )
        if code != 0:
            raise RuntimeError(err or out or f"vmkfstools -i fallito (exit={code})")
        extent_name = _read_extent_filename(esxi_ssh, clone_desc_abs)
        clone_data_abs = desc_dir.rstrip("/") + "/" + (extent_name or "").lstrip("/")
        return clone_desc_abs, clone_data_abs

    @app.post("/api/backups/capture/esxi/direct")
    def api_backups_capture_esxi_direct():
        body = request.get_json(force=True, silent=True) or {}
        vmid_raw = str(body.get("vmid") or "").strip()
        if not vmid_raw:
            return jsonify({"error": "vmid mancante"}), 400
        try:
            vmid = int(vmid_raw)
        except Exception:
            return jsonify({"error": "vmid non valido"}), 400

        try:
            esxi_host, esxi_user, esxi_pass, esxi_port = _resolve_esxi_conn(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        snapshot_name = (body.get("snapshot_name") or "").strip() or None
        allow_power_off = bool(body.get("allow_power_off"))
        remove_snapshot_after = bool(body.get("remove_snapshot_after", True))
        backup_label = (body.get("backup_label") or "").strip()
        repo_storage_id = (body.get("repo_storage_id") or "").strip()

        def _start_job_esxi_direct(
            job: JobState,
            vmid: int,
            esxi_host: str,
            esxi_user: str,
            esxi_pass: str,
            esxi_port: int,
            snapshot_name: Optional[str],
            allow_power_off: bool,
            remove_snapshot_after: bool,
            backup_label: str,
            repo_dir: str,
        ):
            backup_id = str(uuid.uuid4())
            job.backup_id = backup_id
            _job_persist(job, force=True)
            backup_dir = os.path.join(repo_dir, backup_id)
            os.makedirs(backup_dir, exist_ok=True)

            def _run_job():
                ssh: Optional[SSHClient] = None
                staging_dirs: List[str] = []
                was_powered_on = False
                did_power_off = False
                created_snapshot_id: Optional[int] = None
                created_snapshot_name: Optional[str] = None
                try:
                    job.status = "running"
                    job.emit({"type": "status", "status": "running"})
                    job.emit({"type": "log", "line": f"Backup repo: {backup_dir}"})
                    job.emit({"type": "log", "line": f"ESXi: {esxi_host}:{esxi_port} user={esxi_user} vmid={vmid}"})
                    if snapshot_name:
                        job.emit({"type": "log", "line": f"Snapshot (selezionata): {snapshot_name}"})
                    ssh = SSHClient(esxi_host, esxi_user, esxi_pass, port=esxi_port, log_cb=None)
                    ssh.connect()

                    try:
                        st = (esxi_power_state_direct(ssh, vmid) or "").strip()
                        st_norm = re.sub(r"\s+", "", st.lower())
                        was_powered_on = ("poweredon" in st_norm) or ("poweredon" in st_norm.replace("-", ""))
                        job.emit({"type": "log", "line": f"Power state: {st or '(unknown)'}"})
                    except Exception:
                        was_powered_on = False

                    if was_powered_on:
                        snap_id_existing: Optional[int] = None
                        if snapshot_name:
                            try:
                                snap_id_existing = esxi_find_snapshot_id_by_name_direct(ssh, vmid, snapshot_name)
                            except Exception:
                                snap_id_existing = None
                        if snap_id_existing is None:
                            created_snapshot_name = f"vm-migration-tool-export-{int(time.time())}"
                            job.emit(
                                {
                                    "type": "log",
                                    "line": f"Creo snapshot temporanea '{created_snapshot_name}' (quiesce) per export hot…",
                                }
                            )
                            try:
                                esxi_create_snapshot_direct(
                                    ssh,
                                    vmid,
                                    created_snapshot_name,
                                    "Snapshot temporanea per export hot (vm-migration-tool)",
                                    quiesce=True,
                                    memory=False,
                                )
                            except Exception as e:
                                job.emit({"type": "log", "line": f"Snapshot quiesce fallita, retry senza quiesce: {e}"})
                                esxi_create_snapshot_direct(
                                    ssh,
                                    vmid,
                                    created_snapshot_name,
                                    "Snapshot temporanea per export hot (vm-migration-tool)",
                                    quiesce=False,
                                    memory=False,
                                )
                            created_snapshot_id = esxi_find_snapshot_id_by_name_direct(ssh, vmid, created_snapshot_name)
                            if created_snapshot_id is None:
                                raise RuntimeError("Snapshot creata ma snapshot_id non trovato")
                            job.emit(
                                {
                                    "type": "log",
                                    "line": f"Snapshot export creata: name={created_snapshot_name} id={created_snapshot_id}",
                                }
                            )
                        else:
                            job.emit({"type": "log", "line": f"Uso snapshot esistente: id={snap_id_existing}"})

                    summary = esxi_get_summary_direct(ssh, vmid)
                    config = esxi_get_config_direct(ssh, vmid)
                    devices = ""
                    filelayout = ""
                    try:
                        devices = esxi_get_devices_direct(ssh, vmid)
                    except Exception:
                        devices = ""
                    try:
                        filelayout = esxi_get_filelayout_direct(ssh, vmid)
                    except Exception:
                        filelayout = ""

                    with open(os.path.join(backup_dir, "summary.txt"), "w", encoding="utf-8") as f:
                        f.write(summary or "")
                    with open(os.path.join(backup_dir, "config.txt"), "w", encoding="utf-8") as f:
                        f.write(config or "")
                    with open(os.path.join(backup_dir, "devices.txt"), "w", encoding="utf-8") as f:
                        f.write(devices or "")
                    with open(os.path.join(backup_dir, "filelayout.txt"), "w", encoding="utf-8") as f:
                        f.write(filelayout or "")

                    ds_url_map = _parse_datastore_url_map(config)
                    job.emit({"type": "log", "line": f"Datastore in config: {', '.join(sorted(ds_url_map.keys())) or '(none)'}"})
                    vms_map = list_vms_direct(ssh)
                    vm_info = vms_map.get(str(vmid)) or {}
                    vm_cfg = vm_info.get("config", {}) if isinstance(vm_info, dict) else {}
                    vmx_rel = (vm_cfg.get("path") or "").strip()
                    vmx_ds = (vm_cfg.get("datastore") or "").strip()
                    vmx_filename: Optional[str] = None
                    if vmx_rel and vmx_ds:
                        vmx_abs = _abs_path_from_bracket(ds_url_map, f"[{vmx_ds}] {vmx_rel}")
                        vmx_filename = vmx_rel.split("/")[-1]
                        local_vmx = os.path.join(backup_dir, vmx_filename)
                        total = 0
                        try:
                            total = int(ssh._sftp.stat(vmx_abs).st_size) if ssh._sftp else 0
                        except Exception:
                            total = 0

                        def _cb_vmx(transferred: int, tt: int):
                            t = tt or total or 0
                            pct = 0.0
                            if t > 0:
                                pct = min(100.0, transferred * 100.0 / t)
                            job.ops_pct = float(pct)
                            job.ops_msg = f"Download: {vmx_filename} ({transferred}/{t} bytes)"
                            job.emit(
                                {
                                    "type": "progress",
                                    "copy_pct": job.copy_pct,
                                    "copy_msg": job.copy_msg,
                                    "ops_pct": job.ops_pct,
                                    "ops_msg": job.ops_msg,
                                    "bytes_total": job.bytes_total,
                                    "bytes_done": job.bytes_done,
                                    "rate_bps": job.rate_bps,
                                }
                            )

                        job.emit({"type": "log", "line": f"Download VMX: {vmx_abs}"})
                        ssh.get_file(vmx_abs, local_vmx, progress_cb=_cb_vmx if total > 0 else None)

                    descriptors: List[str] = []
                    expanded_candidates: List[str] = []
                    candidates: List[str] = []
                    for attempt in range(5):
                        candidates = _parse_vmdk_candidates(filelayout)
                        candidates_cfg = _parse_vmdk_candidates_from_config(config)
                        candidates_dev = _parse_vmdk_candidates_from_devices(devices)
                        for p in candidates_cfg + candidates_dev:
                            if p not in candidates:
                                candidates.append(p)
                        expanded_candidates = _expand_vmdk_candidates(candidates)
                        job.emit(
                            {
                                "type": "log",
                                "line": (
                                    f"VMDK candidati: filelayout={len(_parse_vmdk_candidates(filelayout))} "
                                    f"config={len(candidates_cfg)} devices={len(candidates_dev)} "
                                    f"tot={len(candidates)} (espansi: {len(expanded_candidates)})"
                                ),
                            }
                        )
                        descriptors = []
                        for p in expanded_candidates:
                            abs_p = _abs_path_from_bracket(ds_url_map, p)
                            if _is_vmdk_descriptor_abs(ssh, abs_p):
                                descriptors.append(p)
                        job.emit({"type": "log", "line": f"VMDK descriptor rilevati: {len(descriptors)}"})
                        if descriptors:
                            break
                        if attempt < 4:
                            job.emit({"type": "log", "line": f"Descriptor non trovato, retry {attempt+1}/4…"})
                            time.sleep(2)
                            try:
                                config = esxi_get_config_direct(ssh, vmid)
                            except Exception:
                                pass
                            try:
                                devices = esxi_get_devices_direct(ssh, vmid)
                            except Exception:
                                pass
                            try:
                                filelayout = esxi_get_filelayout_direct(ssh, vmid)
                            except Exception:
                                pass
                            ds_url_map = _parse_datastore_url_map(config)

                    if not descriptors:
                        if expanded_candidates:
                            sample = ", ".join(expanded_candidates[:5])
                            job.emit({"type": "log", "line": f"Esempio candidati: {sample}"})
                        raise RuntimeError("Nessun VMDK descriptor trovato (filelayout/vmkfstools)")

                    local_disks: List[dict] = []
                    latest_by_key: Dict[str, str] = {}
                    base_by_key: Dict[str, str] = {}
                    for p in descriptors:
                        parts = _split_candidate_path(p)
                        if not parts:
                            continue
                        ds, rel = parts
                        key = _base_vmdk_key(ds, rel)
                        if _snapshot_seq(rel) == -1:
                            base_by_key[key] = p
                        prev = latest_by_key.get(key)
                        if not prev:
                            latest_by_key[key] = p
                            continue
                        prev_parts = _split_candidate_path(prev)
                        if not prev_parts:
                            latest_by_key[key] = p
                            continue
                        prev_seq = _snapshot_seq(prev_parts[1])
                        new_seq = _snapshot_seq(rel)
                        if new_seq > prev_seq:
                            latest_by_key[key] = p

                    selected_descriptors = list(base_by_key.values()) or list(latest_by_key.values())
                    if was_powered_on and selected_descriptors:
                        job.emit(
                            {
                                "type": "log",
                                "line": "VM accesa: snapshot attiva, copio il disco base (flat) per evitare lock delta/sesparse.",
                            }
                        )

                    completed_bytes = 0
                    completed_total = 0

                    for idx, src in enumerate(selected_descriptors):
                        parts = _split_candidate_path(src)
                        if not parts:
                            continue
                        ds, rel = parts
                        src_abs_desc = _abs_path_from_bracket(ds_url_map, src)
                        extent_name = _read_extent_filename(ssh, src_abs_desc)
                        desc_dir = src_abs_desc.rsplit("/", 1)[0] if "/" in src_abs_desc else src_abs_desc
                        extent_rel = (extent_name or "").lstrip("/")
                        src_abs_data = desc_dir.rstrip("/") + "/" + extent_rel

                        local_desc_name = rel.split("/")[-1]
                        local_desc = os.path.join(backup_dir, local_desc_name)
                        local_data_name = extent_rel.split("/")[-1]
                        local_data = os.path.join(backup_dir, local_data_name)

                        def _download(remote_path: str, local_path: str, label: str):
                            nonlocal completed_bytes, completed_total
                            total = 0
                            try:
                                total = int(ssh._sftp.stat(remote_path).st_size) if ssh._sftp else 0
                            except Exception:
                                total = 0
                            if total > 0:
                                completed_total += total
                                job.update_transfer(completed_bytes, completed_total)
                            lock_logged = False

                            def _cb(transferred: int, tt: int):
                                t = tt or total or 0
                                pct = 0.0
                                if t > 0:
                                    pct = min(100.0, transferred * 100.0 / t)
                                if t > 0:
                                    job.update_transfer(completed_bytes + int(transferred or 0), completed_total)
                                job.copy_pct = float(pct)
                                job.copy_msg = f"Download: {label} ({transferred}/{t} bytes)"
                                job.emit(
                                    {
                                        "type": "progress",
                                        "copy_pct": job.copy_pct,
                                        "copy_msg": job.copy_msg,
                                        "ops_pct": job.ops_pct,
                                        "ops_msg": job.ops_msg,
                                    "bytes_total": job.bytes_total,
                                    "bytes_done": job.bytes_done,
                                    "rate_bps": job.rate_bps,
                                    }
                                )

                            for attempt in range(31):
                                try:
                                    ssh.get_file(remote_path, local_path, progress_cb=_cb if total > 0 else None)
                                    if total > 0:
                                        completed_bytes += total
                                        job.update_transfer(completed_bytes, completed_total)
                                    return
                                except Exception as e:
                                    msg = str(e or "").lower()
                                    if ("device or resource busy" in msg or "resource busy" in msg) and attempt < 30:
                                        if not lock_logged:
                                            lock_logged = True
                                            try:
                                                _, out_l, _ = ssh.run(
                                                    f"vmkfstools -D {shlex.quote(remote_path)} 2>/dev/null | head -n 12 || true",
                                                    timeout=30,
                                                )
                                                for ln in (out_l or "").splitlines()[:12]:
                                                    t = (ln or "").strip()
                                                    if t:
                                                        job.emit({"type": "log", "line": t})
                                            except Exception:
                                                pass
                                        if allow_power_off and was_powered_on and not did_power_off:
                                            job.emit(
                                                {
                                                    "type": "log",
                                                    "line": "File occupato, spengo la VM e riprovo il download…",
                                                }
                                            )
                                            try:
                                                ssh.run(f"vim-cmd vmsvc/power.off {vmid}", timeout=60)
                                            except Exception:
                                                pass
                                            did_power_off = True
                                            time.sleep(3)
                                        else:
                                            if attempt in (0, 1, 2, 4, 7, 11, 17, 24, 30):
                                                job.emit({"type": "log", "line": f"File occupato, retry {attempt+1}/30…"})
                                            time.sleep(min(15, 2 + attempt // 2))
                                        continue
                                    raise

                        job.emit({"type": "log", "line": f"Download descriptor: {src_abs_desc}"})
                        _download(src_abs_desc, local_desc, local_desc_name)
                        job.emit({"type": "log", "line": f"Download data: {src_abs_data}"})
                        try:
                            _download(src_abs_data, local_data, local_data_name)
                        except Exception as e:
                            msg = str(e or "").lower()
                            if "device or resource busy" not in msg and "resource busy" not in msg:
                                raise
                            job.emit(
                                {
                                    "type": "log",
                                    "line": "Lock persistente sul VMDK: tento clone su ESXi e scarico il clone…",
                                }
                            )
                            try:
                                if os.path.exists(local_desc):
                                    os.remove(local_desc)
                            except Exception:
                                pass
                            try:
                                if os.path.exists(local_data):
                                    os.remove(local_data)
                            except Exception:
                                pass
                            clone_desc_abs, clone_data_abs = _clone_vmdk_for_download_abs(ssh, src_abs_desc, job)
                            clone_desc_name = clone_desc_abs.rsplit("/", 1)[-1]
                            clone_data_name = clone_data_abs.rsplit("/", 1)[-1]
                            local_desc_name = clone_desc_name
                            local_desc = os.path.join(backup_dir, local_desc_name)
                            local_data_name = clone_data_name
                            local_data = os.path.join(backup_dir, local_data_name)
                            job.emit({"type": "log", "line": f"Download descriptor (clone): {clone_desc_abs}"})
                            _download(clone_desc_abs, local_desc, local_desc_name)
                            job.emit({"type": "log", "line": f"Download data (clone): {clone_data_abs}"})
                            _download(clone_data_abs, local_data, local_data_name)
                            try:
                                ssh.run(
                                    f"rm -f {shlex.quote(clone_desc_abs)} {shlex.quote(clone_data_abs)} 2>/dev/null || true",
                                    timeout=60,
                                )
                            except Exception:
                                pass
                            src_abs_desc = clone_desc_abs
                            src_abs_data = clone_data_abs
                        local_disks.append(
                            {
                                "idx": idx,
                                "descriptor": local_desc_name,
                                "data": local_data_name,
                                "source_descriptor": src_abs_desc,
                                "source_data": src_abs_data,
                            }
                        )

                    manifest = {
                        "backup_id": backup_id,
                        "created_ms": _now_ms(),
                        "label": (
                            f"{backup_label} — esxi:{esxi_host} vmid:{vmid} — {backup_id}"
                            if backup_label
                            else f"{backup_id} — esxi:{esxi_host} vmid:{vmid}"
                        ),
                        "label_user": backup_label,
                        "source": {"type": "esxi-direct", "host": esxi_host, "user": esxi_user, "port": esxi_port},
                        "vm": {"vmid": vmid, "snapshot_name": snapshot_name, "info": vm_info},
                        "files": {
                            "vmx": vmx_filename,
                            "disks": local_disks,
                            "meta": ["summary.txt", "config.txt", "devices.txt", "filelayout.txt"],
                        },
                    }
                    with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as f:
                        json.dump(manifest, f, ensure_ascii=False, indent=2)

                    job.status = "done"
                    job.emit({"type": "backup", "backup_id": backup_id})
                    job.emit({"type": "status", "status": "done"})
                except Exception as e:
                    job.status = "error"
                    job.error = str(e)
                    job.emit({"type": "log", "line": f"ERRORE: {job.error}"})
                    tb = traceback.format_exc()
                    try:
                        app.logger.error(tb)
                    except Exception:
                        pass
                    for line in tb.splitlines()[-40:]:
                        job.emit({"type": "log", "line": line})
                    job.emit({"type": "status", "status": "error", "error": job.error})
                finally:
                    if ssh:
                        if did_power_off and was_powered_on:
                            try:
                                ssh.run(f"vim-cmd vmsvc/power.on {vmid}", timeout=60)
                            except Exception:
                                pass
                        if created_snapshot_id is not None:
                            try:
                                ssh.run(f"vim-cmd vmsvc/snapshot.remove {vmid} {created_snapshot_id} 0", timeout=300)
                            except Exception:
                                pass
                        if remove_snapshot_after and snapshot_name:
                            try:
                                sid = esxi_find_snapshot_id_by_name_direct(ssh, vmid, snapshot_name)
                                if sid is not None:
                                    job.emit({"type": "log", "line": f"Rimozione snapshot '{snapshot_name}' (id={sid})…"})
                                    ssh.run(f"vim-cmd vmsvc/snapshot.remove {vmid} {sid} 0", timeout=300)
                            except Exception:
                                pass
                        try:
                            ssh.close()
                        except Exception:
                            pass
                    with _job_lock:
                        global _active_job_id
                        if _active_job_id == job.job_id:
                            _active_job_id = None

            threading.Thread(target=_run_job, daemon=True).start()
            return backup_id

        with _job_lock:
            global _active_job_id
            if _active_job_id and _jobs.get(_active_job_id) and _jobs[_active_job_id].status in ("queued", "running"):
                return jsonify({"error": "C'è già un job in esecuzione (MVP: 1 job alla volta)"}), 409

            job_id = str(uuid.uuid4())
            title = f"Backup ESXi vmid={vmid}"
            if backup_label:
                title = f"{backup_label} (vmid={vmid})"
            job = JobState(job_id=job_id, created_ms=_now_ms(), status="queued", kind="backup_esxi", title=title)
            job.vmid = int(vmid)
            job.payload = {
                "vmid": int(vmid),
                "allow_power_off": allow_power_off,
                "remove_snapshot_after": remove_snapshot_after,
                "backup_label": backup_label,
                "repo_storage_id": repo_storage_id,
            }
            _jobs[job_id] = job
            _active_job_id = job_id
            _job_persist(job, force=True)

        try:
            repo_dir = _repo_dir_for_storage(repo_storage_id) if repo_storage_id else _repo_root_dir()
            backup_id = _start_job_esxi_direct(
                job,
                vmid=vmid,
                esxi_host=esxi_host,
                esxi_user=esxi_user,
                esxi_pass=esxi_pass,
                esxi_port=esxi_port,
                snapshot_name=snapshot_name,
                allow_power_off=allow_power_off,
                remove_snapshot_after=remove_snapshot_after,
                backup_label=backup_label,
                repo_dir=repo_dir,
            )
        except Exception as e:
            return jsonify({"error": f"Repository non scrivibile: {e}"}), 400
        return jsonify({"job_id": job_id, "backup_id": backup_id})

    @app.post("/api/jobs/create/backup/proxmox-vzdump")
    def api_jobs_create_backup_proxmox_vzdump():
        body = request.get_json(force=True, silent=True) or {}
        vmid_raw = str(body.get("vmid") or "").strip()
        if not vmid_raw:
            return jsonify({"error": "vmid mancante"}), 400
        try:
            vmid = int(vmid_raw)
        except Exception:
            return jsonify({"error": "vmid non valido"}), 400
        try:
            _resolve_pmx_conn(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        allow_power_off = bool(body.get("allow_power_off"))
        remove_snapshot_after = bool(body.get("remove_snapshot_after", True))
        backup_label = (body.get("backup_label") or "").strip()
        repo_storage_id = (body.get("repo_storage_id") or "").strip()
        pmx_id = (body.get("pmx_id") or "").strip()
        title = f"Backup Proxmox vmid={vmid}"
        if backup_label:
            title = f"{backup_label} (vmid={vmid})"

        with _job_lock:
            global _active_job_id
            if _active_job_id and _jobs.get(_active_job_id) and _jobs[_active_job_id].status in ("queued", "running"):
                return jsonify({"error": "C'è già un job in esecuzione (MVP: 1 job alla volta)"}), 409
            job_id = str(uuid.uuid4())
            job = JobState(job_id=job_id, created_ms=_now_ms(), status="queued", kind="backup_proxmox", title=title)
            job.payload = {
                "vmid": vmid,
                "pmx_id": pmx_id,
                "allow_power_off": allow_power_off,
                "remove_snapshot_after": remove_snapshot_after,
                "backup_label": backup_label,
                "repo_storage_id": repo_storage_id,
            }
            job.vmid = int(vmid)
            _jobs[job_id] = job
            _job_persist(job, force=True)
        return jsonify({"job_id": job_id})

    @app.post("/api/jobs/create/backup/esxi-direct")
    def api_jobs_create_backup_esxi_direct():
        body = request.get_json(force=True, silent=True) or {}
        vmid_raw = str(body.get("vmid") or "").strip()
        if not vmid_raw:
            return jsonify({"error": "vmid mancante"}), 400
        try:
            vmid = int(vmid_raw)
        except Exception:
            return jsonify({"error": "vmid non valido"}), 400
        try:
            _resolve_esxi_conn(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        snapshot_name = (body.get("snapshot_name") or "").strip() or None
        allow_power_off = bool(body.get("allow_power_off"))
        remove_snapshot_after = bool(body.get("remove_snapshot_after", True))
        backup_label = (body.get("backup_label") or "").strip()
        repo_storage_id = (body.get("repo_storage_id") or "").strip()
        esxi_id = (body.get("esxi_id") or "").strip()
        title = f"Backup ESXi vmid={vmid}"
        if backup_label:
            title = f"{backup_label} (vmid={vmid})"

        with _job_lock:
            global _active_job_id
            if _active_job_id and _jobs.get(_active_job_id) and _jobs[_active_job_id].status in ("queued", "running"):
                return jsonify({"error": "C'è già un job in esecuzione (MVP: 1 job alla volta)"}), 409
            job_id = str(uuid.uuid4())
            job = JobState(job_id=job_id, created_ms=_now_ms(), status="queued", kind="backup_esxi", title=title)
            job.payload = {
                "vmid": vmid,
                "esxi_id": esxi_id,
                "snapshot_name": snapshot_name,
                "allow_power_off": allow_power_off,
                "remove_snapshot_after": remove_snapshot_after,
                "backup_label": backup_label,
                "repo_storage_id": repo_storage_id,
            }
            job.vmid = int(vmid)
            _jobs[job_id] = job
            _job_persist(job, force=True)
        return jsonify({"job_id": job_id})

    @app.post("/api/jobs/<job_id>/start")
    def api_jobs_start_by_id(job_id: str):
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "job_id non trovato"}), 404
        if job.status != "queued":
            return jsonify({"error": "Job non avviabile (status != queued)"}), 409
        if job.kind not in ("backup_esxi", "backup_proxmox"):
            return jsonify({"error": "Tipo job non supportato"}), 400

        payload = job.payload or {}
        vmid = int(payload.get("vmid") or 0)
        if vmid <= 0:
            return jsonify({"error": "Payload job non valida (vmid)"}), 400

        with _job_lock:
            global _active_job_id
            if _active_job_id and _active_job_id != job_id and _jobs.get(_active_job_id) and _jobs[_active_job_id].status in ("queued", "running"):
                return jsonify({"error": "C'è già un job in esecuzione (MVP: 1 job alla volta)"}), 409
            _active_job_id = job_id

        def _start_job_proxmox_vzdump(
            job: JobState,
            vmid: int,
            pmx_host: str,
            pmx_user: str,
            pmx_pass: str,
            pmx_port: int,
            allow_power_off: bool,
            remove_snapshot_after: bool,
            backup_label: str,
            repo_dir: str,
        ) -> str:
            backup_id = str(uuid.uuid4())
            job.backup_id = backup_id
            _job_persist(job, force=True)
            backup_dir = os.path.join(repo_dir, backup_id)
            os.makedirs(backup_dir, exist_ok=True)

            def _run_job():
                ssh: Optional[SSHClient] = None
                remote_dir = f"/tmp/vm-migration-tool-backup/{backup_id}"
                try:
                    job.status = "running"
                    job.emit({"type": "status", "status": "running"})
                    job.emit({"type": "log", "line": f"Backup repo: {backup_dir}"})
                    job.emit({"type": "log", "line": f"Proxmox: {pmx_host}:{pmx_port} user={pmx_user} vmid={vmid}"})
                    ssh = SSHClient(pmx_host, pmx_user, pmx_pass, port=pmx_port, log_cb=None)
                    ssh.connect()

                    def _qm_list_snapshots() -> set[str]:
                        try:
                            code_s, out_s, _err_s = ssh.run(f"qm listsnapshot {int(vmid)}", timeout=30)
                            if code_s != 0:
                                return set()
                            names: set[str] = set()
                            for raw in (out_s or "").splitlines():
                                t = (raw or "").strip()
                                if not t:
                                    continue
                                t = t.lstrip("│├└─+\\- ")
                                if not t:
                                    continue
                                if t.lower().startswith("snap"):
                                    continue
                                parts = t.split()
                                if not parts:
                                    continue
                                name = (parts[0] or "").strip()
                                if name and name.lower() != "current":
                                    names.add(name)
                            return names
                        except Exception:
                            return set()

                    def _qm_delete_snapshot(snapshot_name: str) -> None:
                        if not snapshot_name:
                            return
                        name_q = shlex.quote(snapshot_name)
                        cmds = [
                            f"qm delsnapshot {int(vmid)} {name_q} --force 1",
                            f"qm delsnapshot {int(vmid)} {name_q} --force",
                            f"qm delsnapshot {int(vmid)} {name_q}",
                        ]
                        last = None
                        for c in cmds:
                            try:
                                code_d, out_d, err_d = ssh.run(c, timeout=300)
                                last = (code_d, out_d, err_d)
                                if code_d == 0:
                                    return
                            except Exception as e:
                                last = (-1, "", str(e))
                        if last:
                            code_d, out_d, err_d = last
                            job.emit(
                                {
                                    "type": "log",
                                    "line": f"Cleanup snapshot fallito '{snapshot_name}' (code={code_d}): {err_d or out_d}".strip(),
                                }
                            )

                    cfg_text = ""
                    try:
                        code_cfg, out_cfg, err_cfg = ssh.run(f"qm config {int(vmid)}")
                        if code_cfg == 0:
                            cfg_text = out_cfg or ""
                        else:
                            cfg_text = ""
                            job.emit({"type": "log", "line": f"qm config -> code={code_cfg}\n{out_cfg}\n{err_cfg}"})
                    except Exception:
                        cfg_text = ""

                    try:
                        with open(os.path.join(backup_dir, "qm_config.txt"), "w", encoding="utf-8") as f:
                            f.write(cfg_text or "")
                    except Exception:
                        pass

                    try:
                        ssh.run(f"mkdir -p {shlex.quote(remote_dir)}")
                    except Exception:
                        pass

                    modes: list[str] = ["snapshot", "suspend"]
                    if allow_power_off:
                        modes.append("stop")

                    last_out = ""
                    last_err = ""
                    selected_mode = ""
                    ok = False
                    for mode in modes:
                        selected_mode = mode
                        snaps_before: set[str] = set()
                        if mode == "snapshot":
                            snaps_before = _qm_list_snapshots()
                        job.ops_pct = 1.0
                        job.ops_msg = f"vzdump: avvio (mode={mode})"
                        job.emit(
                            {
                                "type": "progress",
                                "copy_pct": job.copy_pct,
                                "copy_msg": job.copy_msg,
                                "ops_pct": job.ops_pct,
                                "ops_msg": job.ops_msg,
                                "bytes_total": job.bytes_total,
                                "bytes_done": job.bytes_done,
                                "rate_bps": job.rate_bps,
                            }
                        )
                        code_b, out_b, err_b = ssh.run_streaming(
                            f"vzdump {int(vmid)} --mode {shlex.quote(mode)} --compress zstd --dumpdir {shlex.quote(remote_dir)} --remove 0",
                            timeout=6 * 3600,
                        )
                        last_out = out_b or ""
                        last_err = err_b or ""
                        try:
                            with open(os.path.join(backup_dir, f"vzdump-{mode}.log"), "w", encoding="utf-8") as f:
                                f.write((last_out or "") + ("\n\n" + last_err if last_err else ""))
                        except Exception:
                            pass
                        if mode == "snapshot" and remove_snapshot_after:
                            try:
                                snaps_after = _qm_list_snapshots()
                                created = sorted([s for s in (snaps_after - snaps_before) if (s or "").lower().startswith("vzdump")])
                                for s in created:
                                    job.emit({"type": "log", "line": f"Rimozione snapshot Proxmox '{s}' (cleanup post-vzdump)…"})
                                    _qm_delete_snapshot(s)
                            except Exception:
                                pass
                        if code_b == 0:
                            ok = True
                            break
                        job.emit({"type": "log", "line": f"vzdump mode={mode} fallito (code={code_b}): {last_err or last_out}"})

                    if not ok:
                        raise RuntimeError(f"vzdump fallito: {last_err or last_out}".strip() or "vzdump fallito")

                    job.ops_pct = 20.0
                    job.ops_msg = f"vzdump completato (mode={selected_mode})"
                    job.emit(
                        {
                            "type": "progress",
                            "copy_pct": job.copy_pct,
                            "copy_msg": job.copy_msg,
                            "ops_pct": job.ops_pct,
                            "ops_msg": job.ops_msg,
                            "bytes_total": job.bytes_total,
                            "bytes_done": job.bytes_done,
                            "rate_bps": job.rate_bps,
                        }
                    )

                    code_ls, out_ls, err_ls = ssh.run(f"ls -1 {shlex.quote(remote_dir)}")
                    if code_ls != 0:
                        raise RuntimeError(err_ls or out_ls or "Impossibile elencare file backup")
                    candidates = [ln.strip() for ln in (out_ls or "").splitlines() if ln.strip()]
                    archive_name = ""
                    for fn in candidates:
                        if fn.startswith("vzdump-") and (fn.endswith(".vma") or fn.endswith(".vma.zst") or fn.endswith(".vma.gz") or fn.endswith(".vma.lzo")):
                            archive_name = fn
                            break
                    if not archive_name and candidates:
                        archive_name = candidates[0]
                    if not archive_name:
                        raise RuntimeError("Archivio vzdump non trovato nella cartella temporanea")
                    remote_archive = f"{remote_dir}/{archive_name}"
                    local_archive = os.path.join(backup_dir, archive_name)

                    total = 0
                    try:
                        code_sz, out_sz, _err_sz = ssh.run(f"stat -c %s {shlex.quote(remote_archive)} 2>/dev/null || echo 0")
                        if code_sz == 0:
                            total = int(str(out_sz or "0").strip() or "0")
                    except Exception:
                        total = 0

                    start_ms = _now_ms()

                    def _cb(transferred: int, tt: int):
                        t = tt or total or 0
                        if t > 0:
                            job.update_transfer(int(transferred or 0), int(t))
                        pct = 0.0
                        if t > 0:
                            pct = min(100.0, int(transferred or 0) * 100.0 / t)
                        job.copy_pct = float(pct)
                        job.copy_msg = f"Download: {archive_name} ({transferred}/{t} bytes)"
                        job.ops_pct = max(job.ops_pct, 25.0)
                        job.ops_msg = "Download archivio"
                        job.emit(
                            {
                                "type": "progress",
                                "copy_pct": job.copy_pct,
                                "copy_msg": job.copy_msg,
                                "ops_pct": job.ops_pct,
                                "ops_msg": job.ops_msg,
                                "bytes_total": job.bytes_total,
                                "bytes_done": job.bytes_done,
                                "rate_bps": job.rate_bps,
                            }
                        )
                        if (int(transferred or 0) % (64 * 1024 * 1024)) < (256 * 1024):
                            elapsed = max(0.001, (_now_ms() - start_ms) / 1000.0)
                            if elapsed > 0:
                                job.emit({"type": "log", "line": f"Download {archive_name}: {pct:.1f}% ({(int(transferred or 0) / (1024*1024)):.1f} MiB)"} )

                    ssh.get_file(remote_archive, local_archive, progress_cb=_cb if (total > 0) else None)
                    if total > 0:
                        job.update_transfer(total, total)
                    job.copy_pct = 100.0
                    job.copy_msg = f"Download: {archive_name} (completo)"
                    job.emit(
                        {
                            "type": "progress",
                            "copy_pct": job.copy_pct,
                            "copy_msg": job.copy_msg,
                            "ops_pct": job.ops_pct,
                            "ops_msg": job.ops_msg,
                            "bytes_total": job.bytes_total,
                            "bytes_done": job.bytes_done,
                            "rate_bps": job.rate_bps,
                        }
                    )

                    vm_name = ""
                    try:
                        m = re.search(r"^name:\s*(.+)$", cfg_text or "", flags=re.M)
                        if m:
                            vm_name = (m.group(1) or "").strip()
                    except Exception:
                        vm_name = ""

                    manifest = {
                        "backup_id": backup_id,
                        "created_ms": _now_ms(),
                        "label": (
                            f"{backup_label} — pmx:{pmx_host} vmid:{vmid} — {backup_id}"
                            if backup_label
                            else f"{backup_id} — pmx:{pmx_host} vmid:{vmid}"
                        ),
                        "label_user": backup_label,
                        "source": {"type": "proxmox-vzdump", "host": pmx_host, "user": pmx_user, "port": pmx_port},
                        "vm": {"vmid": vmid, "name": vm_name},
                        "files": {"archive": archive_name, "meta": ["qm_config.txt"]},
                    }
                    with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as f:
                        json.dump(manifest, f, ensure_ascii=False, indent=2)

                    try:
                        ssh.run(f"rm -rf {shlex.quote(remote_dir)}")
                    except Exception:
                        pass

                    job.status = "done"
                    job.emit({"type": "backup", "backup_id": backup_id})
                    job.emit({"type": "status", "status": "done"})
                except Exception as e:
                    job.status = "error"
                    job.error = str(e)
                    job.emit({"type": "log", "line": f"ERRORE: {job.error}"})
                    job.emit({"type": "status", "status": "error", "error": job.error})
                    try:
                        if ssh:
                            ssh.run(f"rm -rf {shlex.quote(remote_dir)}")
                    except Exception:
                        pass
                finally:
                    try:
                        if ssh:
                            ssh.close()
                    except Exception:
                        pass
                    with _job_lock:
                        global _active_job_id
                        if _active_job_id == job.job_id:
                            _active_job_id = None

            threading.Thread(target=_run_job, daemon=True).start()
            return backup_id

        if job.kind == "backup_proxmox":
            repo_storage_id = (payload.get("repo_storage_id") or "").strip()
            try:
                repo_dir = _repo_dir_for_storage(repo_storage_id) if repo_storage_id else _repo_root_dir()
            except Exception as e:
                return jsonify({"error": f"Repository non scrivibile: {e}"}), 400
            pmx_id = (payload.get("pmx_id") or "").strip()
            start_body = {"pmx_id": pmx_id}
            try:
                pmx_host, pmx_user, pmx_pass, pmx_port = _resolve_pmx_conn(start_body)
            except Exception as e:
                return jsonify({"error": str(e)}), 400
            allow_power_off = bool(payload.get("allow_power_off"))
            remove_snapshot_after = bool(payload.get("remove_snapshot_after", True))
            backup_label = (payload.get("backup_label") or "").strip()
            try:
                backup_id = _start_job_proxmox_vzdump(
                    job,
                    vmid=vmid,
                    pmx_host=pmx_host,
                    pmx_user=pmx_user,
                    pmx_pass=pmx_pass,
                    pmx_port=pmx_port,
                    allow_power_off=allow_power_off,
                    remove_snapshot_after=remove_snapshot_after,
                    backup_label=backup_label,
                    repo_dir=repo_dir,
                )
            except Exception as e:
                return jsonify({"error": f"Repository non scrivibile: {e}"}), 400
            return jsonify({"job_id": job_id, "backup_id": backup_id})

        repo_storage_id = (payload.get("repo_storage_id") or "").strip()
        try:
            repo_dir = _repo_dir_for_storage(repo_storage_id) if repo_storage_id else _repo_root_dir()
        except Exception as e:
            return jsonify({"error": f"Repository non scrivibile: {e}"}), 400
        esxi_id = (payload.get("esxi_id") or "").strip()
        start_body = {"esxi_id": esxi_id}
        try:
            esxi_host, esxi_user, esxi_pass, esxi_port = _resolve_esxi_conn(start_body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        snapshot_name = (payload.get("snapshot_name") or "").strip() or None
        allow_power_off = bool(payload.get("allow_power_off"))
        remove_snapshot_after = bool(payload.get("remove_snapshot_after", True))
        backup_label = (payload.get("backup_label") or "").strip()

        def _start_job_esxi_direct(
            job: JobState,
            vmid: int,
            esxi_host: str,
            esxi_user: str,
            esxi_pass: str,
            esxi_port: int,
            snapshot_name: Optional[str],
            allow_power_off: bool,
            remove_snapshot_after: bool,
            backup_label: str,
            repo_dir: str,
        ):
            backup_id = str(uuid.uuid4())
            job.backup_id = backup_id
            _job_persist(job, force=True)
            backup_dir = os.path.join(repo_dir, backup_id)
            os.makedirs(backup_dir, exist_ok=True)

            def _run_job():
                ssh: Optional[SSHClient] = None
                staging_dirs: List[str] = []
                was_powered_on = False
                did_power_off = False
                created_snapshot_id: Optional[int] = None
                created_snapshot_name: Optional[str] = None
                try:
                    job.status = "running"
                    job.emit({"type": "status", "status": "running"})
                    job.emit({"type": "log", "line": f"Backup repo: {backup_dir}"})
                    job.emit({"type": "log", "line": f"ESXi: {esxi_host}:{esxi_port} user={esxi_user} vmid={vmid}"})
                    if snapshot_name:
                        job.emit({"type": "log", "line": f"Snapshot (selezionata): {snapshot_name}"})
                    ssh = SSHClient(esxi_host, esxi_user, esxi_pass, port=esxi_port, log_cb=None)
                    ssh.connect()

                    try:
                        st = (esxi_power_state_direct(ssh, vmid) or "").strip()
                        st_norm = re.sub(r"\s+", "", st.lower())
                        was_powered_on = ("poweredon" in st_norm) or ("poweredon" in st_norm.replace("-", ""))
                        job.emit({"type": "log", "line": f"Power state: {st or '(unknown)'}"})
                    except Exception:
                        was_powered_on = False

                    if was_powered_on:
                        snap_id_existing: Optional[int] = None
                        if snapshot_name:
                            try:
                                snap_id_existing = esxi_find_snapshot_id_by_name_direct(ssh, vmid, snapshot_name)
                            except Exception:
                                snap_id_existing = None
                        if snap_id_existing is None:
                            created_snapshot_name = f"vm-migration-tool-export-{int(time.time())}"
                            job.emit(
                                {
                                    "type": "log",
                                    "line": f"Creo snapshot temporanea '{created_snapshot_name}' (quiesce) per export hot…",
                                }
                            )
                            try:
                                esxi_create_snapshot_direct(
                                    ssh,
                                    vmid,
                                    created_snapshot_name,
                                    "Snapshot temporanea per export hot (vm-migration-tool)",
                                    quiesce=True,
                                    memory=False,
                                )
                            except Exception as e:
                                job.emit({"type": "log", "line": f"Snapshot quiesce fallita, retry senza quiesce: {e}"})
                                esxi_create_snapshot_direct(
                                    ssh,
                                    vmid,
                                    created_snapshot_name,
                                    "Snapshot temporanea per export hot (vm-migration-tool)",
                                    quiesce=False,
                                    memory=False,
                                )
                            created_snapshot_id = esxi_find_snapshot_id_by_name_direct(ssh, vmid, created_snapshot_name)
                            if created_snapshot_id is None:
                                raise RuntimeError("Snapshot creata ma snapshot_id non trovato")
                            job.emit(
                                {
                                    "type": "log",
                                    "line": f"Snapshot export creata: name={created_snapshot_name} id={created_snapshot_id}",
                                }
                            )
                        else:
                            job.emit({"type": "log", "line": f"Uso snapshot esistente: id={snap_id_existing}"})

                    summary = esxi_get_summary_direct(ssh, vmid)
                    config = esxi_get_config_direct(ssh, vmid)
                    devices = ""
                    filelayout = ""
                    try:
                        devices = esxi_get_devices_direct(ssh, vmid)
                    except Exception:
                        devices = ""
                    try:
                        filelayout = esxi_get_filelayout_direct(ssh, vmid)
                    except Exception:
                        filelayout = ""

                    with open(os.path.join(backup_dir, "summary.txt"), "w", encoding="utf-8") as f:
                        f.write(summary or "")
                    with open(os.path.join(backup_dir, "config.txt"), "w", encoding="utf-8") as f:
                        f.write(config or "")
                    with open(os.path.join(backup_dir, "devices.txt"), "w", encoding="utf-8") as f:
                        f.write(devices or "")
                    with open(os.path.join(backup_dir, "filelayout.txt"), "w", encoding="utf-8") as f:
                        f.write(filelayout or "")

                    ds_url_map = _parse_datastore_url_map(config)
                    job.emit({"type": "log", "line": f"Datastore in config: {', '.join(sorted(ds_url_map.keys())) or '(none)'}"})
                    vms_map = list_vms_direct(ssh)
                    vm_info = vms_map.get(str(vmid)) or {}
                    vm_cfg = vm_info.get("config", {}) if isinstance(vm_info, dict) else {}
                    vmx_rel = (vm_cfg.get("path") or "").strip()
                    vmx_ds = (vm_cfg.get("datastore") or "").strip()
                    vmx_filename: Optional[str] = None
                    if vmx_rel and vmx_ds:
                        vmx_abs = _abs_path_from_bracket(ds_url_map, f"[{vmx_ds}] {vmx_rel}")
                        vmx_filename = vmx_rel.split("/")[-1]
                        local_vmx = os.path.join(backup_dir, vmx_filename)
                        total = 0
                        try:
                            total = int(ssh._sftp.stat(vmx_abs).st_size) if ssh._sftp else 0
                        except Exception:
                            total = 0

                        def _cb_vmx(transferred: int, tt: int):
                            t = tt or total or 0
                            pct = 0.0
                            if t > 0:
                                pct = min(100.0, transferred * 100.0 / t)
                            job.ops_pct = float(pct)
                            job.ops_msg = f"Download: {vmx_filename} ({transferred}/{t} bytes)"
                            job.emit(
                                {
                                    "type": "progress",
                                    "copy_pct": job.copy_pct,
                                    "copy_msg": job.copy_msg,
                                    "ops_pct": job.ops_pct,
                                    "ops_msg": job.ops_msg,
                                    "bytes_total": job.bytes_total,
                                    "bytes_done": job.bytes_done,
                                    "rate_bps": job.rate_bps,
                                }
                            )

                        job.emit({"type": "log", "line": f"Download VMX: {vmx_abs}"})
                        ssh.get_file(vmx_abs, local_vmx, progress_cb=_cb_vmx if total > 0 else None)

                    descriptors: List[str] = []
                    expanded_candidates: List[str] = []
                    candidates: List[str] = []
                    for attempt in range(5):
                        candidates = _parse_vmdk_candidates(filelayout)
                        candidates_cfg = _parse_vmdk_candidates_from_config(config)
                        candidates_dev = _parse_vmdk_candidates_from_devices(devices)
                        for p in candidates_cfg + candidates_dev:
                            if p not in candidates:
                                candidates.append(p)
                        expanded_candidates = _expand_vmdk_candidates(candidates)
                        job.emit(
                            {
                                "type": "log",
                                "line": (
                                    f"VMDK candidati: filelayout={len(_parse_vmdk_candidates(filelayout))} "
                                    f"config={len(candidates_cfg)} devices={len(candidates_dev)} "
                                    f"tot={len(candidates)} (espansi: {len(expanded_candidates)})"
                                ),
                            }
                        )
                        descriptors = []
                        for p in expanded_candidates:
                            abs_p = _abs_path_from_bracket(ds_url_map, p)
                            if _is_vmdk_descriptor_abs(ssh, abs_p):
                                descriptors.append(p)
                        job.emit({"type": "log", "line": f"VMDK descriptor rilevati: {len(descriptors)}"})
                        if descriptors:
                            break
                        if attempt < 4:
                            job.emit({"type": "log", "line": f"Descriptor non trovato, retry {attempt+1}/4…"})
                            time.sleep(2)
                            try:
                                config = esxi_get_config_direct(ssh, vmid)
                            except Exception:
                                pass
                            try:
                                devices = esxi_get_devices_direct(ssh, vmid)
                            except Exception:
                                pass
                            try:
                                filelayout = esxi_get_filelayout_direct(ssh, vmid)
                            except Exception:
                                pass
                            ds_url_map = _parse_datastore_url_map(config)

                    if not descriptors:
                        if expanded_candidates:
                            sample = ", ".join(expanded_candidates[:5])
                            job.emit({"type": "log", "line": f"Esempio candidati: {sample}"})
                        raise RuntimeError("Nessun VMDK descriptor trovato (filelayout/vmkfstools)")

                    local_disks: List[dict] = []
                    latest_by_key: Dict[str, str] = {}
                    base_by_key: Dict[str, str] = {}
                    for p in descriptors:
                        parts = _split_candidate_path(p)
                        if not parts:
                            continue
                        ds, rel = parts
                        key = _base_vmdk_key(ds, rel)
                        if _snapshot_seq(rel) == -1:
                            base_by_key[key] = p
                        prev = latest_by_key.get(key)
                        if not prev:
                            latest_by_key[key] = p
                            continue
                        prev_parts = _split_candidate_path(prev)
                        if not prev_parts:
                            latest_by_key[key] = p
                            continue
                        prev_seq = _snapshot_seq(prev_parts[1])
                        new_seq = _snapshot_seq(rel)
                        if new_seq > prev_seq:
                            latest_by_key[key] = p

                    selected_descriptors = list(base_by_key.values()) or list(latest_by_key.values())
                    if was_powered_on and selected_descriptors:
                        job.emit(
                            {
                                "type": "log",
                                "line": "VM accesa: snapshot attiva, copio il disco base (flat) per evitare lock delta/sesparse.",
                            }
                        )

                    completed_bytes = 0
                    completed_total = 0

                    for idx, src in enumerate(selected_descriptors):
                        parts = _split_candidate_path(src)
                        if not parts:
                            continue
                        ds, rel = parts
                        src_abs_desc = _abs_path_from_bracket(ds_url_map, src)
                        extent_name = _read_extent_filename(ssh, src_abs_desc)
                        desc_dir = src_abs_desc.rsplit("/", 1)[0] if "/" in src_abs_desc else src_abs_desc
                        extent_rel = (extent_name or "").lstrip("/")
                        src_abs_data = desc_dir.rstrip("/") + "/" + extent_rel

                        local_desc_name = rel.split("/")[-1]
                        local_desc = os.path.join(backup_dir, local_desc_name)
                        local_data_name = extent_rel.split("/")[-1]
                        local_data = os.path.join(backup_dir, local_data_name)

                        def _download(remote_path: str, local_path: str, label: str):
                            nonlocal completed_bytes, completed_total
                            total = 0
                            try:
                                total = int(ssh._sftp.stat(remote_path).st_size) if ssh._sftp else 0
                            except Exception:
                                total = 0
                            if total > 0:
                                completed_total += total
                                job.update_transfer(completed_bytes, completed_total)
                            lock_logged = False

                            def _cb(transferred: int, tt: int):
                                t = tt or total or 0
                                pct = 0.0
                                if t > 0:
                                    pct = min(100.0, transferred * 100.0 / t)
                                if t > 0:
                                    job.update_transfer(completed_bytes + int(transferred or 0), completed_total)
                                job.copy_pct = float(pct)
                                job.copy_msg = f"Download: {label} ({transferred}/{t} bytes)"
                                job.emit(
                                    {
                                        "type": "progress",
                                        "copy_pct": job.copy_pct,
                                        "copy_msg": job.copy_msg,
                                        "ops_pct": job.ops_pct,
                                        "ops_msg": job.ops_msg,
                                    "bytes_total": job.bytes_total,
                                    "bytes_done": job.bytes_done,
                                    "rate_bps": job.rate_bps,
                                    }
                                )

                            for attempt in range(31):
                                try:
                                    ssh.get_file(remote_path, local_path, progress_cb=_cb if total > 0 else None)
                                    if total > 0:
                                        completed_bytes += total
                                        job.update_transfer(completed_bytes, completed_total)
                                    return
                                except Exception as e:
                                    msg = str(e or "").lower()
                                    if ("device or resource busy" in msg or "resource busy" in msg) and attempt < 30:
                                        if not lock_logged:
                                            lock_logged = True
                                            try:
                                                _, out_l, _ = ssh.run(
                                                    f"vmkfstools -D {shlex.quote(remote_path)} 2>/dev/null | head -n 12 || true",
                                                    timeout=30,
                                                )
                                                for ln in (out_l or "").splitlines()[:12]:
                                                    t = (ln or "").strip()
                                                    if t:
                                                        job.emit({"type": "log", "line": t})
                                            except Exception:
                                                pass
                                        if allow_power_off and was_powered_on and not did_power_off:
                                            job.emit(
                                                {
                                                    "type": "log",
                                                    "line": "File occupato, spengo la VM e riprovo il download…",
                                                }
                                            )
                                            try:
                                                ssh.run(f"vim-cmd vmsvc/power.off {vmid}", timeout=60)
                                            except Exception:
                                                pass
                                            did_power_off = True
                                            time.sleep(3)
                                        else:
                                            if attempt in (0, 1, 2, 4, 7, 11, 17, 24, 30):
                                                job.emit({"type": "log", "line": f"File occupato, retry {attempt+1}/30…"})
                                            time.sleep(min(15, 2 + attempt // 2))
                                        continue
                                    raise

                        job.emit({"type": "log", "line": f"Download descriptor: {src_abs_desc}"})
                        _download(src_abs_desc, local_desc, local_desc_name)
                        job.emit({"type": "log", "line": f"Download data: {src_abs_data}"})
                        try:
                            _download(src_abs_data, local_data, local_data_name)
                        except Exception as e:
                            msg = str(e or "").lower()
                            if "device or resource busy" not in msg and "resource busy" not in msg:
                                raise
                            job.emit(
                                {
                                    "type": "log",
                                    "line": "Lock persistente sul VMDK: tento clone su ESXi e scarico il clone…",
                                }
                            )
                            try:
                                if os.path.exists(local_desc):
                                    os.remove(local_desc)
                            except Exception:
                                pass
                            try:
                                if os.path.exists(local_data):
                                    os.remove(local_data)
                            except Exception:
                                pass
                            clone_desc_abs, clone_data_abs = _clone_vmdk_for_download_abs(ssh, src_abs_desc, job)
                            clone_desc_name = clone_desc_abs.rsplit("/", 1)[-1]
                            clone_data_name = clone_data_abs.rsplit("/", 1)[-1]
                            local_desc_name = clone_desc_name
                            local_desc = os.path.join(backup_dir, local_desc_name)
                            local_data_name = clone_data_name
                            local_data = os.path.join(backup_dir, local_data_name)
                            job.emit({"type": "log", "line": f"Download descriptor (clone): {clone_desc_abs}"})
                            _download(clone_desc_abs, local_desc, local_desc_name)
                            job.emit({"type": "log", "line": f"Download data (clone): {clone_data_abs}"})
                            _download(clone_data_abs, local_data, local_data_name)
                            try:
                                ssh.run(
                                    f"rm -f {shlex.quote(clone_desc_abs)} {shlex.quote(clone_data_abs)} 2>/dev/null || true",
                                    timeout=60,
                                )
                            except Exception:
                                pass
                            src_abs_desc = clone_desc_abs
                            src_abs_data = clone_data_abs
                        local_disks.append(
                            {
                                "idx": idx,
                                "descriptor": local_desc_name,
                                "data": local_data_name,
                                "source_descriptor": src_abs_desc,
                                "source_data": src_abs_data,
                            }
                        )

                    manifest = {
                        "backup_id": backup_id,
                        "created_ms": _now_ms(),
                        "label": (
                            f"{backup_label} — esxi:{esxi_host} vmid:{vmid} — {backup_id}"
                            if backup_label
                            else f"{backup_id} — esxi:{esxi_host} vmid:{vmid}"
                        ),
                        "label_user": backup_label,
                        "source": {"type": "esxi-direct", "host": esxi_host, "user": esxi_user, "port": esxi_port},
                        "vm": {"vmid": vmid, "snapshot_name": snapshot_name, "info": vm_info},
                        "files": {
                            "vmx": vmx_filename,
                            "disks": local_disks,
                            "meta": ["summary.txt", "config.txt", "devices.txt", "filelayout.txt"],
                        },
                    }
                    with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as f:
                        json.dump(manifest, f, ensure_ascii=False, indent=2)

                    job.status = "done"
                    job.emit({"type": "backup", "backup_id": backup_id})
                    job.emit({"type": "status", "status": "done"})
                except Exception as e:
                    job.status = "error"
                    job.error = str(e)
                    job.emit({"type": "log", "line": f"ERRORE: {job.error}"})
                    tb = traceback.format_exc()
                    try:
                        app.logger.error(tb)
                    except Exception:
                        pass
                    for line in tb.splitlines()[-40:]:
                        job.emit({"type": "log", "line": line})
                    job.emit({"type": "status", "status": "error", "error": job.error})
                finally:
                    if ssh:
                        if did_power_off and was_powered_on:
                            try:
                                ssh.run(f"vim-cmd vmsvc/power.on {vmid}", timeout=60)
                            except Exception:
                                pass
                        if created_snapshot_id is not None:
                            try:
                                ssh.run(f"vim-cmd vmsvc/snapshot.remove {vmid} {created_snapshot_id} 0", timeout=300)
                            except Exception:
                                pass
                        if remove_snapshot_after and snapshot_name:
                            try:
                                sid = esxi_find_snapshot_id_by_name_direct(ssh, vmid, snapshot_name)
                                if sid is not None:
                                    job.emit({"type": "log", "line": f"Rimozione snapshot '{snapshot_name}' (id={sid})…"})
                                    ssh.run(f"vim-cmd vmsvc/snapshot.remove {vmid} {sid} 0", timeout=300)
                            except Exception:
                                pass
                        try:
                            ssh.close()
                        except Exception:
                            pass
                    with _job_lock:
                        global _active_job_id
                        if _active_job_id == job.job_id:
                            _active_job_id = None

            threading.Thread(target=_run_job, daemon=True).start()
            return backup_id

        try:
            backup_id = _start_job_esxi_direct(
                job,
                vmid=vmid,
                esxi_host=esxi_host,
                esxi_user=esxi_user,
                esxi_pass=esxi_pass,
                esxi_port=esxi_port,
                snapshot_name=snapshot_name,
                allow_power_off=allow_power_off,
                remove_snapshot_after=remove_snapshot_after,
                backup_label=backup_label,
                repo_dir=repo_dir,
            )
        except Exception as e:
            return jsonify({"error": f"Repository non scrivibile: {e}"}), 400
        return jsonify({"job_id": job_id, "backup_id": backup_id})

    @app.post("/api/backups/restore/proxmox")
    def api_backups_restore_proxmox():
        body = request.get_json(force=True, silent=True) or {}
        backup_id = (body.get("backup_id") or "").strip()
        repo_storage_id = (body.get("repo_storage_id") or "").strip()
        try:
            pmx_host, pmx_user, pmx_pass, pmx_port = _resolve_pmx_conn(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        storage = (body.get("storage") or "").strip()
        bridge = (body.get("bridge") or "").strip()
        name_raw = (body.get("name") or "").strip()
        start_vm = bool(body.get("start_vm", True))

        vmid: Optional[int] = None
        vmid_raw = str(body.get("vmid") or "").strip()
        if vmid_raw:
            try:
                vmid = int(vmid_raw)
            except Exception:
                return jsonify({"error": "VMID non valido"}), 400

        mem_raw = str(body.get("mem") or "").strip()
        cores_raw = str(body.get("cores") or "").strip()
        try:
            mem = int(mem_raw) if mem_raw else 4096
            cores = int(cores_raw) if cores_raw else 2
        except Exception:
            return jsonify({"error": "RAM/vCPU non validi"}), 400

        use_uefi = bool(body.get("uefi"))

        if not backup_id:
            return jsonify({"error": "backup_id mancante"}), 400
        if not storage or not bridge:
            return jsonify({"error": "Storage/Bridge mancanti"}), 400

        try:
            repo_dir = _repo_dir_for_storage(repo_storage_id) if repo_storage_id else _repo_root_dir()
            manifest = _load_backup_manifest(backup_id, repo_dir=repo_dir)
        except Exception:
            return jsonify({"error": "Backup non trovato o manifest non valido"}), 404

        source = manifest.get("source") or {}
        source_type = str(source.get("type") or "").strip()
        vm_obj = manifest.get("vm") or {}
        manifest_vm_name = str(vm_obj.get("name") or "").strip()
        name = name_raw or manifest_vm_name or "vm"
        files = manifest.get("files") or {}
        disks = files.get("disks") or []
        archive_name = (files.get("archive") or "").strip()
        if source_type == "proxmox-vzdump":
            if not archive_name:
                return jsonify({"error": "Backup senza archivio"}), 400
        else:
            if not isinstance(disks, list) or not disks:
                return jsonify({"error": "Backup senza dischi"}), 400

        with _job_lock:
            global _active_job_id
            if _active_job_id and _jobs.get(_active_job_id) and _jobs[_active_job_id].status in ("queued", "running"):
                return jsonify({"error": "C'è già un job in esecuzione (MVP: 1 job alla volta)"}), 409

            job_id = str(uuid.uuid4())
            job = JobState(job_id=job_id, created_ms=_now_ms(), status="queued", kind="restore_proxmox", title=f"Restore {backup_id}")
            job.payload = {
                "backup_id": backup_id,
                "vmid": vmid,
                "name": name,
                "storage": storage,
                "bridge": bridge,
                "repo_storage_id": repo_storage_id,
                "mem": mem,
                "cores": cores,
                "uefi": use_uefi,
                "start_vm": start_vm,
            }
            _jobs[job_id] = job
            _active_job_id = job_id
            _job_persist(job, force=True)

        backup_dir = os.path.join(repo_dir, backup_id)

        def _run_job():
            nonlocal vmid
            ssh: Optional[SSHClient] = None
            remote_dir = f"/root/tmp/vm-migration-tool-restore/{job_id}"
            try:
                job.status = "running"
                job.emit({"type": "status", "status": "running"})
                ssh = SSHClient(pmx_host, pmx_user, pmx_pass, port=pmx_port, log_cb=None)
                ssh.connect()
                ensure_dir(ssh, remote_dir)

                if not storage_supports_images(ssh, storage):
                    raise RuntimeError(
                        f"Lo storage '{storage}' non supporta il contenuto 'images'. Seleziona uno storage idoneo o abilita 'images'."
                    )

                if vmid is None:
                    vmid_next = get_next_vmid(ssh)
                    if vmid_next is None:
                        raise RuntimeError("Impossibile determinare un VMID libero (nextid)")
                    vmid = int(vmid_next)
                    job.vmid = int(vmid)
                    try:
                        job.payload["vmid"] = int(vmid)
                        _job_persist(job, force=True)
                    except Exception:
                        pass

                if source_type == "proxmox-vzdump":
                    local_archive = os.path.join(backup_dir, archive_name)
                    remote_archive = f"{remote_dir}/{archive_name}"

                    total = 0
                    try:
                        total = int(os.path.getsize(local_archive))
                    except Exception:
                        total = 0

                    def _cb(transferred: int, _total: int):
                        tt = _total or total or 0
                        pct = 0.0
                        if tt > 0:
                            pct = min(100.0, transferred * 100.0 / tt)
                            job.update_transfer(int(transferred or 0), tt)
                        job.copy_pct = float(pct)
                        job.copy_msg = f"Copia repository→Proxmox: {archive_name} ({transferred}/{tt} bytes)"
                        job.emit(
                            {
                                "type": "progress",
                                "copy_pct": job.copy_pct,
                                "copy_msg": job.copy_msg,
                                "ops_pct": job.ops_pct,
                                "ops_msg": job.ops_msg,
                                "bytes_total": job.bytes_total,
                                "bytes_done": job.bytes_done,
                                "rate_bps": job.rate_bps,
                            }
                        )

                    ssh.put_file(local_archive, remote_archive, progress_cb=_cb if total > 0 else None)
                    if total > 0:
                        job.update_transfer(total, total)
                    job.copy_pct = 100.0
                    job.copy_msg = f"Copia repository→Proxmox: {archive_name} (completo)"

                    job.ops_pct = 1.0
                    job.ops_msg = "qmrestore: avvio"
                    job.emit(
                        {
                            "type": "progress",
                            "copy_pct": job.copy_pct,
                            "copy_msg": job.copy_msg,
                            "ops_pct": job.ops_pct,
                            "ops_msg": job.ops_msg,
                            "bytes_total": job.bytes_total,
                            "bytes_done": job.bytes_done,
                            "rate_bps": job.rate_bps,
                        }
                    )

                    code_r, out_r, err_r = ssh.run_streaming(
                        f"qmrestore {shlex.quote(remote_archive)} {int(vmid)} --storage {shlex.quote(storage)}",
                        timeout=6 * 3600,
                    )
                    job.emit({"type": "log", "line": f"qmrestore -> code={code_r}\n{out_r}\n{err_r}"})
                    if code_r != 0:
                        raise RuntimeError(f"qmrestore fallito (code={code_r}): {err_r or out_r}")

                    net0 = f"virtio,bridge={bridge}"
                    code_s, out_s, err_s = ssh.run(f"qm set {int(vmid)} --name {shlex.quote(name)} --memory {int(mem)} --cores {int(cores)} --net0 {shlex.quote(net0)}")
                    job.emit({"type": "log", "line": f"qm set net/name/mem/cores -> code={code_s}\n{out_s}\n{err_s}"})
                    if code_s != 0:
                        raise RuntimeError(f"Config VM fallita (code={code_s}): {err_s or out_s}")

                    if use_uefi:
                        code_u, out_u, err_u = qm_set_uefi(ssh, vmid, storage)
                        job.emit({"type": "log", "line": f"qm set UEFI -> code={code_u}\n{out_u}\n{err_u}"})
                        if code_u != 0:
                            raise RuntimeError(f"UEFI fallito (code={code_u}): {err_u or out_u}")

                    if start_vm:
                        code_s2, out_s2, err_s2 = qm_start(ssh, vmid)
                        job.emit({"type": "log", "line": f"qm start -> code={code_s2}\n{out_s2}\n{err_s2}"})
                        if code_s2 != 0:
                            raise RuntimeError(f"Start VM fallito (code={code_s2}): {err_s2 or out_s2}")
                    else:
                        job.emit({"type": "log", "line": "Avvio VM disabilitato: skip qm start"})

                    try:
                        ssh.run(f"rm -rf '{remote_dir}'")
                    except Exception:
                        pass

                    job.status = "done"
                    job.emit({"type": "status", "status": "done"})
                    return

                completed_bytes = 0
                completed_total = 0

                def _upload(local_path: str, remote_path: str, label: str):
                    nonlocal completed_bytes, completed_total
                    total = 0
                    try:
                        total = int(os.path.getsize(local_path))
                    except Exception:
                        total = 0
                    if total > 0:
                        completed_total += total
                        job.update_transfer(completed_bytes, completed_total)

                    def _cb(transferred: int, _total: int):
                        tt = _total or total or 0
                        pct = 0.0
                        if tt > 0:
                            pct = min(100.0, transferred * 100.0 / tt)
                        if tt > 0:
                            job.update_transfer(completed_bytes + int(transferred or 0), completed_total)
                        job.copy_pct = float(pct)
                        job.copy_msg = f"Copia repository→Proxmox: {label} ({transferred}/{tt} bytes)"
                        job.emit(
                            {
                                "type": "progress",
                                "copy_pct": job.copy_pct,
                                "copy_msg": job.copy_msg,
                                "ops_pct": job.ops_pct,
                                "ops_msg": job.ops_msg,
                                "bytes_total": job.bytes_total,
                                "bytes_done": job.bytes_done,
                                "rate_bps": job.rate_bps,
                            }
                        )

                    ssh.put_file(local_path, remote_path, progress_cb=_cb if total > 0 else None)
                    if total > 0:
                        completed_bytes += total
                        job.update_transfer(completed_bytes, completed_total)

                for d in disks:
                    desc = (d.get("descriptor") or "").strip()
                    data = (d.get("data") or "").strip()
                    if not desc or not data:
                        raise RuntimeError("Manifest dischi non valido")
                    _upload(os.path.join(backup_dir, desc), f"{remote_dir}/{desc}", desc)
                    _upload(os.path.join(backup_dir, data), f"{remote_dir}/{data}", data)

                net0 = f"virtio,bridge={bridge}"
                code, out, err = qm_create(ssh, vmid, name, mem, cores, net0)
                job.emit({"type": "log", "line": f"qm create -> code={code}\n{out}\n{err}"})
                if code != 0:
                    raise RuntimeError(f"Creazione VM fallita (code={code}): {err or out}")

                def progress_cb(pct: float, msg: str):
                    m = (msg or "")
                    job.ops_pct = float(pct or 0.0)
                    job.ops_msg = m
                    job.emit(
                        {
                            "type": "progress",
                            "copy_pct": job.copy_pct,
                            "copy_msg": job.copy_msg,
                            "ops_pct": job.ops_pct,
                            "ops_msg": job.ops_msg,
                            "bytes_total": job.bytes_total,
                            "bytes_done": job.bytes_done,
                            "rate_bps": job.rate_bps,
                        }
                    )
                    job.emit({"type": "log", "line": f"{pct:.1f}% — {m}"})

                for d in disks:
                    idx = int(d.get("idx") or 0)
                    desc = (d.get("descriptor") or "").strip()
                    remote_desc = f"{remote_dir}/{desc}"
                    if progress_cb:
                        try:
                            progress_cb(0.0, f"Import: avvio importdisk su storage '{storage}'")
                        except Exception:
                            pass
                        code_i, out_i, err_i = qm_importdisk_with_progress(ssh, vmid, remote_desc, storage, progress_cb)
                    else:
                        code_i, out_i, err_i = qm_importdisk(ssh, vmid, remote_desc, storage)
                    job.emit({"type": "log", "line": f"qm importdisk (disk {idx}) -> code={code_i}\n{out_i}\n{err_i}"})
                    if code_i != 0:
                        raise RuntimeError(f"Import disk {idx} fallito (code={code_i}): {err_i or out_i}")
                    disk_id = parse_importdisk_disk_id(out_i) or f"{storage}:vm-{vmid}-disk-{idx}"
                    code_a, out_a, err_a = qm_attach_scsi(ssh, vmid, disk_id, index=idx)
                    job.emit({"type": "log", "line": f"qm set --scsi{idx} -> code={code_a}\n{out_a}\n{err_a}"})
                    if code_a != 0:
                        raise RuntimeError(f"Attach disk {idx} fallito (code={code_a}): {err_a or out_a}")

                if use_uefi:
                    code_u, out_u, err_u = qm_set_uefi(ssh, vmid, storage)
                    job.emit({"type": "log", "line": f"qm set UEFI -> code={code_u}\n{out_u}\n{err_u}"})
                    if code_u != 0:
                        raise RuntimeError(f"UEFI fallito (code={code_u}): {err_u or out_u}")

                code_b, out_b, err_b = qm_set_boot(ssh, vmid, "scsi0")
                job.emit({"type": "log", "line": f"qm set --boot -> code={code_b}\n{out_b}\n{err_b}"})
                if code_b != 0:
                    raise RuntimeError(f"Boot order fallito (code={code_b}): {err_b or out_b}")

                if start_vm:
                    code_s, out_s, err_s = qm_start(ssh, vmid)
                    job.emit({"type": "log", "line": f"qm start -> code={code_s}\n{out_s}\n{err_s}"})
                    if code_s != 0:
                        raise RuntimeError(f"Start VM fallito (code={code_s}): {err_s or out_s}")
                else:
                    job.emit({"type": "log", "line": "Avvio VM disabilitato: skip qm start"})

                try:
                    ssh.run(f"rm -rf '{remote_dir}'")
                except Exception:
                    pass

                job.status = "done"
                job.emit({"type": "status", "status": "done"})
            except Exception as e:
                job.status = "error"
                job.error = str(e)
                job.emit({"type": "log", "line": f"ERRORE: {job.error}"})
                job.emit({"type": "status", "status": "error"})
                try:
                    if ssh:
                        ssh.run(f"rm -rf '{remote_dir}'")
                except Exception:
                    pass
            finally:
                try:
                    if ssh:
                        ssh.close()
                except Exception:
                    pass
                with _job_lock:
                    global _active_job_id
                    if _active_job_id == job_id:
                        _active_job_id = None

        threading.Thread(target=_run_job, daemon=True).start()
        return jsonify({"job_id": job_id})

    @app.post("/api/backups/restore/esxi-direct")
    def api_backups_restore_esxi_direct():
        body = request.get_json(force=True, silent=True) or {}
        backup_id = (body.get("backup_id") or "").strip()
        repo_storage_id = (body.get("repo_storage_id") or "").strip()
        datastore = (body.get("datastore") or "").strip()
        name_raw = (body.get("name") or "").strip()
        start_vm = bool(body.get("start_vm", True))

        esxi_id = (body.get("esxi_id") or "").strip()
        try:
            esxi_host, esxi_user, esxi_pass, esxi_port = _resolve_esxi_conn({"esxi_id": esxi_id})
        except Exception as e:
            return jsonify({"error": f"ESXi destinazione: {e}"}), 400

        mem_raw = str(body.get("mem") or "").strip()
        cores_raw = str(body.get("cores") or "").strip()
        try:
            mem = int(mem_raw) if mem_raw else 4096
            cores = int(cores_raw) if cores_raw else 2
        except Exception:
            return jsonify({"error": "RAM/vCPU non validi"}), 400
        use_uefi = bool(body.get("uefi"))

        if not backup_id:
            return jsonify({"error": "backup_id mancante"}), 400
        if not datastore:
            return jsonify({"error": "Datastore ESXi mancante"}), 400

        try:
            repo_dir = _repo_dir_for_storage(repo_storage_id) if repo_storage_id else _repo_root_dir()
            manifest = _load_backup_manifest(backup_id, repo_dir=repo_dir)
        except Exception:
            return jsonify({"error": "Backup non trovato o manifest non valido"}), 404

        source = manifest.get("source") or {}
        source_type = str(source.get("type") or "").strip()
        if source_type != "esxi-direct":
            return jsonify({"error": "Restore ESXi diretto supportato solo per backup esxi-direct"}), 400

        vm_obj = manifest.get("vm") or {}
        vm_info = vm_obj.get("info") if isinstance(vm_obj, dict) else None
        manifest_vm_name = ""
        if isinstance(vm_info, dict):
            manifest_vm_name = str(vm_info.get("name") or "").strip()
        name = name_raw or manifest_vm_name or "vm"

        files = manifest.get("files") or {}
        disks = files.get("disks") or []
        vmx_name = (files.get("vmx") or "").strip()
        if not isinstance(disks, list) or not disks:
            return jsonify({"error": "Backup senza dischi"}), 400

        with _job_lock:
            global _active_job_id
            if _active_job_id and _jobs.get(_active_job_id) and _jobs[_active_job_id].status in ("queued", "running"):
                return jsonify({"error": "C'è già un job in esecuzione (MVP: 1 job alla volta)"}), 409

            job_id = str(uuid.uuid4())
            job = JobState(
                job_id=job_id,
                created_ms=_now_ms(),
                status="queued",
                kind="restore_esxi_direct",
                title=f"Restore ESXi {backup_id}",
            )
            job.payload = {
                "backup_id": backup_id,
                "name": name,
                "mem": mem,
                "cores": cores,
                "uefi": use_uefi,
                "start_vm": start_vm,
                "esxi_host": esxi_host,
                "esxi_user": esxi_user,
                "esxi_port": esxi_port,
                "datastore": datastore,
                "repo_storage_id": repo_storage_id,
            }
            _jobs[job_id] = job
            _active_job_id = job_id
            _job_persist(job, force=True)

        backup_dir = os.path.join(repo_dir, backup_id)

        def _safe_fs_name(raw: str) -> str:
            t = (raw or "").strip()
            t = re.sub(r"[^A-Za-z0-9._-]+", "-", t)
            t = t.strip("-._")
            return t or "vm"

        def _run_job():
            ssh_esxi: Optional[SSHClient] = None
            local_tmp_dir = ""
            esxi_vm_dir = ""
            registered_vmid: Optional[int] = None

            def _esxi_find_vmid_by_expected_vmx(expected: str) -> Optional[int]:
                if not expected or not ssh_esxi:
                    return None
                code_a, out_a, err_a = ssh_esxi.run("vim-cmd vmsvc/getallvms", timeout=60)
                if code_a != 0:
                    try:
                        job.emit({"type": "log", "line": f"getallvms -> code={code_a}\n{out_a}\n{err_a}"})
                    except Exception:
                        pass
                    return None
                for line in (out_a or "").splitlines():
                    if expected not in line:
                        continue
                    m = re.match(r"\s*(\d+)\s+", line)
                    if m:
                        try:
                            return int(m.group(1))
                        except Exception:
                            return None
                return None

            try:
                job.status = "running"
                job.emit({"type": "status", "status": "running"})
                job.emit({"type": "log", "line": f"Backup repo: {backup_dir}"})
                job.emit({"type": "log", "line": f"Dest ESXi: {esxi_host}:{esxi_port} user={esxi_user} datastore={datastore}"})

                ssh_esxi = SSHClient(esxi_host, esxi_user, esxi_pass, port=esxi_port, log_cb=None)
                ssh_esxi.connect()

                vm_folder = f"{_safe_fs_name(name)}-{backup_id[:8]}"
                ds_path = f"/vmfs/volumes/{datastore}"
                esxi_vm_dir = f"{ds_path}/{vm_folder}"
                code_m, out_m, err_m = ssh_esxi.run(f"mkdir -p {shlex.quote(esxi_vm_dir)}", timeout=120)
                if code_m != 0:
                    raise RuntimeError(f"mkdir fallito (code={code_m}): {err_m or out_m}")

                completed_bytes = 0
                completed_total = 0

                def _upload(local_path: str, remote_path: str, label: str):
                    nonlocal completed_bytes, completed_total
                    total = 0
                    try:
                        total = int(os.path.getsize(local_path))
                    except Exception:
                        total = 0
                    if total > 0:
                        completed_total += total
                        job.update_transfer(completed_bytes, completed_total)

                    def _cb(transferred: int, _total: int):
                        tt = _total or total or 0
                        done = completed_bytes + int(transferred or 0)
                        if completed_total > 0:
                            pct = min(100.0, done * 100.0 / completed_total)
                        else:
                            pct = 0.0
                        job.copy_pct = float(pct)
                        job.copy_msg = f"Copia repository→ESXi: {label} ({transferred}/{tt} bytes)"
                        if completed_total > 0:
                            job.update_transfer(done, completed_total)
                        job.emit(
                            {
                                "type": "progress",
                                "copy_pct": job.copy_pct,
                                "copy_msg": job.copy_msg,
                                "ops_pct": job.ops_pct,
                                "ops_msg": job.ops_msg,
                                "bytes_total": job.bytes_total,
                                "bytes_done": job.bytes_done,
                                "rate_bps": job.rate_bps,
                            }
                        )

                    ssh_esxi.put_file(local_path, remote_path, progress_cb=_cb if total > 0 else None)
                    if total > 0:
                        completed_bytes += total
                        job.update_transfer(completed_bytes, completed_total)

                disk_items: List[dict] = []
                for d in disks:
                    desc = (d.get("descriptor") or "").strip()
                    data = (d.get("data") or "").strip()
                    if not desc or not data:
                        raise RuntimeError("Manifest dischi non valido")
                    try:
                        idx = int(d.get("idx") or 0)
                    except Exception:
                        idx = 0
                    disk_items.append({"idx": idx, "descriptor": desc, "data": data})
                disk_items.sort(key=lambda x: int(x.get("idx") or 0))

                for d in disk_items:
                    desc = d["descriptor"]
                    data = d["data"]
                    _upload(os.path.join(backup_dir, desc), f"{esxi_vm_dir}/{desc}", desc)
                    _upload(os.path.join(backup_dir, data), f"{esxi_vm_dir}/{data}", data)

                guest_os = "otherGuest64"
                if vmx_name:
                    try:
                        with open(os.path.join(backup_dir, vmx_name), "r", encoding="utf-8", errors="ignore") as f:
                            for ln in f.read().splitlines():
                                m = re.match(r'\s*guestOS\s*=\s*"([^"]+)"\s*$', ln)
                                if m:
                                    guest_os = (m.group(1) or "").strip() or guest_os
                                    break
                    except Exception:
                        pass

                local_tmp_dir = tempfile.mkdtemp(prefix="vm-migration-tool-esxi-direct-")
                uploaded_vmdk_names = [d["descriptor"] for d in disk_items]
                vmx_lines: List[str] = []
                vmx_lines.append('.encoding = "UTF-8"')
                vmx_lines.append('config.version = "8"')
                vmx_lines.append('virtualHW.version = "14"')
                vmx_lines.append(f'displayName = "{name}"')
                vmx_lines.append(f'guestOS = "{guest_os}"')
                vmx_lines.append(f"memSize = \"{int(mem)}\"")
                vmx_lines.append(f"numvcpus = \"{int(cores)}\"")
                if use_uefi:
                    vmx_lines.append('firmware = "efi"')
                vmx_lines.append('scsi0.present = "TRUE"')
                vmx_lines.append('scsi0.virtualDev = "lsilogic"')
                for idx, disk_name in enumerate(uploaded_vmdk_names):
                    vmx_lines.append(f'scsi0:{idx}.present = "TRUE"')
                    vmx_lines.append(f'scsi0:{idx}.fileName = "{disk_name}"')
                    vmx_lines.append(f'scsi0:{idx}.deviceType = "scsi-hardDisk"')
                vmx_lines.append('ethernet0.present = "TRUE"')
                vmx_lines.append('ethernet0.virtualDev = "vmxnet2"')
                vmx_lines.append('ethernet0.connectionType = "custom"')
                vmx_lines.append('ethernet0.networkName = "VM Network"')
                vmx_lines.append('ethernet0.startConnected = "TRUE"')
                vmx_lines.append('ethernet0.connected = "TRUE"')
                vmx_lines.append('ethernet0.addressType = "generated"')
                vmx_lines.append('floppy0.present = "FALSE"')
                vmx_text = "\n".join(vmx_lines) + "\n"

                local_vmx = os.path.join(local_tmp_dir, f"{vm_folder}.vmx")
                with open(local_vmx, "w", encoding="utf-8") as f:
                    f.write(vmx_text)
                remote_vmx = f"{esxi_vm_dir}/{vm_folder}.vmx"
                expected_vmx_ref = f"[{datastore}] {vm_folder}/{vm_folder}.vmx"
                _upload(local_vmx, remote_vmx, f"{vm_folder}.vmx")

                job.ops_pct = 95.0
                job.ops_msg = "Register VM su ESXi"
                job.emit(
                    {
                        "type": "progress",
                        "copy_pct": job.copy_pct,
                        "copy_msg": job.copy_msg,
                        "ops_pct": job.ops_pct,
                        "ops_msg": job.ops_msg,
                        "bytes_total": job.bytes_total,
                        "bytes_done": job.bytes_done,
                        "rate_bps": job.rate_bps,
                    }
                )

                code_r, out_r, err_r = ssh_esxi.run(f"vim-cmd solo/registervm {shlex.quote(remote_vmx)}")
                job.emit({"type": "log", "line": f"registervm -> code={code_r}\n{out_r}\n{err_r}"})
                vmid_reg: Optional[int] = None
                if code_r != 0:
                    exists = ("AlreadyExists" in (err_r or "")) or ("already exists" in (err_r or "").lower())
                    if exists and expected_vmx_ref:
                        vmid_reg = _esxi_find_vmid_by_expected_vmx(expected_vmx_ref)
                        if vmid_reg is None:
                            raise RuntimeError(f"registervm fallito (code={code_r}): {err_r or out_r}")
                    else:
                        raise RuntimeError(f"registervm fallito (code={code_r}): {err_r or out_r}")
                else:
                    try:
                        vmid_reg = int(str(out_r or "").strip().splitlines()[-1])
                    except Exception:
                        vmid_reg = None

                registered_vmid = vmid_reg
                if vmid_reg is not None and start_vm:
                    code_p, out_p, err_p = ssh_esxi.run(f"vim-cmd vmsvc/power.on {int(vmid_reg)}")
                    job.emit({"type": "log", "line": f"power.on -> code={code_p}\n{out_p}\n{err_p}"})
                    if code_p != 0:
                        raise RuntimeError(f"Power on fallito (code={code_p}): {err_p or out_p}")
                elif vmid_reg is not None and not start_vm:
                    job.emit({"type": "log", "line": "Avvio VM disabilitato: skip power.on"})

                job.status = "done"
                job.emit({"type": "status", "status": "done"})
            except Exception as e:
                job.status = "error"
                job.error = str(e)
                job.emit({"type": "log", "line": f"ERRORE: {job.error}"})
                job.emit({"type": "status", "status": "error", "error": job.error})
            finally:
                try:
                    if ssh_esxi:
                        ssh_esxi.close()
                except Exception:
                    pass
                if local_tmp_dir:
                    try:
                        shutil.rmtree(local_tmp_dir, ignore_errors=True)
                    except Exception:
                        pass
                with _job_lock:
                    global _active_job_id
                    if _active_job_id == job_id:
                        _active_job_id = None

        threading.Thread(target=_run_job, daemon=True).start()
        return jsonify({"job_id": job_id})

    @app.post("/api/backups/restore/esxi")
    def api_backups_restore_esxi():
        body = request.get_json(force=True, silent=True) or {}
        backup_id = (body.get("backup_id") or "").strip()
        repo_storage_id = (body.get("repo_storage_id") or "").strip()
        datastore = (body.get("datastore") or "").strip()
        name = (body.get("name") or "").strip() or "vm"
        start_vm = bool(body.get("start_vm", True))
        pmx_tmp_base = (body.get("pmx_tmp_base") or "").strip()

        try:
            pmx_host, pmx_user, pmx_pass, pmx_port = _resolve_pmx_conn({"pmx_id": (body.get("pmx_id") or "").strip()})
        except Exception as e:
            return jsonify({"error": f"Proxmox worker: {e}"}), 400
        try:
            esxi_host, esxi_user, esxi_pass, esxi_port = _resolve_esxi_conn({"esxi_id": (body.get("esxi_id") or "").strip()})
        except Exception as e:
            return jsonify({"error": f"ESXi destinazione: {e}"}), 400

        try:
            mem = int(str(body.get("mem") or "").strip())
            cores = int(str(body.get("cores") or "").strip())
        except Exception:
            return jsonify({"error": "RAM/vCPU non validi"}), 400
        use_uefi = bool(body.get("uefi"))

        if not backup_id:
            return jsonify({"error": "backup_id mancante"}), 400
        if not datastore:
            return jsonify({"error": "Datastore ESXi mancante"}), 400

        try:
            repo_dir = _repo_dir_for_storage(repo_storage_id) if repo_storage_id else _repo_root_dir()
            manifest = _load_backup_manifest(backup_id, repo_dir=repo_dir)
        except Exception:
            return jsonify({"error": "Backup non trovato o manifest non valido"}), 404
        source = manifest.get("source") or {}
        source_type = str(source.get("type") or "").strip()
        if source_type != "proxmox-vzdump":
            return jsonify({"error": "Restore ESXi supportato solo per backup Proxmox vzdump"}), 400
        files = manifest.get("files") or {}
        archive_name = (files.get("archive") or "").strip()
        if not archive_name:
            return jsonify({"error": "Backup senza archivio"}), 400

        with _job_lock:
            global _active_job_id
            if _active_job_id and _jobs.get(_active_job_id) and _jobs[_active_job_id].status in ("queued", "running"):
                return jsonify({"error": "C'è già un job in esecuzione (MVP: 1 job alla volta)"}), 409

            job_id = str(uuid.uuid4())
            job = JobState(
                job_id=job_id,
                created_ms=_now_ms(),
                status="queued",
                kind="restore_esxi",
                title=f"Restore ESXi {backup_id}",
            )
            job.payload = {
                "backup_id": backup_id,
                "name": name,
                "mem": mem,
                "cores": cores,
                "uefi": use_uefi,
                "start_vm": start_vm,
                "pmx_host": pmx_host,
                "pmx_user": pmx_user,
                "pmx_port": pmx_port,
                "esxi_host": esxi_host,
                "esxi_user": esxi_user,
                "esxi_port": esxi_port,
                "datastore": datastore,
                "repo_storage_id": repo_storage_id,
            }
            _jobs[job_id] = job
            _active_job_id = job_id
            _job_persist(job, force=True)

        backup_dir = os.path.join(repo_dir, backup_id)

        def _safe_fs_name(raw: str) -> str:
            t = (raw or "").strip()
            t = re.sub(r"[^A-Za-z0-9._-]+", "-", t)
            t = t.strip("-._")
            return t or "vm"

        def _parse_qm_config_value(text: str, key: str) -> Optional[str]:
            m = re.search(rf"^{re.escape(key)}:\s*(.+)$", text or "", flags=re.M)
            if not m:
                return None
            return (m.group(1) or "").strip() or None

        def _run_job():
            ssh_pmx: Optional[SSHClient] = None
            ssh_esxi: Optional[SSHClient] = None
            local_tmp_dir = ""
            remote_dir = ""
            esxi_vm_dir = ""
            registered_vmid: Optional[int] = None
            remote_vmx = ""
            expected_vmx_ref = ""

            def _esxi_find_vmid_by_expected_vmx(expected: str) -> Optional[int]:
                if not expected or not ssh_esxi:
                    return None
                code_a, out_a, err_a = ssh_esxi.run("vim-cmd vmsvc/getallvms", timeout=60)
                if code_a != 0:
                    try:
                        job.emit({"type": "log", "line": f"getallvms -> code={code_a}\n{out_a}\n{err_a}"})
                    except Exception:
                        pass
                    return None
                for line in (out_a or "").splitlines():
                    if expected not in line:
                        continue
                    m = re.match(r"\s*(\d+)\s+", line)
                    if m:
                        try:
                            return int(m.group(1))
                        except Exception:
                            return None
                return None
            try:
                job.status = "running"
                job.emit({"type": "status", "status": "running"})
                job.emit({"type": "log", "line": f"Backup repo: {backup_dir}"})
                job.emit({"type": "log", "line": f"Worker Proxmox: {pmx_host}:{pmx_port} user={pmx_user}"})
                job.emit({"type": "log", "line": f"Dest ESXi: {esxi_host}:{esxi_port} user={esxi_user} datastore={datastore}"})

                local_archive = os.path.join(backup_dir, archive_name)
                if not os.path.isfile(local_archive):
                    raise RuntimeError("Archivio non trovato nel repository locale")

                ssh_pmx = SSHClient(pmx_host, pmx_user, pmx_pass, port=pmx_port, log_cb=None)
                ssh_pmx.connect()

                def _df_avail_bytes(path: str) -> Optional[int]:
                    code_df, out_df, _err_df = ssh_pmx.run(f"df -P -B1 {shlex.quote(path)} | tail -n 1", timeout=30)
                    if code_df != 0:
                        return None
                    parts = (out_df or "").strip().split()
                    if len(parts) < 6:
                        return None
                    try:
                        return int(parts[3])
                    except Exception:
                        return None

                def _pick_tmp_base_dir() -> str:
                    candidates: List[str] = ["/var/lib/vz", "/root/tmp", "/tmp", "/root"]
                    code_mp, out_mp, _err_mp = ssh_pmx.run("ls -1d /mnt/pve/* 2>/dev/null | head -n 50", timeout=30)
                    if code_mp == 0:
                        for ln in (out_mp or "").splitlines():
                            p = (ln or "").strip()
                            if p:
                                candidates.append(p)
                    best = "/var/lib/vz"
                    best_avail = -1
                    for c in candidates:
                        a = _df_avail_bytes(c)
                        if a is None:
                            continue
                        if a > best_avail:
                            best_avail = a
                            best = c
                    try:
                        code_dbg, out_dbg, err_dbg = ssh_pmx.run(
                            f"df -h {shlex.quote(best)} | tail -n 1",
                            timeout=30,
                        )
                        if code_dbg == 0:
                            job.emit({"type": "log", "line": f"Spazio worker (df -h): {out_dbg.strip()}"})
                        else:
                            job.emit({"type": "log", "line": f"Spazio worker (df -h): {err_dbg or out_dbg}"})
                    except Exception:
                        pass
                    return best

                tmp_base = pmx_tmp_base
                if tmp_base:
                    if not tmp_base.startswith("/"):
                        tmp_base = f"/mnt/pve/{tmp_base}"
                    try:
                        code_dbg, out_dbg, err_dbg = ssh_pmx.run(
                            f"df -h {shlex.quote(tmp_base)} | tail -n 1",
                            timeout=30,
                        )
                        if code_dbg == 0:
                            job.emit({"type": "log", "line": f"Spazio worker (df -h): {out_dbg.strip()}"})
                        else:
                            job.emit({"type": "log", "line": f"Spazio worker (df -h): {err_dbg or out_dbg}"})
                    except Exception:
                        pass
                else:
                    tmp_base = _pick_tmp_base_dir()
                remote_dir = f"{tmp_base}/vm-migration-tool-restore-esxi/{job_id}"
                ensure_dir(ssh_pmx, remote_dir)

                remote_archive = f"{remote_dir}/{archive_name}"

                total = 0
                try:
                    total = int(os.path.getsize(local_archive))
                except Exception:
                    total = 0

                def _cb_put(transferred: int, _total: int):
                    tt = _total or total or 0
                    pct = 0.0
                    if tt > 0:
                        pct = min(100.0, transferred * 100.0 / tt)
                        job.update_transfer(int(transferred or 0), tt)
                    job.copy_pct = float(pct)
                    job.copy_msg = f"Copia repository→Proxmox: {archive_name} ({transferred}/{tt} bytes)"
                    job.emit(
                        {
                            "type": "progress",
                            "copy_pct": job.copy_pct,
                            "copy_msg": job.copy_msg,
                            "ops_pct": job.ops_pct,
                            "ops_msg": job.ops_msg,
                            "bytes_total": job.bytes_total,
                            "bytes_done": job.bytes_done,
                            "rate_bps": job.rate_bps,
                        }
                    )

                ssh_pmx.put_file(local_archive, remote_archive, progress_cb=_cb_put if total > 0 else None)
                if total > 0:
                    job.update_transfer(total, total)
                job.copy_pct = 100.0
                job.copy_msg = f"Copia repository→Proxmox: {archive_name} (completo)"

                job.ops_pct = 1.0
                job.ops_msg = "Estrazione vzdump: preparo"
                job.emit(
                    {
                        "type": "progress",
                        "copy_pct": job.copy_pct,
                        "copy_msg": job.copy_msg,
                        "ops_pct": job.ops_pct,
                        "ops_msg": job.ops_msg,
                        "bytes_total": job.bytes_total,
                        "bytes_done": job.bytes_done,
                        "rate_bps": job.rate_bps,
                    }
                )

                remote_vma = remote_archive
                if remote_archive.endswith(".zst"):
                    remote_vma = remote_archive[: -len(".zst")]
                    code_d, out_d, err_d = ssh_pmx.run_streaming(
                        f"zstd -d --force {shlex.quote(remote_archive)} -o {shlex.quote(remote_vma)}",
                        timeout=6 * 3600,
                    )
                    job.emit({"type": "log", "line": f"zstd -d -> code={code_d}\n{out_d}\n{err_d}"})
                    if code_d != 0:
                        raise RuntimeError(f"Decompressione zstd fallita (code={code_d}): {err_d or out_d}")

                extract_dir = f"{remote_dir}/extract-{uuid.uuid4().hex[:8]}"
                try:
                    ssh_pmx.run(f"rm -rf {shlex.quote(extract_dir)}")
                except Exception:
                    pass
                job.ops_pct = 5.0
                job.ops_msg = "Estrazione VMA"
                code_x, out_x, err_x = ssh_pmx.run_streaming(
                    f"vma extract {shlex.quote(remote_vma)} {shlex.quote(extract_dir)}",
                    timeout=6 * 3600,
                )
                job.emit({"type": "log", "line": f"vma extract -> code={code_x}\n{out_x}\n{err_x}"})
                if code_x != 0:
                    raise RuntimeError(f"vma extract fallito (code={code_x}): {err_x or out_x}")

                code_ls, out_ls, err_ls = ssh_pmx.run(f"ls -1 {shlex.quote(extract_dir)}")
                if code_ls != 0:
                    raise RuntimeError(err_ls or out_ls or "Impossibile elencare file estratti")
                raw_files = [ln.strip() for ln in (out_ls or "").splitlines() if ln.strip().lower().endswith(".raw")]
                if not raw_files:
                    raise RuntimeError("Nessun file .raw trovato dopo vma extract")

                vmdk_files: List[str] = []
                for i, raw_name in enumerate(raw_files):
                    job.ops_pct = 15.0 + (i * 60.0 / max(1, len(raw_files)))
                    job.ops_msg = f"Conversione disco {i+1}/{len(raw_files)} (raw→vmdk)"
                    job.emit(
                        {
                            "type": "progress",
                            "copy_pct": job.copy_pct,
                            "copy_msg": job.copy_msg,
                            "ops_pct": job.ops_pct,
                            "ops_msg": job.ops_msg,
                            "bytes_total": job.bytes_total,
                            "bytes_done": job.bytes_done,
                            "rate_bps": job.rate_bps,
                        }
                    )
                    remote_raw = f"{extract_dir}/{raw_name}"
                    vmdk_name = f"disk-{i}.vmdk"
                    remote_vmdk = f"{remote_dir}/{vmdk_name}"
                    code_c, out_c, err_c = ssh_pmx.run_streaming(
                        " ".join(
                            [
                                "qemu-img",
                                "convert",
                                "-f",
                                "raw",
                                "-O",
                                "vmdk",
                                "-o",
                                "subformat=monolithicSparse",
                                shlex.quote(remote_raw),
                                shlex.quote(remote_vmdk),
                            ]
                        ),
                        timeout=6 * 3600,
                    )
                    job.emit({"type": "log", "line": f"qemu-img convert -> code={code_c}\n{out_c}\n{err_c}"})
                    if code_c != 0:
                        if "No space left on device" in (err_c or "") or "No space left on device" in (out_c or ""):
                            try:
                                _c2, _o2, _e2 = ssh_pmx.run(f"df -h {shlex.quote(remote_dir)}", timeout=30)
                                job.emit({"type": "log", "line": f"df -h (worker tmp):\n{_o2}\n{_e2}"})
                            except Exception:
                                pass
                        raise RuntimeError(f"Conversione raw→vmdk fallita (code={code_c}): {err_c or out_c}")
                    vmdk_files.append(vmdk_name)

                local_tmp_dir = tempfile.mkdtemp(prefix="vm-migration-tool-restore-esxi-")

                def _remote_size(ssh: SSHClient, p: str) -> int:
                    try:
                        code_s, out_s, _err_s = ssh.run(f"stat -c %s {shlex.quote(p)} 2>/dev/null || echo 0")
                        if code_s == 0:
                            return int(str(out_s or "0").strip() or "0")
                    except Exception:
                        return 0
                    return 0

                local_vmdks: List[tuple[str, str]] = []
                for i, vmdk_name in enumerate(vmdk_files):
                    job.ops_pct = 80.0
                    job.ops_msg = "Download vmdk su host app"
                    remote_vmdk = f"{remote_dir}/{vmdk_name}"
                    local_vmdk = os.path.join(local_tmp_dir, vmdk_name)
                    total_v = _remote_size(ssh_pmx, remote_vmdk)

                    def _cb_get(transferred: int, _total: int):
                        tt = _total or total_v or 0
                        pct = 0.0
                        if tt > 0:
                            pct = min(100.0, transferred * 100.0 / tt)
                        job.copy_pct = float(pct)
                        job.copy_msg = f"Download Proxmox→host: {vmdk_name} ({transferred}/{tt} bytes)"
                        job.emit(
                            {
                                "type": "progress",
                                "copy_pct": job.copy_pct,
                                "copy_msg": job.copy_msg,
                                "ops_pct": job.ops_pct,
                                "ops_msg": job.ops_msg,
                                "bytes_total": job.bytes_total,
                                "bytes_done": job.bytes_done,
                                "rate_bps": job.rate_bps,
                            }
                        )

                    ssh_pmx.get_file(remote_vmdk, local_vmdk, progress_cb=_cb_get if total_v > 0 else None)
                    local_vmdks.append((vmdk_name, local_vmdk))

                ssh_esxi = SSHClient(esxi_host, esxi_user, esxi_pass, port=esxi_port, log_cb=None)
                ssh_esxi.connect()

                safe_name = _safe_fs_name(name)
                vm_folder = f"{safe_name}-{backup_id[:8]}"
                esxi_vm_dir = f"/vmfs/volumes/{datastore}/{vm_folder}"
                code_m, out_m, err_m = ssh_esxi.run(f"mkdir -p {shlex.quote(esxi_vm_dir)}")
                if code_m != 0:
                    raise RuntimeError(f"Creazione dir VM su ESXi fallita: {err_m or out_m}")

                uploaded_vmdk_names: List[str] = []
                for idx, (src_name, local_path) in enumerate(local_vmdks):
                    dest_name = f"{safe_name}-scsi0-{idx}.vmdk"
                    remote_path = f"{esxi_vm_dir}/{dest_name}"
                    total_u = 0
                    try:
                        total_u = int(os.path.getsize(local_path))
                    except Exception:
                        total_u = 0

                    def _cb_up(transferred: int, _total: int):
                        tt = _total or total_u or 0
                        pct = 0.0
                        if tt > 0:
                            pct = min(100.0, transferred * 100.0 / tt)
                        job.copy_pct = float(pct)
                        job.copy_msg = f"Upload host→ESXi: {dest_name} ({transferred}/{tt} bytes)"
                        job.emit(
                            {
                                "type": "progress",
                                "copy_pct": job.copy_pct,
                                "copy_msg": job.copy_msg,
                                "ops_pct": job.ops_pct,
                                "ops_msg": job.ops_msg,
                                "bytes_total": job.bytes_total,
                                "bytes_done": job.bytes_done,
                                "rate_bps": job.rate_bps,
                            }
                        )

                    job.ops_pct = 85.0
                    job.ops_msg = "Upload vmdk su ESXi"
                    ssh_esxi.put_file(local_path, remote_path, progress_cb=_cb_up if total_u > 0 else None)
                    job.ops_pct = 88.0
                    job.ops_msg = "Import disco su ESXi (vmkfstools)"
                    job.emit(
                        {
                            "type": "progress",
                            "copy_pct": job.copy_pct,
                            "copy_msg": job.copy_msg,
                            "ops_pct": job.ops_pct,
                            "ops_msg": job.ops_msg,
                            "bytes_total": job.bytes_total,
                            "bytes_done": job.bytes_done,
                            "rate_bps": job.rate_bps,
                        }
                    )
                    imported_name = f"{safe_name}-scsi0-{idx}-esxi.vmdk"
                    code_i, out_i, err_i = ssh_esxi.run_streaming(
                        " ".join(
                            [
                                "cd",
                                shlex.quote(esxi_vm_dir),
                                "&&",
                                "vmkfstools",
                                "-i",
                                shlex.quote(dest_name),
                                shlex.quote(imported_name),
                                "-d",
                                "thin",
                            ]
                        ),
                        timeout=12 * 3600,
                    )
                    job.emit({"type": "log", "line": f"vmkfstools -i -> code={code_i}\n{out_i}\n{err_i}"})
                    if code_i != 0:
                        raise RuntimeError(f"Import disco su ESXi fallito (code={code_i}): {err_i or out_i}")
                    try:
                        ssh_esxi.run(" ".join(["cd", shlex.quote(esxi_vm_dir), "&&", "rm", "-f", shlex.quote(dest_name)]))
                    except Exception:
                        pass
                    try:
                        ssh_esxi.run(
                            " ".join(
                                [
                                    "cd",
                                    shlex.quote(esxi_vm_dir),
                                    "&&",
                                    "rm",
                                    "-f",
                                    shlex.quote(dest_name.replace(".vmdk", "-flat.vmdk")),
                                ]
                            )
                        )
                    except Exception:
                        pass
                    uploaded_vmdk_names.append(imported_name)

                qm_cfg_text = ""
                try:
                    qm_cfg_path = os.path.join(backup_dir, "qm_config.txt")
                    if os.path.isfile(qm_cfg_path):
                        with open(qm_cfg_path, "r", encoding="utf-8") as f:
                            qm_cfg_text = f.read()
                except Exception:
                    qm_cfg_text = ""

                use_uefi_effective = bool(use_uefi)
                bios = (_parse_qm_config_value(qm_cfg_text, "bios") or "").lower()
                if bios == "ovmf":
                    use_uefi_effective = True

                ostype = (_parse_qm_config_value(qm_cfg_text, "ostype") or "").lower()
                ide2 = (_parse_qm_config_value(qm_cfg_text, "ide2") or "").lower()
                guest_os = "otherGuest"
                if ostype.startswith("l"):
                    guest_os = "otherLinux64Guest"
                    if "ubuntu" in ide2:
                        guest_os = "ubuntu-64"
                elif ostype.startswith("win"):
                    guest_os = "windows9_64Guest"
                elif ostype in ("solaris",):
                    guest_os = "solaris11_64Guest"
                job.emit({"type": "log", "line": f"guestOS ESXi: {guest_os} (ostype={ostype or '-'} )"})
                vmx_lines: List[str] = []
                vmx_lines.append('.encoding = "UTF-8"')
                vmx_lines.append('config.version = "8"')
                vmx_lines.append('virtualHW.version = "14"')
                vmx_lines.append(f'displayName = "{name}"')
                vmx_lines.append(f'guestOS = "{guest_os}"')
                vmx_lines.append(f"memSize = \"{int(mem)}\"")
                vmx_lines.append(f"numvcpus = \"{int(cores)}\"")
                if use_uefi_effective:
                    vmx_lines.append('firmware = "efi"')
                vmx_lines.append('scsi0.present = "TRUE"')
                vmx_lines.append('scsi0.virtualDev = "lsilogic"')
                for idx, disk_name in enumerate(uploaded_vmdk_names):
                    vmx_lines.append(f'scsi0:{idx}.present = "TRUE"')
                    vmx_lines.append(f'scsi0:{idx}.fileName = "{disk_name}"')
                    vmx_lines.append(f'scsi0:{idx}.deviceType = "scsi-hardDisk"')
                vmx_lines.append('ethernet0.present = "TRUE"')
                vmx_lines.append('ethernet0.virtualDev = "vmxnet2"')
                vmx_lines.append('ethernet0.connectionType = "custom"')
                vmx_lines.append('ethernet0.networkName = "VM Network"')
                vmx_lines.append('ethernet0.startConnected = "TRUE"')
                vmx_lines.append('ethernet0.connected = "TRUE"')
                vmx_lines.append('ethernet0.addressType = "generated"')
                vmx_lines.append('floppy0.present = "FALSE"')
                vmx_text = "\n".join(vmx_lines) + "\n"

                local_vmx = os.path.join(local_tmp_dir, f"{vm_folder}.vmx")
                with open(local_vmx, "w", encoding="utf-8") as f:
                    f.write(vmx_text)
                remote_vmx = f"{esxi_vm_dir}/{vm_folder}.vmx"
                expected_vmx_ref = f"[{datastore}] {vm_folder}/{vm_folder}.vmx"
                ssh_esxi.put_file(local_vmx, remote_vmx)

                job.ops_pct = 95.0
                job.ops_msg = "Register VM su ESXi"
                job.emit(
                    {
                        "type": "progress",
                        "copy_pct": job.copy_pct,
                        "copy_msg": job.copy_msg,
                        "ops_pct": job.ops_pct,
                        "ops_msg": job.ops_msg,
                        "bytes_total": job.bytes_total,
                        "bytes_done": job.bytes_done,
                        "rate_bps": job.rate_bps,
                    }
                )

                code_r, out_r, err_r = ssh_esxi.run(f"vim-cmd solo/registervm {shlex.quote(remote_vmx)}")
                job.emit({"type": "log", "line": f"registervm -> code={code_r}\n{out_r}\n{err_r}"})
                vmid = None
                if code_r != 0:
                    exists = ("AlreadyExists" in (err_r or "")) or ("already exists" in (err_r or "").lower())
                    if exists and expected_vmx_ref:
                        vmid = _esxi_find_vmid_by_expected_vmx(expected_vmx_ref)
                        if vmid is not None:
                            job.emit({"type": "log", "line": f"registervm: VM già registrata (vmid={vmid}) per {expected_vmx_ref}"})
                        else:
                            raise RuntimeError(f"registervm fallito (code={code_r}): {err_r or out_r}")
                    else:
                        raise RuntimeError(f"registervm fallito (code={code_r}): {err_r or out_r}")
                else:
                    try:
                        vmid = int(str(out_r or "").strip().splitlines()[-1])
                    except Exception:
                        vmid = None
                registered_vmid = vmid
                if vmid is not None and start_vm:
                    code_p, out_p, err_p = ssh_esxi.run(f"vim-cmd vmsvc/power.on {int(vmid)}")
                    job.emit({"type": "log", "line": f"power.on -> code={code_p}\n{out_p}\n{err_p}"})
                    if code_p != 0:
                        job.error = "Power on failed"
                        try:
                            c_s, o_s, e_s = ssh_esxi.run(f"vim-cmd vmsvc/get.summary {int(vmid)}")
                            job.emit({"type": "log", "line": f"get.summary -> code={c_s}\n{o_s}\n{e_s}"})
                        except Exception:
                            pass
                        try:
                            c_t, o_t, e_t = ssh_esxi.run(f"vim-cmd vmsvc/get.tasklist {int(vmid)}")
                            job.emit({"type": "log", "line": f"get.tasklist -> code={c_t}\n{o_t}\n{e_t}"})
                        except Exception:
                            pass
                        try:
                            c_l, o_l, e_l = ssh_esxi.run(f"ls -lh {shlex.quote(esxi_vm_dir)}", timeout=60)
                            job.emit({"type": "log", "line": f"ls -lh VM dir -> code={c_l}\n{o_l}\n{e_l}"})
                        except Exception:
                            pass
                        try:
                            c_v, o_v, e_v = ssh_esxi.run(
                                f"tail -n 120 {shlex.quote(esxi_vm_dir)}/vmware.log 2>/dev/null || true",
                                timeout=60,
                            )
                            if (o_v or "").strip():
                                job.emit({"type": "log", "line": f"vmware.log (tail) -> code={c_v}\n{o_v}\n{e_v}"})
                        except Exception:
                            pass
                elif vmid is not None and not start_vm:
                    job.emit({"type": "log", "line": "Avvio VM disabilitato: skip power.on"})

                try:
                    ssh_pmx.run(f"rm -rf {shlex.quote(remote_dir)}")
                except Exception:
                    pass

                job.status = "done"
                job.emit({"type": "status", "status": "done"})
            except Exception as e:
                job.status = "error"
                job.error = str(e)
                job.emit({"type": "log", "line": f"ERRORE: {job.error}"})
                job.emit({"type": "status", "status": "error", "error": job.error})
                try:
                    if ssh_pmx:
                        ssh_pmx.run(f"rm -rf {shlex.quote(remote_dir)}")
                except Exception:
                    pass
                try:
                    if ssh_esxi and esxi_vm_dir:
                        if registered_vmid is not None:
                            ssh_esxi.run(f"vim-cmd vmsvc/unregister {int(registered_vmid)}")
                        elif expected_vmx_ref:
                            try:
                                evmid = _esxi_find_vmid_by_expected_vmx(expected_vmx_ref)
                                if evmid is not None:
                                    ssh_esxi.run(f"vim-cmd vmsvc/unregister {int(evmid)}")
                            except Exception:
                                pass
                        ssh_esxi.run(f"rm -rf {shlex.quote(esxi_vm_dir)}")
                except Exception:
                    pass
            finally:
                try:
                    if ssh_pmx and remote_dir:
                        ssh_pmx.run(f"rm -rf {shlex.quote(remote_dir)}")
                except Exception:
                    pass
                try:
                    if ssh_esxi:
                        ssh_esxi.close()
                except Exception:
                    pass
                try:
                    if ssh_pmx:
                        ssh_pmx.close()
                except Exception:
                    pass
                try:
                    if local_tmp_dir and os.path.isdir(local_tmp_dir):
                        shutil.rmtree(local_tmp_dir, ignore_errors=True)
                except Exception:
                    pass
                with _job_lock:
                    global _active_job_id
                    if _active_job_id == job_id:
                        _active_job_id = None

        threading.Thread(target=_run_job, daemon=True).start()
        return jsonify({"job_id": job_id})

    @app.post("/api/infrastructure/proxmox/list")
    def api_infra_proxmox_list():
        body = request.get_json(force=True, silent=True) or {}
        try:
            pmx_host, pmx_user, pmx_pass, pmx_port = _resolve_pmx_conn(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        ssh = SSHClient(pmx_host, pmx_user, pmx_pass, port=pmx_port, log_cb=None)
        try:
            ssh.connect()
            code, out, err = ssh.run("qm list")
            if code != 0:
                raise RuntimeError(err or out)
            vms: List[dict] = []
            for line in out.splitlines():
                t = line.strip()
                if not t or t.lower().startswith("vmid"):
                    continue
                parts = t.split()
                if len(parts) < 3:
                    continue
                vmid = parts[0]
                name = parts[1]
                status = parts[2]
                mem = parts[3] if len(parts) > 3 else ""
                vms.append({"vmid": vmid, "name": name, "status": status, "mem": mem})
            return jsonify({"vms": vms})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            try:
                ssh.close()
            except Exception:
                pass

    @app.post("/api/infrastructure/proxmox/config")
    def api_infra_proxmox_config():
        body = request.get_json(force=True, silent=True) or {}
        try:
            pmx_host, pmx_user, pmx_pass, pmx_port = _resolve_pmx_conn(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        vmid_raw = str(body.get("vmid") or "").strip()
        if not vmid_raw:
            return jsonify({"error": "vmid mancante"}), 400
        try:
            vmid = int(vmid_raw)
        except Exception:
            return jsonify({"error": "vmid non valido"}), 400
        ssh = SSHClient(pmx_host, pmx_user, pmx_pass, port=pmx_port, log_cb=None)
        try:
            ssh.connect()
            code, out, err = ssh.run(f"qm config {vmid}")
            if code != 0:
                raise RuntimeError(err or out)
            return jsonify({"text": out})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            try:
                ssh.close()
            except Exception:
                pass

    @app.post("/api/infrastructure/proxmox/prefill")
    def api_infra_proxmox_prefill():
        body = request.get_json(force=True, silent=True) or {}
        try:
            pmx_host, pmx_user, pmx_pass, pmx_port = _resolve_pmx_conn(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        ssh = SSHClient(pmx_host, pmx_user, pmx_pass, port=pmx_port, log_cb=None)
        try:
            ssh.connect()
            storages = list_storages(ssh)
            bridges = list_bridges(ssh)
            nextid = get_next_vmid(ssh)
            return jsonify({"storages": storages, "bridges": bridges, "next_vmid": nextid})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            try:
                ssh.close()
            except Exception:
                pass

    @app.post("/api/infrastructure/proxmox/tmpdirs")
    def api_infra_proxmox_tmpdirs():
        body = request.get_json(force=True, silent=True) or {}
        try:
            pmx_host, pmx_user, pmx_pass, pmx_port = _resolve_pmx_conn(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        def _fmt_gb(avail_bytes: int) -> str:
            try:
                gb = float(avail_bytes) / (1024.0 * 1024.0 * 1024.0)
                if gb >= 100:
                    return f"{gb:.0f} GB"
                if gb >= 10:
                    return f"{gb:.1f} GB"
                return f"{gb:.2f} GB"
            except Exception:
                return ""

        ssh = SSHClient(pmx_host, pmx_user, pmx_pass, port=pmx_port, log_cb=None)
        try:
            ssh.connect()
            script = "\n".join(
                [
                    "set -e",
                    "for p in /var/lib/vz /root/tmp /tmp /root; do",
                    "  if [ -d \"$p\" ]; then",
                    "    df -P -B1 \"$p\" | tail -n 1 | awk -v p=\"$p\" '{print p \"\\t\" $4}'",
                    "  fi",
                    "done",
                    "ls -1d /mnt/pve/* 2>/dev/null | head -n 50 | while IFS= read -r p; do",
                    "  [ -d \"$p\" ] || continue",
                    "  df -P -B1 \"$p\" | tail -n 1 | awk -v p=\"$p\" '{print p \"\\t\" $4}'",
                    "done",
                ]
            )
            code, out, err = ssh.run(f"sh -lc {shlex.quote(script)}", timeout=60)
            if code != 0:
                raise RuntimeError(err or out)

            seen: set[str] = set()
            rows: List[Tuple[str, int]] = []
            for line in (out or "").splitlines():
                t = (line or "").strip()
                if not t or "\t" not in t:
                    continue
                p, a = t.split("\t", 1)
                p = (p or "").strip()
                if not p or p in seen:
                    continue
                try:
                    avail = int((a or "").strip())
                except Exception:
                    continue
                seen.add(p)
                rows.append((p, avail))
            rows.sort(key=lambda x: int(x[1] or 0), reverse=True)

            items: List[dict] = [
                {"value": "auto", "label": "Auto (scegli disco con più spazio)"},
            ]
            for p, avail in rows:
                if p.startswith("/mnt/pve/"):
                    name = p.split("/")[-1]
                    items.append({"value": p, "label": f"{name} — {_fmt_gb(avail)} liberi"})
                elif p == "/var/lib/vz":
                    items.append({"value": p, "label": f"local (/var/lib/vz) — {_fmt_gb(avail)} liberi"})
                else:
                    items.append({"value": p, "label": f"{p} — {_fmt_gb(avail)} liberi"})

            return jsonify({"items": items})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            try:
                ssh.close()
            except Exception:
                pass

    @app.post("/api/infrastructure/esxi/list")
    def api_infra_esxi_list():
        body = request.get_json(force=True, silent=True) or {}
        try:
            esxi_host, esxi_user, esxi_pass, esxi_port = _resolve_esxi_conn(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        ssh = SSHClient(esxi_host, esxi_user, esxi_pass, port=esxi_port, log_cb=None)
        try:
            ssh.connect()
            vms_map = list_vms_direct(ssh)
            vms: List[dict] = []
            for key, info in vms_map.items():
                if not isinstance(info, dict):
                    continue
                try:
                    vmid = int(str(key))
                except Exception:
                    continue
                name = str(info.get("name") or "")
                power = esxi_power_state_direct(ssh, vmid)
                vms.append({"vmid": vmid, "name": name, "power": power})
            vms.sort(key=lambda x: int(x.get("vmid") or 0))
            return jsonify({"vms": vms})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            try:
                ssh.close()
            except Exception:
                pass

    @app.post("/api/infrastructure/esxi/datastores")
    def api_infra_esxi_datastores():
        body = request.get_json(force=True, silent=True) or {}
        try:
            esxi_host, esxi_user, esxi_pass, esxi_port = _resolve_esxi_conn(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        ssh = SSHClient(esxi_host, esxi_user, esxi_pass, port=esxi_port, log_cb=None)
        try:
            ssh.connect()
            code, out, err = ssh.run("ls -l /vmfs/volumes", timeout=60)
            if code != 0:
                raise RuntimeError(err or out)
            dss: List[str] = []
            for line in (out or "").splitlines():
                t = (line or "").strip()
                if not t or t.lower().startswith("total"):
                    continue
                if " -> " not in t:
                    continue
                left = t.split(" -> ", 1)[0]
                parts = left.split()
                if not parts:
                    continue
                name = parts[-1].strip()
                if name and name not in dss:
                    dss.append(name)
            dss.sort()
            return jsonify({"datastores": dss})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            try:
                ssh.close()
            except Exception:
                pass

    @app.post("/api/infrastructure/esxi/details")
    def api_infra_esxi_details():
        body = request.get_json(force=True, silent=True) or {}
        vmid_raw = str(body.get("vmid") or "").strip()
        if not vmid_raw:
            return jsonify({"error": "vmid mancante"}), 400
        try:
            esxi_host, esxi_user, esxi_pass, esxi_port = _resolve_esxi_conn(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        try:
            vmid = int(vmid_raw)
        except Exception:
            return jsonify({"error": "vmid non valido"}), 400
        ssh = SSHClient(esxi_host, esxi_user, esxi_pass, port=esxi_port, log_cb=None)
        try:
            ssh.connect()
            summary = esxi_get_summary_direct(ssh, vmid)
            config = esxi_get_config_direct(ssh, vmid)
            devices = ""
            filelayout = ""
            try:
                devices = esxi_get_devices_direct(ssh, vmid)
            except Exception:
                devices = ""
            try:
                filelayout = esxi_get_filelayout_direct(ssh, vmid)
            except Exception:
                filelayout = ""
            return jsonify({"summary": summary, "config": config, "devices": devices, "filelayout": filelayout})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            try:
                ssh.close()
            except Exception:
                pass

    @app.post("/api/infrastructure/esxi/snapshot/create")
    def api_infra_esxi_snapshot_create():
        body = request.get_json(force=True, silent=True) or {}
        vmid_raw = str(body.get("vmid") or "").strip()
        if not vmid_raw:
            return jsonify({"error": "vmid mancante"}), 400
        try:
            vmid = int(vmid_raw)
        except Exception:
            return jsonify({"error": "vmid non valido"}), 400
        snap_name = (body.get("name") or "").strip()
        if not snap_name:
            snap_name = f"vm-migration-tool-{int(time.time())}"
        desc = (body.get("description") or "").strip() or "Snapshot creata da vm-migration-tool"
        quiesce = bool(body.get("quiesce", True))
        memory = bool(body.get("memory", False))
        try:
            esxi_host, esxi_user, esxi_pass, esxi_port = _resolve_esxi_conn(body)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        ssh = SSHClient(esxi_host, esxi_user, esxi_pass, port=esxi_port, log_cb=None)
        try:
            ssh.connect()
            esxi_create_snapshot_direct(ssh, vmid, snap_name, desc, quiesce=quiesce, memory=memory)
            snap_id = esxi_find_snapshot_id_by_name_direct(ssh, vmid, snap_name)
            return jsonify({"ok": True, "name": snap_name, "snapshot_id": snap_id})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            try:
                ssh.close()
            except Exception:
                pass

    @app.get("/api/jobs")
    def api_jobs_list():
        items = sorted(_jobs.values(), key=lambda j: int(j.created_ms or 0), reverse=True)
        return jsonify({"jobs": [_job_to_dict(j) for j in items[:200]]})

    @app.get("/api/jobs/<job_id>")
    def api_job_get(job_id: str):
        job = _jobs.get(job_id)
        if not job:
            job = _job_get_from_db(job_id)
            if not job:
                return jsonify({"error": "job_id non trovato"}), 404
        data = _job_to_dict(job)
        data["logs"] = job.logs
        return jsonify(data)

    @app.get("/api/jobs/<job_id>/events")
    def api_job_events(job_id: str):
        job = _jobs.get(job_id)
        if not job:
            snap = _job_get_from_db(job_id)
            if not snap:
                return Response("event: error\ndata: {}\n\n", mimetype="text/event-stream")

            def stream_once():
                yield f"data: {json.dumps({'type': 'status', 'status': snap.status, 'error': snap.error})}\n\n"
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "progress",
                            "copy_pct": snap.copy_pct,
                            "copy_msg": snap.copy_msg,
                            "ops_pct": snap.ops_pct,
                            "ops_msg": snap.ops_msg,
                            "bytes_total": snap.bytes_total,
                            "bytes_done": snap.bytes_done,
                            "rate_bps": snap.rate_bps,
                        }
                    )
                    + "\n\n"
                )

            return Response(stream_once(), mimetype="text/event-stream")

        def stream():
            yield f"data: {json.dumps({'type': 'status', 'status': job.status})}\n\n"
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "progress",
                        "copy_pct": job.copy_pct,
                        "copy_msg": job.copy_msg,
                        "ops_pct": job.ops_pct,
                        "ops_msg": job.ops_msg,
                        "bytes_total": job.bytes_total,
                        "bytes_done": job.bytes_done,
                        "rate_bps": job.rate_bps,
                    }
                )
                + "\n\n"
            )
            while True:
                try:
                    payload = job.events.get(timeout=15)
                    yield f"data: {json.dumps(payload)}\n\n"
                except queue.Empty:
                    yield "data: " + json.dumps({"type": "ping"}) + "\n\n"
                if job.status in ("done", "error") and job.events.empty():
                    break

        return Response(stream(), mimetype="text/event-stream")

    return app

