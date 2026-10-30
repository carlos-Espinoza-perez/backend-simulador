# Configuración y Despliegue de Comunicación TCP/IP en ABB IRC5 (RobotWare 6)

Esta guía detalla los requisitos y pasos para configurar el servidor TCP nativo en un controlador ABB IRC5 físico o virtual (RobotStudio) e interactuar desde el IDE Python integrado.

---

## 1. Requisitos del Controlador

- **RobotWare**: Versión 6.x (e.g. RW 6.08, RW 6.13 o superior).
- **Opción de Software Requerida**: **616-1 PC Interface** o **623-1 Multitasking** (para ejecutar sockets en una tarea paralela `SEMI_STATIC` o `NORMAL`).
- **Puerto de Comunicación**: `5001` (configurable en RAPID `SERVER_PORT := 5001`).
- **Dirección IP**:
  - En RobotStudio (Controlador Virtual): `127.0.0.1` o IP de la tarjeta de red virtual.
  - En IRC5 Físico: Puerto de Servicio `192.168.125.1` o puerto LAN de la celda de automatización (e.g., `192.168.0.x`).

---

## 2. Configuración de Red en el Controlador IRC5

1. En el FlexPendant, ingresar a **Panel de Control** -> **Configuración** -> **Communication**.
2. Verificar la interfaz de red (`IP Setting`):
   - **Service Port (X2)**: `192.168.125.1` (fija por defecto).
   - **LAN (X3 / WAN)**: Configurar dirección IP estática, máscara de subred y Gateway acordes a la subred de la estación.
3. Asegurar que los firewalls de la red permitan tráfico bidireccional en el puerto TCP `5001`.

---

## 3. Carga del Módulo RAPID `IRC5_TcpServer.mod`

### En RobotStudio:
1. Abrir la estación `IRB_140.rsproj`.
2. En la pestaña **RAPID**, expandir el árbol del controlador `T_ROB1` (o `TASK1`).
3. Hacer clic derecho en **Program Modules** -> **Load Module...**.
4. Seleccionar `IRC5_TcpServer.mod`.
5. Aplicar cambios en el controlador (**Apply**).

### En Controlador Físico:
1. Copiar `IRC5_TcpServer.mod` a una memoria USB en la carpeta `/HOME`.
2. Insertar la USB en el controlador IRC5.
3. Desde el FlexPendant, abrir **Production Window** o el **Editor de Programas**.
4. En **Módulos**, presionar **Cargar Módulo** y seleccionar el archivo desde el dispositivo USB.
5. Iniciar la ejecución de la tarea en modo continuo.

---

## 4. Señales de E/S Configuradas

El sistema valida las señales digitales autorizadas. Para utilizar señales físicas en el controlador, deben crearse previamente en `EIO.cfg` o mediante el menú E/S del FlexPendant:

| Nombre Señal | Tipo | Dirección | Descripción |
|---|---|---|---|
| `di_pieza_presente` | Digital Input | Lectura | Sensor inductivo / óptico de pieza |
| `di_robot_listo` | Digital Input | Lectura | Confirmación de celda lista |
| `do_valvula_aire` | Digital Output | Lectura/Escritura | Actuador neumático / eyector |
| `do_pinza_actuar` | Digital Output | Lectura/Escritura | Cierre/Apertura de mordaza |
| `do_indicador_verde` | Digital Output | Lectura/Escritura | Torre de baliza verde (operación) |

> [!WARNING]
> Las señales críticas de seguridad (e.g., parada de emergencia, vallas perimetrales, frenos) están estrictamente bloqueadas y no pueden ser forzadas ni modificadas mediante la API Python.

---

## 5. Protocolo de Mensajes

- Delimitador: Salto de línea `\n` (ASCII `0x0A`).
- Formato: JSON delimitado.
- Ejemplo de consulta:
  ```json
  {"id": 1, "cmd": "PING", "params": {}}
  ```
- Ejemplo de respuesta:
  ```json
  {"id": 1, "status": "OK", "data": "PONG", "error": null}
  ```

---

## 6. Administración de E/S Virtuales (Gemelo Digital)

La plataforma cuenta con un administrador dinámico de señales virtuales (`VirtualIOManager`) persistido en `python_workspace/virtual_io.json`.
- Permite crear, modificar y forzar señales lógicas DI/DO tanto desde la interfaz web (pestaña **Gestor E/S Virtuales**) como a través de la API REST (`/api/virtual_io/*`).
- En modo simulado, el servidor emulador (`IRC5MockServer`) sincroniza su estado en memoria con este gestor, permitiendo validar secuencias de control en Python antes de transferir lógica al hardware.

---

## 7. Despliegue de Configuración en IRC5 Físico (`EIO.cfg`)

En RobotWare 6, las instrucciones Socket de RAPID **no pueden** crear o alterar la base de datos de señales del sistema de E/S en tiempo de ejecución. Toda señal física o virtual debe declararse en la configuración `EIO` del controlador:

1. Desde el Gestor E/S de la plataforma web, presionar **Exportar EIO.cfg** o invocar `GET /api/virtual_io/export/eio_cfg`.
2. Guardar el archivo en una memoria USB o transferirlo al controlador vía FTP / RobotStudio.
3. En el FlexPendant:
   - Ir a **Menú ABB** -> **Panel de Control** -> **Configuración** -> **File** -> **Load Parameters**.
   - Seleccionar el archivo `EIO.cfg`.
   - Elegir la opción de combinar o reemplazar parámetros (`By adding new parameters`).
   - Confirmar el reinicio en caliente del controlador (**Warm Start**) para inicializar las nuevas señales en el bus del robot.

---

## 8. Arquitectura RWS (Robot Web Services)

Para consultar o modificar configuraciones sin reiniciar manualmente desde el FlexPendant, RobotWare 6 ofrece **Robot Web Services 1.0**:
- Puerto HTTP: `80` (o HTTPS `443` con certificado).
- Recurso de señales: `http://<IP_CONTROLADOR>/rw/iosys/signals`.
- Requiere autenticación Digest con usuario `Default User` o credenciales con permisos de configuración.
- El socket TCP personalizado (puerto 5001) se mantiene optimizado para control en tiempo de ejecución de bajo retraso (<5 ms), mientras que RWS se reserva para gestión administrativa del controlador.
