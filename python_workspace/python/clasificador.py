import cv2
import numpy as np
from typing import Dict, Any, Optional

DESTINOS_DEPOSITO = {
    "PET": {"preset": "HOME", "offset_descarga": (450.0, -150.0, 180.0)},
    "ALUMINIO": {"preset": "TEST_SAFE_1", "offset_descarga": (450.0, 150.0, 180.0)},
    "CARTON": {"preset": "TEST_DELTA_J1", "offset_descarga": (500.0, 0.0, 180.0)}
}

def clasificar_material(crop: np.ndarray, sensor_inductivo: Optional[int] = None) -> Dict[str, Any]:
    if crop is None or crop.size == 0:
        return {"material": "DESCONOCIDO", "confianza": 0.0}

    if sensor_inductivo == 1:
        return {"material": "ALUMINIO", "confianza": 0.99, "metodo": "fusion_inductiva"}

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)

    media_h = float(np.mean(h))
    media_s = float(np.mean(s))
    media_v = float(np.mean(v))
    std_v = float(np.std(v))

    if 8.0 <= media_h <= 32.0 and 45.0 <= media_s <= 180.0:
        return {
            "material": "CARTON",
            "confianza": 0.88,
            "metricas": {"h": round(media_h, 1), "s": round(media_s, 1), "v": round(media_v, 1)}
        }

    if media_s < 40.0 and media_v > 90.0:
        return {
            "material": "ALUMINIO",
            "confianza": 0.85,
            "metricas": {"h": round(media_h, 1), "s": round(media_s, 1), "v": round(media_v, 1)}
        }

    return {
        "material": "PET",
        "confianza": 0.80,
        "metricas": {"h": round(media_h, 1), "s": round(media_s, 1), "v": round(media_v, 1), "std_v": round(std_v, 1)}
    }
