from collections import deque
import json
import os
import threading
import time
from datetime import datetime
import cv2
import numpy as np
from flask import Blueprint, Response, jsonify, request

from calibracion_coordenadas import (
    ESTADO_SIN_CALIBRAR,
    ESTADO_CONFIGURACION_INCOMPLETA,
    ESTADO_CALCULANDO,
    ESTADO_CALIBRACION_VIRTUAL_VALIDA,
    ESTADO_CALIBRACION_FISICA_PENDIENTE,
    ESTADO_CALIBRACION_FISICA_VALIDADA,
    ESTADO_CALIBRACION_INVALIDA,
    MODO_VIRTUAL,
    MODO_FISICA,
    obtener_geometria_defecto,
    calcular_esquinas_marcador_mm,
    validar_geometria_placa,
    calcular_homografia_mesa,
    transformar_punto_a_mesa,
    transformar_punto_a_imagen,
)

try:
    import gevent
    def _async_sleep(segundos):
        gevent.sleep(segundos)
except ImportError:
    def _async_sleep(segundos):
        time.sleep(segundos)

vision_bp = Blueprint("vision", __name__)

@vision_bp.after_request
def vision_bp_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept, Origin"
    return response

DICCIONARIOS_ARUCO = {
    "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
    "DICT_4X4_100": cv2.aruco.DICT_4X4_100,
    "DICT_5X5_50": cv2.aruco.DICT_5X5_50,
    "DICT_6X6_50": cv2.aruco.DICT_6X6_50,
}

IDS_PLACA_ESPERADOS = [0, 1, 2, 3]
VENTANA_HISTORIAL = 45
ARCHIVO_CALIBRACION = os.path.join(os.path.dirname(__file__), "calibracion_vision.json")
_DETECTORES_CACHE = {}

CRITERIO_SUBPIX = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.03)


def _obtener_detector(nombre_diccionario):
    if nombre_diccionario not in DICCIONARIOS_ARUCO:
        raise ValueError(f"Diccionario ArUco no soportado: {nombre_diccionario}")
    if nombre_diccionario not in _DETECTORES_CACHE:
        aruco_dict = cv2.aruco.getPredefinedDictionary(DICCIONARIOS_ARUCO[nombre_diccionario])
        params = cv2.aruco.DetectorParameters()
        params.adaptiveThreshWinSizeMin = 5
        params.adaptiveThreshWinSizeMax = 29
        params.adaptiveThreshWinSizeStep = 12
        params.minMarkerPerimeterRate = 0.02
        _DETECTORES_CACHE[nombre_diccionario] = cv2.aruco.ArucoDetector(aruco_dict, params)
    return _DETECTORES_CACHE[nombre_diccionario]


def detectar_marcadores_aruco(frame_bgr, nombre_diccionario="DICT_4X4_50", devolver_metricas=False):
    t_inicio = time.perf_counter()
    detector = _obtener_detector(nombre_diccionario)
    gris_full = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    alto, ancho = gris_full.shape[:2]

    escala_det = 0.5 if ancho >= 1280 else 1.0
    if escala_det < 1.0:
        gris_det = cv2.resize(
            gris_full,
            (int(ancho * escala_det), int(alto * escala_det)),
            interpolation=cv2.INTER_AREA,
        )
        corners_raw, ids, rechazados = detector.detectMarkers(gris_det)
        corners = []
        if ids is not None and len(ids) > 0:
            inv = 1.0 / escala_det
            for c in corners_raw:
                pts_full = (np.asarray(c, dtype=np.float32) * inv).reshape(-1, 1, 2)
                cv2.cornerSubPix(gris_full, pts_full, (5, 5), (-1, -1), CRITERIO_SUBPIX)
                corners.append(pts_full.reshape(1, 4, 2))
    else:
        corners, ids, rechazados = detector.detectMarkers(gris_full)

    frame_anotado = frame_bgr.copy()
    marcadores = []

    if ids is not None and len(ids) > 0:
        cv2.aruco.drawDetectedMarkers(frame_anotado, corners, ids)

        for pts_marker, marker_id_arr in zip(corners, ids):
            marker_id = int(np.asarray(marker_id_arr).flat[0])
            pts = np.asarray(pts_marker).reshape(4, 2)
            esquinas = [[round(float(p[0]), 2), round(float(p[1]), 2)] for p in pts]
            centro = [
                round(float(np.mean(pts[:, 0])), 2),
                round(float(np.mean(pts[:, 1])), 2),
            ]

            p0 = (int(pts[0][0]), int(pts[0][1]))
            cv2.circle(frame_anotado, p0, 6, (0, 165, 255), -1)
            cv2.putText(
                frame_anotado,
                f"ID:{marker_id} (E0)",
                (p0[0] + 8, p0[1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )

            marcadores.append({
                "id": marker_id,
                "esquinas_px": esquinas,
                "centro_px": centro,
            })

        marcadores.sort(key=lambda m: m["id"])

    tiempo_ms = (time.perf_counter() - t_inicio) * 1000.0
    num_rechazados = len(rechazados) if rechazados is not None else 0

    if devolver_metricas:
        return marcadores, frame_anotado, tiempo_ms, num_rechazados
    return marcadores, frame_anotado


def calcular_homografia_y_escala(esquinas_px, ancho_mm, alto_mm, origen="manual_4_esquinas"):
    if not isinstance(esquinas_px, (list, tuple)) or len(esquinas_px) != 4:
        raise ValueError("Se requieren exactamente 4 esquinas en píxeles [[u1,v1], [u2,v2], [u3,v3], [u4,v4]].")

    pts_px = np.asarray(esquinas_px, dtype=np.float64)
    if pts_px.shape != (4, 2) or not np.all(np.isfinite(pts_px)):
        raise ValueError("Las coordenadas de las 4 esquinas deben ser pares numéricos válidos [u, v].")

    ancho_mm = float(ancho_mm)
    alto_mm = float(alto_mm)
    if ancho_mm <= 0 or alto_mm <= 0:
        raise ValueError("Las dimensiones físicas ancho_mm y alto_mm deben ser mayores a 0.")

    area_px = float(cv2.contourArea(pts_px.astype(np.float32)))
    if area_px < 100.0:
        raise ValueError("Las 4 esquinas seleccionadas son colineales o están demasiado juntas.")

    pts_mm = np.array(
        [
            [0.0, 0.0],
            [ancho_mm, 0.0],
            [ancho_mm, alto_mm],
            [0.0, alto_mm],
        ],
        dtype=np.float64,
    )

    H_px_a_mm, _ = cv2.findHomography(pts_px, pts_mm, method=0)
    if H_px_a_mm is None:
        raise ValueError("No se pudo calcular una homografía válida con los puntos indicados.")

    try:
        H_mm_a_px = np.linalg.inv(H_px_a_mm)
    except np.linalg.LinAlgError as exc:
        raise ValueError("La matriz de homografía calculada es singular (no invertible).") from exc

    pts_px_h = np.hstack([pts_px, np.ones((4, 1), dtype=np.float64)])
    proy_mm_h = (H_px_a_mm @ pts_px_h.T).T
    proy_mm = proy_mm_h[:, :2] / proy_mm_h[:, 2:3]
    err_mm = np.linalg.norm(proy_mm - pts_mm, axis=1)
    rms_mm = float(np.sqrt(np.mean(err_mm ** 2)))

    pts_mm_h = np.hstack([pts_mm, np.ones((4, 1), dtype=np.float64)])
    proy_px_h = (H_mm_a_px @ pts_mm_h.T).T
    proy_px = proy_px_h[:, :2] / proy_px_h[:, 2:3]
    err_px = np.linalg.norm(proy_px - pts_px, axis=1)
    rms_px = float(np.sqrt(np.mean(err_px ** 2)))

    lado_sup_px = float(np.linalg.norm(pts_px[1] - pts_px[0]))
    lado_der_px = float(np.linalg.norm(pts_px[2] - pts_px[1]))
    lado_inf_px = float(np.linalg.norm(pts_px[2] - pts_px[3]))
    lado_izq_px = float(np.linalg.norm(pts_px[3] - pts_px[0]))

    ancho_medio_px = max((lado_sup_px + lado_inf_px) * 0.5, 1e-6)
    alto_medio_px = max((lado_izq_px + lado_der_px) * 0.5, 1e-6)

    escala_x_mm_px = ancho_mm / ancho_medio_px
    escala_y_mm_px = alto_mm / alto_medio_px
    escala_media_mm_px = (escala_x_mm_px + escala_y_mm_px) * 0.5
    px_por_mm = 1.0 / max(escala_media_mm_px, 1e-9)

    ratio_perspectiva_h = round(max(lado_sup_px, lado_inf_px) / max(min(lado_sup_px, lado_inf_px), 1e-6), 3)
    ratio_perspectiva_v = round(max(lado_izq_px, lado_der_px) / max(min(lado_izq_px, lado_der_px), 1e-6), 3)

    return {
        "valida": True,
        "origen": origen,
        "esquinas_px": [[round(float(p[0]), 2), round(float(p[1]), 2)] for p in pts_px],
        "esquinas_mm": [[round(float(p[0]), 2), round(float(p[1]), 2)] for p in pts_mm],
        "dimensiones_mm": {
            "ancho": round(ancho_mm, 2),
            "alto": round(alto_mm, 2),
        },
        "lados_px": {
            "superior": round(lado_sup_px, 1),
            "derecho": round(lado_der_px, 1),
            "inferior": round(lado_inf_px, 1),
            "izquierdo": round(lado_izq_px, 1),
            "ancho_medio": round(ancho_medio_px, 1),
            "alto_medio": round(alto_medio_px, 1),
        },
        "escala": {
            "mm_por_px_x": round(escala_x_mm_px, 4),
            "mm_por_px_y": round(escala_y_mm_px, 4),
            "mm_por_px_media": round(escala_media_mm_px, 4),
            "px_por_mm_media": round(px_por_mm, 3),
            "relacion_perspectiva_h": ratio_perspectiva_h,
            "relacion_perspectiva_v": ratio_perspectiva_v,
        },
        "homografia_px_a_mm": [[round(float(v), 8) for v in fila] for fila in H_px_a_mm],
        "homografia_mm_a_px": [[round(float(v), 8) for v in fila] for fila in H_mm_a_px],
        "error_reproyeccion_px": round(rms_px, 4),
        "error_reproyeccion_mm": round(rms_mm, 4),
        "validacion_distancia": None,
        "fecha": datetime.now().isoformat(timespec="seconds"),
    }


def transformar_puntos_px_a_mm(puntos_px, H_px_a_mm):
    pts = np.asarray(puntos_px, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError("Se requiere una lista de puntos [[u, v], ...].")
    H = np.asarray(H_px_a_mm, dtype=np.float64)
    pts_h = np.hstack([pts, np.ones((pts.shape[0], 1), dtype=np.float64)])
    proy_h = (H @ pts_h.T).T
    proy = proy_h[:, :2] / proy_h[:, 2:3]
    return [[round(float(p[0]), 2), round(float(p[1]), 2)] for p in proy]


def _dibujar_piezas_sinteticas(lienzo, bx0, by0, bx1, by1):
    w_placa = max(bx1 - bx0, 100)
    h_placa = max(by1 - by0, 100)

    cx_pet = int(round(bx0 + w_placa * 0.30))
    cy_pet = int(round(by0 + h_placa * 0.40))
    r_pet = max(16, int(round(min(w_placa, h_placa) * 0.055)))
    cv2.circle(lienzo, (cx_pet, cy_pet), r_pet, (215, 115, 25), -1, cv2.LINE_AA)
    cv2.circle(lienzo, (cx_pet, cy_pet), max(6, r_pet // 2), (235, 145, 55), 2, cv2.LINE_AA)

    cx_alu = int(round(bx0 + w_placa * 0.44))
    cy_alu = int(round(by0 + h_placa * 0.58))
    r_alu = max(18, int(round(min(w_placa, h_placa) * 0.062)))
    cv2.circle(lienzo, (cx_alu, cy_alu), r_alu, (132, 136, 140), -1, cv2.LINE_AA)
    cv2.circle(lienzo, (cx_alu, cy_alu), max(7, int(r_alu * 0.55)), (168, 172, 176), 3, cv2.LINE_AA)

    cx_car = float(bx0 + w_placa * 0.56)
    cy_car = float(by0 + h_placa * 0.43)
    w_car = max(32.0, w_placa * 0.11)
    h_car = max(22.0, h_placa * 0.075)
    box_car = cv2.boxPoints(((cx_car, cy_car), (w_car, h_car), 24.0))
    cv2.fillConvexPoly(lienzo, np.int32(box_car), (55, 118, 178), cv2.LINE_AA)


def generar_frame_sintetico(
    ancho=1280,
    alto=720,
    nombre_diccionario="DICT_4X4_50",
    ids_visibles=None,
    geometria=None,
    incluir_piezas=False,
):
    if ids_visibles is None:
        ids_visibles = IDS_PLACA_ESPERADOS

    aruco_dict = cv2.aruco.getPredefinedDictionary(DICCIONARIOS_ARUCO[nombre_diccionario])
    lienzo = np.full((alto, ancho, 3), (32, 38, 46), dtype=np.uint8)

    if geometria and isinstance(geometria, dict) and "dimensiones_mm" in geometria:
        ancho_mm = float(geometria["dimensiones_mm"]["ancho"])
        alto_mm = float(geometria["dimensiones_mm"]["alto"])
        escala = min((ancho * 0.72) / max(ancho_mm, 1.0), (alto * 0.72) / max(alto_mm, 1.0))
        offset_x = (ancho - ancho_mm * escala) / 2.0
        offset_y = (alto - alto_mm * escala) / 2.0
        bx0, by0 = int(round(offset_x)), int(round(offset_y))
        bx1, by1 = int(round(offset_x + ancho_mm * escala)), int(round(offset_y + alto_mm * escala))
        cv2.rectangle(lienzo, (bx0, by0), (bx1, by1), (215, 218, 222), -1)
        cv2.rectangle(lienzo, (bx0, by0), (bx1, by1), (90, 100, 110), 2)

        if incluir_piezas:
            _dibujar_piezas_sinteticas(lienzo, bx0, by0, bx1, by1)

        for m in geometria.get("marcadores", []):
            m_id = m.get("id")
            cx_mm, cy_mm = m.get("centro_mm", [0.0, 0.0])
            tam_mm = float(m.get("tamano_mm", 50.0))
            lado_px = max(16, int(round(tam_mm * escala)))
            cx_px = offset_x + cx_mm * escala
            cy_px = offset_y + cy_mm * escala
            x0 = int(round(cx_px - lado_px / 2.0))
            y0 = int(round(cy_px - lado_px / 2.0))

            if m_id not in ids_visibles:
                cv2.rectangle(lienzo, (x0, y0), (x0 + lado_px, y0 + lado_px), (160, 165, 170), 2)
                cv2.putText(
                    lienzo,
                    f"ID {m_id} OCULTO",
                    (x0 + 8, y0 + lado_px // 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (100, 105, 110),
                    1,
                    cv2.LINE_AA,
                )
                continue

            img_marker = cv2.aruco.generateImageMarker(aruco_dict, m_id, lado_px)
            img_marker_bgr = cv2.cvtColor(img_marker, cv2.COLOR_GRAY2BGR)
            lienzo[y0:y0 + lado_px, x0:x0 + lado_px] = img_marker_bgr
    else:
        margen_x = int(ancho * 0.14)
        margen_y = int(alto * 0.14)
        cv2.rectangle(
            lienzo,
            (margen_x, margen_y),
            (ancho - margen_x, alto - margen_y),
            (215, 218, 222),
            -1,
        )
        cv2.rectangle(
            lienzo,
            (margen_x, margen_y),
            (ancho - margen_x, alto - margen_y),
            (90, 100, 110),
            2,
        )

        if incluir_piezas:
            _dibujar_piezas_sinteticas(lienzo, margen_x, margen_y, ancho - margen_x, alto - margen_y)

        lado_marker = min(ancho, alto) // 6
        pad = int(lado_marker * 0.25)

        posiciones_esquinas = {
            0: (margen_x + pad, margen_y + pad),
            1: (ancho - margen_x - pad - lado_marker, margen_y + pad),
            2: (ancho - margen_x - pad - lado_marker, alto - margen_y - pad - lado_marker),
            3: (margen_x + pad, alto - margen_y - pad - lado_marker),
        }

        for marker_id, (x0, y0) in posiciones_esquinas.items():
            if marker_id not in ids_visibles:
                cv2.rectangle(
                    lienzo,
                    (x0, y0),
                    (x0 + lado_marker, y0 + lado_marker),
                    (160, 165, 170),
                    2,
                )
                cv2.putText(
                    lienzo,
                    f"ID {marker_id} OCULTO",
                    (x0 + 10, y0 + lado_marker // 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (100, 105, 110),
                    1,
                    cv2.LINE_AA,
                )
                continue

            img_marker = cv2.aruco.generateImageMarker(aruco_dict, marker_id, lado_marker)
            img_marker_bgr = cv2.cvtColor(img_marker, cv2.COLOR_GRAY2BGR)
            lienzo[y0:y0 + lado_marker, x0:x0 + lado_marker] = img_marker_bgr

    ORIGEN_H = np.float32([
        [0, 0],
        [ancho, 0],
        [ancho, alto],
        [0, alto],
    ])
    DESTINO_H = np.float32([
        [ancho * 0.03, alto * 0.04],
        [ancho * 0.97, alto * 0.02],
        [ancho * 0.99, alto * 0.97],
        [ancho * 0.01, alto * 0.95],
    ])
    M = cv2.getPerspectiveTransform(ORIGEN_H, DESTINO_H)
    escena = cv2.warpPerspective(
        lienzo,
        M,
        (ancho, alto),
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(20, 24, 30),
    )

    return escena


class GestorVision:
    def __init__(self):
        self._lock = threading.Lock()
        self._evento_despertar = threading.Event()
        self._hilo = None
        self._stream_id = 0

        self.activa = False
        self.fuente = "sintetico"
        self.indice_camara = 0
        self.diccionario = "DICT_4X4_50"
        self.resolucion = [1280, 720]
        self.autofocus = False
        self.marcadores_simulados = [0, 1, 2, 3]
        self.geometria_placa = self._cargar_geometria_disco()
        self._calibracion = self._cargar_calibracion_disco()

        self._reiniciar_acumuladores_diagnostico()
        frame_base = generar_frame_sintetico(
            ancho=self.resolucion[0],
            alto=self.resolucion[1],
            nombre_diccionario=self.diccionario,
            ids_visibles=list(self.marcadores_simulados),
            geometria=self.geometria_placa,
            incluir_piezas=True,
        )
        ok_init, buf_init = cv2.imencode(".jpg", frame_base, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        bytes_base = buf_init.tobytes() if ok_init else None
        self._ultimo_jpeg = bytes_base
        self._ultimo_jpeg_crudo = bytes_base
        self._estado = self._crear_estado_base()

    def _crear_calibracion_vacia(self):
        geo = getattr(self, "geometria_placa", None) or obtener_geometria_defecto()
        dims = geo.get("dimensiones_mm", {"ancho": 400.0, "alto": 300.0})
        return {
            "schema_version": "2.0",
            "valida": False,
            "modo": MODO_VIRTUAL,
            "estado": ESTADO_SIN_CALIBRAR,
            "apto_para_robot": False,
            "advertencia_seguridad": "Calibración virtual de referencia. NO válida para controlar el robot físico.",
            "motivos_invalidez": ["Calibración no calculada."],
            "id_configuracion": geo.get("id_configuracion", "mesa_trabajo_defecto"),
            "unidades": geo.get("unidades", "mm"),
            "origen_sistema": geo.get("origen_sistema", "esquina_superior_izquierda"),
            "direccion_ejes": geo.get("direccion_ejes", {"eje_x": "hacia_la_derecha", "eje_y": "hacia_abajo"}),
            "dimensiones_mm": dims,
            "es_demostracion": geo.get("es_demostracion", True),
            "marcadores": geo.get("marcadores", []),
            "marcadores_esperados": [m["id"] for m in geo.get("marcadores", [])],
            "resolucion_asociada": list(self.resolucion) if hasattr(self, "resolucion") else [1280, 720],
            "es_simulacion": True,
            "fecha_calculo": None,
            "homografia_px_a_mm": None,
            "homografia_mm_a_px": None,
            "num_correspondencias": 0,
            "error_ajuste": {"rms_mm": None, "max_mm": None, "rms_px": None},
            "error_validacion_independiente": {"num_puntos_validacion": 0, "rms_mm": None, "max_mm": None, "estado": "sin_datos"},
            "escala_estimada": None,
            "zonas_preparacion": geo.get("zonas_preparacion", []),
            "origen": None,
            "esquinas_px": [],
            "esquinas_mm": [],
            "lados_px": None,
            "escala": None,
            "error_reproyeccion_px": None,
            "error_reproyeccion_mm": None,
            "validacion_distancia": None,
            "fecha": None,
        }

    def _cargar_geometria_disco(self):
        if os.path.exists(ARCHIVO_CALIBRACION):
            try:
                with open(ARCHIVO_CALIBRACION, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "geometria_placa" in data:
                    ok, _ = validar_geometria_placa(data["geometria_placa"])
                    if ok:
                        return data["geometria_placa"]
            except Exception:
                pass
        return obtener_geometria_defecto()

    def _cargar_calibracion_disco(self):
        if os.path.exists(ARCHIVO_CALIBRACION):
            try:
                with open(ARCHIVO_CALIBRACION, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    cal = data.get("calibracion", data)
                    if isinstance(cal, dict) and "valida" in cal:
                        base = self._crear_calibracion_vacia()
                        base.update(cal)
                        return base
            except Exception:
                pass
        return self._crear_calibracion_vacia()

    def _guardar_calibracion_disco(self):
        try:
            payload = {
                "schema_version": "2.0",
                "geometria_placa": self.geometria_placa,
                "calibracion": self._calibracion,
                "valida": self._calibracion.get("valida", False),
                "fecha_actualizacion": datetime.now().isoformat(timespec="seconds"),
            }
            with open(ARCHIVO_CALIBRACION, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def obtener_geometria_placa(self):
        with self._lock:
            return dict(self.geometria_placa)

    def obtener_calibracion(self):
        with self._lock:
            return dict(self._calibracion)

    def actualizar_geometria_placa(self, payload):
        ok, errores = validar_geometria_placa(payload)
        if not ok:
            raise ValueError(f"Geometría de placa inválida: {'; '.join(errores)}")

        with self._lock:
            dims_prev = self.geometria_placa.get("dimensiones_mm", {})
            dims_nuevas = payload.get("dimensiones_mm", {})
            marcs_prev = self.geometria_placa.get("marcadores", [])
            marcs_nuevos = payload.get("marcadores", [])

            cambio_geometria = (
                dims_prev.get("ancho") != dims_nuevas.get("ancho")
                or dims_prev.get("alto") != dims_nuevas.get("alto")
                or len(marcs_prev) != len(marcs_nuevos)
                or any(
                    m1.get("id") != m2.get("id")
                    or m1.get("centro_mm") != m2.get("centro_mm")
                    or m1.get("tamano_mm") != m2.get("tamano_mm")
                    for m1, m2 in zip(marcs_prev, marcs_nuevos)
                )
            )

            self.geometria_placa = dict(payload)
            if cambio_geometria and self._calibracion.get("valida"):
                self._calibracion["valida"] = False
                self._calibracion["estado"] = ESTADO_CALIBRACION_INVALIDA
                self._calibracion["motivos_invalidez"] = [
                    "Geometría de la placa modificada; se requiere recalcular la calibración."
                ]
                self._calibracion["fecha_calculo"] = None

            self._calibracion["dimensiones_mm"] = dict(dims_nuevas)
            self._calibracion["marcadores"] = list(marcs_nuevos)
            self._calibracion["marcadores_esperados"] = [m["id"] for m in marcs_nuevos]
            self._estado["geometria_placa"] = dict(self.geometria_placa)
            self._estado["calibracion_virtual"] = dict(self._calibracion)
            self._estado["calibracion_homografia"] = dict(self._calibracion)
            self._estado["modo_calibracion"] = self._calibracion.get("modo", MODO_VIRTUAL)
            self._estado["estado_calibracion"] = self._calibracion.get("estado", ESTADO_SIN_CALIBRAR)
            self._guardar_calibracion_disco()

        return dict(self.geometria_placa)

    def calcular_calibracion_mesa(self, payload=None):
        payload = payload or {}
        usar_aruco = bool(payload.get("usar_aruco", True))
        val_marker_ids = payload.get("puntos_validacion_independiente_ids", [])
        modo_solicitado = payload.get("modo", MODO_VIRTUAL)

        with self._lock:
            es_sim = self.fuente == "sintetico"
            marcadores_actuales = list(self._estado.get("marcadores_detectados", []))
            geo = dict(self.geometria_placa)
            resolucion_actual = list(self._estado.get("resolucion", self.resolucion))

        if es_sim and modo_solicitado == MODO_FISICA:
            raise ValueError("No se permite declarar 'CALIBRACION_FISICA_VALIDADA' operando sobre una fuente sintética/simulada.")

        modo_final = MODO_VIRTUAL if es_sim else modo_solicitado

        if usar_aruco:
            mapa_detectados = {m["id"]: m for m in marcadores_actuales}
            mapa_geo = {m["id"]: m for m in geo.get("marcadores", [])}

            faltantes = [m_id for m_id in mapa_geo if m_id not in mapa_detectados]
            if len(mapa_detectados) < 3 and len(faltantes) > 0:
                raise ValueError(
                    f"Marcadores insuficientes para calcular la calibración. "
                    f"Detectados: {list(mapa_detectados.keys())}, Faltantes esperados: {faltantes}."
                )

            pts_ajuste_px, pts_ajuste_mm = [], []
            pts_val_px, pts_val_mm = [], []

            for m_id, m_det in mapa_detectados.items():
                if m_id not in mapa_geo:
                    continue
                m_geo = mapa_geo[m_id]
                esq_mm = calcular_esquinas_marcador_mm(
                    m_geo.get("centro_mm", [0, 0]),
                    m_geo.get("tamano_mm", 50.0),
                    m_geo.get("orientacion_deg", 0.0),
                )
                esq_px = m_det.get("esquinas_px", [])
                if len(esq_px) != 4 or len(esq_mm) != 4:
                    continue

                if m_id in val_marker_ids:
                    for p_px, p_mm in zip(esq_px, esq_mm):
                        pts_val_px.append(p_px)
                        pts_val_mm.append(p_mm)
                else:
                    for p_px, p_mm in zip(esq_px, esq_mm):
                        pts_ajuste_px.append(p_px)
                        pts_ajuste_mm.append(p_mm)

            if len(pts_ajuste_px) < 4:
                raise ValueError(
                    f"Se requieren al menos 4 puntos para ajustar la homografía (obtenidos para ajuste: {len(pts_ajuste_px)})."
                )

            resultado_hom = calcular_homografia_mesa(
                correspondencias_px=pts_ajuste_px,
                correspondencias_mm=pts_ajuste_mm,
                puntos_validacion_px=pts_val_px if pts_val_px else None,
                puntos_validacion_mm=pts_val_mm if pts_val_mm else None,
                modo=modo_final,
            )
            origen = "aruco_placa_virtual"
        else:
            corresp_px = payload.get("correspondencias_px") or payload.get("esquinas_px")
            corresp_mm = payload.get("correspondencias_mm")
            ancho_mm = payload.get("ancho_mm", geo.get("dimensiones_mm", {}).get("ancho", 400.0))
            alto_mm = payload.get("alto_mm", geo.get("dimensiones_mm", {}).get("alto", 300.0))

            if not corresp_mm and corresp_px and len(corresp_px) == 4:
                corresp_mm = [
                    [0.0, 0.0],
                    [float(ancho_mm), 0.0],
                    [float(ancho_mm), float(alto_mm)],
                    [0.0, float(alto_mm)],
                ]

            resultado_hom = calcular_homografia_mesa(
                correspondencias_px=corresp_px,
                correspondencias_mm=corresp_mm,
                modo=modo_final,
            )
            origen = "manual_4_esquinas"

        cal = dict(self._crear_calibracion_vacia())
        cal.update(resultado_hom)
        cal["origen"] = origen
        cal["resolucion_asociada"] = resolucion_actual
        cal["resolucion_calibracion"] = resolucion_actual
        cal["es_simulacion"] = es_sim
        cal["dimensiones_mm"] = geo.get("dimensiones_mm", {"ancho": 400.0, "alto": 300.0})
        cal["marcadores"] = geo.get("marcadores", [])
        cal["marcadores_esperados"] = [m["id"] for m in geo.get("marcadores", [])]
        cal["motivos_invalidez"] = []

        cal["esquinas_px"] = pts_ajuste_px[:4] if usar_aruco else corresp_px
        cal["esquinas_mm"] = pts_ajuste_mm[:4] if usar_aruco else corresp_mm
        cal["error_reproyeccion_px"] = resultado_hom["error_ajuste"]["rms_px"]
        cal["error_reproyeccion_mm"] = resultado_hom["error_ajuste"]["rms_mm"]
        cal["escala"] = resultado_hom.get("escala_estimada")
        cal["lados_px"] = {
            "superior": 0.0, "derecho": 0.0, "inferior": 0.0, "izquierdo": 0.0,
            "ancho_medio": round(cal["dimensiones_mm"]["ancho"] * (1.0 / max(cal["escala"]["mm_por_px_media"], 1e-6)), 1) if cal["escala"] else 0.0,
            "alto_medio": round(cal["dimensiones_mm"]["alto"] * (1.0 / max(cal["escala"]["mm_por_px_media"], 1e-6)), 1) if cal["escala"] else 0.0,
        }
        cal["fecha"] = cal["fecha_calculo"]

        with self._lock:
            self._calibracion = cal
            self._estado["calibracion_homografia"] = dict(cal)
            self._guardar_calibracion_disco()

        return dict(cal)

    def transformar_px_a_mm(self, payload):
        with self._lock:
            cal = dict(self._calibracion)
            dims = dict(self.geometria_placa.get("dimensiones_mm", {}))

        if not cal.get("valida"):
            raise ValueError("No existe una calibración activa válida.")

        if "u" in payload and "v" in payload:
            return transformar_punto_a_mesa(payload["u"], payload["v"], cal, dims)

        puntos = payload.get("puntos_px")
        if not isinstance(puntos, list) or len(puntos) == 0:
            raise ValueError("Se requiere 'u' y 'v', o una lista 'puntos_px'.")

        resultados = [transformar_punto_a_mesa(p[0], p[1], cal, dims) for p in puntos]
        return {
            "puntos_transformados": resultados,
            "calibracion_modo": cal.get("modo"),
            "unidades": "mm",
        }

    def transformar_mm_a_px(self, payload):
        with self._lock:
            cal = dict(self._calibracion)
            res = list(self.resolucion)

        if not cal.get("valida"):
            raise ValueError("No existe una calibración activa válida.")

        if "x" in payload and "y" in payload:
            return transformar_punto_a_imagen(payload["x"], payload["y"], cal, res)

        puntos = payload.get("puntos_mm")
        if not isinstance(puntos, list) or len(puntos) == 0:
            raise ValueError("Se requiere 'x' e 'y', o una lista 'puntos_mm'.")

        resultados = [transformar_punto_a_imagen(p[0], p[1], cal, res) for p in puntos]
        return {
            "puntos_transformados": resultados,
            "calibracion_modo": cal.get("modo"),
        }

    def invalidar_calibracion(self, motivo="Invalidación manual solicitada."):
        with self._lock:
            self._calibracion["valida"] = False
            self._calibracion["estado"] = ESTADO_CALIBRACION_INVALIDA
            self._calibracion["motivos_invalidez"] = [motivo]
            self._calibracion["fecha_calculo"] = None
            self._estado["calibracion_virtual"] = dict(self._calibracion)
            self._estado["calibracion_homografia"] = dict(self._calibracion)
            self._estado["modo_calibracion"] = self._calibracion.get("modo", MODO_VIRTUAL)
            self._estado["estado_calibracion"] = self._calibracion.get("estado", ESTADO_SIN_CALIBRAR)
            self._guardar_calibracion_disco()
            return dict(self._calibracion)

    def resetear_calibracion_virtual(self):
        with self._lock:
            self.geometria_placa = obtener_geometria_defecto()
            self._calibracion = self._crear_calibracion_vacia()
            self._estado["geometria_placa"] = dict(self.geometria_placa)
            self._estado["calibracion_virtual"] = dict(self._calibracion)
            self._estado["calibracion_homografia"] = dict(self._calibracion)
            self._estado["modo_calibracion"] = self._calibracion.get("modo", MODO_VIRTUAL)
            self._estado["estado_calibracion"] = self._calibracion.get("estado", ESTADO_SIN_CALIBRAR)
            self._guardar_calibracion_disco()
            return {
                "geometria_placa": dict(self.geometria_placa),
                "calibracion": dict(self._calibracion),
            }

    def calcular_calibracion_cuatro_esquinas(self, payload):
        usar_aruco = bool(payload.get("usar_aruco", False))
        ancho_mm = payload.get("ancho_mm", 220.0)
        alto_mm = payload.get("alto_mm", 140.0)

        with self._lock:
            marcadores_actuales = list(self._estado.get("marcadores_detectados", []))
            resolucion_actual = list(self._estado.get("resolucion", self.resolucion))
            es_sim = self.fuente == "sintetico"

        if usar_aruco:
            mapa = {m["id"]: m["esquinas_px"] for m in marcadores_actuales}
            faltan = [i for i in IDS_PLACA_ESPERADOS if i not in mapa]
            if faltan:
                raise ValueError(
                    f"Para auto-seleccionar con ArUco deben verse los 4 marcadores. Faltan IDs: {faltan}"
                )
            esquinas_px = [
                mapa[0][0],
                mapa[1][1],
                mapa[2][2],
                mapa[3][3],
            ]
            origen = "aruco_4_marcadores"
        else:
            esquinas_px = payload.get("esquinas_px")
            origen = "manual_4_esquinas"

        cal = calcular_homografia_y_escala(esquinas_px, ancho_mm, alto_mm, origen=origen)
        cal["schema_version"] = "2.0"
        cal["resolucion_calibracion"] = resolucion_actual
        cal["es_simulacion"] = es_sim
        cal["modo"] = MODO_VIRTUAL if es_sim else MODO_FISICA
        cal["estado"] = ESTADO_CALIBRACION_VIRTUAL_VALIDA if es_sim else ESTADO_CALIBRACION_FISICA_PENDIENTE
        cal["advertencia_seguridad"] = "Calibración virtual en entorno simulado. NO válida para control físico del robot ABB IRB 140."
        cal["motivos_invalidez"] = []
        cal["error_ajuste"] = {
            "rms_mm": cal.get("error_reproyeccion_mm", 0.0),
            "max_mm": cal.get("error_reproyeccion_mm", 0.0),
            "rms_px": cal.get("error_reproyeccion_px", 0.0),
        }
        cal["error_validacion_independiente"] = {
            "num_puntos_validacion": 0,
            "rms_mm": None,
            "max_mm": None,
            "estado": "pendiente_validacion_independiente",
        }
        cal["escala_estimada"] = cal.get("escala")
        cal["fecha_calculo"] = cal.get("fecha")

        with self._lock:
            self._calibracion = cal
            self._estado["calibracion_homografia"] = dict(cal)
            self._guardar_calibracion_disco()

        return dict(cal)

    def validar_distancia_con_homografia(self, payload):
        with self._lock:
            cal = dict(self._calibracion)

        if not cal.get("valida") or not cal.get("homografia_px_a_mm"):
            raise ValueError("Primero debes calcular la homografía con las 4 esquinas.")

        puntos_px = payload.get("puntos_px")
        if not isinstance(puntos_px, list) or len(puntos_px) not in (1, 2):
            raise ValueError("Se requiere 'puntos_px' con 1 o 2 puntos [[u1,v1], [u2,v2]].")

        puntos_mm = transformar_puntos_px_a_mm(puntos_px, cal["homografia_px_a_mm"])
        resultado = {
            "puntos_px": [[round(float(p[0]), 2), round(float(p[1]), 2)] for p in puntos_px],
            "puntos_mm": puntos_mm,
        }

        if len(puntos_mm) == 2:
            p1 = np.asarray(puntos_mm[0], dtype=np.float64)
            p2 = np.asarray(puntos_mm[1], dtype=np.float64)
            dist_medida_mm = float(np.linalg.norm(p2 - p1))
            dist_px = float(
                np.linalg.norm(
                    np.asarray(puntos_px[1], dtype=np.float64)
                    - np.asarray(puntos_px[0], dtype=np.float64)
                )
            )
            resultado["distancia_px"] = round(dist_px, 2)
            resultado["distancia_medida_mm"] = round(dist_medida_mm, 2)

            dist_real = payload.get("distancia_real_mm")
            if dist_real is not None and float(dist_real) > 0:
                dist_real_f = float(dist_real)
                err_abs = abs(dist_medida_mm - dist_real_f)
                err_pct = (err_abs / dist_real_f) * 100.0
                validacion = {
                    "puntos_px": resultado["puntos_px"],
                    "puntos_mm": puntos_mm,
                    "distancia_px": resultado["distancia_px"],
                    "distancia_medida_mm": round(dist_medida_mm, 2),
                    "distancia_real_mm": round(dist_real_f, 2),
                    "error_absoluto_mm": round(err_abs, 2),
                    "error_porcentual": round(err_pct, 2),
                    "fecha": datetime.now().isoformat(timespec="seconds"),
                }
                resultado["validacion"] = validacion
                with self._lock:
                    self._calibracion["validacion_distancia"] = validacion
                    self._estado["calibracion_homografia"] = dict(self._calibracion)
                    self._guardar_calibracion_disco()

        return resultado

    def resetear_calibracion_homografia(self):
        with self._lock:
            self._calibracion = self._crear_calibracion_vacia()
            self._estado["calibracion_homografia"] = dict(self._calibracion)
            self._guardar_calibracion_disco()
        return dict(self._calibracion)

    def _reiniciar_acumuladores_diagnostico(self):
        self._frames_evaluados = 0
        self._frames_completos = 0
        self._frames_parciales = 0
        self._frames_perdidos = 0
        self._ventana_4_de_4 = deque(maxlen=60)
        self._tiempos_ms = deque(maxlen=VENTANA_HISTORIAL)
        self._historial_esquinas = {m_id: deque(maxlen=VENTANA_HISTORIAL) for m_id in IDS_PLACA_ESPERADOS}

    def resetear_diagnostico(self):
        with self._lock:
            self._reiniciar_acumuladores_diagnostico()
            if "diagnostico" in self._estado:
                self._estado["diagnostico"] = self._construir_diagnostico_vacio()
        return self.obtener_estado()

    def _construir_diagnostico_vacio(self):
        return {
            "frames_evaluados": 0,
            "frames_completos": 0,
            "frames_parciales": 0,
            "frames_perdidos": 0,
            "porcentaje_cuatro_marcadores": 0.0,
            "porcentaje_reciente_cuatro_marcadores": 0.0,
            "tiempo_procesamiento_ms": {
                "actual": 0.0,
                "promedio": 0.0,
                "maximo": 0.0,
            },
            "variacion_esquinas_px": {
                "std_global_px": 0.0,
                "max_desplazamiento_px": 0.0,
                "estabilidad": "sin_datos",
                "ventana_muestras": VENTANA_HISTORIAL,
                "por_marcador": {},
            },
            "candidatos_rechazados": 0,
        }

    def _calcular_diagnostico(self, marcadores, estado_det, tiempo_ms, num_rechazados):
        self._frames_evaluados += 1
        es_completo = estado_det == "completa"
        if es_completo:
            self._frames_completos += 1
        elif estado_det == "parcial":
            self._frames_parciales += 1
        else:
            self._frames_perdidos += 1

        self._ventana_4_de_4.append(1 if es_completo else 0)
        self._tiempos_ms.append(float(tiempo_ms))

        vistos_ahora = set()
        for m in marcadores:
            m_id = m["id"]
            if m_id in self._historial_esquinas:
                vistos_ahora.add(m_id)
                self._historial_esquinas[m_id].append(np.asarray(m["esquinas_px"], dtype=np.float64))

        for m_id in IDS_PLACA_ESPERADOS:
            if m_id not in vistos_ahora and len(self._historial_esquinas[m_id]) > 0:
                self._historial_esquinas[m_id].clear()

        por_marcador = {}
        stds_globales = []
        max_globales = []

        for m_id, cola in self._historial_esquinas.items():
            n_muestras = len(cola)
            if n_muestras >= 3:
                arr = np.stack(cola, axis=0)
                media = np.mean(arr, axis=0, keepdims=True)
                desv = np.linalg.norm(arr - media, axis=2)
                std_marker = float(np.sqrt(np.mean(desv ** 2)))
                max_marker = float(np.max(desv))
                stds_globales.append(std_marker)
                max_globales.append(max_marker)
                por_marcador[str(m_id)] = {
                    "std_px": round(std_marker, 3),
                    "max_px": round(max_marker, 3),
                    "muestras": n_muestras,
                }
            elif n_muestras > 0:
                por_marcador[str(m_id)] = {
                    "std_px": 0.0,
                    "max_px": 0.0,
                    "muestras": n_muestras,
                }

        std_global = round(float(np.mean(stds_globales)), 3) if stds_globales else 0.0
        max_global = round(float(np.max(max_globales)), 3) if max_globales else 0.0

        if not stds_globales:
            estabilidad = "sin_datos"
        elif std_global < 0.75:
            estabilidad = "estable"
        elif std_global < 2.5:
            estabilidad = "moderada"
        else:
            estabilidad = "inestable"

        pct_total = (
            round((self._frames_completos / self._frames_evaluados) * 100.0, 1)
            if self._frames_evaluados > 0
            else 0.0
        )
        pct_reciente = (
            round((sum(self._ventana_4_de_4) / len(self._ventana_4_de_4)) * 100.0, 1)
            if self._ventana_4_de_4
            else 0.0
        )

        tiempos_lista = list(self._tiempos_ms)
        return {
            "frames_evaluados": self._frames_evaluados,
            "frames_completos": self._frames_completos,
            "frames_parciales": self._frames_parciales,
            "frames_perdidos": self._frames_perdidos,
            "porcentaje_cuatro_marcadores": pct_total,
            "porcentaje_reciente_cuatro_marcadores": pct_reciente,
            "tiempo_procesamiento_ms": {
                "actual": round(float(tiempo_ms), 2),
                "promedio": round(float(np.mean(tiempos_lista)), 2) if tiempos_lista else 0.0,
                "maximo": round(float(np.max(tiempos_lista)), 2) if tiempos_lista else 0.0,
            },
            "variacion_esquinas_px": {
                "std_global_px": std_global,
                "max_desplazamiento_px": max_global,
                "estabilidad": estabilidad,
                "ventana_muestras": VENTANA_HISTORIAL,
                "por_marcador": por_marcador,
            },
            "candidatos_rechazados": num_rechazados,
        }

    def _asegurar_hilo(self):
        if self._hilo is None or not self._hilo.is_alive():
            self._hilo = threading.Thread(target=self._bucle_trabajador, daemon=True)
            self._hilo.start()

    def _crear_estado_base(self):
        es_sim = self.fuente == "sintetico"
        return {
            "activa": self.activa,
            "fuente": self.fuente,
            "es_simulacion": es_sim,
            "apto_calibracion_fisica": False,
            "motivo_bloqueo_fisico": (
                "Modo sintético activo: solo para pruebas de interfaz y detección."
                if es_sim
                else "Calibración mesa-robot (wobj) aún no validada físicamente."
            ),
            "indice_camara": self.indice_camara,
            "diccionario": self.diccionario,
            "resolucion": list(self.resolucion),
            "autofocus": self.autofocus,
            "marcadores_esperados": list(IDS_PLACA_ESPERADOS),
            "marcadores_simulados": list(self.marcadores_simulados),
            "marcadores_detectados": [],
            "cantidad_detectados": 0,
            "ids_detectados": [],
            "ids_faltantes": list(IDS_PLACA_ESPERADOS),
            "estado_deteccion": "inactiva",
            "fps": 0.0,
            "error_camara": None,
            "ultima_actualizacion": None,
            "diagnostico": self._construir_diagnostico_vacio(),
            "geometria_placa": dict(self.geometria_placa),
            "calibracion_virtual": dict(self._calibracion),
            "calibracion_homografia": dict(self._calibracion),
            "modo_calibracion": self._calibracion.get("modo", MODO_VIRTUAL),
            "estado_calibracion": self._calibracion.get("estado", ESTADO_SIN_CALIBRAR),
        }

    def iniciar(self):
        with self._lock:
            self.activa = True
            if self.fuente == "sintetico":
                frame_init = generar_frame_sintetico(
                    ancho=self.resolucion[0],
                    alto=self.resolucion[1],
                    nombre_diccionario=self.diccionario,
                    ids_visibles=list(self.marcadores_simulados),
                    geometria=dict(self.geometria_placa),
                    incluir_piezas=True,
                )
                ok, buf = cv2.imencode(".jpg", frame_init, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if ok:
                    bytes_init = buf.tobytes()
                    self._ultimo_jpeg = bytes_init
                    self._ultimo_jpeg_crudo = bytes_init
            else:
                frame_espera = self._generar_frame_mensaje(
                    f"Iniciando camara fisica #{self.indice_camara}...",
                    color=(255, 200, 0),
                )
                ok, buf = cv2.imencode(".jpg", frame_espera, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                if ok:
                    self._ultimo_jpeg = buf.tobytes()

        self._asegurar_hilo()
        self._evento_despertar.set()

    def detener(self):
        with self._lock:
            self.activa = False
            self._estado["activa"] = False
            self._estado["fps"] = 0.0
            self._estado["estado_deteccion"] = "inactiva"
        self._evento_despertar.set()

    def configurar(self, payload):
        fuente = payload.get("fuente", self.fuente)
        if fuente not in ("sintetico", "camara_fisica"):
            raise ValueError("El campo 'fuente' debe ser 'sintetico' o 'camara_fisica'.")

        diccionario = payload.get("diccionario", self.diccionario)
        if diccionario not in DICCIONARIOS_ARUCO:
            raise ValueError(
                f"Diccionario '{diccionario}' inválido. Opciones: {list(DICCIONARIOS_ARUCO.keys())}"
            )

        indice_camara = payload.get("indice_camara", self.indice_camara)
        if not isinstance(indice_camara, int) or isinstance(indice_camara, bool) or indice_camara < 0:
            raise ValueError("El campo 'indice_camara' debe ser un entero mayor o igual a 0.")

        resolucion = payload.get("resolucion", self.resolucion)
        if (
            not isinstance(resolucion, (list, tuple))
            or len(resolucion) != 2
            or not all(isinstance(v, int) and 160 <= v <= 3840 for v in resolucion)
        ):
            raise ValueError("El campo 'resolucion' debe ser [ancho, alto] en píxeles.")

        marcadores_sim = payload.get("marcadores_simulados", self.marcadores_simulados)
        if not isinstance(marcadores_sim, list) or not all(
            isinstance(m, int) and m in IDS_PLACA_ESPERADOS for m in marcadores_sim
        ):
            raise ValueError(f"'marcadores_simulados' solo admite subconjuntos de {IDS_PLACA_ESPERADOS}.")

        autofocus = bool(payload.get("autofocus", self.autofocus))
        activa = payload.get("activa", True)
        if not isinstance(activa, bool):
            raise ValueError("El campo 'activa' debe ser booleano.")

        with self._lock:
            cambio_fuente = (
                fuente != self.fuente
                or indice_camara != self.indice_camara
                or list(resolucion) != self.resolucion
            )
            self.fuente = fuente
            self.diccionario = diccionario
            self.indice_camara = indice_camara
            self.resolucion = [int(resolucion[0]), int(resolucion[1])]
            self.autofocus = autofocus
            self.marcadores_simulados = sorted(list(set(marcadores_sim)))
            self.activa = activa
            if cambio_fuente or payload.get("reset_diagnostico"):
                self._reiniciar_acumuladores_diagnostico()
            if not activa:
                self._estado["activa"] = False
                self._estado["fps"] = 0.0
                self._estado["estado_deteccion"] = "inactiva"

        if activa:
            self._asegurar_hilo()
        self._evento_despertar.set()
        return self.obtener_estado()

    def _abrir_camara_segura(self, indice, resolucion, autofocus):
        cap = None
        try:
            cap = cv2.VideoCapture(indice, cv2.CAP_DSHOW)
            if not cap or not cap.isOpened():
                if cap:
                    cap.release()
                cap = cv2.VideoCapture(indice)

            if not cap or not cap.isOpened():
                if cap:
                    cap.release()
                return None

            for prop, val in (
                (cv2.CAP_PROP_BUFFERSIZE, 1),
                (cv2.CAP_PROP_FRAME_WIDTH, resolucion[0]),
                (cv2.CAP_PROP_FRAME_HEIGHT, resolucion[1]),
                (cv2.CAP_PROP_FPS, 30),
                (cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")),
                (cv2.CAP_PROP_AUTOFOCUS, 1 if autofocus else 0),
            ):
                try:
                    cap.set(prop, val)
                except Exception:
                    pass

            return cap
        except Exception:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            return None

    def _cerrar_camara_segura(self, cap):
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

    def _bucle_trabajador(self):
        cap_actual = None
        cfg_cam_activa = None
        error_camara = None
        t_prev = time.perf_counter()
        fps_suavizado = 0.0

        while True:
            with self._lock:
                activa = self.activa
                fuente = self.fuente
                indice = self.indice_camara
                resolucion = list(self.resolucion)
                autofocus = self.autofocus
                diccionario = self.diccionario
                simulados = list(self.marcadores_simulados)

            if not activa:
                if cap_actual is not None:
                    self._cerrar_camara_segura(cap_actual)
                    cap_actual = None
                    cfg_cam_activa = None
                self._evento_despertar.wait(timeout=0.5)
                self._evento_despertar.clear()
                continue

            if fuente == "sintetico":
                if cap_actual is not None:
                    self._cerrar_camara_segura(cap_actual)
                    cap_actual = None
                    cfg_cam_activa = None
                with self._lock:
                    geo_actual = dict(self.geometria_placa)
                frame = generar_frame_sintetico(
                    ancho=resolucion[0],
                    alto=resolucion[1],
                    nombre_diccionario=diccionario,
                    ids_visibles=simulados,
                    geometria=geo_actual,
                    incluir_piezas=True,
                )
                error_camara = None
            else:
                cfg_deseada = (indice, resolucion[0], resolucion[1], autofocus)
                if cap_actual is None or cfg_cam_activa != cfg_deseada:
                    self._cerrar_camara_segura(cap_actual)
                    frame_init = self._generar_frame_mensaje(
                        f"Abriendo camara USB #{indice} ({resolucion[0]}x{resolucion[1]} MJPG)...",
                        resolucion,
                        color=(255, 200, 0),
                    )
                    self._actualizar_frame_y_estado(frame_init, [], 0.0, None, 0.0, 0, contar_diagnostico=False)
                    cap_actual = self._abrir_camara_segura(indice, resolucion, autofocus)
                    cfg_cam_activa = cfg_deseada
                    t_prev = time.perf_counter()
                    fps_suavizado = 0.0
                    if cap_actual is None:
                        error_camara = (
                            f"No se pudo abrir la cámara física #{indice}. "
                            "Prueba otro índice (#0, #1) o verifica que no esté ocupada."
                        )

                if cap_actual is None:
                    with self._lock:
                        geo_actual = dict(self.geometria_placa)
                    frame = generar_frame_sintetico(
                        ancho=resolucion[0],
                        alto=resolucion[1],
                        nombre_diccionario=diccionario,
                        ids_visibles=simulados,
                        geometria=geo_actual,
                        incluir_piezas=True,
                    )
                    error_camara = (
                        f"Cámara física #{indice} no detectada. Operando en modo sintético de respaldo."
                    )
                    self._actualizar_frame_y_estado(frame, [], 0.0, error_camara, 0.0, 0, contar_diagnostico=False)
                    time.sleep(0.05)
                    continue

                try:
                    ok, frame_leido = cap_actual.read()
                except Exception:
                    ok, frame_leido = False, None

                if not ok or frame_leido is None:
                    error_camara = f"Sin señal de video en cámara #{indice}."
                    frame = self._generar_frame_mensaje(
                        error_camara, resolucion, color=(80, 80, 255)
                    )
                    self._actualizar_frame_y_estado(frame, [], 0.0, error_camara, 0.0, 0, contar_diagnostico=False)
                    time.sleep(0.2)
                    continue

                frame = frame_leido
                error_camara = None

            try:
                marcadores, frame_anotado, tiempo_ms, num_rechazados = detectar_marcadores_aruco(
                    frame, diccionario, devolver_metricas=True
                )
            except Exception as e:
                marcadores = []
                frame_anotado = frame.copy()
                tiempo_ms = 0.0
                num_rechazados = 0
                error_camara = str(e)

            t_actual = time.perf_counter()
            dt = max(t_actual - t_prev, 1e-4)
            t_prev = t_actual
            fps_inst = 1.0 / dt
            fps_suavizado = (
                fps_inst if fps_suavizado == 0.0 else (0.75 * fps_suavizado + 0.25 * fps_inst)
            )

            self._actualizar_frame_y_estado(
                frame_anotado,
                marcadores,
                fps_suavizado,
                error_camara,
                tiempo_ms,
                num_rechazados,
                contar_diagnostico=True,
                frame_crudo=frame,
            )
            if fuente == "sintetico":
                time.sleep(0.03)

    def _generar_frame_mensaje(self, mensaje, resolucion=None, color=(80, 80, 255)):
        ancho, alto = resolucion if resolucion else self.resolucion
        img = np.full((alto, ancho, 3), (20, 20, 28), dtype=np.uint8)
        cv2.putText(
            img,
            mensaje,
            (40, alto // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            color,
            2,
            cv2.LINE_AA,
        )
        return img

    def _actualizar_frame_y_estado(
        self,
        frame_anotado,
        marcadores,
        fps,
        error_camara,
        tiempo_ms=0.0,
        num_rechazados=0,
        contar_diagnostico=True,
        frame_crudo=None,
    ):
        h, w = frame_anotado.shape[:2]
        if w > 1280:
            frame_stream = cv2.resize(frame_anotado, (960, int(h * 960 / w)), interpolation=cv2.INTER_AREA)
        else:
            frame_stream = frame_anotado

        ok, buffer = cv2.imencode(".jpg", frame_stream, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        jpeg_bytes = buffer.tobytes() if ok else None

        jpeg_crudo_bytes = None
        if frame_crudo is not None:
            ok_c, buf_c = cv2.imencode(".jpg", frame_crudo, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if ok_c:
                jpeg_crudo_bytes = buf_c.tobytes()

        ids_detectados = [m["id"] for m in marcadores]
        ids_esperados_visibles = [i for i in IDS_PLACA_ESPERADOS if i in ids_detectados]
        ids_faltantes = [i for i in IDS_PLACA_ESPERADOS if i not in ids_detectados]

        if error_camara:
            estado_det = "error_camara"
        elif len(ids_esperados_visibles) == len(IDS_PLACA_ESPERADOS):
            estado_det = "completa"
        elif len(ids_esperados_visibles) > 0:
            estado_det = "parcial"
        else:
            estado_det = "perdida"

        with self._lock:
            if not self.activa:
                return
            es_sim = self.fuente == "sintetico"
            if jpeg_bytes is not None:
                self._ultimo_jpeg = jpeg_bytes
            if jpeg_crudo_bytes is not None:
                self._ultimo_jpeg_crudo = jpeg_crudo_bytes

            if contar_diagnostico and not error_camara:
                diagnostico = self._calcular_diagnostico(
                    marcadores, estado_det, tiempo_ms, num_rechazados
                )
            else:
                diagnostico = self._estado.get("diagnostico", self._construir_diagnostico_vacio())

            self._estado = {
                "activa": self.activa,
                "fuente": self.fuente,
                "es_simulacion": es_sim,
                "apto_calibracion_fisica": False,
                "motivo_bloqueo_fisico": (
                    "Modo sintético activo: solo para pruebas de interfaz y detección."
                    if es_sim
                    else "Calibración mesa-robot (wobj) aún no validada físicamente."
                ),
                "indice_camara": self.indice_camara,
                "diccionario": self.diccionario,
                "resolucion": [w, h],
                "autofocus": self.autofocus,
                "marcadores_esperados": list(IDS_PLACA_ESPERADOS),
                "marcadores_simulados": list(self.marcadores_simulados),
                "marcadores_detectados": marcadores,
                "cantidad_detectados": len(marcadores),
                "ids_detectados": ids_detectados,
                "ids_faltantes": ids_faltantes,
                "estado_deteccion": estado_det,
                "fps": round(float(fps), 1),
                "error_camara": error_camara,
                "ultima_actualizacion": datetime.now().isoformat(timespec="seconds"),
                "diagnostico": diagnostico,
                "geometria_placa": dict(self.geometria_placa),
                "calibracion_virtual": dict(self._calibracion),
                "calibracion_homografia": dict(self._calibracion),
                "modo_calibracion": self._calibracion.get("modo", MODO_VIRTUAL),
                "estado_calibracion": self._calibracion.get("estado", ESTADO_SIN_CALIBRAR),
            }

    def obtener_estado(self):
        with self._lock:
            return dict(self._estado)

    def obtener_jpeg(self, crudo=False):
        with self._lock:
            if crudo and self._ultimo_jpeg_crudo is not None:
                return self._ultimo_jpeg_crudo
            return self._ultimo_jpeg


gestor_vision = GestorVision()


@vision_bp.route("/api/vision/estado", methods=["GET"])
def obtener_estado_vision():
    return jsonify({
        "success": True,
        "vision": gestor_vision.obtener_estado(),
        "diccionarios_disponibles": list(DICCIONARIOS_ARUCO.keys()),
    })


@vision_bp.route("/api/vision/diagnostico/reset", methods=["POST"])
def resetear_diagnostico_vision():
    return jsonify({
        "success": True,
        "vision": gestor_vision.resetear_diagnostico(),
    })


@vision_bp.route("/api/vision/homografia/calcular", methods=["POST"])
def endpoint_calcular_homografia():
    try:
        data = request.get_json(silent=True) or {}
        cal = gestor_vision.calcular_calibracion_cuatro_esquinas(data)
        return jsonify({
            "success": True,
            "calibracion": cal,
            "vision": gestor_vision.obtener_estado(),
        })
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Error calculando homografía: {str(e)}"}), 500


@vision_bp.route("/api/vision/homografia/validar", methods=["POST"])
def endpoint_validar_distancia():
    try:
        data = request.get_json(silent=True) or {}
        res = gestor_vision.validar_distancia_con_homografia(data)
        return jsonify({
            "success": True,
            "resultado": res,
            "vision": gestor_vision.obtener_estado(),
        })
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Error validando distancia: {str(e)}"}), 500


@vision_bp.route("/api/vision/homografia/reset", methods=["POST"])
def endpoint_reset_homografia():
    cal = gestor_vision.resetear_calibracion_homografia()
    return jsonify({
        "success": True,
        "calibracion": cal,
        "vision": gestor_vision.obtener_estado(),
    })


@vision_bp.route("/api/vision/configurar", methods=["POST"])
def configurar_vision():
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({
                "success": False,
                "error": "Se requiere un cuerpo JSON válido.",
            }), 400

        nuevo_estado = gestor_vision.configurar(data)
        return jsonify({
            "success": True,
            "vision": nuevo_estado,
        })
    except ValueError as ve:
        return jsonify({
            "success": False,
            "error": str(ve),
        }), 400
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Error interno en configuración de visión: {str(e)}",
        }), 500


@vision_bp.route("/api/vision/frame", methods=["GET"])
def obtener_frame_individual():
    if not gestor_vision.activa:
        gestor_vision.iniciar()
    crudo = request.args.get("crudo", "0") in ("1", "true", "True")
    jpeg = gestor_vision.obtener_jpeg(crudo=crudo)
    if jpeg is None:
        return Response(status=204)
    resp = Response(jpeg, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@vision_bp.route("/api/vision/capturar", methods=["POST"])
def capturar_frame():
    if not gestor_vision.activa:
        gestor_vision.iniciar()
    jpeg = gestor_vision.obtener_jpeg()
    if jpeg is None:
        return jsonify({"success": False, "error": "No hay fotograma disponible de la camara"}), 503

    workspace_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "python_workspace", "capturas")
    os.makedirs(workspace_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"captura_{ts}.jpg"
    filepath = os.path.join(workspace_dir, filename)
    with open(filepath, "wb") as f:
        f.write(jpeg)

    return jsonify({
        "success": True,
        "filename": filename,
        "rel_path": f"capturas/{filename}"
    })


@vision_bp.route("/api/vision/iniciar", methods=["POST"])
def endpoint_iniciar_vision():
    gestor_vision.iniciar()
    return jsonify({"success": True, "vision": gestor_vision.obtener_estado()})


@vision_bp.route("/api/vision/detener", methods=["POST"])
def endpoint_detener_vision():
    gestor_vision.detener()
    return jsonify({"success": True, "vision": gestor_vision.obtener_estado()})


@vision_bp.route("/api/vision/stream", methods=["GET"])
def stream_video():
    if not gestor_vision.activa:
        gestor_vision.iniciar()

    def generar():
        ultimo_enviado = None
        try:
            while gestor_vision.activa:
                jpeg = gestor_vision.obtener_jpeg()
                if jpeg is not None and jpeg is not ultimo_enviado:
                    ultimo_enviado = jpeg
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                    )
                _async_sleep(0.03)
        except (GeneratorExit, ConnectionResetError, BrokenPipeError, Exception):
            pass

    resp = Response(
        generar(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@vision_bp.route("/api/vision/calibracion/geometria", methods=["GET", "POST"])
def endpoint_geometria_calibracion():
    if request.method == "GET":
        return jsonify({
            "success": True,
            "geometria": gestor_vision.obtener_geometria_placa(),
        })
    try:
        data = request.get_json(silent=True) or {}
        geo = gestor_vision.actualizar_geometria_placa(data)
        return jsonify({
            "success": True,
            "geometria": geo,
            "vision": gestor_vision.obtener_estado(),
        })
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Error actualizando geometría: {str(e)}"}), 500


@vision_bp.route("/api/vision/calibracion/calcular", methods=["POST"])
def endpoint_calcular_calibracion_virtual():
    try:
        data = request.get_json(silent=True) or {}
        cal = gestor_vision.calcular_calibracion_mesa(data)
        return jsonify({
            "success": True,
            "calibracion": cal,
            "vision": gestor_vision.obtener_estado(),
        })
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Error en cálculo de calibración: {str(e)}"}), 500


@vision_bp.route("/api/vision/calibracion/transformar/px-a-mm", methods=["POST"])
def endpoint_transformar_px_a_mm():
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"success": False, "error": "Se requiere un cuerpo JSON con coordenadas de imagen."}), 400
        res = gestor_vision.transformar_px_a_mm(data)
        return jsonify({
            "success": True,
            "resultado": res,
        })
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Error en transformación px->mm: {str(e)}"}), 500


@vision_bp.route("/api/vision/calibracion/transformar/mm-a-px", methods=["POST"])
def endpoint_transformar_mm_a_px():
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"success": False, "error": "Se requiere un cuerpo JSON con coordenadas de mesa en mm."}), 400
        res = gestor_vision.transformar_mm_a_px(data)
        return jsonify({
            "success": True,
            "resultado": res,
        })
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Error en transformación mm->px: {str(e)}"}), 500


@vision_bp.route("/api/vision/calibracion/guardar", methods=["POST"])
def endpoint_guardar_calibracion():
    try:
        gestor_vision._guardar_calibracion_disco()
        return jsonify({
            "success": True,
            "mensaje": "Configuración y calibración guardadas exitosamente en disco.",
            "calibracion": gestor_vision.obtener_calibracion(),
            "geometria": gestor_vision.obtener_geometria_placa(),
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Error guardando calibración: {str(e)}"}), 500


@vision_bp.route("/api/vision/calibracion/invalidar", methods=["POST"])
def endpoint_invalidar_calibracion():
    try:
        data = request.get_json(silent=True) or {}
        motivo = data.get("motivo", "Invalidación manual solicitada.")
        cal = gestor_vision.invalidar_calibracion(motivo)
        return jsonify({
            "success": True,
            "calibracion": cal,
            "vision": gestor_vision.obtener_estado(),
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Error invalidando calibración: {str(e)}"}), 500


@vision_bp.route("/api/vision/calibracion/reset", methods=["POST"])
def endpoint_reset_calibracion_virtual():
    try:
        res = gestor_vision.resetear_calibracion_virtual()
        return jsonify({
            "success": True,
            "resultado": res,
            "vision": gestor_vision.obtener_estado(),
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Error al reiniciar calibración: {str(e)}"}), 500


_ULTIMA_IMAGEN_PROCESADA = None
_socketio_instance = None

def register_vision_socketio(sio):
    global _socketio_instance
    _socketio_instance = sio

@vision_bp.route("/api/vision/procesada", methods=["GET", "POST"])
def endpoint_imagen_procesada():
    global _ULTIMA_IMAGEN_PROCESADA
    capturas_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "python_workspace", "capturas")

    if request.method == "POST":
        if "file" in request.files:
            _ULTIMA_IMAGEN_PROCESADA = request.files["file"].read()
        elif request.data:
            _ULTIMA_IMAGEN_PROCESADA = request.data
        if _ULTIMA_IMAGEN_PROCESADA:
            os.makedirs(capturas_dir, exist_ok=True)
            with open(os.path.join(capturas_dir, "ultima_deteccion.jpg"), "wb") as f:
                f.write(_ULTIMA_IMAGEN_PROCESADA)
            if _socketio_instance is not None:
                piezas_cnt = request.args.get("piezas", None)
                piezas_meta = None
                meta_path = os.path.join(capturas_dir, "ultima_deteccion.json")
                if os.path.isfile(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as mf:
                            piezas_meta = json.load(mf)
                    except Exception:
                        piezas_meta = None
                payload_ws = {
                    "timestamp": time.time(),
                    "piezas_detectadas": int(piezas_cnt) if piezas_cnt is not None else (len(piezas_meta) if piezas_meta else 0),
                }
                if piezas_meta is not None:
                    payload_ws["piezas"] = piezas_meta
                _socketio_instance.emit("vision_procesada", payload_ws)
        return jsonify({"success": True})

    det_path = os.path.join(capturas_dir, "ultima_deteccion.jpg")
    if os.path.exists(det_path):
        try:
            with open(det_path, "rb") as f:
                _ULTIMA_IMAGEN_PROCESADA = f.read()
        except OSError:
            pass

    if _ULTIMA_IMAGEN_PROCESADA is None:
        frame = gestor_vision.obtener_jpeg()
        if frame:
            _ULTIMA_IMAGEN_PROCESADA = frame
        else:
            return Response(status=204)

    resp = Response(_ULTIMA_IMAGEN_PROCESADA, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@vision_bp.route("/api/vision/detectar", methods=["POST"])
def endpoint_detectar_objetos():
    if not gestor_vision.activa:
        gestor_vision.iniciar()
    jpeg = gestor_vision.obtener_jpeg(crudo=True)
    if jpeg is None:
        time.sleep(0.3)
        jpeg = gestor_vision.obtener_jpeg(crudo=True)
    if jpeg is None:
        return jsonify({"success": False, "error": "No hay fotograma de camara disponible"}), 503

    arr = np.frombuffer(jpeg, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        return jsonify({"success": False, "error": "Fallo al decodificar imagen"}), 500

    req_data = request.get_json(silent=True) or {}
    criterio = req_data.get("criterio", "proximidad")

    py_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "python_workspace", "python")
    import sys
    if py_dir not in sys.path:
        sys.path.insert(0, py_dir)

    from detector import detectar_piezas, dibujar_detecciones

    cal = gestor_vision.obtener_calibracion()
    cal["geometria_placa"] = gestor_vision.obtener_geometria_placa()

    piezas_raw = detectar_piezas(frame, calibracion=cal, criterio=criterio)
    anotada = dibujar_detecciones(frame, piezas_raw, calibracion=cal)

    piezas = []
    for p in piezas_raw:
        item = {}
        for k, v in p.items():
            if k in ("crop", "mascara") or isinstance(v, np.ndarray):
                continue
            item[k] = list(v) if isinstance(v, tuple) else v
        piezas.append(item)

    ok, buf = cv2.imencode(".jpg", anotada, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if ok:
        global _ULTIMA_IMAGEN_PROCESADA
        _ULTIMA_IMAGEN_PROCESADA = buf.tobytes()
        capturas_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "python_workspace", "capturas")
        os.makedirs(capturas_dir, exist_ok=True)
        with open(os.path.join(capturas_dir, "ultima_deteccion.jpg"), "wb") as f:
            f.write(_ULTIMA_IMAGEN_PROCESADA)
        with open(os.path.join(capturas_dir, "ultima_deteccion.json"), "w", encoding="utf-8") as mf:
            json.dump(piezas, mf, ensure_ascii=False, indent=2)

        if _socketio_instance is not None:
            _socketio_instance.emit("vision_procesada", {
                "timestamp": time.time(),
                "piezas_detectadas": len(piezas),
                "piezas": piezas
            })

    return jsonify({"success": True, "piezas_detectadas": len(piezas), "piezas": piezas})


