

import numpy as np
from typing import List, Dict, Any
from scipy.spatial.transform import Slerp, Rotation

def interpolar_joints(q_inicio: List[float], q_fin: List[float], num_pasos: int = 20) -> List[List[float]]:
    
    q_inicio = np.array(q_inicio)
    q_fin = np.array(q_fin)

    min_len = min(len(q_inicio), len(q_fin))
    q_inicio = q_inicio[:min_len]
    q_fin = q_fin[:min_len]

    trayectoria = []
    for i in range(num_pasos + 1):
        t = i / num_pasos
        q_intermedio = q_inicio + t * (q_fin - q_inicio)
        trayectoria.append(q_intermedio.tolist())
    
    return trayectoria

def interpolar_lineal_cartesiano(
    pos_inicio: List[float], 
    quat_inicio: List[float],
    pos_fin: List[float], 
    quat_fin: List[float],
    num_pasos: int = 20
) -> List[Dict[str, Any]]:
    pos_inicio = np.array(pos_inicio)
    pos_fin = np.array(pos_fin)
    trayectoria = []

    q_ini_scipy = [quat_inicio[1], quat_inicio[2], quat_inicio[3], quat_inicio[0]]
    q_fin_scipy = [quat_fin[1], quat_fin[2], quat_fin[3], quat_fin[0]]

    rot_inicio = Rotation.from_quat(q_ini_scipy)
    rot_fin = Rotation.from_quat(q_fin_scipy)
    
    tiempos = np.linspace(0, 1, num_pasos + 1)
    slerp = Slerp([0, 1], Rotation.concatenate([rot_inicio, rot_fin]))
    
    for t in tiempos:
        pos_intermedia = pos_inicio + t * (pos_fin - pos_inicio)
        q_scipy = slerp([t])[0].as_quat()
        q_rapid = [float(q_scipy[3]), float(q_scipy[0]), float(q_scipy[1]), float(q_scipy[2])]
        
        trayectoria.append({
            'position': pos_intermedia.tolist(),
            'quaternion': q_rapid
        })
    
    return trayectoria

def interpolar_circular(
    pos_inicio: List[float],
    quat_inicio: List[float],
    pos_via: List[float],
    quat_via: List[float],
    pos_fin: List[float],
    quat_fin: List[float],
    num_pasos: int = 30
) -> List[Dict[str, Any]]:
    
    p1 = np.array(pos_inicio)
    p2 = np.array(pos_via)
    p3 = np.array(pos_fin)

    centro, radio = calcular_circulo_3_puntos(p1, p2, p3)

    v_12 = p2 - p1
    v_13 = p3 - p1
    cross_p = np.cross(v_12, v_13)
    
    if centro is None or np.linalg.norm(cross_p) < 1e-6:

        print("Puntos colineales en MoveC, usando interpolación lineal")
        return interpolar_lineal_cartesiano(pos_inicio, quat_inicio, pos_fin, quat_fin, num_pasos)
        
    normal = cross_p / np.linalg.norm(cross_p)

    v1 = p1 - centro
    v3 = p3 - centro
    
    sin_total = np.dot(np.cross(v1, v3), normal)
    cos_total = np.dot(v1, v3)
    angulo_total = np.arctan2(sin_total, cos_total)

    if angulo_total <= 0:
        angulo_total += 2 * np.pi

    trayectoria = []

    q_ini_scipy = [quat_inicio[1], quat_inicio[2], quat_inicio[3], quat_inicio[0]]
    q_fin_scipy = [quat_fin[1], quat_fin[2], quat_fin[3], quat_fin[0]]
    rot_inicio = Rotation.from_quat(q_ini_scipy)
    rot_fin = Rotation.from_quat(q_fin_scipy)
    slerp = Slerp([0, 1], Rotation.concatenate([rot_inicio, rot_fin]))
    
    for i in range(num_pasos + 1):
        t = i / num_pasos
        angulo = angulo_total * t

        pos_intermedia = centro + rotar_vector(v1, normal, angulo)
        q_scipy = slerp([t])[0].as_quat()
        q_rapid = [float(q_scipy[3]), float(q_scipy[0]), float(q_scipy[1]), float(q_scipy[2])]
        
        trayectoria.append({
            'position': pos_intermedia.tolist(),
            'quaternion': q_rapid
        })
    
    return trayectoria

def calcular_circulo_3_puntos(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray):

    v1 = p2 - p1
    v2 = p3 - p1

    cross = np.cross(v1, v2)
    if np.linalg.norm(cross) < 1e-6:
        return None, None

    normal = cross / np.linalg.norm(cross)

    m1 = (p1 + p2) / 2
    m2 = (p1 + p3) / 2

    perp1 = np.cross(v1, normal)
    perp2 = np.cross(v2, normal)

    A = np.column_stack([perp1, -perp2])
    b = m2 - m1
    
    try:

        u1 = v1 / np.linalg.norm(v1)
        u2 = np.cross(normal, u1)

        m1_2d = np.array([np.dot(m1 - p1, u1), np.dot(m1 - p1, u2)])
        m2_2d = np.array([np.dot(m2 - p1, u1), np.dot(m2 - p1, u2)])
        perp1_2d = np.array([np.dot(perp1, u1), np.dot(perp1, u2)])
        perp2_2d = np.array([np.dot(perp2, u1), np.dot(perp2, u2)])
        
        A_2d = np.column_stack([perp1_2d, -perp2_2d])
        b_2d = m2_2d - m1_2d
        
        t = np.linalg.solve(A_2d, b_2d)

        centro = m1 + t[0] * perp1
        radio = np.linalg.norm(p1 - centro)
        
        return centro, radio
    except:
        return None, None

def rotar_vector(v: np.ndarray, eje: np.ndarray, angulo: float) -> np.ndarray:
    
    cos_ang = np.cos(angulo)
    sin_ang = np.sin(angulo)
    
    return (v * cos_ang + 
            np.cross(eje, v) * sin_ang + 
            eje * np.dot(eje, v) * (1 - cos_ang))

def calcular_num_pasos_por_velocidad(velocidad: str, distancia: float = None) -> int:
    import re
    match = re.search(r'v(\d+)', velocidad.lower())
    
    if match:
        vel_mm_s = float(match.group(1))
    elif 'max' in velocidad.lower():
        vel_mm_s = 2000.0
    else:
        vel_mm_s = 1000.0

    if vel_mm_s <= 0:
        vel_mm_s = 1000.0

    tiempo_por_paso = 0.04
    
    if distancia is not None:
        if distancia < 1.0:
            return 2
        tiempo_total = distancia / vel_mm_s
        pasos = tiempo_total / tiempo_por_paso
    else:
        tiempo_total = 300.0 / vel_mm_s
        pasos = tiempo_total / tiempo_por_paso

    return min(max(int(round(pasos)), 2), 500)
