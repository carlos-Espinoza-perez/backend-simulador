import json
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

ESTADO_SIN_CALIBRAR = "SIN_CALIBRAR"
ESTADO_CONFIGURACION_INCOMPLETA = "CONFIGURACION_INCOMPLETA"
ESTADO_CALCULANDO = "CALCULANDO"
ESTADO_CALIBRACION_VIRTUAL_VALIDA = "CALIBRACION_VIRTUAL_VALIDA"
ESTADO_CALIBRACION_FISICA_PENDIENTE = "CALIBRACION_FISICA_PENDIENTE"
ESTADO_CALIBRACION_FISICA_VALIDADA = "CALIBRACION_FISICA_VALIDADA"
ESTADO_CALIBRACION_INVALIDA = "CALIBRACION_INVALIDA"

MODO_VIRTUAL = "virtual"
MODO_FISICA = "fisica"


def obtener_geometria_defecto() -> Dict[str, Any]:
    return {
        "id_configuracion": "mesa_trabajo_defecto",
        "unidades": "mm",
        "dimensiones_mm": {
            "ancho": 400.0,
            "alto": 300.0,
        },
        "origen_sistema": "esquina_superior_izquierda",
        "direccion_ejes": {
            "eje_x": "hacia_la_derecha",
            "eje_y": "hacia_abajo",
        },
        "es_demostracion": True,
        "marcadores": [
            {
                "id": 0,
                "centro_mm": [40.0, 40.0],
                "tamano_mm": 50.0,
                "orientacion_deg": 0.0,
            },
            {
                "id": 1,
                "centro_mm": [360.0, 40.0],
                "tamano_mm": 50.0,
                "orientacion_deg": 0.0,
            },
            {
                "id": 2,
                "centro_mm": [360.0, 260.0],
                "tamano_mm": 50.0,
                "orientacion_deg": 0.0,
            },
            {
                "id": 3,
                "centro_mm": [40.0, 260.0],
                "tamano_mm": 50.0,
                "orientacion_deg": 0.0,
            },
        ],
        "zonas_preparacion": [
            {
                "id": "clasificacion",
                "nombre": "Área de Clasificación",
                "color": "#38bdf8",
                "poligono_mm": [[80.0, 70.0], [320.0, 70.0], [320.0, 230.0], [80.0, 230.0]],
            },
            {
                "id": "pet",
                "nombre": "Depósito PET",
                "color": "#4ade80",
                "poligono_mm": [[15.0, 90.0], [65.0, 90.0], [65.0, 210.0], [15.0, 210.0]],
            },
            {
                "id": "aluminio",
                "nombre": "Depósito Aluminio",
                "color": "#facc15",
                "poligono_mm": [[335.0, 90.0], [385.0, 90.0], [385.0, 210.0], [335.0, 210.0]],
            },
        ],
    }


def calcular_esquinas_marcador_mm(
    centro_mm: List[float],
    tamano_mm: float,
    orientacion_deg: float = 0.0,
) -> List[List[float]]:
    cx, cy = float(centro_mm[0]), float(centro_mm[1])
    mitad = float(tamano_mm) * 0.5
    theta = math.radians(float(orientacion_deg))
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    # Orden canónico ArUco: E0: sup-izq, E1: sup-der, E2: inf-der, E3: inf-izq
    esquinas_locales = [
        (-mitad, -mitad),
        (mitad, -mitad),
        (mitad, mitad),
        (-mitad, mitad),
    ]

    esquinas_globales = []
    for dx, dy in esquinas_locales:
        gx = cx + (dx * cos_t - dy * sin_t)
        gy = cy + (dx * sin_t + dy * cos_t)
        esquinas_globales.append([round(gx, 3), round(gy, 3)])
    return esquinas_globales


def validar_geometria_placa(geometria: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errores = []
    if not isinstance(geometria, dict):
        return False, ["La configuración debe ser un diccionario de datos."]

    dims = geometria.get("dimensiones_mm", {})
    ancho = dims.get("ancho")
    alto = dims.get("alto")

    if ancho is None or not isinstance(ancho, (int, float)) or ancho <= 0 or math.isnan(ancho) or math.isinf(ancho):
        errores.append("El ancho de la placa en mm debe ser un número finito estrictamente positivo.")
    if alto is None or not isinstance(alto, (int, float)) or alto <= 0 or math.isnan(alto) or math.isinf(alto):
        errores.append("El alto de la placa en mm debe ser un número finito estrictamente positivo.")

    marcadores = geometria.get("marcadores", [])
    if not isinstance(marcadores, list) or len(marcadores) < 4:
        errores.append(f"Se requieren al menos 4 marcadores ArUco configurados (recibidos: {len(marcadores) if isinstance(marcadores, list) else 0}).")
        return False, errores

    ids_vistos = set()
    centros_vistos = []
    ancho_f = float(ancho) if ancho and not math.isnan(ancho) and not math.isinf(ancho) and ancho > 0 else None
    alto_f = float(alto) if alto and not math.isnan(alto) and not math.isinf(alto) and alto > 0 else None

    for idx, m in enumerate(marcadores):
        if not isinstance(m, dict):
            errores.append(f"El marcador en el índice {idx} debe ser un objeto estructurado.")
            continue

        m_id = m.get("id")
        if m_id is None or not isinstance(m_id, int) or isinstance(m_id, bool) or m_id < 0:
            errores.append(f"Marcador #{idx}: ID de ArUco debe ser un entero no negativo.")
        elif m_id in ids_vistos:
            errores.append(f"Marcador #{idx}: ID {m_id} duplicado en la configuración de la placa.")
        else:
            ids_vistos.add(m_id)

        centro = m.get("centro_mm")
        if not isinstance(centro, (list, tuple)) or len(centro) != 2:
            errores.append(f"Marcador ID {m_id}: 'centro_mm' debe ser una lista [x, y].")
        else:
            cx, cy = centro[0], centro[1]
            if not all(isinstance(v, (int, float)) and not math.isnan(v) and not math.isinf(v) for v in (cx, cy)):
                errores.append(f"Marcador ID {m_id}: coordenadas del centro deben ser números finitos.")
            else:
                centros_vistos.append((float(cx), float(cy)))
                if ancho_f and (cx < 0.0 or cx > ancho_f):
                    errores.append(f"Marcador ID {m_id}: X={cx} mm fuera de los límites de la placa [0, {ancho_f}].")
                if alto_f and (cy < 0.0 or cy > alto_f):
                    errores.append(f"Marcador ID {m_id}: Y={cy} mm fuera de los límites de la placa [0, {alto_f}].")

        tam = m.get("tamano_mm")
        if tam is None or not isinstance(tam, (int, float)) or tam <= 0 or math.isnan(tam) or math.isinf(tam):
            errores.append(f"Marcador ID {m_id}: 'tamano_mm' debe ser un número positivo finito.")

    if len(centros_vistos) >= 3:
        pts = np.array(centros_vistos, dtype=np.float64)
        area = float(cv2.contourArea(pts.astype(np.float32)))
        if area < 10.0:
            errores.append("La configuración geométrica de los marcadores es colineal o degenerada (área plana casi nula).")

    return (len(errores) == 0), errores


def calcular_homografia_mesa(
    correspondencias_px: List[List[float]],
    correspondencias_mm: List[List[float]],
    puntos_validacion_px: Optional[List[List[float]]] = None,
    puntos_validacion_mm: Optional[List[List[float]]] = None,
    modo: str = MODO_VIRTUAL,
) -> Dict[str, Any]:
    if not isinstance(correspondencias_px, (list, tuple)) or not isinstance(correspondencias_mm, (list, tuple)):
        raise ValueError("Las correspondencias deben ser listas de coordenadas [[u,v], ...] y [[x,y], ...].")

    n_pts = len(correspondencias_px)
    if n_pts != len(correspondencias_mm):
        raise ValueError(f"Discrepancia en cantidad de puntos: px={n_pts} vs mm={len(correspondencias_mm)}.")

    if n_pts < 4:
        raise ValueError(f"Se requieren mínimo 4 correspondencias para homografía planar. Puntos disponibles: {n_pts}.")

    pts_px = np.asarray(correspondencias_px, dtype=np.float64)
    pts_mm = np.asarray(correspondencias_mm, dtype=np.float64)

    if not np.all(np.isfinite(pts_px)) or not np.all(np.isfinite(pts_mm)):
        raise ValueError("Las correspondencias contienen valores NaN o no finitos.")

    if pts_px.shape[1] != 2 or pts_mm.shape[1] != 2:
        raise ValueError("Los puntos deben tener exactamente 2 componentes [u, v] o [x, y].")

    area_px = float(cv2.contourArea(pts_px.astype(np.float32)))
    area_mm = float(cv2.contourArea(pts_mm.astype(np.float32)))
    if area_px < 50.0 or area_mm < 50.0:
        raise ValueError("Las correspondencias forman una geometría colineal o degenerada.")

    metodo = cv2.RANSAC if n_pts > 6 else 0
    H_px_a_mm, mascara = cv2.findHomography(pts_px, pts_mm, method=metodo, ransacReprojThreshold=3.0)
    if H_px_a_mm is None or not np.all(np.isfinite(H_px_a_mm)):
        raise ValueError("cv2.findHomography falló al calcular una matriz de proyección finita.")

    det_H = float(np.linalg.det(H_px_a_mm))
    if abs(det_H) < 1e-12:
        raise ValueError("La matriz de homografía calculada es singular o degenerada (determinante nulo).")

    c22 = H_px_a_mm[2, 2]
    if abs(c22) > 1e-9:
        H_px_a_mm = H_px_a_mm / c22
    else:
        H_px_a_mm = H_px_a_mm / np.linalg.norm(H_px_a_mm)

    try:
        H_mm_a_px = np.linalg.inv(H_px_a_mm)
        c22_inv = H_mm_a_px[2, 2]
        if abs(c22_inv) > 1e-9:
            H_mm_a_px = H_mm_a_px / c22_inv
    except np.linalg.LinAlgError as exc:
        raise ValueError("No fue posible invertir la matriz de homografía.") from exc

    pts_px_h = np.hstack([pts_px, np.ones((n_pts, 1), dtype=np.float64)])
    proy_mm_h = (H_px_a_mm @ pts_px_h.T).T
    w_mm = proy_mm_h[:, 2:3]
    if np.any(np.abs(w_mm) < 1e-9):
        raise ValueError("Inestabilidad proyectiva: puntos de ajuste proyectados al infinito.")
    proy_mm = proy_mm_h[:, :2] / w_mm

    residuos_mm = np.linalg.norm(proy_mm - pts_mm, axis=1)
    rms_ajuste_mm = float(np.sqrt(np.mean(residuos_mm ** 2)))
    max_ajuste_mm = float(np.max(residuos_mm))

    pts_mm_h = np.hstack([pts_mm, np.ones((n_pts, 1), dtype=np.float64)])
    proy_px_h = (H_mm_a_px @ pts_mm_h.T).T
    w_px = proy_px_h[:, 2:3]
    proy_px = proy_px_h[:, :2] / w_px
    residuos_px = np.linalg.norm(proy_px - pts_px, axis=1)
    rms_ajuste_px = float(np.sqrt(np.mean(residuos_px ** 2)))

    metricas_validacion = None
    if (
        puntos_validacion_px is not None
        and puntos_validacion_mm is not None
        and len(puntos_validacion_px) > 0
        and len(puntos_validacion_px) == len(puntos_validacion_mm)
    ):
        v_px = np.asarray(puntos_validacion_px, dtype=np.float64)
        v_mm = np.asarray(puntos_validacion_mm, dtype=np.float64)
        v_px_h = np.hstack([v_px, np.ones((len(v_px), 1), dtype=np.float64)])
        v_proy_h = (H_px_a_mm @ v_px_h.T).T
        v_w = v_proy_h[:, 2:3]
        v_proy = v_proy_h[:, :2] / np.where(np.abs(v_w) < 1e-9, 1e-9, v_w)
        v_err = np.linalg.norm(v_proy - v_mm, axis=1)
        metricas_validacion = {
            "num_puntos_validacion": len(v_px),
            "rms_mm": round(float(np.sqrt(np.mean(v_err ** 2))), 4),
            "max_mm": round(float(np.max(v_err)), 4),
            "estado": "validado_independiente",
        }
    else:
        metricas_validacion = {
            "num_puntos_validacion": 0,
            "rms_mm": None,
            "max_mm": None,
            "estado": "pendiente_validacion_independiente",
        }

    p_centro_px = np.mean(pts_px, axis=0)
    p_c_h = np.array([p_centro_px[0], p_centro_px[1], 1.0], dtype=np.float64)
    p_cx_h = np.array([p_centro_px[0] + 10.0, p_centro_px[1], 1.0], dtype=np.float64)
    p_cy_h = np.array([p_centro_px[0], p_centro_px[1] + 10.0, 1.0], dtype=np.float64)

    m_c = (H_px_a_mm @ p_c_h)[:2] / (H_px_a_mm @ p_c_h)[2]
    m_cx = (H_px_a_mm @ p_cx_h)[:2] / (H_px_a_mm @ p_cx_h)[2]
    m_cy = (H_px_a_mm @ p_cy_h)[:2] / (H_px_a_mm @ p_cy_h)[2]

    escala_x_mm_px = float(np.linalg.norm(m_cx - m_c) / 10.0)
    escala_y_mm_px = float(np.linalg.norm(m_cy - m_c) / 10.0)
    escala_media = (escala_x_mm_px + escala_y_mm_px) * 0.5

    estado_final = (
        ESTADO_CALIBRACION_VIRTUAL_VALIDA
        if modo == MODO_VIRTUAL
        else ESTADO_CALIBRACION_FISICA_PENDIENTE
    )

    return {
        "valida": True,
        "modo": modo,
        "estado": estado_final,
        "apto_para_robot": False,
        "advertencia_seguridad": "Calibración plana de referencia; no válida directamente para mover el robot físico sin calibración wobj/TCP.",
        "num_correspondencias": n_pts,
        "homografia_px_a_mm": [[round(float(v), 9) for v in fila] for fila in H_px_a_mm],
        "homografia_mm_a_px": [[round(float(v), 9) for v in fila] for fila in H_mm_a_px],
        "error_ajuste": {
            "rms_mm": round(rms_ajuste_mm, 4),
            "max_mm": round(max_ajuste_mm, 4),
            "rms_px": round(rms_ajuste_px, 4),
        },
        "error_validacion_independiente": metricas_validacion,
        "escala_estimada": {
            "mm_por_px_x": round(escala_x_mm_px, 4),
            "mm_por_px_y": round(escala_y_mm_px, 4),
            "mm_por_px_media": round(escala_media, 4),
            "px_por_mm_media": round(1.0 / max(escala_media, 1e-9), 3),
        },
        "fecha_calculo": datetime.now().isoformat(timespec="seconds"),
    }


def transformar_punto_a_mesa(
    u: float,
    v: float,
    calibracion: Dict[str, Any],
    dimensiones_mm: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    if u is None or v is None or not isinstance(u, (int, float)) or not isinstance(v, (int, float)):
        raise ValueError("Coordenadas de imagen [u, v] deben ser numéricas.")
    if math.isnan(u) or math.isnan(v) or math.isinf(u) or math.isinf(v):
        raise ValueError("Coordenadas de imagen [u, v] no son finitas.")

    if not isinstance(calibracion, dict) or not calibracion.get("valida"):
        raise ValueError("La calibración suministrada no es válida o está incompleta.")

    H = calibracion.get("homografia_px_a_mm")
    if not H or len(H) != 3:
        raise ValueError("Matriz homografia_px_a_mm ausente en la calibración.")

    H_arr = np.asarray(H, dtype=np.float64)
    pt_h = np.array([float(u), float(v), 1.0], dtype=np.float64)
    proy = H_arr @ pt_h

    w = proy[2]
    if abs(w) < 1e-9 or math.isnan(w) or math.isinf(w):
        raise ValueError("Inestabilidad numérica: denominador proyectivo nulo.")

    x_mm = float(proy[0] / w)
    y_mm = float(proy[1] / w)

    if math.isnan(x_mm) or math.isnan(y_mm) or math.isinf(x_mm) or math.isinf(y_mm):
        raise ValueError("Coordenadas proyectadas en la mesa no son finitas.")

    dentro_area = True
    margen_fuera_mm = 0.0

    if dimensiones_mm and isinstance(dimensiones_mm, dict):
        ancho_max = float(dimensiones_mm.get("ancho", 0.0))
        alto_max = float(dimensiones_mm.get("alto", 0.0))
        if ancho_max > 0.0 and alto_max > 0.0:
            if x_mm < 0.0 or x_mm > ancho_max or y_mm < 0.0 or y_mm > alto_max:
                dentro_area = False
                dx = max(0.0, -x_mm, x_mm - ancho_max)
                dy = max(0.0, -y_mm, y_mm - alto_max)
                margen_fuera_mm = math.hypot(dx, dy)

    return {
        "punto_px": [round(float(u), 2), round(float(v), 2)],
        "punto_mesa_mm": [round(x_mm, 2), round(y_mm, 2)],
        "dentro_area_trabajo": dentro_area,
        "distancia_fuera_mm": round(margen_fuera_mm, 2),
        "unidades": "mm",
        "es_estimacion_planar": True,
    }


def transformar_punto_a_imagen(
    x_mm: float,
    y_mm: float,
    calibracion: Dict[str, Any],
    resolucion_px: Optional[List[int]] = None,
) -> Dict[str, Any]:
    if x_mm is None or y_mm is None or not isinstance(x_mm, (int, float)) or not isinstance(y_mm, (int, float)):
        raise ValueError("Coordenadas de mesa [x_mm, y_mm] deben ser numéricas.")
    if math.isnan(x_mm) or math.isnan(y_mm) or math.isinf(x_mm) or math.isinf(y_mm):
        raise ValueError("Coordenadas de mesa [x_mm, y_mm] no son finitas.")

    if not isinstance(calibracion, dict) or not calibracion.get("valida"):
        raise ValueError("La calibración suministrada no es válida o está incompleta.")

    H_inv = calibracion.get("homografia_mm_a_px")
    if not H_inv or len(H_inv) != 3:
        raise ValueError("Matriz homografia_mm_a_px ausente en la calibración.")

    H_arr = np.asarray(H_inv, dtype=np.float64)
    pt_h = np.array([float(x_mm), float(y_mm), 1.0], dtype=np.float64)
    proy = H_arr @ pt_h

    w = proy[2]
    if abs(w) < 1e-9 or math.isnan(w) or math.isinf(w):
        raise ValueError("Inestabilidad numérica en proyección inversa.")

    u = float(proy[0] / w)
    v = float(proy[1] / w)

    if math.isnan(u) or math.isnan(v) or math.isinf(u) or math.isinf(v):
        raise ValueError("Coordenadas proyectadas en píxeles no son finitas.")

    dentro_imagen = True
    if resolucion_px and len(resolucion_px) == 2:
        w_px, h_px = resolucion_px[0], resolucion_px[1]
        if u < 0.0 or u > w_px or v < 0.0 or v > h_px:
            dentro_imagen = False

    return {
        "punto_mesa_mm": [round(float(x_mm), 2), round(float(y_mm), 2)],
        "punto_px": [round(u, 2), round(v, 2)],
        "dentro_imagen": dentro_imagen,
    }
