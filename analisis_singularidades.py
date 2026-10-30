
import numpy as np
from typing import Dict, List, Tuple
from cinematica_directa import cinematica_directa

def calcular_jacobiano(joints_deg: List[float], tabla_dh: List[List[float]], tipos_articulaciones: List[str] = None) -> np.ndarray:
    
    num_joints = len(joints_deg)
    if tipos_articulaciones is None:
        tipos_articulaciones = ["R"] * num_joints

    T_final, transformaciones = cinematica_directa(joints_deg, tabla_dh, tipos_articulaciones)

    p_n = T_final[:3, 3]

    J = np.zeros((6, num_joints))

    for i in range(num_joints):

        if i == 0:
            T_i = np.eye(4)
        else:
            T_i = transformaciones[i-1]

        z_i = T_i[:3, 2]

        z_norm = np.linalg.norm(z_i)
        if z_norm > 1e-10:
            z_i = z_i / z_norm
        
        p_i = T_i[:3, 3]
        
        if tipos_articulaciones[i] == 'R':

            J[:3, i] = np.cross(z_i, p_n - p_i)

            J[3:, i] = z_i
        else:

            J[:3, i] = z_i
            J[3:, i] = 0.0

    if np.any(np.isnan(J)) or np.any(np.isinf(J)):

        J = np.zeros((6, num_joints))
    
    return J

def analizar_singularidades(joints_deg: List[float], tabla_dh: List[List[float]], tipos_articulaciones: List[str] = None) -> Dict:
    
    J = calcular_jacobiano(joints_deg, tabla_dh, tipos_articulaciones)
    num_joints = len(joints_deg)

    if np.any(np.isnan(J)) or np.any(np.isinf(J)):

        return {
            "estado_general": "normal",
            "singularidades": {
                "singularidades": [],
                "total": 0
            },
            "metricas": {
                "determinante": 0.0,
                "numero_condicion": 1.0,
                "valores_singulares": [1.0] * min(6, num_joints),
                "manipulabilidad": 1.0
            },
            "limites": {
                "violaciones": [],
                "total": 0
            }
        }

    try:
        if J.shape[0] == J.shape[1]:
            det_J = np.linalg.det(J)
        else:

            det_J = np.sqrt(np.linalg.det(J @ J.T))
            
        if np.isnan(det_J) or np.isinf(det_J):
            det_J = 0.0
    except:
        det_J = 0.0

    try:

        U, s, Vt = np.linalg.svd(J, full_matrices=False)

        if np.any(np.isnan(s)) or np.any(np.isinf(s)):
            raise ValueError("Valores singulares inválidos")
            
    except (np.linalg.LinAlgError, ValueError):

        s = np.array([1.0] * min(6, num_joints))
        cond_number = 1.0
    else:

        if s[-1] > 1e-10:
            cond_number = float(s[0] / s[-1])
        else:
            cond_number = 1e6

    singularidades = []

    if num_joints == 6:

        j5 = joints_deg[4]
        if abs(j5) < 1.0 or abs(abs(j5) - 180) < 1.0:
            singularidades.append({
                "tipo": "Muñeca",
                "descripcion": "J5 cerca de 0° o 180° - ejes J4 y J6 alineados",
                "severidad": "alta",
                "articulaciones": [4, 5, 6],
                "recomendacion": "Evitar J5=0° o J5=180°"
            })
        elif abs(j5) < 3.0: # Advertencia leve
            singularidades.append({
                "tipo": "Cerca de Muñeca",
                "descripcion": "J5 se aproxima a configuración singular",
                "severidad": "baja",
                "articulaciones": [4, 5, 6],
                "recomendacion": "Aumentar ángulo de J5"
            })

        j3 = joints_deg[2]
        if abs(j3 - 50) < 1 or abs(j3 + 52) < 1:
            singularidades.append({
                "tipo": "Límite de Codo",
                "descripcion": "Brazo cerca de su máxima extensión/retracción",
                "severidad": "media",
                "articulaciones": [2, 3],
                "recomendacion": "Mantener J3 alejado de los límites extremos"
            })

        j2 = joints_deg[1]
        if abs(j2 - 90) < 2:
            singularidades.append({
                "tipo": "Hombro vertical",
                "descripcion": "Brazo vertical sobre la base - pérdida de dirección",
                "severidad": "baja",
                "articulaciones": [1, 2],
                "recomendacion": "Evitar J2=90°"
            })

    if abs(det_J) < 1e-4: # Umbral de tolerancia reducido (más permisivo)
        estado = "singular"
    elif cond_number > 500: # Aumentado de 100 a 500
        estado = "cerca_singular"
    else:
        estado = "normal"

    cond_clean = float(cond_number)
    if np.isinf(cond_clean) or np.isnan(cond_clean) or cond_clean > 1e6:
        cond_clean = 1e6

    det_clean = float(det_J)
    if np.isinf(det_clean) or np.isnan(det_clean):
        det_clean = 0.0

    manip_clean = float(abs(det_J))
    if np.isinf(manip_clean) or np.isnan(manip_clean):
        manip_clean = 0.0

    s_clean = [float(v) if not (np.isinf(v) or np.isnan(v)) else 0.0 for v in s]

    return {
        "estado": estado,
        "determinante": det_clean,
        "numero_condicion": cond_clean,
        "valores_singulares": s_clean,
        "singularidades": singularidades,
        "manipulabilidad": manip_clean,
        "jacobiano": J.tolist()
    }

def verificar_limites_articulares(joints_deg: List[float], limites: List[List[float]]) -> Dict:
    
    advertencias = []
    margen_seguridad = 10  # grados
    
    for i, (angulo, (min_lim, max_lim)) in enumerate(zip(joints_deg, limites)):

        if angulo < min_lim or angulo > max_lim:
            advertencias.append({
                "articulacion": i + 1,
                "tipo": "fuera_limites",
                "angulo": angulo,
                "limite_min": min_lim,
                "limite_max": max_lim,
                "severidad": "critica"
            })

        elif angulo < min_lim + margen_seguridad:
            advertencias.append({
                "articulacion": i + 1,
                "tipo": "cerca_limite_inferior",
                "angulo": angulo,
                "limite_min": min_lim,
                "margen": angulo - min_lim,
                "severidad": "advertencia"
            })
        elif angulo > max_lim - margen_seguridad:
            advertencias.append({
                "articulacion": i + 1,
                "tipo": "cerca_limite_superior",
                "angulo": angulo,
                "limite_max": max_lim,
                "margen": max_lim - angulo,
                "severidad": "advertencia"
            })
    
    return {
        "en_limites": len([a for a in advertencias if a["tipo"] == "fuera_limites"]) == 0,
        "advertencias": advertencias
    }

def analisis_completo(joints_deg: List[float], tabla_dh: List[List[float]], 
                      limites: List[List[float]], tipos_articulaciones: List[str] = None) -> Dict:
    
    singularidades = analizar_singularidades(joints_deg, tabla_dh, tipos_articulaciones)
    limites_check = verificar_limites_articulares(joints_deg, limites)

    if not limites_check["en_limites"]:
        estado_general = "error"
    elif singularidades["estado"] == "singular":
        estado_general = "singular"
    elif singularidades["estado"] == "cerca_singular":
        estado_general = "advertencia"
    else:
        estado_general = "normal"
    
    return {
        "estado_general": estado_general,
        "singularidades": singularidades,
        "limites": limites_check,
        "joints": joints_deg
    }
