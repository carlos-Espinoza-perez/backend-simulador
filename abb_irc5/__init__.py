"""Biblioteca cliente de conexion con ABB IRC5 mediante sockets TCP y protocolo RobotWare 6."""
from .client import RobotClient, IRC5ClientError

__all__ = ["RobotClient", "IRC5ClientError"]
