import time
import cv2
import numpy as np
from typing import List, Dict, Any, Tuple
from camara import obtener_frame, publicar_deteccion

ANCHO_MESA_MM = 500.0
ALTO_MESA_MM = 350.0
AREA_MIN_PX = 800
AREA_MAX_PX = 250000
INTERVALO_SEGUNDOS = 1.0

def detectar_piezas(
    frame: np.ndarray,
    escala_mm_px: float = 0.5,
    origen_mesa_mm: Tuple[float, float] = (350.0, -250.0)
) -> List[Dict[str, Any]]:
    alto, ancho = frame.shape[:2]
    gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    desenfoque = cv2.GaussianBlur(gris, (5, 5), 0)

    _, mascara = cv2.threshold(desenfoque, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, kernel, iterations=2)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, kernel, iterations=1)

    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    piezas = []
    idx = 1

    for c in contornos:
        area = cv2.contourArea(c)
        if area < AREA_MIN_PX or area > AREA_MAX_PX:
            continue

        M = cv2.moments(c)
        if M["m00"] == 0:
            continue

        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])

        x, y, w, h = cv2.boundingRect(c)

        x_mm = round(origen_mesa_mm[0] + (cy * escala_mm_px), 2)
        y_mm = round(origen_mesa_mm[1] + (cx * escala_mm_px), 2)

        crop = frame[max(0, y):min(alto, y + h), max(0, x):min(ancho, x + w)]

        piezas.append({
            "id": idx,
            "centro_px": (cx, cy),
            "posicion_mm": (x_mm, y_mm),
            "bbox": (x, y, w, h),
            "area_px": int(area),
            "crop": crop
        })
        idx += 1

    return piezas

def dibujar_detecciones(frame: np.ndarray, piezas: List[Dict[str, Any]]) -> np.ndarray:
    anotada = frame.copy()
    for p in piezas:
        x, y, w, h = p["bbox"]
        cx, cy = p["centro_px"]
        x_mm, y_mm = p["posicion_mm"]

        cv2.rectangle(anotada, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.circle(anotada, (cx, cy), 5, (0, 0, 255), -1)

        texto = f"#{p['id']} ({x_mm}, {y_mm})mm"
        cv2.putText(anotada, texto, (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)

    return anotada

def bucle_deteccion(intervalo: float = INTERVALO_SEGUNDOS):
    print(f"Iniciando deteccion OpenCV en tiempo real (cada {intervalo}s)...")
    print("Para detener, presiona el boton Detener en el IDE.")
    
    conteo = 0
    try:
        while True:
            conteo += 1
            frame = obtener_frame()
            piezas = detectar_piezas(frame)
            anotado = dibujar_detecciones(frame, piezas)
            publicar_deteccion(anotado, len(piezas))

            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] Ciclo #{conteo} | Objetos: {len(piezas)}")
            for p in piezas:
                x_mm, y_mm = p["posicion_mm"]
                print(f"   -> #{p['id']}: ({x_mm}, {y_mm}) mm | Centro px: {p['centro_px']} | Area: {p['area_px']} px")

            time.sleep(intervalo)
    except KeyboardInterrupt:
        print("Bucle de deteccion finalizado.")

if __name__ == "__main__":
    bucle_deteccion(INTERVALO_SEGUNDOS)
