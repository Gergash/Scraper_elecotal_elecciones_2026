"""
Scraper para divulgacione14congreso.registraduria.gov.co/home

Estructura HTML:
- Menú: SENADO, CAMARA, CONSULTAS, CITREP
- Tabla: Departamento | Esperados | Publicados | Avances | Faltantes
- Paginador: 01, 02, 03, 04
- VALLE, CALDAS, RISARALDA en secciones 01, 03 y 04

Extrae progreso por mesas (Esperados, Publicados, Avances, Faltantes)
por departamento para Cámara y Senado.
"""

import asyncio
import csv
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from playwright.async_api import Page, async_playwright, TimeoutError as PlaywrightTimeout

from scrapper.config import (
    CANDIDATOS_CAMARA,
    CANDIDATO_SENADO,
    DEPARTAMENTOS,
)

logger = logging.getLogger(__name__)

URL_HOME = "https://divulgacione14congreso.registraduria.gov.co/home"

# Secciones del paginador donde están VALLE (76), CALDAS (17), RISARALDA (66)
# Página 01: primeros depts (incluye CALDAS)
# Páginas 03, 04: VALLE, RISARALDA
PAGINAS_OBJETIVO = ["01", "03", "04"]

TIMEOUT_MS = 25_000
SLEEP_PAGE = 2.0
SLEEP_MENU = 1.5

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "backup"

CSV_COLS = [
    "CORPORACION",
    "DEPARTAMENTO",
    "ESPERADOS",
    "PUBLICADOS",
    "AVANCE_PCT",
    "FALTANTES",
    "HREF",
    "FECHA_EXTRACCION",
]


@dataclass
class FilaDepartamento:
    departamento: str
    esperados: int
    publicados: int
    avance_pct: str
    faltantes: int
    href: str


def _extraer_int(texto: str) -> int:
    try:
        return int(re.sub(r"\D", "", texto or "0"))
    except (ValueError, TypeError):
        return 0


def _extraer_pct(texto: str) -> str:
    m = re.search(r"(\d+\.?\d*)\s*%", str(texto or ""))
    return m.group(1) + "%" if m else "0%"


# ──────────────────────────────────────────────
# Operaciones sobre la página
# ──────────────────────────────────────────────


async def _click_menu(page: Page, opcion: str) -> bool:
    """Click en menú SENADO o CAMARA."""
    try:
        selector = f'div.menu .item:has-text("{opcion.strip().upper()}")'
        el = await page.wait_for_selector(selector, timeout=5000)
        if el:
            await el.click()
            await page.wait_for_timeout(int(SLEEP_MENU * 1000))
            return True
    except Exception as e:
        logger.debug(f"Error click menú {opcion}: {e}")
    return False


async def _click_pagina(page: Page, num: str) -> bool:
    """Click en paginador 01, 02, 03, 04."""
    try:
        # app-custom-paginator .page con texto "01", "02", etc.
        pages = await page.query_selector_all("app-custom-paginator .page")
        for p in pages:
            txt = (await p.text_content() or "").strip()
            if txt == num:
                await p.click()
                await page.wait_for_timeout(int(SLEEP_PAGE * 1000))
                return True
    except Exception as e:
        logger.debug(f"Error click página {num}: {e}")
    return False


async def _extraer_filas(page: Page) -> List[FilaDepartamento]:
    """Extrae filas de la tabla: Departamento, Esperados, Publicados, Avances, Faltantes."""
    filas: List[FilaDepartamento] = []
    try:
        rows = await page.query_selector_all(".tbody .columns.data-row")
        for row in rows:
            depto_el = await row.query_selector(".td.departamento a")
            depto = (await depto_el.inner_text() if depto_el else "").strip()
            href = await depto_el.get_attribute("href") if depto_el else ""

            expected_el = await row.query_selector(".td.expected-cell h4")
            published_el = await row.query_selector(".td.published-cell h4")
            avance_el = await row.query_selector(".td.progress-cell .progress-title")
            missing_el = await row.query_selector(".td.missing-cell h4")

            esperados = _extraer_int(await expected_el.inner_text() if expected_el else "0")
            publicados = _extraer_int(await published_el.inner_text() if published_el else "0")
            avance_pct = _extraer_pct(await avance_el.inner_text() if avance_el else "0%")
            faltantes = _extraer_int(await missing_el.inner_text() if missing_el else "0")

            filas.append(
                FilaDepartamento(
                    departamento=depto,
                    esperados=esperados,
                    publicados=publicados,
                    avance_pct=avance_pct,
                    faltantes=faltantes,
                    href=href or "",
                )
            )
    except Exception as e:
        logger.debug(f"Error extrayendo filas: {e}")
    return filas


async def _obtener_todas_filas_por_paginas(
    page: Page,
    paginas: Optional[List[str]] = None,
    departamentos: Optional[List[str]] = None,
) -> List[FilaDepartamento]:
    """Recorre paginas 01, 03, 04 y extrae filas. Filtra VALLE, CALDAS, RISARALDA."""
    nums = paginas or PAGINAS_OBJETIVO
    objetivo = {d.upper() for d in (departamentos or DEPARTAMENTOS or ["VALLE", "CALDAS", "RISARALDA"])}
    resultado: List[FilaDepartamento] = []
    vistos: set = set()

    for num in nums:
        await _click_pagina(page, num)
        filas = await _extraer_filas(page)
        for f in filas:
            norm = f.departamento.upper().strip()
            if norm in objetivo and norm not in vistos:
                vistos.add(norm)
                resultado.append(f)
                logger.info(
                    f"  [{num}] {f.departamento}: {f.publicados}/{f.esperados} mesas ({f.avance_pct})"
                )

    return resultado


# ──────────────────────────────────────────────
# Scraper principal
# ──────────────────────────────────────────────


async def scrape_divulgacion_e14(
    corporaciones: Optional[List[str]] = None,
    departamentos_objetivo: Optional[List[str]] = None,
    paginas: Optional[List[str]] = None,
    headless: bool = False,
    csv_path: Optional[Path] = None,
) -> Path:
    """
    Scraping de divulgacione14congreso/home.
    Navega entre SENADO/CAMARA y paginas 01, 03, 04.
    Extrae progreso de mesas para VALLE, CALDAS, RISARALDA.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if csv_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = OUTPUT_DIR / f"divulgacion_e14_{ts}.csv"

    corps = corporaciones or ["SENADO", "CAMARA"]
    deptos = departamentos_objetivo or DEPARTAMENTOS or ["VALLE", "CALDAS", "RISARALDA"]
    paginas_list = paginas or PAGINAS_OBJETIVO

    logger.info(
        f"Scraper divulgación E14 | Corporaciones: {corps} | Deptos: {deptos} | Páginas: {paginas_list}"
    )

    existe = csv_path.exists()
    f = open(csv_path, "a", newline="", encoding="utf-8-sig")
    w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
    if not existe:
        w.writeheader()

    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="es-CO",
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            )
            page = await context.new_page()

            logger.info(f"Cargando {URL_HOME} ...")
            try:
                await page.goto(URL_HOME, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
            except PlaywrightTimeout:
                logger.warning("Timeout en carga inicial, continuando...")
            await page.wait_for_timeout(3000)

            for corp in corps:
                logger.info(f"\n{'='*50}\nCorporación: {corp}\n{'='*50}")

                ok = await _click_menu(page, corp)
                if not ok:
                    logger.warning(f"No se pudo seleccionar menú {corp}")
                    continue

                time.sleep(SLEEP_PAGE)

                filas = await _obtener_todas_filas_por_paginas(
                    page,
                    paginas=paginas_list,
                    departamentos=deptos,
                )

                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for f in filas:
                    w.writerow({
                        "CORPORACION": corp,
                        "DEPARTAMENTO": f.departamento,
                        "ESPERADOS": f.esperados,
                        "PUBLICADOS": f.publicados,
                        "AVANCE_PCT": f.avance_pct,
                        "FALTANTES": f.faltantes,
                        "HREF": f.href,
                        "FECHA_EXTRACCION": now,
                    })
                f.flush()

    except Exception as e:
        logger.error(f"Error en scraper divulgación E14: {e}")
        raise
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        f.close()

    logger.info(f"Resultados guardados en {csv_path}")
    return csv_path


def run_sync(
    corporaciones: Optional[List[str]] = None,
    departamentos_objetivo: Optional[List[str]] = None,
    headless: bool = False,
) -> Path:
    """Wrapper síncrono."""
    return asyncio.run(
        scrape_divulgacion_e14(
            corporaciones=corporaciones,
            departamentos_objetivo=departamentos_objetivo,
            headless=headless,
        )
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_sync(headless=False)
