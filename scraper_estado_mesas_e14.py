"""
Scraper de Estado de Mesas E14 - Actas Escrutinio Congreso 2026
Extrae el estado de todas las mesas por puesto, zona, municipio en Valle, Caldas y Risaralda
para Senado y Camara.

URL: https://escrutinioscongreso2026.registraduria.gov.co/actas-e14
Jerarquia: Corporacion -> Departamento -> Municipio -> Zona -> Puesto -> Estado Mesas
"""

import asyncio
import csv
import json
import os
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError

# Configuracion
URL_ACTAS_E14 = "https://escrutinioscongreso2026.registraduria.gov.co/actas-e14"
OUTPUT_CSV = "estado_mesas_e14.csv"
OUTPUT_JSON = "estado_mesas_e14.json"
TIMEOUT = 45000
SLEEP_BASE = 7  # Pausas largas para evitar CAPTCHA / bloqueos
DELAY_ENTRE_OPCIONES = 2

# Corporaciones a procesar: SENADO (001), CAMARA (002)
CORPORACIONES = [
    ("001", "SENADO"),
    ("002", "CAMARA"),
]

# Departamentos: nombre para filtro, codigo si la pagina lo usa
# Codigos DANE: Valle 76, Risaralda 66, Caldas 17
# La pagina puede usar otros codigos - se obtienen dinamicamente
DEPARTAMENTOS_OBJETIVO = ["VALLE", "CALDAS", "RISARALDA"]


def random_sleep(base: float = SLEEP_BASE, variance: float = 2) -> None:
    t = base + random.uniform(0, variance)
    print(f"  Esperando {t:.1f}s...")
    time.sleep(t)


async def get_select_options(page: Page, selector: str) -> List[Dict[str, str]]:
    """Obtiene opciones de un select, excluyendo vacias."""
    try:
        opts = await page.eval_on_selector(
            selector,
            """el => {
                const select = el.tagName === 'SELECT' ? el : el.querySelector('select');
                if (!select) return [];
                return Array.from(select.options)
                    .filter(o => o.value && o.value.trim() !== '')
                    .map(o => ({ value: o.value.trim(), text: o.textContent.trim() }));
            }"""
        )
        return opts if opts else []
    except Exception:
        return []


async def get_all_selects_info(page: Page) -> List[Dict]:
    """
    Descubre todos los selects en la pagina y devuelve info para mapearlos.
    Orden tipico: corporacion, departamento, municipio, zona, puesto
    """
    selects = await page.query_selector_all(
        "select, [role='combobox'], app-select select, [class*='select'] select"
    )
    result = []
    for i, sel in enumerate(selects):
        try:
            # Intentar obtener id, name o aria-label
            id_attr = await sel.get_attribute("id") or f"select_{i}"
            name_attr = await sel.get_attribute("name") or ""
            # Label asociado
            parent = await sel.evaluate_handle("el => el.closest('label, div, p, app-select')")
            label_text = ""
            try:
                label_el = await parent.query_selector("label, .label, [class*='label']")
                if label_el:
                    label_text = (await label_el.inner_text()).strip()
            except Exception:
                pass
            result.append({
                "index": i,
                "id": id_attr,
                "name": name_attr,
                "label": label_text,
                "selector": f"#{id_attr}" if id_attr and id_attr.startswith("select") else f"select:nth-of-type({i+1})",
            })
        except Exception:
            result.append({"index": i, "selector": f"select:nth-of-type({i+1})"})
    return result


async def select_by_selector(page: Page, selector: str, value: str) -> bool:
    """Selecciona una opcion en un select por selector."""
    try:
        await page.select_option(selector, value=value, timeout=5000)
        await page.wait_for_timeout(DELAY_ENTRE_OPCIONES * 1000)
        return True
    except Exception as e:
        print(f"    Error seleccionando {value}: {e}")
        return False


async def wait_select_enabled(page: Page, selector: str, max_wait: int = 15000) -> bool:
    """Espera a que un select este habilitado."""
    try:
        await page.wait_for_function(
            "s => document.querySelector(s) && !document.querySelector(s).disabled",
            selector,
            timeout=max_wait,
        )
        return True
    except Exception:
        return False


async def extraer_estado_mesas(page: Page) -> List[Dict]:
    """
    Extrae el estado de las mesas mostradas despues de hacer Consultar.
    Busca tablas, cards o listas con informacion de mesas.
    """
    mesas = []
    try:
        # Buscar tabla de mesas
        tablas = await page.query_selector_all("table")
        for tabla in tablas:
            filas = await tabla.query_selector_all("tr")
            headers = []
            header_row = await tabla.query_selector("thead tr, tr:first-child")
            if header_row:
                ths = await header_row.query_selector_all("th, td")
                headers = [await th.inner_text() for th in ths]

            for fila in filas[1:] if len(filas) > 1 else filas:
                celdas = await fila.query_selector_all("td")
                if not celdas:
                    continue
                row_data = {}
                for i, celda in enumerate(celdas):
                    texto = (await celda.inner_text()).strip()
                    key = headers[i] if i < len(headers) else f"col_{i}"
                    row_data[key] = texto
                if row_data:
                    mesas.append(row_data)

        # Si no hay tabla, buscar cards o divs con estado de mesa
        if not mesas:
            cards = await page.query_selector_all(
                "[class*='mesa'], [class*='acta'], [class*='estado']"
            )
            for card in cards:
                texto = (await card.inner_text()).strip()
                if texto and len(texto) < 200:
                    mesas.append({"mesa": texto, "estado": "N/A"})

        # Buscar numeros de mesa (ej: "Mesa 1", "001")
        if not mesas:
            body = await page.query_selector("body")
            if body:
                content = await body.inner_text()
                # Patron: Mesa X o numero de 3 digitos
                matches = re.findall(r"(?:Mesa\s*)?(\d{1,3})", content)
                for m in set(matches):
                    mesas.append({"mesa": m, "estado": "detectada"})
    except Exception as e:
        print(f"    Error extrayendo mesas: {e}")
    return mesas


async def obtener_selectores_pagina(page: Page) -> Dict[str, str]:
    """
    Descubre los selectores de los 5 filtros.
    Orden esperado: corporacion, departamento, municipio, zona, puesto
    """
    nombres = ["corporacion", "departamento", "municipio", "zona", "puesto"]
    posibles = {
        "corporacion": ["#select_corporacion", "#corporacion", "[id*='corporacion']", "select[name*='corporacion']"],
        "departamento": ["#select_departamento", "#departamento", "[id*='departamento']", "select[name*='departamento']"],
        "municipio": ["#select_municipio", "#municipio", "[id*='municipio']", "select[name*='municipio']"],
        "zona": ["#select_zona", "#zona", "[id*='zona']", "select[name*='zona']"],
        "puesto": ["#select_puesto", "#puesto", "[id*='puesto']", "select[name*='puesto']"],
    }
    resultado = {}
    for nombre, selectores in posibles.items():
        for sel in selectores:
            try:
                el = await page.query_selector(sel)
                if el:
                    # Obtener selector unico (id si existe)
                    id_el = await el.get_attribute("id")
                    resultado[nombre] = f"#{id_el}" if id_el else sel
                    break
            except Exception:
                continue
        if nombre not in resultado:
            idx = nombres.index(nombre) + 1
            resultado[nombre] = f"select:nth-of-type({idx})"
    return resultado


async def scrape_actas_e14(
    headless: bool = False,
    solo_primer_puesto: bool = False,  # Para pruebas rapidas
) -> List[Dict]:
    """
    Scraper principal: recorre corporacion -> depto -> municipio -> zona -> puesto
    y extrae el estado de cada mesa.
    """
    todos_registros = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="es-CO",
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)
        page = await context.new_page()

        print(f"\nNavegando a: {URL_ACTAS_E14}")
        try:
            await page.goto(URL_ACTAS_E14, timeout=TIMEOUT, wait_until="domcontentloaded")
        except PlaywrightTimeoutError:
            print("  Timeout en carga inicial, intentando continuar...")
        random_sleep(SLEEP_BASE + 3)

        selects = await obtener_selectores_pagina(page)
        print(f"  Selectores detectados: {selects}")
        if not selects:
            print("  No se encontraron selects. Verifica la URL y la estructura de la pagina.")
            await browser.close()
            return todos_registros

        boton_consultar = await page.query_selector(
            "button:has-text('Consultar'), app-button button, [class*='consultar'] button, input[value='Consultar']"
        )
        if not boton_consultar:
            boton_consultar = await page.query_selector("button")
        if not boton_consultar:
            print("  No se encontro boton Consultar.")

        for corp_code, corp_nombre in CORPORACIONES:
            print(f"\n{'='*60}")
            print(f"Corporacion: {corp_nombre} ({corp_code})")
            print(f"{'='*60}")

            if "corporacion" in selects:
                ok = await select_by_selector(page, selects["corporacion"], corp_code)
                if not ok:
                    # Probar por texto
                    opts = await get_select_options(page, selects["corporacion"])
                    for o in opts:
                        if corp_nombre.upper() in (o.get("text") or "").upper():
                            await select_by_selector(page, selects["corporacion"], o["value"])
                            break
                random_sleep(SLEEP_BASE)

            opts_depto = await get_select_options(page, selects["departamento"])
            deptos_filtrados = [
                o for o in opts_depto
                if any(d in (o.get("text") or "").upper() for d in DEPARTAMENTOS_OBJETIVO)
            ]
            if not deptos_filtrados:
                deptos_filtrados = opts_depto

            for depto_opt in deptos_filtrados:
                depto_text = depto_opt.get("text", "")
                depto_val = depto_opt.get("value", "")
                print(f"\n  Departamento: {depto_text}")

                await select_by_selector(page, selects["departamento"], depto_val)
                random_sleep(SLEEP_BASE)
                await wait_select_enabled(page, selects["municipio"])

                municipios = await get_select_options(page, selects["municipio"])
                for muni_opt in municipios:
                    muni_text = muni_opt.get("text", "")
                    muni_val = muni_opt.get("value", "")
                    print(f"    Municipio: {muni_text}")

                    await select_by_selector(page, selects["municipio"], muni_val)
                    random_sleep(SLEEP_BASE)
                    await wait_select_enabled(page, selects["zona"])

                    zonas = await get_select_options(page, selects["zona"])
                    for zona_opt in zonas:
                        zona_text = zona_opt.get("text", "")
                        zona_val = zona_opt.get("value", "")
                        await select_by_selector(page, selects["zona"], zona_val)
                        random_sleep(SLEEP_BASE)
                        await wait_select_enabled(page, selects["puesto"])

                        puestos = await get_select_options(page, selects["puesto"])
                        for j, puesto_opt in enumerate(puestos):
                            puesto_text = puesto_opt.get("text", "")
                            puesto_val = puesto_opt.get("value", "")
                            print(f"      Puesto [{j+1}/{len(puestos)}]: {puesto_text}")

                            await select_by_selector(page, selects["puesto"], puesto_val)
                            random_sleep(SLEEP_BASE)

                            if boton_consultar:
                                try:
                                    await boton_consultar.click()
                                    await page.wait_for_timeout(3000)
                                except Exception as e:
                                    print(f"        Error al hacer click en Consultar: {e}")

                            mesas = await extraer_estado_mesas(page)
                            if mesas:
                                for mesa_info in mesas:
                                    registro = {
                                        "corporacion": corp_nombre,
                                        "departamento": depto_text,
                                        "municipio": muni_text,
                                        "zona": zona_text,
                                        "puesto": puesto_text,
                                        "estado_mesas": mesa_info,
                                        "fecha_extraccion": datetime.now().isoformat(),
                                    }
                                    todos_registros.append(registro)
                                print(f"        Mesas encontradas: {len(mesas)}")
                            else:
                                registro = {
                                    "corporacion": corp_nombre,
                                    "departamento": depto_text,
                                    "municipio": muni_text,
                                    "zona": zona_text,
                                    "puesto": puesto_text,
                                    "estado_mesas": {"estado": "sin_mesas_detectadas"},
                                    "fecha_extraccion": datetime.now().isoformat(),
                                }
                                todos_registros.append(registro)

                            if solo_primer_puesto:
                                break

                        if solo_primer_puesto:
                            break
                    if solo_primer_puesto:
                        break
                if solo_primer_puesto:
                    break
            if solo_primer_puesto:
                break

        await browser.close()

    return todos_registros


async def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, OUTPUT_CSV)
    json_path = os.path.join(script_dir, OUTPUT_JSON)

    print("Scraper Estado Mesas E14 - Actas Congreso 2026")
    print(f"Departamentos: {', '.join(DEPARTAMENTOS_OBJETIVO)}")
    print(f"Corporaciones: Senado, Camara")
    print(f"Salida CSV: {csv_path}")

    # Para pruebas: python scraper_estado_mesas_e14.py --test
    import sys
    solo_primer_puesto = "--test" in sys.argv
    registros = await scrape_actas_e14(headless=False, solo_primer_puesto=solo_primer_puesto)

    if registros:
        # Guardar CSV (aplanado para mesas)
        rows_csv = []
        for r in registros:
            em = r.get("estado_mesas", {})
            if isinstance(em, dict):
                row = {
                    "corporacion": r.get("corporacion"),
                    "departamento": r.get("departamento"),
                    "municipio": r.get("municipio"),
                    "zona": r.get("zona"),
                    "puesto": r.get("puesto"),
                    **{f"mesa_{k}": v for k, v in em.items()},
                    "fecha_extraccion": r.get("fecha_extraccion"),
                }
            else:
                row = {**r, "estado_mesas": str(em)}
            rows_csv.append(row)

        if rows_csv:
            keys = list(rows_csv[0].keys())
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows_csv)
            print(f"\nCSV guardado: {csv_path} ({len(rows_csv)} filas)")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(registros, f, ensure_ascii=False, indent=2)
        print(f"JSON guardado: {json_path}")
    else:
        print("\nNo se extrajeron registros. Revisa selectores y estructura de la pagina.")


if __name__ == "__main__":
