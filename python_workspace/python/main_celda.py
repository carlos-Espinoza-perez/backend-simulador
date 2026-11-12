import json
import math
import os
import time
import urllib.request
from typing import Dict, Any, List, Optional, Tuple

from camara import obtener_frame, obtener_calibracion, guardar_captura, publicar_deteccion
from detector import detectar_piezas, dibujar_detecciones
from clasificador import DESTINOS_DEPOSITO
from abb_irc5 import RobotClient, IRC5ClientError

try:
    from especificaciones_robot import ROBOTS
    from cinematica_inversa import solve_ik_from_robtarget
    _LIMITES_IRB140 = ROBOTS["ABB_IRB_140"]["limites_articulares"]
except Exception:
    solve_ik_from_robtarget = None
    _LIMITES_IRB140 = [
        (-180.0, 180.0),
        (-90.0, 110.0),
        (-230.0, 50.0),
        (-200.0, 200.0),
        (-115.0, 115.0),
        (-400.0, 400.0),
    ]

BASE_URL = f"http://127.0.0.1:{os.environ.get('PORT', '5000')}"
Z_APROXIMACION_MM = 220.0
Z_AGARRE_MM = 135.0


def _cuaternion_herramienta_vertical(yaw_deg: float = 0.0) -> List[float]:
    mitad = math.radians(float(yaw_deg)) * 0.5
    # Rotación de 180° en torno a Y (herramienta apuntando hacia -Z) combinada con giro Z (yaw)
    qx = -math.sin(mitad)
    qy = math.cos(mitad)
    return [0.0, round(qx, 6), round(qy, 6), 0.0]


def _resolver_joints_pick_place(
    x_mm: float,
    y_mm: float,
    z_mm: float,
    yaw_deg: float = 0.0,
) -> Optional[List[float]]:
    if solve_ik_from_robtarget is None:
        return None
    try:
        quat = _cuaternion_herramienta_vertical(yaw_deg)
        res = solve_ik_from_robtarget(
            [float(x_mm), float(y_mm), float(z_mm)],
            quat,
            _LIMITES_IRB140,
            from_robotstudio=False,
            robot_id="ABB_IRB_140",
        )
        if res.get("success") and res.get("joints"):
            return [round(float(q), 2) for q in res["joints"]]
    except Exception:
        pass
    return None


_q_actual = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def _mover_simulador_web(target_joints: List[float], speed: float = 60.0) -> bool:
    global _q_actual
    q0 = list(_q_actual)
    q1 = list(target_joints)

    delta_max = max(abs(b - a) for a, b in zip(q0, q1))
    if delta_max < 0.1:
        return True

    pasos = max(10, min(30, int(delta_max / 3.0)))
    dt = max(0.015, min(0.035, (80.0 / max(speed, 20.0)) * 0.025))

    for i in range(1, pasos + 1):
        t = i / pasos
        s = 0.5 * (1.0 - math.cos(math.pi * t))
        q_step = [round(a + s * (b - a), 2) for a, b in zip(q0, q1)]
        try:
            body = json.dumps({"angulos": q_step}).encode("utf-8")
            req = urllib.request.Request(
                f"{BASE_URL}/api/robot/mover",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                pass
        except Exception:
            pass
        time.sleep(dt)

    _q_actual = list(target_joints)
    return True


def _ejecutar_movimiento(
    robot: Optional[RobotClient],
    conectado_irc5: bool,
    joints: Optional[List[float]],
    preset_fallback: str = "HOME",
    speed: float = 60.0,
) -> None:
    if joints is not None:
        _mover_simulador_web(joints, speed=speed)

    if not conectado_irc5 or robot is None:
        return

    if joints is not None:
        try:
            robot.move_joints(joints, speed=speed, physical_confirmed=True)
            return
        except Exception:
            pass

    robot.move_preset(preset_fallback, speed=speed, physical_confirmed=True)


def ejecutar_ciclo_clasificacion(
    modo: str = "SIMULATED",
    criterio_orden: str = "proximidad",
) -> List[Dict[str, Any]]:
    print(f"[Celda ABB IRB 140] Ciclo de deteccion, clasificacion y ordenamiento ({criterio_orden})")

    print("\n[1] Capturando fotograma y calibracion activa...")
    cal = obtener_calibracion()
    frame = obtener_frame(crudo=True)
    ruta_captura = guardar_captura(frame)
    estado_cal = "Homografia activa" if cal.get("valida") else "Escala lineal por defecto"
    print(f"    Fotograma guardado en: {ruta_captura} ({estado_cal})")

    print(f"\n[2] Detectando, clasificando y ordenando piezas (criterio: {criterio_orden})...")
    piezas = detectar_piezas(frame, calibracion=cal, criterio=criterio_orden)
    print(f"    Total de piezas detectadas: {len(piezas)}")

    anotada = dibujar_detecciones(frame, piezas, calibracion=cal)
    publicar_deteccion(anotada, len(piezas), piezas=piezas)

    if not piezas:
        print("    No se encontraron objetos dentro del area de clasificacion.")
        return []

    for p in piezas:
        dest = p.get("destino", {})
        pos_dest = dest.get("posicion_robot_mm", (0.0, 0.0, 0.0))
        print(
            f"    Orden #{p['orden']} -> Pieza ID {p['id']}: {p['material']} "
            f"({p['color']}, {p['forma']}, {p['tamano']}, conf={p['confianza']}) | "
            f"Pick=({p['posicion_mm'][0]}, {p['posicion_mm'][1]}) mm | "
            f"Place=({pos_dest[0]}, {pos_dest[1]}) mm [Slot #{dest.get('indice_slot', 0) + 1}]"
        )

    host = "192.168.125.1" if modo == "CONNECTED_PHYSICAL" else "127.0.0.1"
    robot = RobotClient(host=host, port=5001, mode=modo)
    res_conn = robot.connect(timeout=2.0)
    conectado_irc5 = bool(res_conn.get("success"))

    if not conectado_irc5:
        print(f"\n[3] Controlador IRC5 no enlazado ({res_conn.get('error')}). Ejecutando secuencia en simulador 3D...")
    else:
        print(f"\n[3] Conectado a controlador IRC5 ({host}:5001). Ejecutando secuencia Pick & Place...")

    try:
        if conectado_irc5:
            robot.arm_physical_writes()

        for p in piezas:
            mat = p["material"]
            x_pick, y_pick = p["posicion_mm"]
            ang_pieza = float(p.get("orientacion_deg", 0.0))
            dest = p.get("destino") or DESTINOS_DEPOSITO.get(mat, DESTINOS_DEPOSITO["PET"])
            preset = dest.get("preset", "HOME")
            x_place, y_place, z_place = dest.get(
                "posicion_robot_mm",
                DESTINOS_DEPOSITO.get(mat, DESTINOS_DEPOSITO["PET"])["offset_descarga"],
            )

            print(f"\n[Ejecutando Orden #{p['orden']} - Pieza #{p['id']} ({mat})]")
            print(f"  1. Aproximando a Pick: X={x_pick} mm, Y={y_pick} mm, Z={Z_APROXIMACION_MM} mm (Yaw={ang_pieza}°)")
            q_pre_pick = _resolver_joints_pick_place(x_pick, y_pick, Z_APROXIMACION_MM, ang_pieza)
            _ejecutar_movimiento(robot, conectado_irc5, q_pre_pick, preset_fallback="HOME", speed=70.0)

            print(f"  2. Descendiendo a agarre: Z={Z_AGARRE_MM} mm y cerrando pinza (do_pinza_actuar=1)")
            q_pick = _resolver_joints_pick_place(x_pick, y_pick, Z_AGARRE_MM, ang_pieza)
            _ejecutar_movimiento(robot, conectado_irc5, q_pick, preset_fallback="HOME", speed=45.0)
            if conectado_irc5:
                robot.set_do("do_pinza_actuar", 1, physical_confirmed=True)
            time.sleep(0.25)

            print(f"  3. Elevando pieza a cota segura: Z={Z_APROXIMACION_MM} mm")
            _ejecutar_movimiento(robot, conectado_irc5, q_pre_pick, preset_fallback="HOME", speed=65.0)

            print(f"  4. Trasladando a deposito {mat} [Slot #{dest.get('indice_slot', 0) + 1}]: X={x_place} mm, Y={y_place} mm")
            q_pre_place = _resolver_joints_pick_place(x_place, y_place, Z_APROXIMACION_MM, 0.0)
            _ejecutar_movimiento(robot, conectado_irc5, q_pre_place, preset_fallback=preset, speed=70.0)

            q_place = _resolver_joints_pick_place(x_place, y_place, z_place, 0.0)
            _ejecutar_movimiento(robot, conectado_irc5, q_place, preset_fallback=preset, speed=45.0)

            print("  5. Liberando pieza (do_pinza_actuar=0)")
            if conectado_irc5:
                robot.set_do("do_pinza_actuar", 0, physical_confirmed=True)
            time.sleep(0.25)

            _ejecutar_movimiento(robot, conectado_irc5, q_pre_place, preset_fallback=preset, speed=65.0)

        print("\n[4] Retornando manipulador a posicion HOME...")
        _ejecutar_movimiento(robot, conectado_irc5, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], preset_fallback="HOME", speed=60.0)
        print("    Ciclo de ordenamiento completado exitosamente.")

    except IRC5ClientError as e:
        print(f"    Error durante la secuencia de control: {e}")
    finally:
        if conectado_irc5:
            robot.disconnect()

    return piezas


if __name__ == "__main__":
    ejecutar_ciclo_clasificacion()
