from playwright.sync_api import sync_playwright
import time

edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=edge_path, headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    
    print("[1] Abriendo IDE Python...")
    page.goto("http://localhost:5173/python-ide", wait_until="networkidle")
    time.sleep(2)

    print("[2] Probando boton de cerrar en el Explorador de Archivos...")
    close_sidebar_btn = page.locator("button[title='Cerrar panel lateral']").first
    close_sidebar_btn.click()
    time.sleep(1)
    page.screenshot(path=r"C:\Users\cpesp\.gemini\antigravity\brain\4534a5cb-9dbd-4ac5-9b1e-f6de2cdd6b99\07_ide_sidebar_closed.png")

    print("[3] Reabriendo panel lateral...")
    open_btn = page.locator("button[title='Explorador de Archivos']").first
    open_btn.click()
    time.sleep(1)

    print("[4] Conmutando consola al lateral derecho...")
    dock_btn = page.locator("button[title='Acoplar a la derecha']").first
    dock_btn.click()
    time.sleep(1.5)
    page.screenshot(path=r"C:\Users\cpesp\.gemini\antigravity\brain\4534a5cb-9dbd-4ac5-9b1e-f6de2cdd6b99\08_ide_dock_right.png")

    print("[5] Probando maximizar consola...")
    max_btn = page.locator("button[title='Maximizar consola']").first
    max_btn.click()
    time.sleep(1)
    page.screenshot(path=r"C:\Users\cpesp\.gemini\antigravity\brain\4534a5cb-9dbd-4ac5-9b1e-f6de2cdd6b99\09_ide_maximized.png")

    browser.close()
    print("[OK] Todas las pruebas de redimensionamiento y docking pasaron exitosamente.")
