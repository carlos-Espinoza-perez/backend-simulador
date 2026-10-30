import os
import re
import json
import time
import shutil
import threading
from flask import Blueprint, request, jsonify
from flask_socketio import SocketIO

from .workspace_manager import WorkspaceManager
from .script_runner import ScriptRunner
from .completion_service import CompletionService
from robot_connection.irc5_mock_server import IRC5MockServer
from robot_connection.virtual_io_manager import VirtualIOManager
from abb_irc5 import RobotClient, IRC5ClientError
from robot_connection.safety_validator import SafetyValidationError

ide_bp = Blueprint("ide_bp", __name__)

BASE_WORKSPACE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python_workspace")

DEFAULT_PROFILES = [
    {
        "id": "virtual_local",
        "name": "ABB RobotStudio - Controlador Virtual (127.0.0.1)",
        "host": "127.0.0.1",
        "port": 5001,
        "timeout": 3.0,
        "mode": "SIMULATED",
        "description": "Conexion TCP directa al controlador virtual IRB 140 en RobotStudio (puerto 5001)"
    },
    {
        "id": "irc5_service_port",
        "name": "ABB IRC5 Físico - Puerto de Servicio (X2)",
        "host": "192.168.125.1",
        "port": 5001,
        "timeout": 4.0,
        "mode": "CONNECTED_PHYSICAL",
        "description": "Conexion directa por cable Ethernet al puerto de servicio X2 del IRC5"
    },
    {
        "id": "irc5_lan_cell",
        "name": "ABB IRC5 Físico - Red LAN de Celda",
        "host": "0.0.0.0",
        "port": 5001,
        "timeout": 3.0,
        "mode": "CONNECTED_PHYSICAL",
        "description": "Configurar la IP real asignada al controlador en el laboratorio"
    }
]

_socketio_instance: SocketIO = None
_joint_sync_callback = None

def register_ide_socketio(sio: SocketIO):
    global _socketio_instance
    _socketio_instance = sio

def register_joint_sync_callback(cb):
    global _joint_sync_callback
    _joint_sync_callback = cb

shared_robot_client = RobotClient(host="127.0.0.1", port=5001, mode="SIMULATED")

def get_shared_robot_client() -> RobotClient:
    return shared_robot_client

def _notify_joints_if_present(res: dict):
    if _joint_sync_callback is None or not isinstance(res, dict) or not res.get("success"):
        return
    data = res.get("data")
    if isinstance(data, dict) and isinstance(data.get("joints"), list) and len(data["joints"]) == 6:
        try:
            _joint_sync_callback([float(x) for x in data["joints"]])
        except Exception:
            pass

class ClientSession:
    def __init__(self, client_id: str):
        self.client_id = client_id
        if client_id == "default":
            self.workspace_root = BASE_WORKSPACE
        else:
            self.workspace_root = os.path.join(BASE_WORKSPACE, "users", client_id)
            self._seed_workspace()

        self.workspace_mgr = WorkspaceManager(self.workspace_root)
        self.runner = ScriptRunner(self.workspace_root)
        self.completion_svc = CompletionService(self.workspace_root)
        self.virtual_io_mgr = VirtualIOManager(os.path.join(self.workspace_root, "virtual_io.json"))
        self.profiles_file = os.path.join(self.workspace_root, "connection_profiles.json")
        self.traffic_logs = []

    @property
    def active_robot_client(self) -> RobotClient:
        return shared_robot_client

    @active_robot_client.setter
    def active_robot_client(self, client: RobotClient):
        global shared_robot_client
        shared_robot_client = client

    def _seed_workspace(self):
        if os.path.exists(self.workspace_root):
            return
        os.makedirs(self.workspace_root, exist_ok=True)
        for name in os.listdir(BASE_WORKSPACE):
            src = os.path.join(BASE_WORKSPACE, name)
            if os.path.isfile(src) and (name.endswith(".py") or name.endswith(".json")):
                shutil.copy2(src, os.path.join(self.workspace_root, name))

    def log_traffic(self, direction: str, payload: dict, latency_ms: float = None):
        entry = {
            "timestamp": time.strftime("%H:%M:%S"),
            "direction": direction,
            "payload": payload,
            "latency_ms": latency_ms
        }
        self.traffic_logs.append(entry)
        if len(self.traffic_logs) > 100:
            self.traffic_logs.pop(0)

    def load_connection_profiles(self):
        if os.path.isfile(self.profiles_file):
            try:
                with open(self.profiles_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "profiles" in data:
                    return data
            except Exception:
                pass
        initial_data = {
            "active_profile": "virtual_local",
            "profiles": DEFAULT_PROFILES
        }
        self.save_connection_profiles(initial_data)
        return initial_data

    def save_connection_profiles(self, data: dict):
        os.makedirs(os.path.dirname(self.profiles_file), exist_ok=True)
        with open(self.profiles_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

_sessions = {}
_sessions_lock = threading.Lock()

def get_current_session() -> ClientSession:
    client_id = request.headers.get("X-Client-ID", "").strip()
    if not client_id or not re.match(r"^[a-zA-Z0-9_-]{4,64}$", client_id):
        client_id = "default"
    with _sessions_lock:
        if client_id not in _sessions:
            _sessions[client_id] = ClientSession(client_id)
        return _sessions[client_id]

default_session = ClientSession("default")
_sessions["default"] = default_session

workspace_mgr = default_session.workspace_mgr
runner = default_session.runner
completion_svc = default_session.completion_svc
virtual_io_mgr = default_session.virtual_io_mgr
active_robot_client = default_session.active_robot_client
mock_server = IRC5MockServer(host="127.0.0.1", port=5001, virtual_io_manager=virtual_io_mgr)

def emit_output(stream_type: str, text: str, client_id: str = "default"):
    if _socketio_instance is not None:
        _socketio_instance.emit("python_output", {
            "type": stream_type,
            "text": text,
            "timestamp": time.time(),
            "client_id": client_id
        })
        sess = _sessions.get(client_id, default_session)
        _socketio_instance.emit("python_status", {
            **sess.runner.get_status(),
            "client_id": client_id
        })

def notify_virtual_io_change(session: ClientSession):
    if _socketio_instance is not None:
        _socketio_instance.emit("virtual_io_updated", {
            "signals": session.virtual_io_mgr.list_signals(),
            "timestamp": time.time(),
            "client_id": session.client_id
        })
    session.active_robot_client.sync_validator_signals(
        session.virtual_io_mgr.get_allowed_di(),
        session.virtual_io_mgr.get_allowed_do()
    )

@ide_bp.route("/api/ide/files", methods=["GET"])
def list_files():
    session = get_current_session()
    try:
        files = session.workspace_mgr.list_files()
        return jsonify({"success": True, "files": files})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@ide_bp.route("/api/ide/file/read", methods=["POST"])
def read_file():
    session = get_current_session()
    data = request.get_json() or {}
    rel_path = data.get("path")
    if not rel_path:
        return jsonify({"success": False, "error": "Falta parametro 'path'"}), 400
    try:
        content = session.workspace_mgr.read_file(rel_path)
        return jsonify({"success": True, "path": rel_path, "content": content})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@ide_bp.route("/api/ide/file/write", methods=["POST"])
def write_file():
    session = get_current_session()
    data = request.get_json() or {}
    rel_path = data.get("path")
    content = data.get("content", "")
    if not rel_path:
        return jsonify({"success": False, "error": "Falta parametro 'path'"}), 400
    try:
        session.workspace_mgr.write_file(rel_path, content)
        return jsonify({"success": True, "message": "Archivo guardado exitosamente."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@ide_bp.route("/api/ide/file/create", methods=["POST"])
def create_file():
    session = get_current_session()
    data = request.get_json() or {}
    rel_path = data.get("path")
    content = data.get("content", "")
    if not rel_path:
        return jsonify({"success": False, "error": "Falta parametro 'path'"}), 400
    try:
        session.workspace_mgr.create_file(rel_path, content)
        return jsonify({"success": True, "message": "Archivo creado."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@ide_bp.route("/api/ide/directory/create", methods=["POST"])
def create_directory():
    session = get_current_session()
    data = request.get_json() or {}
    rel_path = data.get("path")
    if not rel_path:
        return jsonify({"success": False, "error": "Falta parametro 'path'"}), 400
    try:
        session.workspace_mgr.create_directory(rel_path)
        return jsonify({"success": True, "message": "Carpeta creada."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@ide_bp.route("/api/ide/item/rename", methods=["POST"])
def rename_item():
    session = get_current_session()
    data = request.get_json() or {}
    old_path = data.get("old_path")
    new_path = data.get("new_path")
    if not old_path or not new_path:
        return jsonify({"success": False, "error": "Parametros insuficientes"}), 400
    try:
        session.workspace_mgr.rename_item(old_path, new_path)
        return jsonify({"success": True, "message": "Elemento renombrado."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@ide_bp.route("/api/ide/item/delete", methods=["POST"])
def delete_item():
    session = get_current_session()
    data = request.get_json() or {}
    rel_path = data.get("path")
    if not rel_path:
        return jsonify({"success": False, "error": "Falta parametro 'path'"}), 400
    try:
        session.workspace_mgr.delete_item(rel_path)
        return jsonify({"success": True, "message": "Elemento eliminado."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@ide_bp.route("/api/ide/script/run", methods=["POST"])
def run_script():
    session = get_current_session()
    data = request.get_json() or {}
    rel_path = data.get("path")
    timeout = float(data.get("timeout", 60.0))
    if not rel_path:
        return jsonify({"success": False, "error": "Falta parametro 'path'"}), 400

    cid = session.client_id
    def _cb(stream_type: str, text: str):
        emit_output(stream_type, text, client_id=cid)

    res = session.runner.run_script(rel_path, _cb, timeout_sec=timeout)
    if res.get("success"):
        return jsonify(res)
    return jsonify(res), 400

@ide_bp.route("/api/ide/script/stop", methods=["POST"])
def stop_script():
    session = get_current_session()
    data = request.get_json() or {}
    force = bool(data.get("force", False))
    res = session.runner.stop_script(force=force)
    return jsonify(res)

@ide_bp.route("/api/ide/script/status", methods=["GET"])
def get_script_status():
    session = get_current_session()
    return jsonify(session.runner.get_status())

@ide_bp.route("/api/ide/script/logs", methods=["GET"])
def get_script_logs():
    session = get_current_session()
    since = int(request.args.get("since", 0))
    return jsonify({
        "success": True,
        "logs": session.runner.get_logs(since=since),
        "status": session.runner.get_status()
    })

@ide_bp.route("/api/ide/autocomplete", methods=["POST"])
def autocomplete():
    session = get_current_session()
    data = request.get_json() or {}
    code = data.get("code", "")
    line = int(data.get("line", 1))
    col = int(data.get("column", 1))
    filename = data.get("filename", "main.py")
    suggestions = session.completion_svc.get_completions(code, line, col, filename)
    return jsonify({"success": True, "suggestions": suggestions})

@ide_bp.route("/api/ide/ai-complete", methods=["POST"])
def ai_complete():
    session = get_current_session()
    data = request.get_json() or {}
    prompt = data.get("prompt", "")
    suffix = data.get("suffix", "")
    completion = session.completion_svc.get_ai_completion(prompt, suffix)
    return jsonify({"success": True, "completion": completion})

@ide_bp.route("/api/connection/status", methods=["GET"])
def connection_status():
    session = get_current_session()
    client = session.active_robot_client
    return jsonify({
        "success": True,
        "is_connected": client.is_connected(),
        "host": client.host,
        "port": client.port,
        "mode": client.mode,
        "timeout": client.timeout,
        "latency_ms": client.last_latency_ms,
        "last_seen": client.last_seen,
        "mock_server_running": mock_server.is_running,
        "physical_armed": client.validator.physical_armed
    })

@ide_bp.route("/api/connection/arm", methods=["POST"])
def arm_physical_connection():
    session = get_current_session()
    data = request.get_json() or {}
    arm = bool(data.get("armed", False))
    if arm:
        session.active_robot_client.arm_physical_writes()
    else:
        session.active_robot_client.disarm_physical_writes()
    return jsonify({
        "success": True,
        "physical_armed": session.active_robot_client.validator.physical_armed
    })

@ide_bp.route("/api/connection/connect", methods=["POST"])
def connect_robot():
    session = get_current_session()
    data = request.get_json() or {}
    host = data.get("host", session.active_robot_client.host)
    port = int(data.get("port", session.active_robot_client.port))
    timeout = float(data.get("timeout", session.active_robot_client.timeout))
    mode = data.get("mode", session.active_robot_client.mode)

    if session.active_robot_client.is_connected():
        session.active_robot_client.disconnect()

    session.active_robot_client = RobotClient(host=host, port=port, timeout=timeout, mode=mode, allow_loopback=True)
    session.active_robot_client.sync_validator_signals(
        session.virtual_io_mgr.get_allowed_di(),
        session.virtual_io_mgr.get_allowed_do()
    )
    res = session.active_robot_client.connect()
    session.log_traffic("OUT", {"cmd": "CONNECT", "host": host, "port": port})
    session.log_traffic("IN", res)
    if res.get("success"):
        try:
            j_res = session.active_robot_client.get_joints()
            _notify_joints_if_present(j_res)
        except Exception:
            pass
    return jsonify(res)

@ide_bp.route("/api/connection/disconnect", methods=["POST"])
def disconnect_robot():
    session = get_current_session()
    res = session.active_robot_client.disconnect()
    session.log_traffic("OUT", {"cmd": "DISCONNECT"})
    session.log_traffic("IN", res)
    return jsonify(res)

@ide_bp.route("/api/connection/ping", methods=["POST"])
def ping_robot():
    session = get_current_session()
    if not session.active_robot_client.is_connected():
        return jsonify({"success": False, "error": "No conectado al controlador"}), 400
    try:
        session.log_traffic("OUT", {"cmd": "PING"})
        res = session.active_robot_client.ping()
        session.log_traffic("IN", res, latency_ms=res.get("latency_ms"))
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@ide_bp.route("/api/connection/command", methods=["POST"])
def execute_command():
    session = get_current_session()
    if not session.active_robot_client.is_connected():
        return jsonify({"success": False, "error": "No conectado al controlador"}), 400

    data = request.get_json() or {}
    cmd = data.get("cmd", "").upper()
    name = data.get("name", "")
    val = data.get("value")
    physical_confirmed = bool(data.get("physical_confirmed", False))

    session.log_traffic("OUT", data)
    try:
        if cmd == "PING":
            res = session.active_robot_client.ping()
        elif cmd == "GET_STATUS":
            res = session.active_robot_client.get_status()
        elif cmd == "GET_DI":
            res = session.active_robot_client.get_di(name)
        elif cmd == "GET_DO":
            res = session.active_robot_client.get_do(name)
        elif cmd == "SET_DO":
            res = session.active_robot_client.set_do(name, val, physical_confirmed=physical_confirmed)
            if res.get("success"):
                notify_virtual_io_change(session)
        elif cmd == "GET_VARIABLE":
            res = session.active_robot_client.get_variable(name)
        elif cmd == "GET_JOINTS":
            res = session.active_robot_client.get_joints()
        elif cmd == "MOVE_JOINTS":
            joints = data.get("joints") if data.get("joints") is not None else data.get("params", {}).get("joints")
            speed = float(data.get("speed") or data.get("params", {}).get("speed", 50.0))
            res = session.active_robot_client.move_joints(joints, speed=speed, physical_confirmed=physical_confirmed)
        elif cmd == "MOVE_PRESET":
            target = data.get("target") or data.get("name") or data.get("params", {}).get("target", "HOME")
            speed = float(data.get("speed") or data.get("params", {}).get("speed", 50.0))
            res = session.active_robot_client.move_preset(target, speed=speed, physical_confirmed=physical_confirmed)
            if res.get("success") and _joint_sync_callback is not None:
                preset_q = session.active_robot_client.validator.AUTHORIZED_PRESETS.get(str(target).upper())
                if preset_q:
                    _joint_sync_callback(list(preset_q))
        else:
            return jsonify({"success": False, "error": f"Comando no reconocido: {cmd}"}), 400

        _notify_joints_if_present(res)
        session.log_traffic("IN", res, latency_ms=res.get("latency_ms"))
        return jsonify(res)

    except SafetyValidationError as sve:
        err_res = {"success": False, "error": f"Seguridad: {str(sve)}"}
        session.log_traffic("IN", err_res)
        return jsonify(err_res), 403
    except Exception as e:
        err_res = {"success": False, "error": str(e)}
        session.log_traffic("IN", err_res)
        return jsonify(err_res), 500

@ide_bp.route("/api/connection/mock_server/start", methods=["POST"])
def start_mock_server():
    try:
        mock_server.start()
        return jsonify({"success": True, "message": f"Servidor simulado iniciado en {mock_server.host}:{mock_server.port}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@ide_bp.route("/api/connection/mock_server/stop", methods=["POST"])
def stop_mock_server():
    try:
        mock_server.stop()
        return jsonify({"success": True, "message": "Servidor simulado detenido."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@ide_bp.route("/api/connection/traffic", methods=["GET"])
def get_traffic():
    session = get_current_session()
    return jsonify({"success": True, "logs": session.traffic_logs})

@ide_bp.route("/api/connection/profiles", methods=["GET"])
def get_profiles():
    session = get_current_session()
    try:
        data = session.load_connection_profiles()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@ide_bp.route("/api/connection/profiles/save", methods=["POST"])
def save_profile():
    session = get_current_session()
    data = request.get_json() or {}
    profile = data.get("profile")
    if not profile or not isinstance(profile, dict) or "id" not in profile:
        return jsonify({"success": False, "error": "Datos de perfil invalidos"}), 400

    profiles_data = session.load_connection_profiles()
    existing = False
    for i, p in enumerate(profiles_data["profiles"]):
        if p["id"] == profile["id"]:
            profiles_data["profiles"][i] = profile
            existing = True
            break
    if not existing:
        profiles_data["profiles"].append(profile)

    session.save_connection_profiles(profiles_data)
    return jsonify({"success": True, "message": "Perfil guardado correctamente", **profiles_data})

@ide_bp.route("/api/connection/profiles/select", methods=["POST"])
def select_profile():
    session = get_current_session()
    data = request.get_json() or {}
    profile_id = data.get("profile_id")
    profiles_data = session.load_connection_profiles()

    selected = next((p for p in profiles_data["profiles"] if p["id"] == profile_id), None)
    if not selected:
        return jsonify({"success": False, "error": f"Perfil '{profile_id}' no encontrado"}), 404

    profiles_data["active_profile"] = profile_id
    session.save_connection_profiles(profiles_data)
    return jsonify({"success": True, "profile": selected})

@ide_bp.route("/api/virtual_io/signals", methods=["GET"])
def list_virtual_signals():
    session = get_current_session()
    signal_type = request.args.get("type")
    signals = session.virtual_io_mgr.list_signals(signal_type=signal_type)
    return jsonify({"success": True, "signals": signals})

@ide_bp.route("/api/virtual_io/signal/create", methods=["POST"])
def create_virtual_signal():
    session = get_current_session()
    data = request.get_json() or {}
    name = data.get("name")
    stype = data.get("type", "DI")
    init_val = data.get("value", 0)
    desc = data.get("description", "")

    if not name:
        return jsonify({"success": False, "error": "El nombre de la senal es obligatorio"}), 400

    try:
        created = session.virtual_io_mgr.create_signal(name, stype, initial_value=init_val, description=desc)
        notify_virtual_io_change(session)
        return jsonify({"success": True, "signal": created})
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@ide_bp.route("/api/virtual_io/signal/update", methods=["POST"])
def update_virtual_signal():
    session = get_current_session()
    data = request.get_json() or {}
    name = data.get("name")
    val = data.get("value")

    if not name or val is None:
        return jsonify({"success": False, "error": "Parametros insuficientes ('name', 'value')"}), 400

    try:
        updated = session.virtual_io_mgr.update_signal_value(name, val)
        notify_virtual_io_change(session)
        return jsonify({"success": True, "signal": updated})
    except KeyError:
        return jsonify({"success": False, "error": f"Senal '{name}' no encontrada"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@ide_bp.route("/api/virtual_io/signal/delete", methods=["POST"])
def delete_virtual_signal():
    session = get_current_session()
    data = request.get_json() or {}
    name = data.get("name")
    if not name:
        return jsonify({"success": False, "error": "Falta parametro 'name'"}), 400

    try:
        session.virtual_io_mgr.delete_signal(name)
        notify_virtual_io_change(session)
        return jsonify({"success": True, "message": f"Senal '{name}' eliminada"})
    except KeyError:
        return jsonify({"success": False, "error": f"Senal '{name}' no encontrada"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@ide_bp.route("/api/virtual_io/reset", methods=["POST"])
def reset_virtual_signals():
    session = get_current_session()
    try:
        signals = session.virtual_io_mgr.reset_defaults()
        notify_virtual_io_change(session)
        return jsonify({"success": True, "signals": signals})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@ide_bp.route("/api/virtual_io/export/eio_cfg", methods=["GET"])
def export_eio_cfg():
    session = get_current_session()
    try:
        content = session.virtual_io_mgr.generate_eio_cfg()
        return jsonify({"success": True, "content": content, "filename": "EIO.cfg"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
