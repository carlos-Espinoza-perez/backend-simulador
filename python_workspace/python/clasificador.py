import math
import cv2
import numpy as np
from typing import Dict, Any, List, Optional, Tuple

PRIORIDAD_MATERIAL = {
    "ALUMINIO": 1,
    "PET": 2,
    "CARTON": 3,
    "DESCONOCIDO": 9,
}

DESTINOS_DEPOSITO = {
    "PET": {
        "preset": "HOME",
        "offset_descarga": (460.0, -185.0, 145.0),
        "centro_mesa_mm": (40.0, 150.0),
        "paso_grid_mm": (32.0, 32.0),
        "color_bgr": (128, 222, 74),
    },
    "ALUMINIO": {
        "preset": "TEST_SAFE_1",
        "offset_descarga": (460.0, 185.0, 145.0),
        "centro_mesa_mm": (360.0, 150.0),
        "paso_grid_mm": (32.0, 32.0),
        "color_bgr": (21, 204, 250),
    },
    "CARTON": {
        "preset": "TEST_DELTA_J1",
        "offset_descarga": (540.0, 0.0, 145.0),
        "centro_mesa_mm": (200.0, 295.0),
        "paso_grid_mm": (38.0, 34.0),
        "color_bgr": (60, 140, 230),
    },
}


def _identificar_color_hsv(h: float, s: float, v: float) -> str:
    if s < 38.0:
        return "GRIS" if v < 185.0 else "CLARO"
    if h < 8.0 or h >= 168.0:
        return "ROJO"
    if 8.0 <= h < 24.0:
        return "MARRON" if v < 195.0 else "AMARILLO"
    if 24.0 <= h < 36.0:
        return "AMARILLO"
    if 36.0 <= h < 88.0:
        return "VERDE"
    if 88.0 <= h < 138.0:
        return "AZUL"
    return "ROJO"


def _clasificar_forma(geometria: Optional[Dict[str, float]]) -> Tuple[str, str]:
    if not geometria:
        return "IRREGULAR", "MEDIANO"

    circ = float(geometria.get("circularidad", 0.0))
    ar = float(geometria.get("relacion_aspecto", 1.0))
    area_mm2 = float(geometria.get("area_mm2", 900.0))

    if circ >= 0.78 and ar <= 1.28:
        forma = "CIRCULAR"
    elif ar >= 1.35:
        forma = "RECTANGULAR"
    else:
        forma = "CUADRADA"

    if area_mm2 < 650.0:
        tamano = "PEQUENO"
    elif area_mm2 <= 1850.0:
        tamano = "MEDIANO"
    else:
        tamano = "GRANDE"

    return forma, tamano


def clasificar_material(
    crop: np.ndarray,
    sensor_inductivo: Optional[int] = None,
    sensor_capacitivo: Optional[int] = None,
    mascara: Optional[np.ndarray] = None,
    geometria: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    if crop is None or crop.size == 0:
        return {
            "material": "DESCONOCIDO",
            "color": "DESCONOCIDO",
            "forma": "IRREGULAR",
            "tamano": "MEDIANO",
            "prioridad": PRIORIDAD_MATERIAL["DESCONOCIDO"],
            "confianza": 0.0,
        }

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    if mascara is not None and mascara.shape[:2] == crop.shape[:2] and np.count_nonzero(mascara) > 16:
        pix_h = hsv[:, :, 0][mascara > 0]
        pix_s = hsv[:, :, 1][mascara > 0]
        pix_v = hsv[:, :, 2][mascara > 0]
    else:
        alto, ancho = hsv.shape[:2]
        my, mx = max(1, alto // 6), max(1, ancho // 6)
        roi = hsv[my:alto - my, mx:ancho - mx] if (alto > 6 and ancho > 6) else hsv
        pix_h = roi[:, :, 0].ravel()
        pix_s = roi[:, :, 1].ravel()
        pix_v = roi[:, :, 2].ravel()

    media_h = float(np.mean(pix_h))
    media_s = float(np.mean(pix_s))
    media_v = float(np.mean(pix_v))
    std_v = float(np.std(pix_v))

    color = _identificar_color_hsv(media_h, media_s, media_v)
    forma, tamano = _clasificar_forma(geometria)
    metricas = {
        "h": round(media_h, 1),
        "s": round(media_s, 1),
        "v": round(media_v, 1),
        "std_v": round(std_v, 1),
    }

    if sensor_inductivo == 1:
        return {
            "material": "ALUMINIO",
            "color": "GRIS",
            "forma": forma,
            "tamano": tamano,
            "prioridad": PRIORIDAD_MATERIAL["ALUMINIO"],
            "confianza": 0.99,
            "metodo": "sensor_inductivo",
            "metricas": metricas,
        }

    if sensor_capacitivo == 1 and sensor_inductivo != 1:
        mat_cap = "CARTON" if (8.0 <= media_h <= 30.0 and 42.0 <= media_s <= 185.0) else "PET"
        return {
            "material": mat_cap,
            "color": color,
            "forma": forma,
            "tamano": tamano,
            "prioridad": PRIORIDAD_MATERIAL[mat_cap],
            "confianza": 0.96,
            "metodo": "sensor_capacitivo",
            "metricas": metricas,
        }

    if 8.0 <= media_h <= 30.0 and 42.0 <= media_s <= 185.0:
        conf = 0.91 if forma in ("RECTANGULAR", "CUADRADA") else 0.86
        return {
            "material": "CARTON",
            "color": "MARRON" if color == "AMARILLO" else color,
            "forma": forma,
            "tamano": tamano,
            "prioridad": PRIORIDAD_MATERIAL["CARTON"],
            "confianza": conf,
            "metodo": "hsv_geometria",
            "metricas": metricas,
        }

    if media_s < 42.0 and media_v > 85.0:
        conf = 0.90 if std_v >= 12.0 or forma == "CIRCULAR" else 0.85
        return {
            "material": "ALUMINIO",
            "color": "GRIS",
            "forma": forma,
            "tamano": tamano,
            "prioridad": PRIORIDAD_MATERIAL["ALUMINIO"],
            "confianza": conf,
            "metodo": "reflectancia_hsv",
            "metricas": metricas,
        }

    conf_pet = 0.89 if media_s >= 65.0 else 0.82
    return {
        "material": "PET",
        "color": color,
        "forma": forma,
        "tamano": tamano,
        "prioridad": PRIORIDAD_MATERIAL["PET"],
        "confianza": conf_pet,
        "metodo": "cromatico_hsv",
        "metricas": metricas,
    }


def obtener_punto_deposito(material: str, indice: int = 0) -> Dict[str, Any]:
    mat = (material or "PET").upper()
    cfg = DESTINOS_DEPOSITO.get(mat, DESTINOS_DEPOSITO["PET"])
    bx, by, bz = cfg["offset_descarga"]
    mx, my = cfg["centro_mesa_mm"]
    dx, dy = cfg["paso_grid_mm"]

    fila = indice // 2
    col = indice % 2
    offset_x = (fila - 1) * dx
    offset_y = (col - 0.5) * dy

    return {
        "material": mat,
        "preset": cfg["preset"],
        "indice_slot": indice,
        "posicion_robot_mm": (round(bx + offset_x, 2), round(by + offset_y, 2), round(bz, 2)),
        "z_aproximacion_mm": round(bz + 75.0, 2),
        "posicion_mesa_mm": (round(mx + offset_y, 2), round(my + offset_x, 2)),
    }


def ordenar_piezas(
    piezas: List[Dict[str, Any]],
    criterio: str = "proximidad",
    ref_xy: Tuple[float, float] = (450.0, 0.0),
) -> List[Dict[str, Any]]:
    if not piezas:
        return []

    modo = (criterio or "proximidad").strip().lower()
    rx, ry = float(ref_xy[0]), float(ref_xy[1])

    def _dist(p: Dict[str, Any]) -> float:
        pos = p.get("posicion_mm", (0.0, 0.0))
        return math.hypot(float(pos[0]) - rx, float(pos[1]) - ry)

    if modo == "material":
        clave = lambda p: (
            PRIORIDAD_MATERIAL.get(p.get("material", "PET"), 9),
            _dist(p),
        )
    elif modo == "tamano":
        clave = lambda p: (
            -float(p.get("area_mm2", p.get("area_px", 0.0))),
            _dist(p),
        )
    elif modo in ("barrido_xy", "camara"):
        clave = lambda p: (
            round(float(p.get("posicion_mesa_mm", p.get("posicion_mm", (0.0, 0.0)))[1]) / 25.0),
            float(p.get("posicion_mesa_mm", p.get("posicion_mm", (0.0, 0.0)))[0]),
        )
    elif modo == "color":
        clave = lambda p: (str(p.get("color", "Z")), _dist(p))
    else:
        clave = _dist

    ordenadas = sorted(piezas, key=clave)
    conteo_por_material: Dict[str, int] = {}

    for idx, pieza in enumerate(ordenadas, start=1):
        mat = pieza.get("material", "PET")
        slot = conteo_por_material.get(mat, 0)
        conteo_por_material[mat] = slot + 1
        pieza["orden"] = idx
        pieza["distancia_robot_mm"] = round(_dist(pieza), 1)
        pieza["destino"] = obtener_punto_deposito(mat, slot)

    return ordenadas
