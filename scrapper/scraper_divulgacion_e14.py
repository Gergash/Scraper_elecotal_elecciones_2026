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

URL_BASE = "https://divulgacione14congreso.registraduria.gov.co"
URL_HOME = URL_BASE + "/home"

# Secciones del paginador donde están VALLE, CALDAS, RISARALDA
PAGINAS_OBJETIVO = ["01", "03", "04"]

TIMEOUT_MS = 25_000
SLEEP_PAGE = 2.0
SLEEP_MENU = 1.5
SLEEP_DESCARGA = 1.0

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "backup"
E14_DESCARGA_DIR = OUTPUT_DIR / "e14_descargas"

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
    target = opcion.strip().upper()
    try:
        # Esperar a que el menú esté renderizado (Angular puede tardar en paralelo)
        await page.wait_for_selector("div.menu .item", timeout=12000)
        items = await page.query_selector_all("div.menu .item")
        for item in items:
            txt = (await item.inner_text() or "").strip().upper()
            if txt == target:
                await item.click()
                await page.wait_for_timeout(int(SLEEP_MENU * 1000))
                logger.debug(f"Menú '{target}' seleccionado.")
                return True
        logger.debug(f"Menú '{target}' no encontrado entre {[( await i.inner_text()) for i in items]}")
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
# Descarga de E14 por departamento
# ──────────────────────────────────────────────


def _es_enlace_e14(href: str) -> bool:
    """Determina si un href parece ser un E14 o acta descargable."""
    if not href or not isinstance(href, str):
        return False
    h = href.lower().strip()
    if h.endswith(".pdf"):
        return True
    if ".pdf?" in h or "acta" in h or "e14" in h or "e-14" in h:
        return True
    if "descargar" in h or "download" in h:
        return True
    return False


async def _enlaces_e14_en_pagina(page: Page) -> List[tuple]:
    """Obtiene (href, texto) de enlaces que parecen E14/acta en la página actual."""
    seen: set = set()
    out: List[tuple] = []
    try:
        links = await page.query_selector_all('a[href]')
        for a in links:
            href = await a.get_attribute("href")
            if not _es_enlace_e14(href):
                continue
            href = href or ""
            if href in seen:
                continue
            seen.add(href)
            text = (await a.inner_text() or "").strip()[:200]
            out.append((href, text))
        # Filas de tabla con enlace tipo E14
        rows = await page.query_selector_all(".tbody .columns.data-row a[href]")
        for a in rows:
            href = await a.get_attribute("href")
            if not href or not _es_enlace_e14(href) or href in seen:
                continue
            seen.add(href)
            text = (await a.inner_text() or "").strip()[:200]
            out.append((href, text))
    except Exception as e:
        logger.debug(f"Error recogiendo enlaces E14: {e}")
    return out


async def _enlaces_subpaginas(page: Page) -> List[tuple]:
    """En la página de departamento, enlaces de la tabla que llevan a subpáginas (municipio/zona/mesa)."""
    out: List[tuple] = []
    try:
        rows = await page.query_selector_all(".tbody .columns.data-row .td.departamento a[href], .tbody .columns.data-row .td a[href]")
        for a in rows:
            href = await a.get_attribute("href")
            if not href or href in {x for x, _ in out}:
                continue
            if _es_enlace_e14(href):
                continue
            text = (await a.inner_text() or "").strip()[:200]
            out.append((href, text))
    except Exception as e:
        logger.debug(f"Error recogiendo subpáginas: {e}")
    return out


async def _descargar_e14_departamento(
    page: Page,
    corp: str,
    fila: FilaDepartamento,
    dir_base: Path,
    max_descargas: int = 5000,
    seguir_subpaginas: bool = True,
) -> int:
    """
    Navega a la página del departamento (URL_BASE + href) y descarga
    todos los E14 encontrados. Si seguir_subpaginas=True, entra en cada
    enlace de la tabla (municipio/zona/mesa) y descarga E14 allí.
    """
    if not fila.href or not fila.href.strip():
        return 0
    url_depto = URL_BASE + fila.href if fila.href.startswith("/") else (URL_BASE + "/" + fila.href)
    depto_nombre = re.sub(r"[^\w\s-]", "", fila.departamento.strip()).replace(" ", "_")
    carpeta = dir_base / corp.upper().replace(" ", "_") / depto_nombre
    carpeta.mkdir(parents=True, exist_ok=True)

    descargados = 0
    try:
        logger.info(f"    Navegando a {url_depto} ...")
        await page.goto(url_depto, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(int(SLEEP_PAGE * 1000))

        enlaces = await _enlaces_e14_en_pagina(page)

        # Si no hay E14 directos, intentar subpáginas (tabla municipio/zona/mesa)
        if seguir_subpaginas and not enlaces:
            subpaginas = await _enlaces_subpaginas(page)
            for sub_href, sub_text in subpaginas:
                if descargados >= max_descargas:
                    break
                sub_url = sub_href if sub_href.startswith("http") else (URL_BASE + (sub_href if sub_href.startswith("/") else "/" + sub_href))
                try:
                    await page.goto(sub_url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
                    await page.wait_for_timeout(500)
                    sub_enlaces = await _enlaces_e14_en_pagina(page)
                    for href, texto in sub_enlaces:
                        if descargados >= max_descargas:
                            break
                        full_url = href if href.startswith("http") else (URL_BASE + (href if href.startswith("/") else "/" + href))
                        try:
                            response = await page.request.get(full_url, timeout=15000)
                            body = await response.body() if response.status == 200 else None
                            if not body:
                                continue
                            safe_name = re.sub(r"[^\w\.\-]", "_", (sub_text + "_" + (texto or "e14"))[:80]) or "e14"
                            if not safe_name.lower().endswith(".pdf"):
                                safe_name += ".pdf"
                            path = carpeta / f"{descargados:04d}_{safe_name}"
                            path.write_bytes(body)
                            descargados += 1
                            logger.info(f"    Descargado: {path.name}")
                        except Exception as e:
                            logger.debug(f"    No descargar {full_url}: {e}")
                        await page.wait_for_timeout(int(SLEEP_DESCARGA * 1000))
                except Exception as e:
                    logger.debug(f"    Subpágina {sub_url}: {e}")
                await page.goto(url_depto, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
                await page.wait_for_timeout(500)

        if not enlaces and descargados == 0:
            debug_html = OUTPUT_DIR / "debug_departamento_e14.html"
            if not debug_html.exists():
                content = await page.content()
                debug_html.write_bytes(content.encode("utf-8"))
                logger.info(f"    Sin enlaces E14; HTML en {debug_html} para revisión.")

        for href, texto in enlaces:
            if descargados >= max_descargas:
                break
            full_url = href if href.startswith("http") else (URL_BASE + (href if href.startswith("/") else "/" + href))
            try:
                # Usar request del contexto para GET y guardar cuerpo si es PDF
                response = await page.request.get(full_url, timeout=15000)
                if response.status != 200:
                    continue
                ct = (response.headers.get("content-type") or "").lower()
                body = await response.body()
                if not body:
                    continue
                safe_name = re.sub(r"[^\w\.\-]", "_", (texto or "e14")[:80]) or "e14"
                if not safe_name.lower().endswith(".pdf"):
                    safe_name += ".pdf"
                path = carpeta / f"{descargados:04d}_{safe_name}"
                path.write_bytes(body)
                descargados += 1
                logger.info(f"    Descargado: {path.name}")
            except Exception as e:
                logger.debug(f"    No se pudo descargar {full_url}: {e}")
            await page.wait_for_timeout(int(SLEEP_DESCARGA * 1000))
    except Exception as e:
        logger.warning(f"    Error en departamento {fila.departamento}: {e}")
    return descargados


# ──────────────────────────────────────────────
# Scraper principal
# ──────────────────────────────────────────────


async def scrape_divulgacion_e14(
    corporaciones: Optional[List[str]] = None,
    departamentos_objetivo: Optional[List[str]] = None,
    paginas: Optional[List[str]] = None,
    headless: bool = False,
    csv_path: Optional[Path] = None,
    descargar_e14: bool = True,
) -> Path:
    """
    Scraping de divulgacione14congreso/home.
    Navega entre SENADO/CAMARA y páginas 01, 03, 04.
    Extrae progreso de mesas para VALLE, CALDAS, RISARALDA.
    Si descargar_e14=True, entra a cada /departamento/XX y descarga los E14 encontrados.
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
    csv_file = open(csv_path, "a", newline="", encoding="utf-8-sig")
    w = csv.DictWriter(csv_file, fieldnames=CSV_COLS, extrasaction="ignore")
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
            await page.wait_for_timeout(5000)

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
                for fila in filas:
                    w.writerow({
                        "CORPORACION": corp,
                        "DEPARTAMENTO": fila.departamento,
                        "ESPERADOS": fila.esperados,
                        "PUBLICADOS": fila.publicados,
                        "AVANCE_PCT": fila.avance_pct,
                        "FALTANTES": fila.faltantes,
                        "HREF": fila.href,
                        "FECHA_EXTRACCION": now,
                    })
                csv_file.flush()

                # Descargar E14 de cada departamento (VALLE, CALDAS, RISARALDA)
                if descargar_e14 and filas:
                    E14_DESCARGA_DIR.mkdir(parents=True, exist_ok=True)
                    for fila in filas:
                        n = await _descargar_e14_departamento(
                            page, corp, fila, E14_DESCARGA_DIR
                        )
                        if n > 0:
                            logger.info(f"  {fila.departamento}: {n} E14 descargados.")

    except Exception as e:
        logger.error(f"Error en scraper divulgación E14: {e}")
        raise
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        csv_file.close()

    logger.info(f"Resultados guardados en {csv_path}")
    return csv_path


def run_sync(
    corporaciones: Optional[List[str]] = None,
    departamentos_objetivo: Optional[List[str]] = None,
    headless: bool = False,
    descargar_e14: bool = True,
) -> Path:
    """Wrapper síncrono."""
    return asyncio.run(
        scrape_divulgacion_e14(
            corporaciones=corporaciones,
            departamentos_objetivo=departamentos_objetivo,
            headless=headless,
            descargar_e14=descargar_e14,
        )
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_sync(headless=False)
