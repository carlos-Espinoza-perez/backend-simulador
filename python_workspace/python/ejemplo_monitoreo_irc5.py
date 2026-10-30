from abb_irc5 import RobotClient, IRC5ClientError

def monitorear_sistema():
    print("Monitoreo de sistema y telemetria IRC5:")
    robot = RobotClient(host="127.0.0.1", port=5001, mode="SIMULATED")
    res = robot.connect(timeout=2.0)
    if not res.get("success"):
        print("No se pudo establecer conexion:", res.get("error"))
        return

    try:
        ping_res = robot.ping()
        print(f"Ping RTT: {ping_res.get('latency_ms')} ms")

        status_res = robot.get_status()
        print(f"Estado del controlador: {status_res.get('data')}")

        cycle = robot.get_variable("cycle_count")
        print(f"Contador de ciclos: {cycle.get('data')}")

        robot_listo = robot.get_di("di_robot_listo")
        print(f"Robot listo en celda: {robot_listo.get('data')}")

    except IRC5ClientError as e:
        print(f"Fallo en telemetria: {e}")
    finally:
        robot.disconnect()

if __name__ == "__main__":
    monitorear_sistema()
