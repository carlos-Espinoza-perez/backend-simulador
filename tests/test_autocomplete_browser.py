from playwright.sync_api import sync_playwright
import time

edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=edge_path, headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    
    print("[1] Abriendo IDE Python...")
    page.goto("http://localhost:5173/python-ide", wait_until="networkidle")
    time.sleep(2)

    editor_container = page.locator(".monaco-editor").first
    editor_container.click()
    time.sleep(0.5)

    print("[2] Escribiendo 'robot.' en el editor Monaco...")
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.type("robot.", delay=100)
    time.sleep(1.5)

    suggest_widget = page.locator(".monaco-editor .suggest-widget")
    is_visible = suggest_widget.is_visible()
    print("[3] Widget de autocompletado visible:", is_visible)

    shot = r"C:\Users\cpesp\.gemini\antigravity\brain\4534a5cb-9dbd-4ac5-9b1e-f6de2cdd6b99\06_autocompletado_monaco.png"
    page.screenshot(path=shot)
    print(f"[4] Captura guardada en: {shot}")

    browser.close()
    print("[OK] Prueba de autocompletado completada exitosamente.")
