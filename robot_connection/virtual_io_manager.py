import os
import json
import re
import threading
from typing import Dict, List, Any, Optional, Set

SIGNAL_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,31}$")

BLOCKED_SYSTEM_SIGNALS = {
    "safety_guard",
    "emergencia",
    "es_active",
    "es_override",
    "brake_release",
    "safety_override"
}

DEFAULT_SIGNALS = [
    {"name": "di_pieza_presente", "type": "DI", "value": 1, "description": "Sensor de pieza en mesa de trabajo"},
    {"name": "di_ciclo_inicio", "type": "DI", "value": 0, "description": "Pulsador de inicio de ciclo"},
    {"name": "di_parada_celda", "type": "DI", "value": 0, "description": "Entrada de paro de ciclo"},
    {"name": "di_robot_listo", "type": "DI", "value": 1, "description": "Confirmacion de robot en posicion"},
    {"name": "di_pinza_abierta", "type": "DI", "value": 1, "description": "Fin de carrera pinza abierta"},
    {"name": "di_pinza_cerrada", "type": "DI", "value": 0, "description": "Fin de carrera pinza cerrada"},
    {"name": "do_valvula_aire", "type": "DO", "value": 0, "description": "Valvula de alimentacion neumatica"},
    {"name": "do_pinza_actuar", "type": "DO", "value": 0, "description": "Cilindro actuador de mordaza"},
    {"name": "do_indicador_verde", "type": "DO", "value": 1, "description": "Luz indicadora de ejecucion"},
    {"name": "do_indicador_rojo", "type": "DO", "value": 0, "description": "Luz indicadora de alarma"},
    {"name": "do_indicador_amarillo", "type": "DO", "value": 0, "description": "Luz indicadora de espera"}
]

class VirtualIOManager:
    def __init__(self, storage_path: Optional[str] = None):
        if storage_path is None:
            cwd_file = os.path.abspath("virtual_io.json")
            if os.path.isfile(cwd_file):
                self.storage_path = cwd_file
            else:
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                self.storage_path = os.path.join(base_dir, "python_workspace", "virtual_io.json")
        else:
            self.storage_path = os.path.abspath(storage_path)

        self._lock = threading.Lock()
        self.signals: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if os.path.isfile(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        self.signals[item["name"]] = item
                    return
            except Exception:
                pass
        self._populate_defaults()
        self._save()

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(list(self.signals.values()), f, indent=2, ensure_ascii=False)

    def _populate_defaults(self) -> None:
        self.signals = {}
        for s in DEFAULT_SIGNALS:
            self.signals[s["name"]] = {
                "name": s["name"],
                "type": s["type"],
                "value": int(s["value"]),
                "description": s.get("description", ""),
                "is_virtual": True
            }

    def list_signals(self, signal_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            res = list(self.signals.values())
            if signal_type:
                st = signal_type.upper()
                res = [s for s in res if s["type"] == st]
            return sorted(res, key=lambda x: (x["type"], x["name"]))

    def get_signal(self, name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.signals.get(name)

    def get_value(self, name: str) -> Optional[int]:
        with self._lock:
            s = self.signals.get(name)
            return s["value"] if s else None

    def create_signal(
        self,
        name: str,
        signal_type: str,
        initial_value: int = 0,
        description: str = ""
    ) -> Dict[str, Any]:
        cleaned_name = name.strip()
        st = signal_type.strip().upper()

        if not SIGNAL_NAME_PATTERN.match(cleaned_name):
            raise ValueError(f"Identificador invalido '{name}': solo letras, numeros y guion bajo (max 32)")

        if cleaned_name.lower() in BLOCKED_SYSTEM_SIGNALS:
            raise ValueError(f"Identificador reservado por seguridad: '{name}'")

        if st not in ("DI", "DO"):
            raise ValueError(f"Tipo de senal invalido: {signal_type}. Solo 'DI' o 'DO'")

        val = 1 if int(initial_value) > 0 else 0

        with self._lock:
            if cleaned_name in self.signals:
                raise ValueError(f"La senal '{cleaned_name}' ya existe")

            entry = {
                "name": cleaned_name,
                "type": st,
                "value": val,
                "description": description.strip(),
                "is_virtual": True
            }
            self.signals[cleaned_name] = entry
            self._save()
            return entry

    def update_signal_value(self, name: str, value: Any) -> Dict[str, Any]:
        if name.lower() in BLOCKED_SYSTEM_SIGNALS:
            raise ValueError(f"Acceso denegado: '{name}' es una senal critica protegida de seguridad")
        val = 1 if int(value) > 0 else 0
        with self._lock:
            if name not in self.signals:
                raise KeyError(f"Senal no encontrada: '{name}'")
            self.signals[name]["value"] = val
            self._save()
            return self.signals[name]

    def delete_signal(self, name: str) -> bool:
        if name.lower() in BLOCKED_SYSTEM_SIGNALS:
            raise ValueError(f"Acceso denegado: '{name}' es una senal critica protegida de seguridad")
        with self._lock:
            if name not in self.signals:
                raise KeyError(f"Senal no encontrada: '{name}'")
            del self.signals[name]
            self._save()
            return True

    def reset_defaults(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._populate_defaults()
            self._save()
            return list(self.signals.values())

    def get_allowed_di(self) -> Set[str]:
        with self._lock:
            return {name for name, s in self.signals.items() if s["type"] == "DI"}

    def get_allowed_do(self) -> Set[str]:
        with self._lock:
            return {name for name, s in self.signals.items() if s["type"] == "DO"}

    def generate_eio_cfg(self) -> str:
        with self._lock:
            lines = [
                "EIO:CFG_1.0:6:0::",
                "# Configuracion de E/S para RobotWare 6",
                "# Senales declaradas en BOARD10 para simulacion / gemelo digital.",
                "",
                "EIO_BUS:",
                "      -Name \"Virtual\" -BusType \"VIRTUAL\"",
                "",
                "EIO_UNIT:",
                "      -Name \"BOARD10\" -UnitType \"Virtual\" -Bus \"Virtual\"",
                "",
                "EIO_SIGNAL:"
            ]

            di_idx = 0
            do_idx = 0

            for name in sorted(self.signals.keys()):
                s = self.signals[name]
                st = s["type"]
                desc = s.get("description", "")
                if st == "DI":
                    lines.append(f'      -Name "{name}" -SignalType "DI" -Unit "BOARD10" -UnitMap "{di_idx}"')
                    di_idx += 1
                elif st == "DO":
                    lines.append(f'      -Name "{name}" -SignalType "DO" -Unit "BOARD10" -UnitMap "{do_idx}"')
                    do_idx += 1

            lines.extend([
                "",
                "# Plantilla borrador para hardware fisico (DSQC 652 en DeviceNet)",
                "# EIO_UNIT:",
                "#       -Name \"d652_cell\" -UnitType \"d652\" -Bus \"DeviceNet\" -DeviceNetAddress 10",
                "# EIO_SIGNAL:",
                "#       -Name \"di_real_pieza\" -SignalType \"DI\" -Unit \"d652_cell\" -UnitMap \"0\"",
                "#       -Name \"do_real_valvula\" -SignalType \"DO\" -Unit \"d652_cell\" -UnitMap \"0\"",
                ""
            ])
            return "\n".join(lines)
