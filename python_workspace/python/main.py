import sys
from abb_irc5 import RobotClient

def main():
    print("Iniciando script de prueba...")
    print(f"Python version: {sys.version.split()[0]}")
    
    robot = RobotClient(host="127.0.0.1", port=5001)
    print("Cliente instanciado en modo desarrollo/simulado.")
    
    res = robot.connect(timeout=2.0)
    print("Resultado conexion:", res)
    
    if res.get("success"):
        print("Ping:", robot.ping())
        print("Estado:", robot.get_status())
        robot.disconnect()
    else:
        print("No se pudo conectar al IRC5 (servidor inactivo o simulado).")

if __name__ == "__main__":
    main()
