"""
Web scraper para extraer puestos de votación de la Registraduría Nacional
Departamentos: VALLE, RISARALDA, CALDAS
URL: https://wapp.registraduria.gov.co/electoral/2026/congreso-de-la-republica/
"""

import asyncio
import csv
import time
import random
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# Configuración
URL = "https://wapp.registraduria.gov.co/electoral/2026/congreso-de-la-republica/"
DEPARTAMENTOS = ["VALLE","RISARALDA","CALDAS"]
OUTPUT_FILE = "puestos_votacion.csv"
TIMEOUT = 30000
SLEEP_BASE = 7


def random_sleep(base=SLEEP_BASE, variance=2):
    sleep_time = base + random.uniform(0, variance)
    print(f"  ⏳ Esperando {sleep_time:.1f}s...")
    time.sleep(sleep_time)


async def get_options(page, select_id):
    options = await page.eval_on_selector(
        f"#{select_id}",
        """select => Array.from(select.options)
            .filter(opt => opt.value !== '')
            .map(opt => ({ value: opt.value, text: opt.text.trim() }))"""
    )
    return options


async def select_option(page, select_id, value):
    await page.select_option(f"#{select_id}", value)
    await page.wait_for_timeout(2000)


async def wait_for_select_enabled(page, select_id, max_wait=15000):
    await page.wait_for_function(
        f"document.getElementById('{select_id}') && !document.getElementById('{select_id}').disabled",
        timeout=max_wait
    )


async def get_puesto_info(page):
    try:
        await page.wait_for_selector("#info_puesto", state="visible", timeout=10000)
        info = {}

        h3 = await page.query_selector("#info_puesto h3")
        if h3:
            texto_h3 = await h3.inner_text()
            info["puesto"] = texto_h3.replace("PUESTO:", "").strip()

        parrafos = await page.query_selector_all("#info_puesto p")
        for p in parrafos:
            texto = await p.inner_text()
            if "Departamento:" in texto:
                info["departamento"] = texto.replace("Departamento:", "").strip()
            elif "Municipio:" in texto:
                info["municipio"] = texto.replace("Municipio:", "").strip()
            elif "Direcci" in texto:
                info["direccion"] = texto.split(":", 1)[-1].strip()

        return info
    except Exception as e:
        print(f"     Error extrayendo info del puesto: {e}")
        return None


# CORRECCIÓN: csvfile se pasa como parámetro para poder llamar flush()
async def scrape_departamento(page, departamento, writer, csvfile):
    print(f"\n{'='*60}")
    print(f"📍 Procesando departamento: {departamento}")
    print(f"{'='*60}")

    await select_option(page, "select_departamento", departamento)
    random_sleep(SLEEP_BASE)

    try:
        await wait_for_select_enabled(page, "select_municipio")
    except Exception as e:
        print(f"  El select de municipio no se habilitó: {e}")
        return

    municipios = await get_options(page, "select_municipio")
    print(f"  Municipios encontrados: {len(municipios)}")

    for i, municipio in enumerate(municipios):
        print(f"\n  🏘️  Municipio {i+1}/{len(municipios)}: {municipio['text']}")

        await select_option(page, "select_municipio", municipio["value"])
        random_sleep(SLEEP_BASE)

        try:
            await wait_for_select_enabled(page, "select_puesto")
        except Exception as e:
            print(f"    Select de puesto no habilitado para {municipio['text']}: {e}")
            await select_option(page, "select_departamento", departamento)
            random_sleep(3)
            await wait_for_select_enabled(page, "select_municipio")
            await select_option(page, "select_municipio", municipio["value"])
            random_sleep(SLEEP_BASE)
            try:
                await wait_for_select_enabled(page, "select_puesto")
            except:
                print(f"    Saltando municipio {municipio['text']}")
                continue

        puestos = await get_options(page, "select_puesto")
        print(f"    Puestos encontrados: {len(puestos)}")

        for j, puesto in enumerate(puestos):
            print(f"    [{j+1}/{len(puestos)}] Procesando: {puesto['text']}")

            await select_option(page, "select_puesto", puesto["value"])
            random_sleep(SLEEP_BASE)

            info = await get_puesto_info(page)

            if info:
                row = {
                    "Departamento": info.get("departamento", departamento),
                    "Municipio": info.get("municipio", municipio["text"]),
                    "Puesto de votación": info.get("puesto", puesto["text"]),
                    "Dirección": info.get("direccion", "N/A")
                }
            else:
                row = {
                    "Departamento": departamento,
                    "Municipio": municipio["text"],
                    "Puesto de votación": puesto["text"],
                    "Dirección": "No disponible"
                }

            writer.writerow(row)
            csvfile.flush()  # Fuerza escritura al disco después de cada fila
            print(f"      Guardado: {row['Puesto de votación']} - {row['Dirección']}")

            if (j + 1) % 10 == 0:
                print(f"    ⏸️  Pausa de seguridad cada 10 puestos...")
                random_sleep(SLEEP_BASE + 5)

        random_sleep(SLEEP_BASE + 3)

        await select_option(page, "select_departamento", departamento)
        random_sleep(3)
        await wait_for_select_enabled(page, "select_municipio")


async def main():
    print("Iniciando scraper de puestos de votación")
    print(f"Archivo de salida: {OUTPUT_FILE}")
    print(f"Departamentos a procesar: {', '.join(DEPARTAMENTOS)}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="es-CO",
        )

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        page = await context.new_page()

        # csvfile definido aquí y pasado como argumento a scrape_departamento
        with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = ["Departamento", "Municipio", "Puesto de votación", "Dirección"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            csvfile.flush()  # Escribir el header de inmediato

            print(f"\n🌐 Navegando a: {URL}")
            try:
                await page.goto(URL, timeout=TIMEOUT, wait_until="networkidle")
            except PlaywrightTimeoutError:
                print("  Timeout en carga inicial, intentando continuar...")

            random_sleep(SLEEP_BASE + 3)

            try:
                await page.wait_for_selector("#select_departamento", timeout=15000)
                print("  Página cargada correctamente")
            except PlaywrightTimeoutError:
                print("  No se encontró el selector de departamento.")
                await browser.close()
                return

            for departamento in DEPARTAMENTOS:
                try:
                    await scrape_departamento(page, departamento, writer, csvfile)
                    print(f"\n  Departamento {departamento} completado")

                    reset_btn = await page.query_selector("#btn_reset")
                    if reset_btn:
                        await reset_btn.click()
                        random_sleep(SLEEP_BASE)

                except Exception as e:
                    print(f"\n  Error procesando {departamento}: {e}")
                    try:
                        reset_btn = await page.query_selector("#btn_reset")
                        if reset_btn:
                            await reset_btn.click()
                        random_sleep(SLEEP_BASE)
                    except:
                        pass

                if departamento != DEPARTAMENTOS[-1]:
                    print(f"\n⏸️  Pausa larga entre departamentos (15s)...")
                    random_sleep(15, 5)

        await browser.close()

    print(f"\n{'='*60}")
    print(f"✅ Scraping completado!")
    print(f"Datos guardados en: {OUTPUT_FILE}")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())