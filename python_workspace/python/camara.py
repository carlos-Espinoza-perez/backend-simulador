import json
import os
import time
import urllib.request
import cv2
import numpy as np

BASE_URL = f"http://127.0.0.1:{os.environ.get('PORT', '5000')}"
API_FRAME_URL = f"{BASE_URL}/api/vision/frame"
API_ESTADO_URL = f"{BASE_URL}/api/vision/estado"
API_PROCESADA_URL = f"{BASE_URL}/api/vision/procesada"

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.dirname(WORKSPACE_DIR)
CARPETA_CAPTURAS = os.path.join(WORKSPACE_DIR, "capturas")
ARCHIVO_CALIBRACION = os.path.join(BACKEND_DIR, "calibracion_vision.json")


def obtener_frame(timeout: float = 3.5, crudo: bool = True) -> np.ndarray:
    t0 = time.time()
    ultimo_valido = None
    url = f"{API_FRAME_URL}?crudo=1" if crudo else API_FRAME_URL

    while time.time() - t0 < timeout:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                data = resp.read()
                arr = np.frombuffer(data, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None and frame.size > 0:
                    ultimo_valido = frame
                    if float(np.mean(frame)) > 45.0:
                        return frame
        except Exception:
            pass
        time.sleep(0.15)

    if ultimo_valido is not None and float(np.mean(ultimo_valido)) > 45.0:
        return ultimo_valido

    try:
        from vision_calibracion import gestor_vision, generar_frame_sintetico
        cal = obtener_calibracion()
        return generar_frame_sintetico(
            geometria=cal.get("geometria_placa") or gestor_vision.obtener_geometria_placa(),
            incluir_piezas=True,
        )
    except Exception:
        pass

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)

    if cap.isOpened():
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            return frame

    raise RuntimeError("No se pudo obtener el fotograma de la camara. Verifica la conexion USB.")


def obtener_calibracion() -> dict:
    try:
        req = urllib.request.Request(API_ESTADO_URL)
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            vision = payload.get("vision", {})
            cal = vision.get("calibracion_homografia") or vision.get("calibracion_virtual") or {}
            geo = vision.get("geometria_placa") or {}
            if cal:
                cal["geometria_placa"] = geo
                cal["marcadores_detectados"] = vision.get("marcadores_detectados", [])
                return cal
    except Exception:
        pass

    if os.path.isfile(ARCHIVO_CALIBRACION):
        try:
            with open(ARCHIVO_CALIBRACION, "r", encoding="utf-8") as f:
                data = json.load(f)
            cal = dict(data.get("calibracion", data))
            cal["geometria_placa"] = data.get("geometria_placa", {})
            return cal
        except Exception:
            pass

    return {"valida": False, "homografia_px_a_mm": None, "geometria_placa": {}}


def guardar_captura(frame: np.ndarray, nombre: str = None) -> str:
    os.makedirs(CARPETA_CAPTURAS, exist_ok=True)
    if not nombre:
        ts = time.strftime("%Y%m%d_%H%M%S")
        nombre = f"captura_{ts}.jpg"
    elif not nombre.lower().endswith((".jpg", ".png")):
        nombre = f"{nombre}.jpg"

    path = os.path.join(CARPETA_CAPTURAS, nombre)
    cv2.imwrite(path, frame)
    return path


def _serializar_piezas(piezas: list) -> list:
    salida = []
    for p in piezas or []:
        item = {}
        for k, v in p.items():
            if k in ("crop", "mascara") or isinstance(v, np.ndarray):
                continue
            if isinstance(v, tuple):
                item[k] = list(v)
            else:
                item[k] = v
        salida.append(item)
    return salida


def publicar_deteccion(frame_anotado: np.ndarray, num_piezas: int = 0, piezas: list = None) -> bool:
    guardar_captura(frame_anotado, "ultima_deteccion.jpg")
    if piezas is not None:
        num_piezas = len(piezas)
        meta_path = os.path.join(CARPETA_CAPTURAS, "ultima_deteccion.json")
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(_serializar_piezas(piezas), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    ok, buf = cv2.imencode(".jpg", frame_anotado, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        return False
    try:
        url = f"{API_PROCESADA_URL}?piezas={num_piezas}"
        req = urllib.request.Request(url, data=buf.tobytes(), headers={"Content-Type": "image/jpeg"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status == 200
    except Exception:
        return False
