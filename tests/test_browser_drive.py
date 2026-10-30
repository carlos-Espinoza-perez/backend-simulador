import os
import time
from playwright.sync_api import sync_playwright

def run_browser_automation():
    artifact_dir = r"C:\Users\cpesp\.gemini\antigravity\brain\4534a5cb-9dbd-4ac5-9b1e-f6de2cdd6b99"
    os.makedirs(artifact_dir, exist_ok=True)
    
    edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    
    with sync_playwright() as p:
        print("[1] Iniciando navegador Edge...")
        browser = p.chromium.launch(
            executable_path=edge_path,
            headless=True
        )
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        
        print("[2] Navegando a http://localhost:5173/ ...")
        page.goto("http://localhost:5173/", wait_until="networkidle")
        time.sleep(2)
        shot1 = os.path.join(artifact_dir, "01_simulador_3d.png")
        page.screenshot(path=shot1)
        print(f" -> Captura 1 guardada: {shot1}")
        
        print("[3] Haciendo click en la pestana 'IDE Python' del Header...")
        ide_tab = page.locator("text=IDE Python")
        if ide_tab.count() > 0:
            ide_tab.first.click()
        else:
            page.goto("http://localhost:5173/python-ide", wait_until="networkidle")
            
        time.sleep(2)
        shot2 = os.path.join(artifact_dir, "02_python_ide_overview.png")
        page.screenshot(path=shot2)
        print(f" -> Captura 2 guardada: {shot2}")
        
        print("[4] Abriendo panel de Conexion ABB IRC5...")
        connection_icon_btn = page.locator("button[title='Conexión ABB IRC5']")
        if connection_icon_btn.count() > 0:
            connection_icon_btn.click()
            time.sleep(1)
        
        mock_btn = page.locator("button:has-text('Iniciar Servidor Mock')")
        if mock_btn.count() > 0:
            print("[5] Iniciando Servidor Simulado Mock local...")
            mock_btn.click()
            time.sleep(1)
            
        connect_btn = page.locator("button:has-text('Conectar IRC5')")
        if connect_btn.count() > 0:
            print("[6] Conectando al controlador IRC5 en 127.0.0.1:5001...")
            connect_btn.click()
            time.sleep(1)
            
        ping_btn = page.get_by_role("button", name="Ping", exact=True)
        if ping_btn.count() > 0:
            print("[7] Enviando comando Ping exacto...")
            ping_btn.click()
            time.sleep(1)
            
        cmd_select = page.locator("select").nth(1) # segundo select en el panel de conexion
        if cmd_select.count() > 0:
            cmd_select.select_option("GET_STATUS")
            time.sleep(0.5)
            send_btn = page.locator("button:has-text('Enviar Comando')")
            if send_btn.count() > 0:
                print("[8] Enviando GET_STATUS...")
                send_btn.click()
                time.sleep(1)

        shot3 = os.path.join(artifact_dir, "03_irc5_connected.png")
        page.screenshot(path=shot3)
        print(f" -> Captura 3 guardada: {shot3}")
        
        files_btn = page.locator("button[title='Explorador de Archivos']")
        if files_btn.count() > 0:
            files_btn.click()
            time.sleep(1)
            
        run_btn = page.locator("button:has-text('Ejecutar Script')")
        if run_btn.count() > 0:
            print("[9] Ejecutando script main.py en subproceso controlado...")
            run_btn.first.click()
            time.sleep(3.5) # Esperar streaming del script
            
        shot4 = os.path.join(artifact_dir, "04_script_executed_console.png")
        page.screenshot(path=shot4)
        print(f" -> Captura 4 guardada: {shot4}")
        
        browser.close()
        print("[OK] Automatizacion del navegador finalizada exitosamente.")

if __name__ == "__main__":
    run_browser_automation()
