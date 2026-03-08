"""
Ejecutor paralelo del scraper
- Timeout de 10 segundos por pagina
- Múltiples ventanas/pestañas en paralelo
- Loop: ejecutar -> guardar en backup -> refrescar -> repetir
"""

import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from playwright.async_api import async_playwright, Page

from .config import CONFIG
from .lista_conservador import extraer_candidatos_desde_html, parsear_y_comparar
from .utils import logger

# Timeout por pagina (10 segundos)
TIMEOUT_PAGINA_MS = 10_000

# Carpeta donde guardar todos los archivos generados
BACKUP_DIR = Path(__file__).resolve().parent.parent / "backup"


def asegurar_backup_dir() -> Path:
    """Crea la carpeta backup si no existe"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


async def extraer_party_detail_row(page: Page, timeout_ms: int = TIMEOUT_PAGINA_MS) -> Optional[str]:
    """
    Extrae el HTML de la seccion party-detail-row de la pagina.
    Busca el selector tr.party-detail-row o .party-detail-row
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass  # Continuar aunque no llegue a networkidle

    try:
        # Esperar que exista el elemento party-detail-row
        selector = "tr.party-detail-row, .party-detail-row, [class*='party-detail-row']"
        element = await page.wait_for_selector(selector, timeout=timeout_ms)
        if element:
            html = await element.evaluate("el => el.outerHTML")
            return html
    except Exception as e:
        logger.debug(f"No se encontro party-detail-row: {e}")

    # Fallback: extraer toda la pagina y buscar en el contenido
    try:
        content = await page.content()
        if "party-detail-row" in content:
            # Extraer el fragmento que contiene party-detail-row
            import re
            match = re.search(
                r'<tr[^>]*class="[^"]*party-detail-row[^"]*"[^>]*>.*?</tr>',
                content,
                re.DOTALL
            )
            if match:
                return match.group(0)
    except Exception as e:
        logger.debug(f"Error extrayendo contenido: {e}")

    return None


async def scrape_pagina(
    context,
    url: str,
    timeout_ms: int = TIMEOUT_PAGINA_MS
) -> Optional[dict]:
    """
    Abre una pagina en una nueva pestaña, extrae party-detail-row y retorna los datos.
    """
    page = None
    try:
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)

        response = await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        if response and response.status != 200:
            logger.warning(f"URL {url} retorno status {response.status}")
            return None

        html = await extraer_party_detail_row(page, timeout_ms)
        if html:
            resultado = parsear_y_comparar(html, guardar_csv=False)
            resultado["_url"] = url
            resultado["_html_raw"] = html  # HTML completo para guardar en backup
            return resultado

        logger.debug(f"No se encontro party-detail-row en {url}")
        return None

    except Exception as e:
        logger.error(f"Error scrapeando {url}: {e}")
        return None
    finally:
        if page:
            await page.close()


async def scrape_urls_paralelo(
    urls: List[str],
    timeout_ms: int = TIMEOUT_PAGINA_MS
) -> List[dict]:
    """
    Abre multiples ventanas/pestañas en paralelo y consulta todas las URLs a la vez.
    """
    resultados = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=CONFIG.get("configuracion_scraper", {}).get("headless", False))
        context = await browser.new_context()

        # Ejecutar todas las URLs en paralelo
        tareas = [scrape_pagina(context, url, timeout_ms) for url in urls]
        resultados_raw = await asyncio.gather(*tareas, return_exceptions=True)

        await browser.close()

    for r in resultados_raw:
        if isinstance(r, Exception):
            logger.error(f"Excepcion en tarea: {r}")
        elif r:
            resultados.append(r)

    return resultados


def guardar_en_backup(resultados: List[dict], ciclo: int) -> Path:
    """Guarda todos los resultados en la carpeta backup"""
    backup = asegurar_backup_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefijo = f"ciclo_{ciclo}_{ts}"

    for i, r in enumerate(resultados):
        # Guardar JSON con metadatos (sin _html_raw para no inflar el archivo)
        json_path = backup / f"{prefijo}_resultado_{i}.json"
        data_guardar = {k: v for k, v in r.items() if k not in ("_html_raw",) and not callable(v)}
        if "jcv" in data_guardar and data_guardar["jcv"] is not None:
            jcv = data_guardar["jcv"]
            try:
                data_guardar["jcv"] = asdict(jcv) if hasattr(jcv, "__dataclass_fields__") else getattr(jcv, "__dict__", str(jcv))
            except Exception:
                data_guardar["jcv"] = str(jcv)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data_guardar, f, ensure_ascii=False, indent=2)

        # Si hay candidatos (party-detail-row), guardar CSV
        html_raw = r.get("_html_raw", "")
        if html_raw:
            candidatos = extraer_candidatos_desde_html(html_raw)
            if candidatos:
                csv_path = backup / f"{prefijo}_lista_{i}.csv"
                with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                    w = __import__("csv").writer(f)
                    w.writerow(["Posicion", "Nombre", "Votos", "Porcentaje"])
                    for c in candidatos:
                        w.writerow([c.posicion, c.nombre, c.votos, f"{c.porcentaje:.2f}"])

    # Guardar resumen del ciclo
    resumen_path = backup / f"{prefijo}_resumen.json"
    resumen = {
        "ciclo": ciclo,
        "timestamp": ts,
        "urls_procesadas": len(resultados),
        "encontrados": sum(1 for r in resultados if r.get("encontrado")),
    }
    with open(resumen_path, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)

    logger.info(f"Guardado en backup: {backup} ({len(resultados)} resultados)")
    return backup


async def ejecutar_ciclo(urls: List[str]) -> List[dict]:
    """Ejecuta un ciclo: scrape paralelo de todas las URLs"""
    resultados = await scrape_urls_paralelo(urls, timeout_ms=TIMEOUT_PAGINA_MS)
    return resultados


async def run_loop_continuo(
    urls: List[str],
    max_ciclos: Optional[int] = None,
    pausa_entre_ciclos: int = 5
):
    """
    Loop continuo: ejecutar -> guardar en backup -> refrescar (pausa) -> repetir.

    urls: Lista de URLs a consultar en paralelo
    max_ciclos: None = infinito, o numero maximo de ciclos
    pausa_entre_ciclos: segundos de pausa (simula refresh) entre ciclos
    """
    asegurar_backup_dir()
    logger.info(f"Iniciando scraper paralelo: {len(urls)} URLs, timeout {TIMEOUT_PAGINA_MS/1000}s")
    logger.info(f"Archivos se guardan en: {BACKUP_DIR}")

    ciclo = 0
    while max_ciclos is None or ciclo < max_ciclos:
        ciclo += 1
        logger.info(f"--- Ciclo {ciclo} ---")

        resultados = await ejecutar_ciclo(urls)
        if resultados:
            guardar_en_backup(resultados, ciclo)
        else:
            logger.warning("No se obtuvieron resultados en este ciclo")

        if max_ciclos is not None and ciclo >= max_ciclos:
            break

        logger.info(f"Pausa {pausa_entre_ciclos}s antes del siguiente ciclo (refresh)...")
        await asyncio.sleep(pausa_entre_ciclos)

    logger.info(f"Scraper finalizado. {ciclo} ciclos ejecutados.")


def obtener_urls_desde_config() -> List[str]:
    """Obtiene las URLs a scrapear desde la configuracion"""
    urls = CONFIG.get("urls_scraper", [])
    if isinstance(urls, str):
        urls = [urls]
    return urls if urls else []
