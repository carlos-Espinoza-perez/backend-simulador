from collections import deque
import json
import os
import threading
import time
from datetime import datetime
import cv2
import numpy as np
from flask import Blueprint, Response, jsonify, request

try:
    import gevent
    def _async_sleep(segundos):
        gevent.sleep(segundos)
except ImportError:
    def _async_sleep(segundos):
        time.sleep(segundos)

vision_bp = Blueprint("vision", __name__)

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

    # Reproyección para verificar ajuste numérico de la transformación
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


def generar_frame_sintetico(
    ancho=1280,
    alto=720,
    nombre_diccionario="DICT_4X4_50",
    ids_visibles=None,
):
    if ids_visibles is None:
        ids_visibles = IDS_PLACA_ESPERADOS

    aruco_dict = cv2.aruco.getPredefinedDictionary(DICCIONARIOS_ARUCO[nombre_diccionario])
    lienzo = np.full((alto, ancho, 3), (32, 38, 46), dtype=np.uint8)

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
        self.fuente = "camara_fisica"
        self.indice_camara = 0
        self.diccionario = "DICT_4X4_50"
        self.resolucion = [1280, 720]
        self.autofocus = False
        self.marcadores_simulados = [0, 1, 2, 3]
        self._calibracion = self._cargar_calibracion_disco()

        self._reiniciar_acumuladores_diagnostico()
        self._ultimo_jpeg = None
        self._estado = self._crear_estado_base()

    def _crear_calibracion_vacia(self):
        return {
            "valida": False,
            "origen": None,
            "esquinas_px": [],
            "esquinas_mm": [],
            "dimensiones_mm": {"ancho": 220.0, "alto": 140.0},
            "lados_px": None,
            "escala": None,
            "homografia_px_a_mm": None,
            "homografia_mm_a_px": None,
            "error_reproyeccion_px": None,
            "error_reproyeccion_mm": None,
            "validacion_distancia": None,
            "fecha": None,
        }

    def _cargar_calibracion_disco(self):
        if os.path.exists(ARCHIVO_CALIBRACION):
            try:
                with open(ARCHIVO_CALIBRACION, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "valida" in data:
                    return data
            except Exception:
                pass
        return self._crear_calibracion_vacia()

    def _guardar_calibracion_disco(self):
        try:
            with open(ARCHIVO_CALIBRACION, "w", encoding="utf-8") as f:
                json.dump(self._calibracion, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

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
            # Esquinas exteriores del casco: E0 de ID0, E1 de ID1, E2 de ID2, E3 de ID3
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
        cal["resolucion_calibracion"] = resolucion_actual
        cal["es_simulacion"] = es_sim

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
            "calibracion_homografia": dict(self._calibracion),
        }

    def iniciar(self):
        with self._lock:
            self.activa = True
            frame_espera = self._generar_frame_mensaje(
                f"Iniciando {'modo sintetico' if self.fuente == 'sintetico' else f'camara fisica #{self.indice_camara}'}...",
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
                frame = generar_frame_sintetico(
                    ancho=resolucion[0],
                    alto=resolucion[1],
                    nombre_diccionario=diccionario,
                    ids_visibles=simulados,
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
                    frame = self._generar_frame_mensaje(
                        error_camara or f"Cámara #{indice} no disponible",
                        resolucion,
                        color=(80, 80, 255),
                    )
                    self._actualizar_frame_y_estado(frame, [], 0.0, error_camara, 0.0, 0, contar_diagnostico=False)
                    time.sleep(0.3)
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

            if fuente == "sintetico":
                cv2.rectangle(
                    frame_anotado, (0, 0), (frame_anotado.shape[1], 36), (15, 23, 42), -1
                )
                cv2.putText(
                    frame_anotado,
                    "SIMULACION SINTETICA - NO APTO PARA CALIBRACION NI MOVIMIENTO FISICO",
                    (14, 24),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.58,
                    (0, 200, 255),
                    2,
                    cv2.LINE_AA,
                )

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
    ):
        h, w = frame_anotado.shape[:2]
        if w > 1280:
            frame_stream = cv2.resize(frame_anotado, (960, int(h * 960 / w)), interpolation=cv2.INTER_AREA)
        else:
            frame_stream = frame_anotado

        ok, buffer = cv2.imencode(".jpg", frame_stream, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        jpeg_bytes = buffer.tobytes() if ok else None

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
                "calibracion_homografia": dict(self._calibracion),
            }

    def obtener_estado(self):
        with self._lock:
            return dict(self._estado)

    def obtener_jpeg(self):
        with self._lock:
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
    jpeg = gestor_vision.obtener_jpeg()
    if jpeg is None:
        return Response(status=204)
    resp = Response(jpeg, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@vision_bp.route("/api/vision/stream", methods=["GET"])
def stream_video():
    if not gestor_vision.activa:
        gestor_vision.iniciar()

    def generar():
        ultimo_enviado = None
        while gestor_vision.activa:
            jpeg = gestor_vision.obtener_jpeg()
            if jpeg is not None and jpeg is not ultimo_enviado:
                ultimo_enviado = jpeg
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                )
            _async_sleep(0.015)

    return Response(
        generar(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )
