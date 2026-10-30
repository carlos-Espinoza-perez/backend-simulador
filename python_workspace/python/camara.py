import os
import time
import urllib.request
import cv2
import numpy as np

API_FRAME_URL = "http://127.0.0.1:5000/api/vision/frame"
API_PROCESADA_URL = "http://127.0.0.1:5000/api/vision/procesada"
CARPETA_CAPTURAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capturas")

def obtener_frame(timeout: float = 3.5) -> np.ndarray:
    t0 = time.time()
    ultimo_valido = None

    while time.time() - t0 < timeout:
        try:
            req = urllib.request.Request(API_FRAME_URL)
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                data = resp.read()
                arr = np.frombuffer(data, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None and frame.size > 0:
                    ultimo_valido = frame
                    if frame.std() > 6.0:
                        return frame
        except Exception:
            pass
        time.sleep(0.15)

    if ultimo_valido is not None:
        return ultimo_valido

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)

    if cap.isOpened():
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            return frame

    raise RuntimeError("No se pudo obtener el fotograma de la camara. Verifica la conexion USB.")

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

def publicar_deteccion(frame_anotado: np.ndarray, num_piezas: int = 0) -> bool:
    guardar_captura(frame_anotado, "ultima_deteccion.jpg")
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
