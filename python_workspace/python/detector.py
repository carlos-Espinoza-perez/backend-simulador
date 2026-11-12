import math
import time
import cv2
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from camara import obtener_frame, obtener_calibracion, publicar_deteccion
from clasificador import clasificar_material, ordenar_piezas, DESTINOS_DEPOSITO

ANCHO_MESA_MM = 500.0
ALTO_MESA_MM = 350.0
AREA_MIN_PX = 450
AREA_MAX_PX = 180000
INTERVALO_SEGUNDOS = 1.0


def _proyectar_px_a_mm(u: float, v: float, H_px_a_mm: Optional[np.ndarray], escala: float) -> Tuple[float, float]:
    if H_px_a_mm is not None:
        pt = np.array([float(u), float(v), 1.0], dtype=np.float64)
        proy = H_px_a_mm @ pt
        if abs(proy[2]) > 1e-9:
            return float(proy[0] / proy[2]), float(proy[1] / proy[2])
    return float(u) * escala, float(v) * escala


def _proyectar_mm_a_px(x_mm: float, y_mm: float, H_mm_a_px: Optional[np.ndarray], escala: float) -> Tuple[int, int]:
    if H_mm_a_px is not None:
        pt = np.array([float(x_mm), float(y_mm), 1.0], dtype=np.float64)
        proy = H_mm_a_px @ pt
        if abs(proy[2]) > 1e-9:
            return int(round(proy[0] / proy[2])), int(round(proy[1] / proy[2]))
    return int(round(x_mm / max(escala, 1e-6))), int(round(y_mm / max(escala, 1e-6)))


def _construir_mascara_mesa_y_aruco(
    frame: np.ndarray,
    H_mm_a_px: Optional[np.ndarray],
    ancho_mm: float,
    alto_mm: float,
) -> np.ndarray:
    alto, ancho = frame.shape[:2]
    mascara_valida = np.zeros((alto, ancho), dtype=np.uint8)

    if H_mm_a_px is not None:
        margen = 8.0
        esq_mm = [
            (margen, margen),
            (ancho_mm - margen, margen),
            (ancho_mm - margen, alto_mm - margen),
            (margen, alto_mm - margen),
        ]
        pts_px = np.array([_proyectar_mm_a_px(x, y, H_mm_a_px, 0.5) for x, y in esq_mm], dtype=np.int32)
        cv2.fillConvexPoly(mascara_valida, pts_px, 255)
    else:
        gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, mask_clara = cv2.threshold(gris, 175, 255, cv2.THRESH_BINARY)
        cnts, _ = cv2.findContours(mask_clara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        placa_cnt = None
        max_area = 0.0
        for c in cnts:
            a = cv2.contourArea(c)
            if a > (ancho * alto * 0.20) and a > max_area:
                max_area = a
                placa_cnt = c
        if placa_cnt is not None:
            hull = cv2.convexHull(placa_cnt)
            cv2.fillConvexPoly(mascara_valida, hull, 255)
            kernel_borde = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
            mascara_valida = cv2.erode(mascara_valida, kernel_borde, iterations=1)
        else:
            mx, my = int(ancho * 0.06), int(alto * 0.06)
            cv2.rectangle(mascara_valida, (mx, my), (ancho - mx, alto - my), 255, -1)

    try:
        gris_aruco = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        for dict_id in (cv2.aruco.DICT_4X4_50, cv2.aruco.DICT_5X5_50):
            detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(dict_id))
            corners, ids, _ = detector.detectMarkers(gris_aruco)
            if ids is not None and len(ids) > 0:
                for c in corners:
                    pts = np.asarray(c, dtype=np.float32).reshape(4, 2)
                    centro = np.mean(pts, axis=0)
                    pts_exp = centro + (pts - centro) * 1.38
                    cv2.fillConvexPoly(mascara_valida, pts_exp.astype(np.int32), 0)
                break
    except Exception:
        pass

    return mascara_valida


def _punto_en_deposito(x_mm: float, y_mm: float, zonas: List[Dict[str, Any]]) -> bool:
    for z in zonas or []:
        if z.get("id") in ("pet", "aluminio", "carton"):
            poly = z.get("poligono_mm")
            if poly and len(poly) >= 3:
                arr = np.array(poly, dtype=np.float32)
                if cv2.pointPolygonTest(arr, (float(x_mm), float(y_mm)), False) >= 0:
                    return True
    return False


def detectar_piezas(
    frame: np.ndarray,
    escala_mm_px: float = 0.5,
    origen_mesa_mm: Tuple[float, float] = (350.0, -200.0),
    calibracion: Optional[Dict[str, Any]] = None,
    criterio: str = "proximidad",
    sensor_inductivo: Optional[int] = None,
    sensor_capacitivo: Optional[int] = None,
    filtrar_depositos: bool = True,
) -> List[Dict[str, Any]]:
    if frame is None or frame.size == 0:
        return []

    if calibracion is None:
        calibracion = obtener_calibracion()

    H_px_a_mm = None
    H_mm_a_px = None
    if isinstance(calibracion, dict) and calibracion.get("valida"):
        if calibracion.get("homografia_px_a_mm"):
            H_px_a_mm = np.asarray(calibracion["homografia_px_a_mm"], dtype=np.float64)
        if calibracion.get("homografia_mm_a_px"):
            H_mm_a_px = np.asarray(calibracion["homografia_mm_a_px"], dtype=np.float64)
        escala_est = calibracion.get("escala_estimada") or calibracion.get("escala") or {}
        if escala_est.get("mm_por_px_media"):
            escala_mm_px = float(escala_est["mm_por_px_media"])

    geo_placa = (calibracion or {}).get("geometria_placa") or {}
    dims_placa = (calibracion or {}).get("dimensiones_mm") or geo_placa.get("dimensiones_mm") or {}
    ancho_mm = float(dims_placa.get("ancho", ANCHO_MESA_MM))
    alto_mm = float(dims_placa.get("alto", ALTO_MESA_MM))
    zonas = (calibracion or {}).get("zonas_preparacion") or geo_placa.get("zonas_preparacion") or []

    alto, ancho = frame.shape[:2]
    mascara_valida = _construir_mascara_mesa_y_aruco(frame, H_mm_a_px, ancho_mm, alto_mm)

    gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    desenfoque = cv2.GaussianBlur(gris, (5, 5), 0)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    canal_s = cv2.GaussianBlur(hsv[:, :, 1], (5, 5), 0)

    pix_mesa = desenfoque[mascara_valida > 0]
    fondo_gris = float(np.median(pix_mesa)) if pix_mesa.size > 0 else 210.0

    diff_gris = cv2.absdiff(desenfoque, int(round(fondo_gris)))
    _, mask_lum = cv2.threshold(diff_gris, 28, 255, cv2.THRESH_BINARY)
    _, mask_sat = cv2.threshold(canal_s, 38, 255, cv2.THRESH_BINARY)

    mascara = cv2.bitwise_or(mask_lum, mask_sat)
    mascara = cv2.bitwise_and(mascara, mascara_valida)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, kernel, iterations=2)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, kernel, iterations=1)

    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    piezas = []
    idx = 1

    for c in contornos:
        area_px = float(cv2.contourArea(c))
        if area_px < AREA_MIN_PX or area_px > AREA_MAX_PX:
            continue

        x, y, w, h = cv2.boundingRect(c)
        if x <= 2 or y <= 2 or (x + w) >= (ancho - 2) or (y + h) >= (alto - 2):
            continue

        M = cv2.moments(c)
        if M["m00"] == 0:
            continue

        cx = int(round(M["m10"] / M["m00"]))
        cy = int(round(M["m01"] / M["m00"]))

        x_mesa, y_mesa = _proyectar_px_a_mm(cx, cy, H_px_a_mm, escala_mm_px)
        if H_px_a_mm is not None:
            if x_mesa < -5.0 or x_mesa > (ancho_mm + 5.0) or y_mesa < -5.0 or y_mesa > (alto_mm + 5.0):
                continue
            if filtrar_depositos and _punto_en_deposito(x_mesa, y_mesa, zonas):
                continue
            x_rob = round(origen_mesa_mm[0] + y_mesa, 2)
            y_rob = round(origen_mesa_mm[1] + x_mesa, 2)
        else:
            x_rob = round(origen_mesa_mm[0] + (cy * escala_mm_px), 2)
            y_rob = round(origen_mesa_mm[1] + (cx * escala_mm_px), 2)

        perimetro = max(float(cv2.arcLength(c, True)), 1e-3)
        circularidad = round((4.0 * math.pi * area_px) / (perimetro * perimetro), 3)

        rect_min = cv2.minAreaRect(c)
        (_, _), (rw, rh), angulo_rect = rect_min
        lado_mayor_px = max(float(rw), float(rh), 1.0)
        lado_menor_px = max(min(float(rw), float(rh)), 1.0)
        relacion_aspecto = round(lado_mayor_px / lado_menor_px, 2)

        if rw < rh:
            orientacion_deg = round(float(angulo_rect) + 90.0, 1)
        else:
            orientacion_deg = round(float(angulo_rect), 1)
        if orientacion_deg > 90.0:
            orientacion_deg -= 180.0
        elif orientacion_deg <= -90.0:
            orientacion_deg += 180.0

        hull = cv2.convexHull(c)
        area_hull = max(float(cv2.contourArea(hull)), 1.0)
        solidez = round(area_px / area_hull, 3)

        ancho_pieza_mm = round(lado_menor_px * escala_mm_px, 1)
        largo_pieza_mm = round(lado_mayor_px * escala_mm_px, 1)
        area_mm2 = round(area_px * (escala_mm_px ** 2), 1)

        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(ancho, x + w), min(alto, y + h)
        crop = frame[y0:y1, x0:x1]

        mascara_crop = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
        c_local = c - np.array([[x0, y0]])
        cv2.drawContours(mascara_crop, [c_local], -1, 255, -1)

        geometria_pieza = {
            "circularidad": circularidad,
            "relacion_aspecto": relacion_aspecto,
            "solidez": solidez,
            "area_mm2": area_mm2,
            "dimensiones_mm": (ancho_pieza_mm, largo_pieza_mm),
        }

        info_mat = clasificar_material(
            crop,
            sensor_inductivo=sensor_inductivo,
            sensor_capacitivo=sensor_capacitivo,
            mascara=mascara_crop,
            geometria=geometria_pieza,
        )

        box_pts = cv2.boxPoints(rect_min)
        box_px = [[int(round(p[0])), int(round(p[1]))] for p in box_pts]

        piezas.append({
            "id": idx,
            "centro_px": (cx, cy),
            "posicion_mm": (x_rob, y_rob),
            "posicion_mesa_mm": (round(x_mesa, 2), round(y_mesa, 2)),
            "bbox": (x, y, w, h),
            "box_px": box_px,
            "area_px": int(round(area_px)),
            "area_mm2": area_mm2,
            "dimensiones_mm": (ancho_pieza_mm, largo_pieza_mm),
            "orientacion_deg": orientacion_deg,
            "circularidad": circularidad,
            "relacion_aspecto": relacion_aspecto,
            "solidez": solidez,
            "material": info_mat["material"],
            "clase": info_mat["material"],
            "color": info_mat["color"],
            "forma": info_mat["forma"],
            "tamano": info_mat["tamano"],
            "confianza": info_mat["confianza"],
            "metricas_hsv": info_mat.get("metricas", {}),
            "crop": crop,
        })
        idx += 1

    return ordenar_piezas(piezas, criterio=criterio)


def dibujar_detecciones(
    frame: np.ndarray,
    piezas: List[Dict[str, Any]],
    calibracion: Optional[Dict[str, Any]] = None,
) -> np.ndarray:
    anotada = frame.copy()

    if calibracion and isinstance(calibracion, dict):
        H_mm_a_px = calibracion.get("homografia_mm_a_px")
        geo = calibracion.get("geometria_placa") or {}
        zonas = calibracion.get("zonas_preparacion") or geo.get("zonas_preparacion") or []
        if H_mm_a_px is not None:
            H_inv = np.asarray(H_mm_a_px, dtype=np.float64)
            for z in zonas:
                poly_mm = z.get("poligono_mm") or []
                if len(poly_mm) >= 3:
                    pts_z = np.array(
                        [_proyectar_mm_a_px(p[0], p[1], H_inv, 0.5) for p in poly_mm],
                        dtype=np.int32,
                    )
                    color_z = (248, 189, 56) if z.get("id") == "clasificacion" else (120, 210, 90)
                    cv2.polylines(anotada, [pts_z], True, color_z, 1, cv2.LINE_AA)

    for p in piezas:
        x, y, w, h = p["bbox"]
        cx, cy = p["centro_px"]
        x_mm, y_mm = p["posicion_mm"]
        mat = p.get("material", "OBJ")
        orden = p.get("orden", p["id"])
        ang = float(p.get("orientacion_deg", 0.0))

        cfg_dest = DESTINOS_DEPOSITO.get(mat, {})
        color_box = cfg_dest.get("color_bgr", (0, 255, 0))

        box_px = p.get("box_px")
        if box_px and len(box_px) == 4:
            pts_box = np.array(box_px, dtype=np.int32)
            cv2.drawContours(anotada, [pts_box], 0, color_box, 2, cv2.LINE_AA)
        else:
            cv2.rectangle(anotada, (x, y), (x + w, y + h), color_box, 2)

        rad = math.radians(ang)
        ex = int(round(cx + 24.0 * math.cos(rad)))
        ey = int(round(cy + 24.0 * math.sin(rad)))
        cv2.line(anotada, (cx, cy), (ex, ey), (255, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(anotada, (cx, cy), 5, (0, 0, 255), -1)

        etiqueta = f"[{orden}] {mat} ({x_mm:.0f},{y_mm:.0f})mm {ang:.0f}deg"
        ty = max(22, y - 10)
        (tw, th), _ = cv2.getTextSize(etiqueta, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
        cv2.rectangle(anotada, (x, ty - th - 4), (x + tw + 6, ty + 4), (18, 22, 28), -1)
        cv2.putText(
            anotada,
            etiqueta,
            (x + 3, ty),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            color_box,
            1,
            cv2.LINE_AA,
        )

    return anotada


def bucle_deteccion(intervalo: float = INTERVALO_SEGUNDOS, criterio: str = "proximidad"):
    print(f"Iniciando deteccion y ordenamiento OpenCV (cada {intervalo}s | criterio: {criterio})...")
    print("Para detener, presiona el boton Detener en el IDE.")

    conteo = 0
    try:
        while True:
            conteo += 1
            cal = obtener_calibracion()
            frame = obtener_frame(crudo=True)
            piezas = detectar_piezas(frame, calibracion=cal, criterio=criterio)
            anotado = dibujar_detecciones(frame, piezas, calibracion=cal)
            publicar_deteccion(anotado, len(piezas), piezas=piezas)

            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] Ciclo #{conteo} | Objetos detectados y ordenados: {len(piezas)}")
            for p in piezas:
                x_mm, y_mm = p["posicion_mm"]
                xm, ym = p.get("posicion_mesa_mm", (0.0, 0.0))
                print(
                    f"   -> Orden #{p['orden']} (ID {p['id']}): {p['material']} [{p['color']}/{p['forma']}] "
                    f"| Robot=({x_mm}, {y_mm}) mm | Mesa=({xm}, {ym}) mm | Ang={p['orientacion_deg']}°"
                )

            time.sleep(intervalo)
    except KeyboardInterrupt:
        print("Bucle de deteccion finalizado.")


if __name__ == "__main__":
    bucle_deteccion(INTERVALO_SEGUNDOS)
