import socket
import threading
import time
from typing import Dict, Any, Optional

from .protocol import IRC5Protocol, IRC5Message, ProtocolError

class IRC5MockServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 5001, virtual_io_manager: Optional[Any] = None):
        self.host = host
        self.port = int(port)
        self.virtual_io = virtual_io_manager
        self.server_socket: Optional[socket.socket] = None
        self.is_running = False
        self.thread: Optional[threading.Thread] = None

        self.digital_inputs: Dict[str, int] = {
            "di_pieza_presente": 1,
            "di_ciclo_inicio": 0,
            "di_parada_celda": 0,
            "di_robot_listo": 1,
            "di_pinza_abierta": 1,
            "di_pinza_cerrada": 0,
            "di1": 1,
            "di2": 0,
            "di3": 0,
            "di4": 0,
        }

        self.digital_outputs: Dict[str, int] = {
            "do_valvula_aire": 0,
            "do_pinza_actuar": 0,
            "do_indicador_verde": 1,
            "do_indicador_rojo": 0,
            "do_indicador_amarillo": 0,
            "do1": 0,
            "do2": 0,
        }

        self.variables: Dict[str, Any] = {
            "cycle_count": 42,
            "part_type": "A140",
            "speed_override": 100,
            "tool_weight": 2.5
        }

        self.current_joints: list = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.presets: Dict[str, list] = {
            "HOME": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "TEST_DELTA_J1": [10.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "TEST_SAFE_1": [0.0, 15.0, -15.0, 0.0, 30.0, 0.0]
        }

    def start(self) -> None:
        if self.is_running:
            return

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.is_running = True

        self.thread = threading.Thread(target=self._accept_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.is_running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

    def _accept_loop(self) -> None:
        while self.is_running:
            try:
                client_sock, addr = self.server_socket.accept()
                t = threading.Thread(target=self._client_handler, args=(client_sock, addr), daemon=True)
                t.start()
            except Exception:
                if not self.is_running:
                    break

    def _client_handler(self, client_sock: socket.socket, addr: Any) -> None:
        client_sock.settimeout(2.0)
        buffer = b""

        while self.is_running:
            try:
                chunk = client_sock.recv(1024)
                if not chunk:
                    break
                buffer += chunk
                messages, buffer = IRC5Protocol.extract_messages_from_buffer(buffer)

                for msg in messages:
                    response_bytes = self._process_command(msg)
                    client_sock.sendall(response_bytes)

            except (socket.timeout, BlockingIOError):
                continue
            except Exception:
                break

        try:
            client_sock.close()
        except Exception:
            pass

    def _process_command(self, msg: IRC5Message) -> bytes:
        msg_id = msg.msg_id
        cmd = msg.cmd
        params = msg.params

        if cmd == "PING":
            return IRC5Protocol.build_response(msg_id, "OK", data="PONG")

        elif cmd == "GET_STATUS":
            return IRC5Protocol.build_response(
                msg_id,
                "OK",
                data={
                    "exec_state": "running",
                    "mode": "virtual_simulated",
                    "controller": "ABB_IRC5_MOCK",
                    "speed_ratio": 100,
                    "cycle": "continuous",
                    "robot_state": "IDLE",
                    "joints": list(self.current_joints),
                    "timestamp": time.time()
                }
            )

        elif cmd == "GET_JOINTS":
            return IRC5Protocol.build_response(msg_id, "OK", data={"joints": list(self.current_joints)})

        elif cmd == "MOVE_JOINTS":
            target_joints = params.get("joints")
            if not isinstance(target_joints, (list, tuple)) or len(target_joints) != 6:
                return IRC5Protocol.build_response(msg_id, "ERROR", error="Parámetro 'joints' inválido: se requieren 6 ángulos")
            self.current_joints = [round(float(q), 2) for q in target_joints]
            return IRC5Protocol.build_response(msg_id, "OK", data={"state": "COMPLETED", "joints": list(self.current_joints)})

        elif cmd == "MOVE_PRESET":
            target = str(params.get("target", "")).upper()
            if target not in self.presets:
                return IRC5Protocol.build_response(msg_id, "ERROR", error=f"Preset '{target}' no reconocido")
            self.current_joints = list(self.presets[target])
            return IRC5Protocol.build_response(msg_id, "OK", data={"state": "COMPLETED", "target": target, "joints": list(self.current_joints)})

        elif cmd == "GET_DI":
            name = params.get("name", "")
            if self.virtual_io:
                sig = self.virtual_io.get_signal(name)
                if sig and sig["type"] == "DI":
                    return IRC5Protocol.build_response(msg_id, "OK", data=sig["value"])
            if name in self.digital_inputs:
                return IRC5Protocol.build_response(msg_id, "OK", data=self.digital_inputs[name])
            return IRC5Protocol.build_response(msg_id, "ERROR", error=f"Entrada digital '{name}' no encontrada")

        elif cmd == "GET_DO":
            name = params.get("name", "")
            if self.virtual_io:
                sig = self.virtual_io.get_signal(name)
                if sig and sig["type"] == "DO":
                    return IRC5Protocol.build_response(msg_id, "OK", data=sig["value"])
            if name in self.digital_outputs:
                return IRC5Protocol.build_response(msg_id, "OK", data=self.digital_outputs[name])
            return IRC5Protocol.build_response(msg_id, "ERROR", error=f"Salida digital '{name}' no encontrada")

        elif cmd == "SET_DO":
            name = params.get("name", "")
            val = params.get("value")
            
            allowed = False
            if self.virtual_io:
                sig = self.virtual_io.get_signal(name)
                if sig and sig["type"] == "DO":
                    allowed = True
            if name in self.digital_outputs:
                allowed = True

            if not allowed:
                return IRC5Protocol.build_response(msg_id, "ERROR", error=f"Salida digital '{name}' no autorizada")
            try:
                val_int = int(val)
                if val_int not in (0, 1):
                    raise ValueError()
                if self.virtual_io and self.virtual_io.get_signal(name):
                    self.virtual_io.update_signal_value(name, val_int)
                self.digital_outputs[name] = val_int
                return IRC5Protocol.build_response(msg_id, "OK", data=val_int)
            except Exception:
                return IRC5Protocol.build_response(msg_id, "ERROR", error="El valor de salida debe ser 0 o 1")

        elif cmd == "GET_VARIABLE":
            name = params.get("name", "")
            if name in self.variables:
                return IRC5Protocol.build_response(msg_id, "OK", data=self.variables[name])
            return IRC5Protocol.build_response(msg_id, "ERROR", error=f"Variable '{name}' no encontrada")

        return IRC5Protocol.build_response(msg_id, "ERROR", error=f"Comando desconocido: {cmd}")
