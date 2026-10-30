import os
import json
import socket
import time
import threading
import urllib.request
from typing import Dict, Any, Optional

from robot_connection.protocol import IRC5Protocol, IRC5Message, ProtocolError
from robot_connection.safety_validator import SafetyValidator, SafetyValidationError

class IRC5ClientError(Exception):
    pass

class RobotClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5001,
        timeout: float = 3.0,
        mode: str = "SIMULATED",
        allow_loopback: bool = True
    ):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.mode = mode
        self.allow_loopback = allow_loopback
        self.sock: Optional[socket.socket] = None
        self._proxy_url: Optional[str] = None
        self._lock = threading.Lock()
        self._seq_id = 0
        self._recv_buffer = b""
        self.validator = SafetyValidator(mode=self.mode)
        self.last_latency_ms: Optional[float] = None
        self.last_seen: Optional[float] = None

    def _next_id(self) -> int:
        self._seq_id += 1
        return self._seq_id

    def _close_unlocked(self) -> None:
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self._proxy_url = None
        self._recv_buffer = b""

    def is_connected(self) -> bool:
        with self._lock:
            return self.sock is not None or self._proxy_url is not None

    def sync_validator_signals(self, allowed_di: Optional[Any] = None, allowed_do: Optional[Any] = None) -> None:
        self.validator.update_allowed_signals(allowed_di=allowed_di, allowed_do=allowed_do)

    def arm_physical_mode_writes(self) -> None:
        self.validator.arm_physical_mode()

    def arm_physical_writes(self) -> None:
        self.validator.arm_physical_mode()

    def disarm_physical_writes(self) -> None:
        self.validator.disarm_physical_mode()

    def _try_proxy_connect(self) -> Optional[Dict[str, Any]]:
        proxy = os.environ.get("IRC5_BACKEND_PROXY", "").strip()
        if not proxy:
            return None
        try:
            req = urllib.request.Request(f"{proxy}/api/connection/status", method="GET")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                st = json.loads(resp.read().decode("utf-8"))
            if st.get("is_connected") and st.get("host") == self.host and int(st.get("port", 0)) == self.port:
                self._proxy_url = proxy
                self.last_latency_ms = st.get("latency_ms")
                self.last_seen = time.time()
                return {
                    "success": True,
                    "latency_ms": self.last_latency_ms,
                    "message": f"Conectado a IRC5 en {self.host}:{self.port} (canal compartido)"
                }
        except Exception:
            pass
        return None

    def _proxy_command(self, cmd: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"cmd": cmd, "physical_confirmed": True}
        if params:
            payload.update(params)
            if "name" in params:
                payload["name"] = params["name"]
            if "value" in params:
                payload["value"] = params["value"]
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self._proxy_url}/api/connection/command",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=max(self.timeout + 2.0, 5.0)) as resp:
                res = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as he:
            try:
                err_body = json.loads(he.read().decode("utf-8"))
                raise IRC5ClientError(err_body.get("error", str(he)))
            except IRC5ClientError:
                raise
            except Exception:
                raise IRC5ClientError(str(he))
        except Exception as e:
            raise IRC5ClientError(f"Error en canal compartido IRC5: {e}")

        if not res.get("success"):
            raise IRC5ClientError(res.get("error", "Error reportado por controlador"))
        self.last_latency_ms = res.get("latency_ms")
        self.last_seen = time.time()
        return res

    def connect(self, timeout: Optional[float] = None, verify_handshake: bool = True) -> Dict[str, Any]:
        with self._lock:
            if self.sock is not None or self._proxy_url is not None:
                return {"success": True, "message": "Ya conectado", "latency_ms": self.last_latency_ms}

            try:
                self.validator.validate_connection_target(self.host, allow_loopback=self.allow_loopback)
            except SafetyValidationError as sve:
                return {"success": False, "error": str(sve)}

            proxied = self._try_proxy_connect()
            if proxied is not None:
                return proxied

            t_val = timeout if timeout is not None else self.timeout
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.settimeout(t_val)
                s.connect((self.host, self.port))
                self.sock = s
                self._recv_buffer = b""
            except Exception as e:
                self._close_unlocked()
                return {
                    "success": False,
                    "error": f"No se pudo conectar a {self.host}:{self.port} ({e}). Verifica que RobotStudio tenga el servidor RAPID iniciado."
                }

            if verify_handshake:
                # RobVC mantiene abierto el backlog TCP en Windows aunque RAPID este detenido; PING confirma ejecucion real
                try:
                    ping_res = self._exchange_unlocked("PING", None, timeout_override=min(max(t_val, 2.0), 4.0))
                    if not ping_res.get("success"):
                        self._close_unlocked()
                        return {"success": False, "error": ping_res.get("error", "Fallo de handshake PING con RAPID")}
                except Exception as e:
                    self._close_unlocked()
                    return {
                        "success": False,
                        "error": (
                            f"Puerto {self.port} abierto, pero RAPID no responde ({e}). "
                            "En RobotStudio ve a la pestaña RAPID y pulsa 'Inicio' para arrancar la tarea T_ROB1."
                        )
                    }

            self.last_seen = time.time()
            return {
                "success": True,
                "latency_ms": self.last_latency_ms,
                "message": f"Conectado a IRC5 en {self.host}:{self.port}"
            }

    def disconnect(self) -> Dict[str, Any]:
        with self._lock:
            if self.sock is None and self._proxy_url is None:
                return {"success": True, "message": "Ya desconectado"}
            self._close_unlocked()
            return {"success": True, "message": "Desconectado de IRC5"}

    def _exchange_unlocked(
        self,
        cmd: str,
        params: Optional[Dict[str, Any]] = None,
        timeout_override: Optional[float] = None
    ) -> Dict[str, Any]:
        if self._proxy_url is not None:
            return self._proxy_command(cmd, params)

        if self.sock is None:
            raise IRC5ClientError("No hay conexion activa con el controlador IRC5")

        msg_id = self._next_id()
        raw_payload = IRC5Protocol.build_request(msg_id, cmd, params)
        wait_limit = timeout_override if timeout_override is not None else (
            max(self.timeout, 8.0) if cmd in ("MOVE_JOINTS", "MOVE_PRESET") else self.timeout
        )

        t0 = time.time()
        try:
            self.sock.settimeout(wait_limit)
            self.sock.sendall(raw_payload)
        except Exception as e:
            self._close_unlocked()
            raise IRC5ClientError(f"Conexion TCP interrumpida al enviar {cmd}: {e}")

        deadline = time.time() + wait_limit
        while time.time() < deadline:
            try:
                chunk = self.sock.recv(1024)
                if not chunk:
                    self._close_unlocked()
                    raise IRC5ClientError("Conexion cerrada por RobotStudio / IRC5")
                self._recv_buffer += chunk

                messages, self._recv_buffer = IRC5Protocol.extract_messages_from_buffer(self._recv_buffer)
                for msg in messages:
                    if msg.msg_id == msg_id:
                        self.last_latency_ms = round((time.time() - t0) * 1000.0, 2)
                        self.last_seen = time.time()
                        if msg.status == "OK":
                            return {
                                "success": True,
                                "data": msg.data,
                                "latency_ms": self.last_latency_ms
                            }
                        return {
                            "success": False,
                            "error": msg.error or "Error reportado por controlador",
                            "latency_ms": self.last_latency_ms
                        }
            except socket.timeout:
                break
            except ProtocolError as pe:
                self._recv_buffer = b""
                raise IRC5ClientError(f"Error de protocolo en respuesta: {pe}")
            except IRC5ClientError:
                raise
            except Exception as e:
                self._close_unlocked()
                raise IRC5ClientError(f"Fallo de lectura TCP ({e})")

        raise IRC5ClientError(f"Tiempo de espera agotado ({wait_limit}s) esperando respuesta a {cmd}")

    def _send_and_receive(self, cmd: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            return self._exchange_unlocked(cmd, params)

    def ping(self) -> Dict[str, Any]:
        return self._send_and_receive("PING")

    def get_status(self) -> Dict[str, Any]:
        return self._send_and_receive("GET_STATUS")

    def get_di(self, name: str) -> Dict[str, Any]:
        self.validator.validate_read_di(name)
        return self._send_and_receive("GET_DI", {"name": name})

    def get_do(self, name: str) -> Dict[str, Any]:
        self.validator.validate_read_do(name)
        return self._send_and_receive("GET_DO", {"name": name})

    def set_do(self, name: str, value: Any, physical_confirmed: bool = False) -> Dict[str, Any]:
        val = self.validator.validate_write_do(name, value, physical_confirmed=physical_confirmed)
        return self._send_and_receive("SET_DO", {"name": name, "value": val})

    def get_variable(self, name: str) -> Dict[str, Any]:
        self.validator.validate_signal_name(name)
        return self._send_and_receive("GET_VARIABLE", {"name": name})

    def get_joints(self) -> Dict[str, Any]:
        return self._send_and_receive("GET_JOINTS")

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            return self._exchange_unlocked("STOP", {})

    def move_joints(self, joints: list, speed: float = 50.0, physical_confirmed: bool = False) -> Dict[str, Any]:
        validated = self.validator.validate_motion_command(
            "MOVE_JOINTS",
            {"joints": joints, "speed": speed},
            physical_confirmed=physical_confirmed
        )
        return self._send_and_receive("MOVE_JOINTS", validated)

    def move_preset(self, preset_name: str, speed: float = 50.0, physical_confirmed: bool = False) -> Dict[str, Any]:
        validated = self.validator.validate_motion_command(
            "MOVE_PRESET",
            {"target": preset_name, "speed": speed},
            physical_confirmed=physical_confirmed
        )
        return self._send_and_receive("MOVE_PRESET", validated)
