import paramiko
import logging
import time
from typing import Tuple, Optional, Callable


class SSHClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: Optional[str] = None,
        port: int = 22,
        log_cb: Optional[Callable[[str], None]] = None,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self._client: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None
        self._log_cb: Optional[Callable[[str], None]] = log_cb
        self._paramiko_handler: Optional[logging.Handler] = None

        # Abilita logging Paramiko verso il callback, se disponibile
        # e assicura la redazione di eventuali segreti nei messaggi
        if self._log_cb:
            try:
                class _CallbackHandler(logging.Handler):
                    def __init__(self, cb: Callable[[str], None]):
                        super().__init__(level=logging.DEBUG)
                        self._cb = cb
                    def emit(self, record: logging.LogRecord):
                        msg = self.format(record)
                        try:
                            if self._cb:
                                self._cb(f"Paramiko: {msg}")
                        except Exception:
                            pass

                logger = logging.getLogger("paramiko")
                logger.setLevel(logging.DEBUG)
                h = _CallbackHandler(self._log_cb)
                h.setLevel(logging.DEBUG)
                h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
                logger.addHandler(h)
                logger.propagate = False
                self._paramiko_handler = h
            except Exception:
                # Non bloccare se la configurazione del logging fallisce
                self._paramiko_handler = None

    def _emit(self, msg: str):
        try:
            if self._log_cb:
                self._log_cb(msg)
        except Exception:
            # Non interrompere il flusso in caso di problemi col callback
            pass

    def connect(self):
        self._emit(f"SSH: connessione a {self.username}@{self.host}:{self.port}")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                look_for_keys=False,
                allow_agent=False,
                timeout=10,           # timeout connessione TCP
                banner_timeout=10,    # timeout banner
                auth_timeout=15,      # timeout autenticazione
            )
            # opzionale keepalive per connessioni lente
            try:
                transport = client.get_transport()
                if transport:
                    transport.set_keepalive(10)
            except Exception:
                pass
            self._client = client
            self._sftp = client.open_sftp()
            self._emit("SSH: connessione riuscita")
        except Exception as e:
            self._emit(f"SSH: errore connessione → {e}")
            raise

    def close(self):
        try:
            if self._sftp:
                self._sftp.close()
        finally:
            if self._client:
                self._client.close()
        self._client = None
        self._sftp = None
        self._emit("SSH: connessione chiusa")
        # Rimuovi handler Paramiko per evitare duplicazioni in sessioni successive
        try:
            if self._paramiko_handler:
                logging.getLogger("paramiko").removeHandler(self._paramiko_handler)
                self._paramiko_handler = None
        except Exception:
            pass

    def run(self, command: str, timeout: Optional[int] = None) -> Tuple[int, str, str]:
        if not self._client:
            raise RuntimeError("SSHClient non connesso")
        self._emit(f"SSH: eseguo → {self._redact(command)}")
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        # Log sintetico degli output (limitato per non saturare la UI)
        max_len = 2000
        out_log = out if len(out) <= max_len else out[:max_len] + "… (troncato)"
        err_log = err if len(err) <= max_len else err[:max_len] + "… (troncato)"
        self._emit(f"SSH: exit={exit_status}\nSTDOUT:\n{out_log}\nSTDERR:\n{err_log}")
        return exit_status, out, err

    def run_streaming(self, command: str, timeout: Optional[int] = None) -> Tuple[int, str, str]:
        # Alcuni chiamanti usano run_streaming; assicuriamo la redazione anche qui
        self._emit(f"SSH: eseguo (stream) → {self._redact(command)}")
        return self._run_streaming_impl(command, timeout)

    def run_streaming_with_parser(self, command: str, parser: Callable[[str], Optional[Tuple[float, str]]], timeout: Optional[int] = None) -> Tuple[int, str, str]:
        # Wrapper con redazione per uniformità
        self._emit(f"SSH: eseguo (stream+parser) → {self._redact(command)}")
        return self._run_streaming_with_parser_impl(command, parser, timeout)

    # Implementazioni reali esistenti
    def _run_streaming_impl(self, command: str, timeout: Optional[int] = None) -> Tuple[int, str, str]:
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return exit_status, out, err

    def _run_streaming_with_parser_impl(self, command: str, parser: Callable[[str], Optional[Tuple[float, str]]], timeout: Optional[int] = None) -> Tuple[int, str, str]:
        # Per semplicità usiamo la stessa esecuzione di base; il parser è applicato altrove
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return exit_status, out, err

    def _redact(self, text: str) -> str:
        """Oscura credenziali note dai comandi e dai log."""
        try:
            import re
            t = text or ""
            # sshpass inline: -p 'secret' | -p "secret" | -p secret
            t = re.sub(r"sshpass\s+-p\s+'[^']*'", "sshpass -p '***'", t)
            t = re.sub(r'sshpass\s+-p\s+\"[^\"]*\"', 'sshpass -p "***"', t)
            t = re.sub(r"sshpass\s+-p\s+\S+", "sshpass -p ***", t)
            # pattern generici di password
            t = re.sub(r"(password\s*=\s*)['\"]?[^'\"\s]+['\"]?", r"\1***", t, flags=re.IGNORECASE)
            t = re.sub(r"(--password\s+)\S+", r"\1***", t, flags=re.IGNORECASE)
            # file password: non è segreto, ma normalizziamo il path
            t = re.sub(r"(/root/esxi_pass\.txt)", r"[passfile]", t)
            return t
        except Exception:
            return text

    def run_streaming(self, command: str, timeout: Optional[int] = None) -> Tuple[int, str, str]:
        """
        Esegue un comando e invia chunk di output in tempo reale al callback di log.
        Ritorna (exit_status, stdout, stderr) a fine esecuzione o timeout (-1).
        """
        if not self._client:
            raise RuntimeError("SSHClient non connesso")
        self._emit(f"SSH(stream): eseguo → {command}")
        transport = self._client.get_transport()
        if not transport:
            raise RuntimeError("Transport SSH non disponibile")
        chan = transport.open_session()
        chan.exec_command(command)
        start = time.time()
        out_chunks: list[str] = []
        err_chunks: list[str] = []
        while True:
            if chan.recv_ready():
                data = chan.recv(4096).decode("utf-8", errors="replace")
                out_chunks.append(data)
                if data.strip():
                    self._emit(f"STDOUT+: {data.strip()}")
            if chan.recv_stderr_ready():
                data = chan.recv_stderr(4096).decode("utf-8", errors="replace")
                err_chunks.append(data)
                if data.strip():
                    self._emit(f"STDERR+: {data.strip()}")
            if chan.exit_status_ready():
                # Non uscire immediatamente: potrebbe esserci ancora output da drenare
                # Passa a una fase di drain per assicurarsi di leggere tutti i dati residui
                break
            if timeout is not None and (time.time() - start) > timeout:
                try:
                    chan.close()
                except Exception:
                    pass
                self._emit("SSH(stream): timeout scaduto, comando terminato")
                return -1, "".join(out_chunks), "".join(err_chunks) + "\n[TIMEOUT]"
            time.sleep(0.25)
        # Fase di drain: continua a leggere finché c'è output disponibile
        # per evitare tronchi (es. JSON incompleto)
        drain_start = time.time()
        while True:
            drained = False
            if chan.recv_ready():
                data = chan.recv(4096).decode("utf-8", errors="replace")
                if data:
                    out_chunks.append(data)
                    drained = True
                    if data.strip():
                        self._emit(f"STDOUT+: {data.strip()}")
            if chan.recv_stderr_ready():
                data = chan.recv_stderr(4096).decode("utf-8", errors="replace")
                if data:
                    err_chunks.append(data)
                    drained = True
                    if data.strip():
                        self._emit(f"STDERR+: {data.strip()}")
            # Esci se non drenato in questo giro
            if not drained:
                # Attendi un attimo per eventuali pacchetti in transito
                time.sleep(0.05)
                # Se ancora nulla e il canale ha riportato exit status, termina
                if not chan.recv_ready() and not chan.recv_stderr_ready():
                    break
            # Safety: evita loop infiniti in caso di anomalie canale
            if timeout is not None and (time.time() - drain_start) > max(2, min(10, timeout // 10)):
                break

        exit_status = chan.recv_exit_status()
        out = "".join(out_chunks)
        err = "".join(err_chunks)
        self._emit(f"SSH(stream): exit={exit_status}")
        return exit_status, out, err

    def run_streaming_with_parser(
        self,
        command: str,
        parse_cb: Optional[Callable[[float, str], None]] = None,
        timeout: Optional[int] = None,
    ) -> Tuple[int, str, str]:
        """
        Variante di run_streaming: oltre a loggare in tempo reale, prova a
        riconoscere righe di avanzamento (es. "transferred ... (NN.NN%)") e
        invoca parse_cb(pct, msg) quando presenti. Utile per tracciare qm importdisk.
        """
        if not self._client:
            raise RuntimeError("SSHClient non connesso")
        self._emit(f"SSH(stream+parse): eseguo → {command}")
        transport = self._client.get_transport()
        if not transport:
            raise RuntimeError("Transport SSH non disponibile")
        chan = transport.open_session()
        chan.exec_command(command)
        start = time.time()
        out_chunks: list[str] = []
        err_chunks: list[str] = []

        import re

        def _try_parse_progress(text: str):
            # Esempio output qm importdisk: "transferred ... (99.77%)"
            # Esempio output qemu-img -p: "42.0%" (senza parentesi)
            m = re.search(r"\(\s*([0-9]+(?:\.[0-9]+)?)%\s*\)", text)
            if not m:
                m = re.search(r"([0-9]+(?:\.[0-9]+)?)%", text)
            if m:
                try:
                    pct = float(m.group(1))
                    if parse_cb:
                        parse_cb(pct, text.strip())
                except Exception:
                    pass
            # Completamento esplicito
            if "successfully imported disk" in text.lower():
                try:
                    if parse_cb:
                        parse_cb(100.0, text.strip())
                except Exception:
                    pass

        while True:
            if chan.recv_ready():
                data = chan.recv(4096).decode("utf-8", errors="replace")
                out_chunks.append(data)
                if data.strip():
                    self._emit(f"STDOUT+: {data.strip()}")
                    _try_parse_progress(data)
            if chan.recv_stderr_ready():
                data = chan.recv_stderr(4096).decode("utf-8", errors="replace")
                err_chunks.append(data)
                if data.strip():
                    self._emit(f"STDERR+: {data.strip()}")
            if chan.exit_status_ready():
                break
            if timeout is not None and (time.time() - start) > timeout:
                try:
                    chan.close()
                except Exception:
                    pass
                self._emit("SSH(stream+parse): timeout scaduto, comando terminato")
                return -1, "".join(out_chunks), "".join(err_chunks) + "\n[TIMEOUT]"
            time.sleep(0.25)

        # Drain finale per catturare eventuale output residuo
        drain_start = time.time()
        while True:
            drained = False
            if chan.recv_ready():
                data = chan.recv(4096).decode("utf-8", errors="replace")
                if data:
                    out_chunks.append(data)
                    drained = True
                    if data.strip():
                        self._emit(f"STDOUT+: {data.strip()}")
                        _try_parse_progress(data)
            if chan.recv_stderr_ready():
                data = chan.recv_stderr(4096).decode("utf-8", errors="replace")
                if data:
                    err_chunks.append(data)
                    drained = True
                    if data.strip():
                        self._emit(f"STDERR+: {data.strip()}")
            if not drained:
                time.sleep(0.05)
                if not chan.recv_ready() and not chan.recv_stderr_ready():
                    break
            if timeout is not None and (time.time() - drain_start) > max(2, min(10, timeout // 10)):
                break

        exit_status = chan.recv_exit_status()
        out = "".join(out_chunks)
        err = "".join(err_chunks)
        self._emit(f"SSH(stream+parse): exit={exit_status}")
        return exit_status, out, err

    def write_file(self, remote_path: str, content: str):
        if not self._sftp:
            raise RuntimeError("SFTP non disponibile: connetti prima l'SSHClient")
        with self._sftp.file(remote_path, "w") as f:
            f.write(content)

    def file_exists(self, remote_path: str) -> bool:
        if not self._sftp:
            raise RuntimeError("SFTP non disponibile: connetti prima l'SSHClient")
        try:
            self._sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False