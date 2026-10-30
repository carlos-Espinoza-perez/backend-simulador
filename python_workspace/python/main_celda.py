import time
from camara import obtener_frame, guardar_captura, publicar_deteccion
from detector import detectar_piezas, dibujar_detecciones
from clasificador import clasificar_material, DESTINOS_DEPOSITO
from abb_irc5 import RobotClient, IRC5ClientError

def ejecutar_ciclo_clasificacion(modo: str = "CONNECTED_PHYSICAL"):
    print("=" * 55)
    print("  CICLO DE CLASIFICACION - ABB IRB 140")
    print("=" * 55)

    print("\n[1] Capturando fotograma de camara fisica...")
    frame = obtener_frame()
    ruta_captura = guardar_captura(frame)
    print(f"    Fotograma almacenado en: {ruta_captura}")

    print("\n[2] Analizando objetos con OpenCV...")
    piezas = detectar_piezas(frame)
    print(f"    Piezas detectadas: {len(piezas)}")

    anotada = dibujar_detecciones(frame, piezas)
    publicar_deteccion(anotada, len(piezas))

    if not piezas:
        print("    No se detectaron objetos en el area de trabajo.")
        return

    host = "192.168.125.1" if modo == "CONNECTED_PHYSICAL" else "127.0.0.1"
    robot = RobotClient(host=host, port=5001, mode=modo)
    res_conn = robot.connect(timeout=2.5)

    if not res_conn.get("success"):
        print(f"    IRC5 desconectado ({res_conn.get('error')}). Modo inspeccion visual activo:")
        for p in piezas:
            info = clasificar_material(p["crop"])
            print(f"    - Objeto #{p['id']} en px={p['centro_px']} -> {info['material']} (confianza: {info['confianza']})")
        return

    try:
        robot.arm_physical_writes()

        for p in piezas:
            info = clasificar_material(p["crop"])
            material = info["material"]
            destino = DESTINOS_DEPOSITO.get(material, DESTINOS_DEPOSITO["PET"])

            print(f"\n[Procesando Objeto #{p['id']}]")
            print(f"  Posicion mesa: X={p['posicion_mm'][0]} mm, Y={p['posicion_mm'][1]} mm")
            print(f"  Material: {material} (Confianza: {info['confianza']})")
            print(f"  Destino: {destino['preset']}")

            print("  -> Aproximando herramienta...")
            time.sleep(0.5)

            print("  -> Activando pinza...")
            robot.set_do("do_pinza_actuar", 1, physical_confirmed=True)
            time.sleep(0.5)

            print(f"  -> Trasladando a deposito ({destino['preset']})...")
            res_mov = robot.move_preset(destino["preset"], speed=50.0, physical_confirmed=True)
            print(f"     Resultado: {res_mov.get('data', {}).get('state', 'OK')}")

            print("  -> Soltando pieza...")
            robot.set_do("do_pinza_actuar", 0, physical_confirmed=True)
            time.sleep(0.5)

        print("\n[3] Retornando a posicion HOME...")
        robot.move_preset("HOME", speed=50.0, physical_confirmed=True)
        print("    Ciclo completado con exito.")

    except IRC5ClientError as e:
        print(f"    Error durante la secuencia de control: {e}")
    finally:
        robot.disconnect()

if __name__ == "__main__":
    ejecutar_ciclo_clasificacion()
