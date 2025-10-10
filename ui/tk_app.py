import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from typing import Dict, Any
import os
import threading
import time

from core.ssh_client import SSHClient
from core.esxi_import import write_esxi_password_file, list_vms
from core.migration_flow import compose_plan, execute_plan, execute_full_migration
from core.proxmox import list_storages, list_bridges, get_next_vmid
from core.transfer import compute_dest_dir
from core.projects import save_project, load_project, list_projects, project_exists
from core.locale import set_language, get_string, _


def run_app():
    root = tk.Tk()
    root.title(_("app_title"))
    root.geometry("1000x700")

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except:
        pass
        
    # Selettore lingua
    lang_frame = ttk.Frame(root)
    lang_frame.pack(fill="x", padx=10, pady=(10,0))
    ttk.Label(lang_frame, text="Language/Lingua:").pack(side="left", padx=(0,5))
    
    def change_language():
        lang = lang_var.get()
        set_language(lang)
        messagebox.showinfo("Info", "Riavvia l'applicazione per applicare la nuova lingua / Restart the application to apply the new language")
    
    # Imposta il valore iniziale del selettore di lingua in base alla lingua corrente
    from core.locale import current_language
    lang_var = tk.StringVar(value=current_language)
    lang_combo = ttk.Combobox(lang_frame, values=["it", "en"], textvariable=lang_var, state="readonly", width=5)
    lang_combo.pack(side="left")
    lang_combo.bind("<<ComboboxSelected>>", lambda e: change_language())

    # Tabs a step (Progetto, Scansione, Migrazione)
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=10, pady=10)

    step1 = ttk.Frame(notebook)
    step2 = ttk.Frame(notebook)
    step3 = ttk.Frame(notebook)
    notebook.add(step1, text=_("tab_project"))
    notebook.add(step2, text=_("tab_connection"))
    notebook.add(step3, text=_("tab_migration"))

    # Frame credenziali (Step 1)
    creds = ttk.LabelFrame(step1, text=_("credentials"))
    creds.pack(fill="x", padx=10, pady=10)

    # Proxmox
    ttk.Label(creds, text="Proxmox " + _("host_ip")).grid(row=0, column=0, sticky="w", padx=5, pady=5)
    pmx_host = ttk.Entry(creds, width=25)
    pmx_host.grid(row=0, column=1, padx=5, pady=5)
    ttk.Label(creds, text=_("user")).grid(row=0, column=2, sticky="w", padx=5, pady=5)
    pmx_user = ttk.Entry(creds, width=15)
    pmx_user.grid(row=0, column=3, padx=5, pady=5)
    ttk.Label(creds, text=_("password")).grid(row=0, column=4, sticky="w", padx=5, pady=5)
    pmx_pass = ttk.Entry(creds, show="*", width=20)
    pmx_pass.grid(row=0, column=5, padx=5, pady=5)

    # ESXi
    ttk.Label(creds, text="ESXi " + _("host_ip")).grid(row=1, column=0, sticky="w", padx=5, pady=5)
    esxi_host = ttk.Entry(creds, width=25)
    esxi_host.grid(row=1, column=1, padx=5, pady=5)
    ttk.Label(creds, text=_("user")).grid(row=1, column=2, sticky="w", padx=5, pady=5)
    esxi_user = ttk.Entry(creds, width=15)
    esxi_user.grid(row=1, column=3, padx=5, pady=5)
    ttk.Label(creds, text=_("password")).grid(row=1, column=4, sticky="w", padx=5, pady=5)
    esxi_pass = ttk.Entry(creds, show="*", width=20)
    esxi_pass.grid(row=1, column=5, padx=5, pady=5)

    # Frame gestione progetto (Step 1)
    proj = ttk.LabelFrame(step1, text=_("project"))
    proj.pack(fill="x", padx=10, pady=(0,10))
    ttk.Label(proj, text=_("project_name")).grid(row=0, column=0, sticky="w", padx=5, pady=5)
    proj_name = ttk.Entry(proj, width=30)
    proj_name.grid(row=0, column=1, padx=5, pady=5)
    ttk.Label(proj, text=_("existing_projects")).grid(row=0, column=2, sticky="w", padx=5, pady=5)
    proj_list = ttk.Combobox(proj, values=list_projects(), state="readonly", width=20)
    proj_list.grid(row=0, column=3, padx=5, pady=5)
    def refresh_projects():
        try:
            proj_list["values"] = list_projects()
        except Exception:
            pass
    def clear_project_fields():
        try:
            for e in (pmx_host, pmx_user, pmx_pass, esxi_host, esxi_user, esxi_pass,
                      new_vmid, new_vmname, new_mem, new_cores, dest_dir_entry):
                e.delete(0, "end")
            fmt_combo.set("qcow2")
            dry_run_var.set(True)
            uefi_var.set(False)
            vlan_var.set(False)
            convert_var.set(False)
        except Exception:
            pass
    def capture_project_data() -> dict:
        return {
            "pmx_host": pmx_host.get(),
            "pmx_user": pmx_user.get(),
            "esxi_host": esxi_host.get(),
            "esxi_user": esxi_user.get(),
            "storage_name": storage_name.get(),
            "bridge_name": bridge_name.get(),
            "new_vmid": new_vmid.get(),
            "new_vmname": new_vmname.get(),
            "new_mem": new_mem.get(),
            "new_cores": new_cores.get(),
            "dest_dir": dest_dir_entry.get(),
            "dry_run": dry_run_var.get(),
            "uefi": uefi_var.get(),
            "vlan": vlan_var.get(),
            "convert": convert_var.get(),
            "format": fmt_combo.get(),
        }
    def apply_project_data(data: dict):
        try:
            def _set(entry, value):
                entry.delete(0, "end")
                entry.insert(0, str(value))
            if "pmx_host" in data: _set(pmx_host, data["pmx_host"])
            if "pmx_user" in data: _set(pmx_user, data["pmx_user"])
            if "esxi_host" in data: _set(esxi_host, data["esxi_host"])
            if "esxi_user" in data: _set(esxi_user, data["esxi_user"])
            if "new_vmid" in data: _set(new_vmid, data["new_vmid"])
            if "new_vmname" in data: _set(new_vmname, data["new_vmname"])
            if "new_mem" in data: _set(new_mem, data["new_mem"])
            if "new_cores" in data: _set(new_cores, data["new_cores"])
            if "dest_dir" in data: _set(dest_dir_entry, data["dest_dir"])
            if "storage_name" in data and data["storage_name"]:
                try:
                    storage_name.set(data["storage_name"])  # verrà validato dopo la scansione
                except Exception:
                    pass
            if "bridge_name" in data and data["bridge_name"]:
                try:
                    bridge_name.set(data["bridge_name"])  # verrà validato dopo la scansione
                except Exception:
                    pass
            if "dry_run" in data: dry_run_var.set(bool(data["dry_run"]))
            if "uefi" in data: uefi_var.set(bool(data["uefi"]))
            if "vlan" in data: vlan_var.set(bool(data["vlan"]))
            if "convert" in data: convert_var.set(bool(data["convert"]))
            if "format" in data:
                try:
                    fmt_combo.set(data["format"])
                except Exception:
                    pass
        except Exception as e:
            log(f"Errore applicazione progetto: {e}")

    def on_save_project():
        name = proj_name.get().strip() or "project"
        try:
            path = save_project(name, capture_project_data())
            log(f"Progetto '{name}' salvato: {path}")
            refresh_projects()
            messagebox.showinfo("Progetto", f"Salvato '{name}'")
        except Exception as e:
            messagebox.showerror("Errore salvataggio", str(e))

    def on_load_project():
        name = (proj_name.get().strip() or proj_list.get().strip())
        if not name:
            messagebox.showwarning("Progetto", "Inserisci o seleziona un nome progetto")
            return
        try:
            data = load_project(name)
            apply_project_data(data)
            log(f"Progetto '{name}' caricato")
            messagebox.showinfo("Progetto", f"Caricato '{name}'")
        except Exception as e:
            messagebox.showerror("Errore caricamento", str(e))

    def on_new_project():
        clear_project_fields()
        log("Nuovo progetto: campi resettati")

    ttk.Button(proj, text=_("new"), command=on_new_project).grid(row=0, column=4, padx=5, pady=5)
    ttk.Button(proj, text=_("save"), command=on_save_project).grid(row=0, column=5, padx=5, pady=5)
    ttk.Button(proj, text=_("load"), command=on_load_project).grid(row=0, column=6, padx=5, pady=5)
    ttk.Button(proj, text=_("refresh_list"), command=refresh_projects).grid(row=0, column=7, padx=5, pady=5)

    # Opzioni Proxmox (Step 3)
    opts = ttk.LabelFrame(step3, text=_("proxmox_options"))
    opts.pack(fill="x", padx=10, pady=10)
    ttk.Label(opts, text=_("storage")).grid(row=0, column=0, sticky="w", padx=5, pady=5)
    storage_name = ttk.Combobox(opts, values=[], state="readonly", width=20)
    storage_name.grid(row=0, column=1, padx=5, pady=5)
    ttk.Label(opts, text=_("network")).grid(row=0, column=2, sticky="w", padx=5, pady=5)
    bridge_name = ttk.Combobox(opts, values=[], state="readonly", width=20)
    bridge_name.grid(row=0, column=3, padx=5, pady=5)

    ttk.Label(opts, text=_("new_vmid")).grid(row=1, column=0, sticky="w", padx=5, pady=5)
    new_vmid = ttk.Entry(opts, width=10)
    new_vmid.insert(0, "120")
    new_vmid.grid(row=1, column=1, padx=5, pady=5)
    ttk.Label(opts, text=_("new_name")).grid(row=1, column=2, sticky="w", padx=5, pady=5)
    new_vmname = ttk.Entry(opts, width=20)
    new_vmname.insert(0, "easydeploy-web")
    new_vmname.grid(row=1, column=3, padx=5, pady=5)

    ttk.Label(opts, text=_("ram_mb")).grid(row=2, column=0, sticky="w", padx=5, pady=5)
    new_mem = ttk.Entry(opts, width=10)
    new_mem.insert(0, "4096")
    new_mem.grid(row=2, column=1, padx=5, pady=5)
    ttk.Label(opts, text=_("vcpu")).grid(row=2, column=2, sticky="w", padx=5, pady=5)
    new_cores = ttk.Entry(opts, width=10)
    new_cores.insert(0, "2")
    new_cores.grid(row=2, column=3, padx=5, pady=5)

    ttk.Label(opts, text=_("destination")).grid(row=3, column=0, sticky="w", padx=5, pady=5)
    dest_dir_entry = ttk.Entry(opts, width=40)
    dest_dir_entry.grid(row=3, column=1, columnspan=2, padx=5, pady=5, sticky="we")
    dest_browse = ttk.Button(opts, text=_("browse"))
    dest_browse.grid(row=3, column=3, padx=5, pady=5, sticky="w")

    dry_run_var = tk.BooleanVar(value=True)
    dry_run = ttk.Checkbutton(opts, text=_("dry_run"), variable=dry_run_var)
    dry_run.grid(row=4, column=0, columnspan=4, sticky="w", padx=5, pady=5)

    uefi_var = tk.BooleanVar(value=False)
    uefi_chk = ttk.Checkbutton(opts, text=_("uefi_ovmf"), variable=uefi_var)
    uefi_chk.grid(row=5, column=0, sticky="w", padx=5, pady=5)

    vlan_var = tk.BooleanVar(value=False)
    vlan_chk = ttk.Checkbutton(opts, text=_("vlan_aware"), variable=vlan_var)
    vlan_chk.grid(row=5, column=1, sticky="w", padx=5, pady=5)

    # Opzioni conversione qemu-img
    convert_var = tk.BooleanVar(value=False)
    convert_chk = ttk.Checkbutton(opts, text=_("convert_qemu"), variable=convert_var)
    convert_chk.grid(row=6, column=0, sticky="w", padx=5, pady=5)
    ttk.Label(opts, text=_("format")).grid(row=6, column=2, sticky="w", padx=5, pady=5)
    fmt_combo = ttk.Combobox(opts, values=["qcow2", "raw", "vmdk"], state="readonly", width=10)
    fmt_combo.set("qcow2")
    fmt_combo.grid(row=6, column=3, padx=5, pady=5)

    # Azioni di scansione (Step 2)
    actions_scan = ttk.Frame(step2)
    actions_scan.pack(fill="x", padx=10, pady=5)
    scan_btn = ttk.Button(actions_scan, text=_("connect_and_scan"))
    scan_btn.pack(side="left", padx=5)

    # Azioni di migrazione (Step 3)
    actions_mig = ttk.Frame(step3)
    actions_mig.pack(fill="x", padx=10, pady=5)
    migrate_btn = ttk.Button(actions_mig, text=_("prepare_execute_migration"))
    migrate_btn.pack(side="left", padx=5)
    cleanup_btn = ttk.Button(actions_mig, text=_("cleanup_esxi_credentials"))
    cleanup_btn.pack(side="left", padx=5)

    # Risultati scansione (Step 2)
    res_frame = ttk.LabelFrame(step2, text=_("vms_found_on_esxi"))
    res_frame.pack(fill="both", expand=True, padx=10, pady=10)
    cols = ("name", "datastore", "path", "capacity", "power")
    tree = ttk.Treeview(res_frame, columns=cols, show="headings", height=12)
    for c, label in zip(cols, [_("vm_name"), _("datastore"), _("disk_path"), _("capacity"), _("power_state")]):
        tree.heading(c, text=label)
        if c == "path":
            tree.column(c, width=360)
        elif c == "name":
            tree.column(c, width=200)
        else:
            tree.column(c, width=160)
    tree.pack(fill="both", expand=True)

    # Dischi della VM selezionata (Step 3)
    disk_frame = ttk.LabelFrame(step3, text=_("selected_vm_disks"))
    disk_frame.pack(fill="x", padx=10, pady=(0,10))
    dcols = ("datastore", "path", "capacity")
    tree_disks = ttk.Treeview(disk_frame, columns=dcols, show="headings", height=6, selectmode="extended")
    for c, label in zip(dcols, [_("datastore"), _("disk_path"), _("capacity")]):
        tree_disks.heading(c, text=label)
        tree_disks.column(c, width=260 if c == "path" else 180)
    tree_disks.pack(fill="x", expand=False)

    # Log (sempre visibile sotto ai tabs)
    log_frame = ttk.LabelFrame(root, text=_("log"))
    log_frame.pack(fill="both", expand=True, padx=10, pady=10)
    log_txt = tk.Text(log_frame, height=10)
    log_txt.pack(fill="both", expand=True)

    # File di log su disco (nuova sessione)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    logs_dir = os.path.join(base_dir, "logs")
    try:
        os.makedirs(logs_dir, exist_ok=True)
    except Exception:
        pass
    session_log_path = os.path.join(logs_dir, datetime.now().strftime("session-%Y%m%d-%H%M%S.log"))
    # Canale log dedicato al progresso (solo eventi di avanzamento)
    progress_log_path = os.path.join(logs_dir, datetime.now().strftime("progress-%Y%m%d-%H%M%S.log"))

    # Progress (Step 3): due barre separate per maggiore chiarezza
    prog_frame = ttk.LabelFrame(step3, text="Avanzamento copia")
    prog_frame.pack(fill="x", padx=10, pady=(0,10))
    progress_copy = ttk.Progressbar(prog_frame, orient="horizontal", mode="determinate", maximum=100)
    progress_copy.pack(fill="x", padx=5, pady=5)
    progress_msg_copy = ttk.Label(prog_frame, text="")
    progress_msg_copy.pack(anchor="w", padx=5)

    prog_ops = ttk.LabelFrame(step3, text="Conversione / Import / Avvio")
    prog_ops.pack(fill="x", padx=10, pady=(0,10))
    progress_ops = ttk.Progressbar(prog_ops, orient="horizontal", mode="determinate", maximum=100)
    progress_ops.pack(fill="x", padx=5, pady=5)
    progress_msg_ops = ttk.Label(prog_ops, text="")
    progress_msg_ops.pack(anchor="w", padx=5)

    state: Dict[str, Any] = {"ssh": None, "vms": {}, "selection": None, "dest_update_running": False}

    def log(msg: str):
        ts = datetime.now().strftime("[%H:%M:%S]")
        line = f"{ts} {msg}"
        # Aggiorna UI in modo thread-safe
        def _append_ui():
            try:
                log_txt.insert("end", line + "\n")
                log_txt.see("end")
            except Exception:
                pass
        try:
            log_txt.after(0, _append_ui)
        except Exception:
            # In casi estremi, ignora errori UI
            pass
        # Scrive sempre su file (thread-safe)
        try:
            with open(session_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            # Ignora errori di scrittura su file
            pass

    # Helper: formatta capacità in GB (base 1024)
    def format_gb(val: Any) -> str:
        try:
            n = float(val)
            return f"{n / (1024**3):.1f}"
        except Exception:
            return str(val)

    # Avvisa percorso del file di log
    log(f"File di log: {session_log_path}")
    try:
        refresh_projects()
    except Exception:
        pass

    # Aggiorna automaticamente la destinazione quando cambia storage/VM name (non bloccare la UI)
    def update_dest_dir():
        # Evita chiamate concorrenti
        if state.get("dest_update_running"):
            return
        state["dest_update_running"] = True
        def _worker():
            dest = ""
            try:
                ssh = state.get("ssh")
                storage = storage_name.get()
                name = new_vmname.get()
                custom = dest_dir_entry.get()
                if ssh and storage and name:
                    dest = compute_dest_dir(ssh, storage, name, custom)
            except Exception as e:
                log(f"Errore calcolo destinazione: {e}")
            finally:
                def _apply():
                    try:
                        if dest:
                            dest_dir_entry.delete(0, "end")
                            dest_dir_entry.insert(0, dest)
                    finally:
                        state["dest_update_running"] = False
                try:
                    root.after(0, _apply)
                except Exception:
                    state["dest_update_running"] = False
        threading.Thread(target=_worker, daemon=True).start()

    storage_name.bind("<<ComboboxSelected>>", lambda e: update_dest_dir())
    new_vmname.bind("<KeyRelease>", lambda e: update_dest_dir())

    def on_scan():
        # Esegue la scansione su thread dedicato per evitare freeze della GUI
        try:
            scan_btn.state(["disabled"])
        except Exception:
            pass
        log("Avvio connessione/scansione…")

        def _do_scan():
            try:
                ssh = SSHClient(pmx_host.get(), pmx_user.get(), pmx_pass.get(), log_cb=log)
                ssh.connect()
                state["ssh"] = ssh
                log("Connesso a Proxmox via SSH")

                # Prefill da Proxmox: storage, bridges, next VMID
                try:
                    storages = list_storages(ssh)
                except Exception as e:
                    storages = []
                    log(f"Impossibile elencare storage: {e}")
                try:
                    bridges = list_bridges(ssh)
                except Exception as e:
                    bridges = []
                    log(f"Impossibile elencare bridge: {e}")
                try:
                    nextid = get_next_vmid(ssh)
                except Exception as e:
                    nextid = None
                    log(f"Impossibile ottenere next VMID: {e}")

                try:
                    write_esxi_password_file(ssh, esxi_pass.get())
                    log("Password ESXi scritta su /root/esxi_pass.txt (Proxmox)")
                except Exception as e:
                    log(f"Errore scrittura password ESXi: {e}")

                try:
                    data = list_vms(ssh, esxi_host.get(), esxi_user.get(), "/root/esxi_pass.txt", skip_cert=True)
                except Exception as e:
                    data = {}
                    log(f"Errore scansione ESXi: {e}")

                state["vms"] = data

                def _apply_results():
                    try:
                        if storages:
                            storage_name["values"] = storages
                            storage_name.set(storages[0])
                            log(f"Storage rilevati: {', '.join(storages)}")
                        if bridges:
                            bridge_name["values"] = bridges
                            bridge_name.set(bridges[0])
                            log(f"Bridge rilevati: {', '.join(bridges)}")
                        if nextid:
                            new_vmid.delete(0, "end")
                            new_vmid.insert(0, str(nextid))
                            log(f"Prossimo VMID suggerito: {nextid}")
                        # Pulisci vista
                        for i in tree.get_children():
                            tree.delete(i)
                        for i in tree_disks.get_children():
                            tree_disks.delete(i)
                        # Popola vista con i dati
                        for name, info in data.items():
                            disks = info.get("disks", [])
                            power = info.get("power", "?")
                            if disks:
                                d = disks[0]
                                ds = d.get("datastore", "")
                                path = d.get("path", "")
                                cap = format_gb(d.get("capacity", ""))
                            else:
                                ds = path = cap = ""
                            # Nome VM estratto dalla path (prima dello slash), fallback al nome chiave
                            vm_name = (path.split("/", 1)[0] if path else name)
                            tree.insert("", "end", iid=name, values=(vm_name, ds, path, cap, power))
                        # Aggiorna destinazione suggerita in base a storage e nome VM
                        try:
                            update_dest_dir()
                        except Exception:
                            pass
                        log("Scansione completata")
                    except Exception as e:
                        log(f"Errore aggiornamento UI: {e}")

                try:
                    root.after(0, _apply_results)
                except Exception:
                    pass
            except Exception as e:
                def _show_err():
                    try:
                        messagebox.showerror("Errore", str(e))
                    except Exception:
                        pass
                log(f"Errore scansione: {e}")
                try:
                    root.after(0, _show_err)
                except Exception:
                    pass
            finally:
                try:
                    root.after(0, lambda: scan_btn.state(["!disabled"]))
                except Exception:
                    pass

        threading.Thread(target=_do_scan, daemon=True).start()

    def on_select(event):
        sel = tree.focus()
        state["selection"] = sel if sel else None
        # Aggiorna lista dischi
        for i in tree_disks.get_children():
            tree_disks.delete(i)
        if sel:
            info = state["vms"].get(sel, {})
            disks = info.get("disks", [])
            for idx, d in enumerate(disks):
                ds = d.get("datastore", "")
                path = d.get("path", "")
                cap = format_gb(d.get("capacity", ""))
                tree_disks.insert("", "end", iid=f"d{idx}", values=(ds, path, cap))

    def on_migrate():
        sel = state.get("selection")
        if not sel:
            messagebox.showwarning("Selezione mancante", "Seleziona una VM dalla lista")
            return
        info = state["vms"].get(sel, {})
        disks = info.get("disks", [])
        if not disks:
            messagebox.showwarning("Nessun disco", "La VM selezionata non ha dischi visibili")
            return
        storage = storage_name.get()
        # Lettura e validazione parametri VM
        try:
            vmid = int(new_vmid.get())
        except Exception:
            messagebox.showerror("Valore non valido", "VMID deve essere un intero")
            return
        name = new_vmname.get()
        try:
            mem = int(new_mem.get())
        except Exception:
            messagebox.showerror("Valore non valido", "RAM (MB) deve essere un intero")
            return
        if mem < 16:
            messagebox.showerror("RAM troppo bassa", "RAM (MB) deve essere almeno 16. Suggerito: 4096 (4 GiB)")
            return
        try:
            cores = int(new_cores.get())
        except Exception:
            messagebox.showerror("Valore non valido", "vCPU deve essere un intero (>=1)")
            return
        if cores < 1:
            messagebox.showerror("vCPU non valida", "vCPU deve essere almeno 1")
            return
        net0 = f"virtio,bridge={bridge_name.get()}"

        vmdk_path = disks[0].get("path", "")
        plan = compose_plan(vmid, name, mem, cores, net0, vmdk_path, storage)
        log("Piano di migrazione:")
        for line in plan:
            log("  " + line)
        if vlan_var.get():
            br = bridge_name.get()
            log(
                f"[VLAN-aware] Suggerimento: abilitare 'bridge-vlan-aware yes' su {br} in /etc/network/interfaces, poi eseguire 'ifreload -a'."
            )

        if dry_run_var.get():
            messagebox.showinfo("Dry-run", "Piano mostrato. Disattiva dry-run per eseguire.")
            return

        ssh = state.get("ssh")
        if not ssh:
            messagebox.showwarning("Connessione mancante", "Connetti a Proxmox prima di migrare")
            return

        # Disabilita il bottone durante la migrazione
        try:
            migrate_btn.state(["disabled"])
        except Exception:
            pass

        dest_custom = dest_dir_entry.get().strip() or None
        # selezione multipla dischi
        sel_disks = tree_disks.selection()
        idxs = [int(i[1:]) for i in sel_disks] if sel_disks else None

        def _do_migrate():
            try:
                # Progress callback sicuro da thread secondario
                last_pct_logged = {"v": -5.0}
                def progress_cb(pct: float, msg: str):
                    def _apply():
                        try:
                            mlow = (msg or "").lower()
                            if mlow.startswith("copia"):
                                progress_copy['value'] = pct
                                progress_msg_copy.config(text=msg)
                            else:
                                progress_ops['value'] = pct
                                progress_msg_ops.config(text=msg)
                        except Exception:
                            pass
                    try:
                        root.after(0, _apply)
                    except Exception:
                        pass
                    # Logga l'avanzamento ogni 5% o alla fine per visibilità su file di sessione
                    try:
                        if pct - last_pct_logged["v"] >= 5.0 or pct >= 100.0 or pct <= 0.1:
                            last_pct_logged["v"] = pct
                            log(f"Progress: {pct:.1f}% — {msg}")
                            # Scrive anche sul canale di progresso dedicato
                            try:
                                with open(progress_log_path, "a", encoding="utf-8") as pf:
                                    pf.write(f"{datetime.now().strftime('[%H:%M:%S]')} {pct:.1f}% — {msg}\n")
                            except Exception:
                                pass
                    except Exception:
                        pass

                # Esegue copia VMDK, crea VM, importa disco, collega, boot, UEFI opzionale e avvio
                logs = execute_full_migration(
                    ssh,
                    esxi_host.get(),
                    esxi_user.get(),
                    esxi_pass.get(),
                    info,
                    vmid,
                    name,
                    mem,
                    cores,
                    net0,
                    storage,
                    dest_custom,
                    uefi_var.get(),
                    selected_disk_indexes=idxs,
                    use_convert=convert_var.get(),
                    convert_fmt=fmt_combo.get(),
                    progress_cb=progress_cb,
                )
                for l in logs:
                    log(l)
                def _done():
                    try:
                        messagebox.showinfo("Completato", "Migrazione eseguita (verifica output/log)")
                    except Exception:
                        pass
                try:
                    root.after(0, _done)
                except Exception:
                    pass
            except Exception as e:
                log(f"Errore migrazione: {e}")
                def _err():
                    try:
                        messagebox.showerror("Errore migrazione", str(e))
                    except Exception:
                        pass
                try:
                    root.after(0, _err)
                except Exception:
                    pass
            finally:
                # Riabilita bottone
                def _enable():
                    try:
                        migrate_btn.state(["!disabled"])
                    except Exception:
                        pass
                try:
                    root.after(0, _enable)
                except Exception:
                    pass

        threading.Thread(target=_do_migrate, daemon=True).start()

    def on_browse():
        ssh = state.get("ssh")
        if not ssh:
            messagebox.showwarning("Connessione mancante", "Connetti a Proxmox prima di sfogliare")
            return
        # Selettore remoto asincrono: mostra directory sotto /mnt/pve e /var/lib/vz
        win = tk.Toplevel(root)
        win.title("Seleziona cartella remota")
        win.geometry("600x400")
        tree_remote = ttk.Treeview(win, columns=("path",), show="headings")
        tree_remote.heading("path", text="Percorso")
        tree_remote.pack(fill="both", expand=True)

        loading = {"v": False}

        def set_loading(is_loading: bool):
            try:
                loading["v"] = is_loading
                win.configure(cursor="watch" if is_loading else "")
                for b in (btn_pve, btn_vz, btn_sel):
                    try:
                        if is_loading:
                            b.state(["disabled"])
                        else:
                            b.state(["!disabled"])
                    except Exception:
                        pass
            except Exception:
                pass

        def load_dir(base: str):
            if loading["v"]:
                return
            set_loading(True)
            def _worker():
                paths = []
                try:
                    # Lista solo directory (1 livello) in modo veloce
                    cmd = f"ls -1 -p '{base}' 2>/dev/null | grep '/$' || true"
                    code, out, err = ssh.run(cmd)
                    for line in out.splitlines():
                        name = line.strip().rstrip('/')
                        if name:
                            # Costruisce path assoluto
                            paths.append(os.path.join(base, name))
                except Exception as e:
                    log(f"Errore sfoglia remota: {e}")
                finally:
                    def _apply():
                        try:
                            for i in tree_remote.get_children():
                                tree_remote.delete(i)
                            for p in sorted(paths):
                                tree_remote.insert("", "end", values=(p,))
                        finally:
                            set_loading(False)
                    try:
                        root.after(0, _apply)
                    except Exception:
                        set_loading(False)
            threading.Thread(target=_worker, daemon=True).start()

        btns = ttk.Frame(win)
        btns.pack(fill="x")
        btn_pve = ttk.Button(btns, text="/mnt/pve", command=lambda: load_dir("/mnt/pve"))
        btn_pve.pack(side="left", padx=5, pady=5)
        btn_vz = ttk.Button(btns, text="/var/lib/vz", command=lambda: load_dir("/var/lib/vz"))
        btn_vz.pack(side="left", padx=5, pady=5)

        def choose():
            sel = tree_remote.focus()
            if not sel:
                return
            path = tree_remote.item(sel, "values")[0]
            dest_dir_entry.delete(0, "end")
            dest_dir_entry.insert(0, path)
            win.destroy()

        btn_sel = ttk.Button(btns, text="Seleziona", command=choose)
        btn_sel.pack(side="right", padx=5, pady=5)

        # Carica subito /mnt/pve per evitare finestra vuota
        try:
            load_dir("/mnt/pve")
        except Exception:
            pass

    dest_browse.configure(command=on_browse)

    def on_cleanup():
        ssh = state.get("ssh")
        if not ssh:
            messagebox.showwarning("Connessione mancante", "Connetti a Proxmox prima di eseguire cleanup")
            return
        try:
            ssh.run("shred -u /root/esxi_pass.txt || rm -f /root/esxi_pass.txt")
            log("Password ESXi rimossa da /root/esxi_pass.txt")
            messagebox.showinfo("Cleanup", "File password ESXi rimosso.")
        except Exception as e:
            messagebox.showerror("Errore cleanup", str(e))
            log(f"Errore cleanup: {e}")

    tree.bind("<<TreeviewSelect>>", on_select)
    scan_btn.configure(command=on_scan)
    migrate_btn.configure(command=on_migrate)
    cleanup_btn.configure(command=on_cleanup)

    root.mainloop()