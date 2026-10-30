import json
from typing import Dict, Any, Optional, Tuple, List

class ProtocolError(Exception):
    pass

class IRC5Message:
    def __init__(
        self,
        msg_id: int,
        cmd: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        data: Optional[Any] = None,
        error: Optional[str] = None
    ):
        self.msg_id = msg_id
        self.cmd = cmd
        self.params = params or {}
        self.status = status
        self.data = data
        self.error = error

    def is_request(self) -> bool:
        return self.cmd is not None

    def is_response(self) -> bool:
        return self.status is not None

    def to_dict(self) -> Dict[str, Any]:
        if self.is_request():
            return {
                "id": self.msg_id,
                "cmd": self.cmd,
                "params": self.params
            }
        return {
            "id": self.msg_id,
            "status": self.status,
            "data": self.data,
            "error": self.error
        }

    def serialize(self) -> bytes:
        payload = json.dumps(self.to_dict(), separators=(',', ':'))
        return f"{payload}\n".encode("utf-8")

    @classmethod
    def from_raw(cls, raw_str: str) -> "IRC5Message":
        raw_str = raw_str.strip()
        if not raw_str:
            raise ProtocolError("Mensaje vacio recibido")
        try:
            data = json.loads(raw_str)
        except json.JSONDecodeError as e:
            raise ProtocolError(f"Formato JSON invalido: {e.msg} en '{raw_str}'")

        if not isinstance(data, dict):
            raise ProtocolError("El cuerpo del mensaje debe ser un objeto JSON")

        if "id" not in data:
            raise ProtocolError("El mensaje carece del campo obligatorio 'id'")

        msg_id = data["id"]
        if "cmd" in data:
            return cls(
                msg_id=msg_id,
                cmd=str(data["cmd"]).upper(),
                params=data.get("params", {})
            )
        elif "status" in data:
            return cls(
                msg_id=msg_id,
                status=str(data["status"]).upper(),
                data=data.get("data"),
                error=data.get("error")
            )
        else:
            raise ProtocolError("Mensaje no reconocido: falta 'cmd' o 'status'")

class IRC5Protocol:
    DELIMITER = b"\n"
    MAX_FRAME_SIZE = 4096
    SUPPORTED_COMMANDS = {
        "PING",
        "GET_STATUS",
        "GET_DI",
        "GET_DO",
        "SET_DO",
        "GET_VARIABLE",
        "GET_JOINTS",
        "MOVE_JOINTS",
        "MOVE_PRESET"
    }

    @staticmethod
    def build_request(msg_id: int, cmd: str, params: Optional[Dict[str, Any]] = None) -> bytes:
        cmd_upper = cmd.upper()
        if cmd_upper not in IRC5Protocol.SUPPORTED_COMMANDS:
            raise ProtocolError(f"Comando no soportado: {cmd}")
        msg = IRC5Message(msg_id=msg_id, cmd=cmd_upper, params=params or {})
        return msg.serialize()

    @staticmethod
    def build_response(msg_id: int, status: str, data: Any = None, error: Optional[str] = None) -> bytes:
        msg = IRC5Message(msg_id=msg_id, status=status.upper(), data=data, error=error)
        return msg.serialize()

    @staticmethod
    def extract_messages_from_buffer(buffer: bytes) -> Tuple[List["IRC5Message"], bytes]:
        messages = []
        while IRC5Protocol.DELIMITER in buffer:
            line, buffer = buffer.split(IRC5Protocol.DELIMITER, 1)
            line = line.strip(b"\r")
            if not line:
                continue
            try:
                decoded = line.decode("utf-8")
                msg = IRC5Message.from_raw(decoded)
                messages.append(msg)
            except UnicodeDecodeError:
                raise ProtocolError("Fallo de decodificacion UTF-8 en trama")

        if len(buffer) > IRC5Protocol.MAX_FRAME_SIZE:
            raise ProtocolError("Desbordamiento de buffer sin delimitador")

        return messages, buffer
