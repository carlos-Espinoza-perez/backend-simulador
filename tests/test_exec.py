from playwright.sync_api import sync_playwright
import time

edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=edge_path, headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    
    page.goto("http://localhost:5173/python-ide", wait_until="networkidle")
    time.sleep(2)

    import urllib.request
    try:
        req = urllib.request.Request("http://localhost:5000/api/connection/mock_server/start", method="POST")
        urllib.request.urlopen(req)
        print("[MOCK SERVER] Servidor mock iniciado en 5001")
    except Exception as e:
        print("[MOCK SERVER] Error al iniciar mock:", e)

    run_btn = page.locator("button:has-text('Ejecutar')").first
    print("Texto boton:", run_btn.inner_text(), "Habilitado:", run_btn.is_enabled())
    run_btn.click()
    
    print("Esperando salida de consola...")
    time.sleep(3.5)

    lines = page.locator("div.whitespace-pre-wrap").all_text_contents()
    print("\n=== LINEAS EN PANTALLA DE LA CONSOLA DEL IDE ===")
    for idx, line in enumerate(lines):
        print(f"[{idx}] {line}")

    page.screenshot(path=r"C:\Users\cpesp\.gemini\antigravity\brain\4534a5cb-9dbd-4ac5-9b1e-f6de2cdd6b99\05_consola_en_vivo.png")
    browser.close()
