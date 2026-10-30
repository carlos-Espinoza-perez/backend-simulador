# Guía de Prueba de Movimiento Controlado en Laboratorio
## Robot ABB IRB 140 / Controlador IRC5
**Fecha de Prueba:** Sábado 31 de Octubre

---

## 1. Requisitos Previos y Licenciamiento RobotWare

1. **Controlador IRC5:**
   - RobotWare versión 6.x (e.g., RW 6.08, RW 6.13) o versión 5.x compatible.
   - **Opción de Software Indispensable:** **616-1 PC Interface** (requerida para las instrucciones `SocketCreate`, `SocketBind`, `SocketListen`, `SocketAccept`, `SocketSend`, `SocketReceive`).
   - Sin esta opción de software, el controlador rechazará la carga del módulo RAPID indicando error de instrucción no reconocida.
2. **Archivos a Transferir en Memoria USB (formato FAT32):**
   - [`rapid/IRC5_TcpServer.mod`](file:///rapid/IRC5_TcpServer.mod): Servidor socket TCP/IP con soporte de telemetría y movimiento seguro (`MOVE_PRESET`, `MOVE_JOINTS`, `GET_JOINTS`).
3. **Equipo Portátil de Control:**
   - Adaptador Ethernet RJ45.
   - Cable de red directo Cat 5e / Cat 6.
   - Entorno Python 3.10+ con dependencias instaladas (`pip install -r requirements.txt`).
   - Node.js 18+ para la interfaz web.

---

## 2. Configuración de Red

### Opción A: Puerto de Servicio Frontal X2 (Recomendada para primera prueba)
- El puerto X2 se encuentra en la parte frontal del controlador IRC5.
- Dirección IP fija del IRC5 en X2: `192.168.125.1` (máscara `255.255.255.0`).
- Configuración de la tarjeta de red en la computadora portátil:
  - IP estática: `192.168.125.100`
  - Máscara de subred: `255.255.255.0`
  - Puerta de enlace: en blanco (o `192.168.125.1`).
- Comprobación previa de nivel 3:
  ```bash
  ping 192.168.125.1
  ```
  Debe responder con latencias `< 5 ms`.

### Opción B: Puerto LAN / WAN X3
- Si el laboratorio exige conectar el robot a un switch de celda:
  - Solicitar al responsable: IP asignada, máscara de subred y confirmación de que el puerto TCP `5001` no tiene filtrado por firewall.

---

## 3. Comprobaciones de Seguridad Previas (Lista de Chequeo Obligatoria)

Antes de encender o habilitar motores:
1. **Inspección Visual del Espacio de Trabajo:**
   - La celda debe estar totalmente libre de personas, herramientas sueltas, cajas o cables en el radio de alcance (radio esférico de 810 mm desde el centro del robot).
2. **Efector Final:**
   - Verificar si el robot tiene montada alguna herramienta (garra neumática, ventosa, etc.). Si está instalada, asegurarse de que no sobresalga ni choque con el pedestal.
3. **Dispositivo de Habilitación (Deadman Switch):**
   - El operador que sostiene el FlexPendant debe mantener el pulsador de tres posiciones en su posición intermedia.
   - Mantener el dedo sobre la seta de Paro de Emergencia del FlexPendant durante toda la prueba.
4. **Modo de Operación:**
   - Seleccionar **Modo Manual** en la llave selectora del controlador.
   - Velocidad manual máxima: **T1 ($\le 250\text{ mm/s}$)**. El software limita internamente a $50-100\text{ mm/s}$.

---

## 4. Despliegue del Servidor RAPID en el Controlador

1. Encender el controlador IRC5 y esperar a que el FlexPendant complete el arranque.
2. Insertar la memoria USB en el puerto USB del controlador o FlexPendant.
3. En el FlexPendant:
   - Abrir **Editor de Programas** (o **Program Editor**).
   - En la tarea principal de movimiento `T_ROB1`, presionar **Módulos** -> **Archivo** -> **Cargar Módulo**.
   - Seleccionar `IRC5_TcpServer.mod` desde el dispositivo USB.
   - En caso de conflicto de nombres con tareas anteriores, descargar cualquier módulo previo no utilizado.
4. Situar el puntero de programa en la rutina principal:
   - Presionar **Depurar** -> **PP a Main**.
5. Presionar el botón de reproducción (**Play** / **Start**) en el FlexPendant.
6. En la pantalla del FlexPendant debe aparecer el mensaje:
   ```
   Servidor TCP IRC5 Iniciando en puerto: 5001
   Esperando conexion cliente TCP...
   ```

---

## 5. Procedimiento de Prueba Paso a Paso

### Paso 1: Inicializar la Plataforma Web y Backend
En la computadora portátil conectada al robot:
```bash
# Terminal 1 - Backend:
cd simulador-robotica/backend-simulador
python main.py

# Terminal 2 - Frontend:
cd simulador-robotica/frontend-simulador
npm run dev
```
Abrir el navegador en `http://localhost:5173/python-ide`.

### Paso 2: Conexión TCP Inicial (Sin Movimiento)
1. Abrir la pestaña **Conexión ABB IRC5** en el lateral izquierdo.
2. Seleccionar el perfil: **ABB IRC5 - Puerto de Servicio (X2)** (`192.168.125.1:5001`).
3. Verificar que el modo indique `CONNECTED_PHYSICAL`.
4. Presionar **Conectar IRC5**.
   - *Resultado esperado:* El estado pasa a `Conectado` en verde y en el FlexPendant se visualiza: `Cliente conectado desde: 192.168.125.100`.
5. Presionar el botón **Ping**:
   - *Resultado esperado:* Respuesta `PONG` con latencia RTT calculada ($< 10\text{ ms}$).

### Paso 3: Lectura de Estado y Articulaciones Actuales
1. En el selector de comandos, elegir `GET_STATUS` y presionar **Enviar Comando**:
   - *Resultado esperado:* JSON con `exec_state: "running"` y el controlador `IRC5_RW6`.
2. Elegir el comando `GET_JOINTS` y presionar **Enviar Comando**:
   - *Resultado esperado:* Arreglo con los 6 ángulos articulares reales leídos directamente del servoaccionamiento mediante `CJointT()`.
   - Comparar las lecturas con la pantalla de posición del FlexPendant para corroborar calibración.

### Paso 4: Prueba de Movimiento Mínimo Controlado (Bajo Supervisión)
> [!IMPORTANT]
> Solicitar autorización expresa del profesor o encargado del laboratorio antes de ejecutar este paso.

1. **Armar el Canal de Seguridad Físico:**
   - En el panel de control, presionar el botón **DESARMADO** para conmutar a **CANAL ARMADO**.
2. **Seleccionar el Comando de Prueba:**
   - Elegir el comando: `MOVE_PRESET`.
   - Seleccionar el objetivo predefinido: `TEST_DELTA_J1`.
   - Este objetivo aplica una pequeña rotación de $+10^\circ$ exclusivamente sobre el eje 1 (base giratoria), sin desplazar verticalmente el codo ni la muñeca.
   - Ajustar la velocidad de prueba en el deslizador a **$50\text{ mm/s}$**.
3. **Confirmación de Seguridad:**
   - Marcar la casilla obligatoria: **Confirmar acción en robot físico real**.
4. **Ejecución:**
   - Mantener el pulsador de habilitación en el FlexPendant en posición intermedia.
   - Presionar **Enviar Comando (MOVE_PRESET)**.
   - *Resultado esperado:* El eje 1 gira lentamente $10^\circ$ y se detiene suavemente.
   - La respuesta en pantalla devuelve `status: "OK"`, `data: {"state": "COMPLETED", "target": "TEST_DELTA_J1"}`.

### Paso 5: Retorno a Posición Cero (HOME)
1. En el selector de `MOVE_PRESET`, elegir `HOME`.
2. Con la confirmación física activa, presionar **Enviar Comando**.
3. *Resultado esperado:* El eje 1 retorna a $0^\circ$ (postura de calibración vertical).

---

## 6. Criterios de Aborto y Vuelta a Estado Seguro

Si durante la prueba ocurre alguna de las siguientes situaciones:
- El robot genera un sonido inusual, vibración o trayectoria no anticipada.
- Una persona ingresa a la zona delimitada.
- Aparece un error de socket o timeout en la computadora portátil.

**Acciones Inmediatas:**
1. **Soltar inmediatamente el pulsador de habilitación del FlexPendant** (esto corta la alimentación de potencia de los frenos y detiene el robot mecánicamente en menos de $100\text{ ms}$).
2. O bien presionar la **seta de Paro de Emergencia** del FlexPendant.
3. En la interfaz web, presionar **Desconectar IRC5**.
4. No reanudar la operación sin investigar el código de evento en el visor de sucesos del FlexPendant.
