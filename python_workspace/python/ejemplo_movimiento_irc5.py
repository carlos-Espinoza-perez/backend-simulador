import time
from abb_irc5 import RobotClient, IRC5ClientError

def probar_movimiento():
    robot = RobotClient(host="127.0.0.1", port=5001, mode="SIMULATED")
    res = robot.connect(timeout=2.0)
    if not res.get("success"):
        print(f"Error de conexion: {res.get('error')}")
        return

    try:
        print("[1] Consultando estado inicial...")
        status = robot.get_status()
        print(f"Estado: {status.get('data')}")

        joints_ini = robot.get_joints()
        print(f"Articulaciones actuales: {joints_ini.get('data')}")

        print("\n[2] Enviando preset HOME [0, 0, 0, 0, 0, 0]...")
        res_home = robot.move_preset("HOME", speed=50.0)
        print(f"Resultado HOME: {res_home}")

        time.sleep(1.0)

        print("\n[3] Enviando movimiento seguro TEST_DELTA_J1 (+10 deg en Eje 1)...")
        res_delta = robot.move_preset("TEST_DELTA_J1", speed=50.0)
        print(f"Resultado TEST_DELTA_J1: {res_delta}")

        joints_fin = robot.get_joints()
        print(f"Articulaciones finales: {joints_fin.get('data')}")

    except IRC5ClientError as e:
        print(f"Fallo en ejecucion de movimiento: {e}")
    finally:
        robot.disconnect()
        print("\nPrueba finalizada.")

if __name__ == "__main__":
    probar_movimiento()
