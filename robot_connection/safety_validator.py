import math
import re
from typing import Tuple, Dict, Any, Set, Optional, List

class SafetyValidationError(Exception):
    pass

class SafetyValidator:
    SIGNAL_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,31}$")
    
    LIMITES_IRB140 = [
        (-180.0, 180.0),
        (-90.0, 110.0),
        (-52.0, 50.0),
        (-200.0, 200.0),
        (-115.0, 115.0),
        (-400.0, 400.0)
    ]

    ENVOLVENTE_TEST_FISICO = [
        (-90.0, 90.0),
        (-45.0, 45.0),
        (-35.0, 35.0),
        (-90.0, 90.0),
        (-60.0, 60.0),
        (-90.0, 90.0)
    ]

    VELOCIDAD_MAX_TEST = 100.0

    AUTHORIZED_PRESETS: Dict[str, List[float]] = {
        "HOME": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "TEST_DELTA_J1": [10.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "TEST_SAFE_1": [0.0, 15.0, -15.0, 0.0, 30.0, 0.0]
    }
    
    DEFAULT_ALLOWED_DI: Set[str] = {
        "di_pieza_presente",
        "di_ciclo_inicio",
        "di_parada_celda",
        "di_robot_listo",
        "di_pinza_abierta",
        "di_pinza_cerrada",
        "di1", "di2", "di3", "di4", "di5", "di6", "di7", "di8"
    }

    DEFAULT_ALLOWED_DO: Set[str] = {
        "do_valvula_aire",
        "do_pinza_actuar",
        "do_indicador_verde",
        "do_indicador_rojo",
        "do_indicador_amarillo",
        "do1", "do2", "do3", "do4", "do5", "do6", "do7", "do8"
    }

    BLOCKED_SIGNALS: Set[str] = {
        "safety_guard",
        "emergencia",
        "es_active",
        "es_override",
        "brake_release",
        "safety_override"
    }

    def __init__(
        self,
        mode: str = "SIMULATED",
        allowed_di: Set[str] = None,
        allowed_do: Set[str] = None
    ):
        self.mode = mode.upper()
        self.allowed_di = allowed_di if allowed_di is not None else set(self.DEFAULT_ALLOWED_DI)
        self.allowed_do = allowed_do if allowed_do is not None else set(self.DEFAULT_ALLOWED_DO)
        self.physical_armed: bool = False

    def arm_physical_mode(self) -> None:
        self.physical_armed = True

    def disarm_physical_mode(self) -> None:
        self.physical_armed = False

    def validate_connection_target(self, host: str, allow_loopback: bool = True) -> None:
        h = host.strip().lower()
        if h in ("0.0.0.0", "pendiente_configurar_lab", ""):
            raise SafetyValidationError("Direccion IP no configurada: defina la direccion IP real del controlador asignada en el laboratorio.")

        is_loopback = h in ("127.0.0.1", "localhost", "::1")
        if self.mode == "SIMULATED" and not is_loopback:
            raise SafetyValidationError(f"Seguridad: modo SIMULATED no puede conectar a la IP remota '{host}'. Utilice CONNECTED_PHYSICAL para hardware real.")
        if self.mode == "CONNECTED_PHYSICAL" and is_loopback and not allow_loopback:
            raise SafetyValidationError("Seguridad: modo CONNECTED_PHYSICAL requiere allow_loopback para conectar a localhost.")

    def set_mode(self, mode: str) -> None:
        valid_modes = {"SIMULATED", "CONNECTED_PHYSICAL", "DEVELOPMENT"}
        m = mode.upper()
        if m not in valid_modes:
            raise SafetyValidationError(f"Modo no valido: {mode}. Permitidos: {valid_modes}")
        self.mode = m

    def update_allowed_signals(self, allowed_di: Optional[Set[str]] = None, allowed_do: Optional[Set[str]] = None) -> None:
        if allowed_di is not None:
            self.allowed_di = set(allowed_di)
        if allowed_do is not None:
            self.allowed_do = set(allowed_do)

    def validate_signal_name(self, name: str) -> None:
        if not name or not isinstance(name, str):
            raise SafetyValidationError("El nombre de la senal debe ser una cadena no vacia")
        if not self.SIGNAL_PATTERN.match(name):
            raise SafetyValidationError(f"Nombre de senal invalido '{name}': solo caracteres alfanumericos y guion bajo (max 32)")
        if name.lower() in self.BLOCKED_SIGNALS:
            raise SafetyValidationError(f"Acceso denegado: '{name}' es una senal critica protegida del sistema")

    def validate_read_di(self, name: str) -> None:
        self.validate_signal_name(name)
        if name not in self.allowed_di:
            raise SafetyValidationError(f"Senal de entrada '{name}' no configurada en la lista autorizada")

    def validate_read_do(self, name: str) -> None:
        self.validate_signal_name(name)
        if name not in self.allowed_do:
            raise SafetyValidationError(f"Senal de salida '{name}' no configurada en la lista autorizada")

    def validate_write_do(self, name: str, value: Any, physical_confirmed: bool = False) -> int:
        self.validate_signal_name(name)
        if name not in self.allowed_do:
            raise SafetyValidationError(f"Escritura rechazada: '{name}' no esta en la lista blanca de salidas autorizadas")

        try:
            val_int = int(value)
        except (ValueError, TypeError):
            raise SafetyValidationError(f"Valor de senal digital invalido '{value}': debe ser 0 o 1")

        if val_int not in (0, 1):
            raise SafetyValidationError(f"Valor digital fuera de rango ({val_int}): solo se admite 0 (desactivado) o 1 (activado)")

        if self.mode == "CONNECTED_PHYSICAL":
            if not self.physical_armed:
                raise SafetyValidationError("Escritura física rechazada: el modo físico no está armado por el operador en el panel de seguridad")
            if not physical_confirmed:
                raise SafetyValidationError("Accion en hardware real denegada: requiere confirmacion explicita de seguridad")

        return val_int

    def validate_motion_command(self, cmd: str, params: Dict[str, Any], physical_confirmed: bool = False) -> Dict[str, Any]:
        cmd_upper = cmd.upper()
        if cmd_upper not in ("MOVE_JOINTS", "MOVE_PRESET"):
            raise SafetyValidationError(f"Comando de movimiento no reconocido: '{cmd}'")

        if self.mode == "CONNECTED_PHYSICAL":
            if not self.physical_armed:
                raise SafetyValidationError("Movimiento físico bloqueado: el canal físico no está armado en el panel de seguridad")
            if not physical_confirmed:
                raise SafetyValidationError("Movimiento físico rechazado: requiere confirmación explícita del operador")

        speed = params.get("speed", 50.0)
        try:
            speed_val = float(speed)
        except (ValueError, TypeError):
            raise SafetyValidationError(f"Velocidad inválida: {speed}")

        if not math.isfinite(speed_val) or speed_val <= 0:
            raise SafetyValidationError(f"Velocidad fuera de rango: {speed_val}")

        if self.mode == "CONNECTED_PHYSICAL" and speed_val > self.VELOCIDAD_MAX_TEST:
            raise SafetyValidationError(f"Velocidad ({speed_val}) excede límite de prueba segura ({self.VELOCIDAD_MAX_TEST} mm/s en modo manual T1)")

        if cmd_upper == "MOVE_PRESET":
            target = str(params.get("target", "")).upper()
            if target not in self.AUTHORIZED_PRESETS:
                raise SafetyValidationError(f"Objetivo predefinido no autorizado: '{target}'. Permitidos: {list(self.AUTHORIZED_PRESETS.keys())}")
            return {"target": target, "joints": list(self.AUTHORIZED_PRESETS[target]), "speed": speed_val}

        joints = params.get("joints")
        if not isinstance(joints, (list, tuple)) or len(joints) != 6:
            raise SafetyValidationError(f"Se requieren exactamente 6 ángulos articulares. Recibidos: {joints}")

        q_clean = []
        for i, val in enumerate(joints):
            try:
                q_i = float(val)
            except (ValueError, TypeError):
                raise SafetyValidationError(f"Eje {i+1}: valor no numérico '{val}'")
            if not math.isfinite(q_i):
                raise SafetyValidationError(f"Eje {i+1}: valor no finito ({q_i})")

            lim_min, lim_max = self.LIMITES_IRB140[i]
            if q_i < lim_min or q_i > lim_max:
                raise SafetyValidationError(f"Eje {i+1}: {q_i}° excede límites del robot [{lim_min}°, {lim_max}°]")

            if self.mode == "CONNECTED_PHYSICAL":
                t_min, t_max = self.ENVOLVENTE_TEST_FISICO[i]
                if q_i < t_min or q_i > t_max:
                    raise SafetyValidationError(f"Eje {i+1}: {q_i}° excede envolvente segura de laboratorio [{t_min}°, {t_max}°]")

            q_clean.append(round(q_i, 2))

        return {"joints": q_clean, "speed": speed_val}
