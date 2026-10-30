import time
from abb_irc5 import RobotClient, IRC5ClientError

def ciclo_automatizado():
    print("Iniciando secuencia de ciclo E/S en celda...")
    robot = RobotClient(host="127.0.0.1", port=5001, mode="SIMULATED")
    conn = robot.connect(timeout=2.0)
    if not conn.get("success"):
        print("Error al conectar:", conn.get("error"))
        return

    try:
        pieza = robot.get_di("di_pieza_presente")
        print(f"Estado sensor di_pieza_presente: {pieza.get('data')}")

        if pieza.get("data") == 1:
            print("Pieza detectada en estacion. Activando alimentacion neumatica...")
            robot.set_do("do_valvula_aire", 1)
            time.sleep(0.5)

            print("Cerrando pinza de agarre...")
            robot.set_do("do_pinza_actuar", 1)
            time.sleep(0.5)

            print("Operacion completada. Indicador verde encendido.")
            robot.set_do("do_indicador_verde", 1)
        else:
            print("No hay pieza en estacion. Esperando sensor...")

    except IRC5ClientError as err:
        print(f"Error de comunicacion IRC5: {err}")
    finally:
        robot.disconnect()
        print("Secuencia finalizada.")

if __name__ == "__main__":
    ciclo_automatizado()
