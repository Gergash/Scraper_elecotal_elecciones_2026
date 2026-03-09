"""
Scraper para resultados.registraduria.gov.co - CÁMARA por territorio.

Flujo:
1. Ir a https://resultados.registraduria.gov.co → Clic CAMARA
2. Desplegable territorios: País=COLOMBIA, Departamento=VALLE, Municipio=...
3. Consultar → en la página resultante buscar la sección de partidos
4. Expandir PARTIDO CONSERVADOR COLOMBIANO y extraer candidatos a Cámara (nombre + votos).
5. Repetir por cada municipio del departamento y guardar CSV.
"""

import asyncio
import csv
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set

from playwright.async_api import Page, async_playwright, TimeoutError as PlaywrightTimeout

from scrapper.config import DEPARTAMENTOS, CONFIG, CANDIDATOS_CAMARA

logger = logging.getLogger(__name__)

URL_BASE = "https://resultados.registraduria.gov.co"
URL_HOME = URL_BASE
URL_CAMARA = URL_BASE + "/resultados/1/00/0/?s=resultados-votes"

TIMEOUT_MS = 25_000
SLEEP_AFTER_CLICK = 800
SLEEP_POPOVER = 600

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "backup"

# CSV salida: resultados Cámara (Conservador) por municipio
CSV_CAMARA_CONSERVADOR = OUTPUT_DIR / "resultados_camara_conservador_por_municipio.csv"
CSV_COLS = ["DEPARTAMENTO", "MUNICIPIO", "CANDIDATO", "VOTOS", "PORCENTAJE", "FECHA_EXTRACCION"]

NOMBRE_PARTIDO_CONSERVADOR = "PARTIDO CONSERVADOR COLOMBIANO"


def _obtener_municipios(depto: str) -> List[str]:
    """Lista de municipios del departamento desde config."""
    if CONFIG.get("departamentos") and depto in CONFIG["departamentos"]:
        return list(CONFIG["departamentos"][depto].get("municipios", []))
    return []


def _candidato_coincide(nombre_extraido: str, nombres_filtrar: Set[str]) -> bool:
    """
    True si nombre_extraido coincide con alguno de nombres_filtrar.
    La página puede mostrar "CRISTIAN HERNAN VIVEROS VASQUEZ"; la lista tiene "Cristian Viveros".
    Se normaliza a minúsculas y se comprueba si el nombre de la lista está contenido en el extraído.
    """
    if not nombres_filtrar:
        return True
    ext = (nombre_extraido or "").strip().lower()
    for n in nombres_filtrar:
        if (n or "").strip().lower() in ext:
            return True
    return False


def _nombres_candidatos_camara_objetivo() -> Set[str]:
    """Set de nombres completos de los candidatos a Cámara a extraer (VALLE, RISARALDA, CALDAS)."""
    # Intentar primero desde info_para_scrpping_costo_por_voto_juan.txt
    base = Path(__file__).resolve().parent.parent
    info_file = base / "info_para_scrpping_costo_por_voto_juan.txt"
    if info_file.exists():
        nombres = set()
        for line in info_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            # Líneas tipo "Rigo Vega Cartago - VALLE - CAMARA"
            if " - " in line and "CAMARA" in line.upper():
                nombre = line.split(" - ")[0].strip()
                if nombre and not nombre.startswith("/"):
                    nombres.add(nombre)
        if nombres:
            return nombres
    # Fallback: config
    nombres = set()
    for depto, lista in (CANDIDATOS_CAMARA or {}).items():
        for c in lista:
            if isinstance(c, dict):
                nombres.add(c.get("nombre_completo", "").strip())
            else:
                nombres.add(str(c).strip())
    return {n for n in nombres if n}


async def _click_camara(page: Page) -> bool:
    """En la página principal, hace clic en el botón CAMARA."""
    try:
        # Enlace que lleva a Cámara: href="/resultados/1/00/0"
        loc = page.locator('a[href="/resultados/1/00/0"]').first
        await loc.wait_for(state="visible", timeout=10000)
        await loc.click()
        await page.wait_for_timeout(SLEEP_AFTER_CLICK)
        await page.wait_for_url("**/resultados/1/**", timeout=TIMEOUT_MS)
        return True
    except Exception as e:
        logger.debug(f"Error clic CAMARA: {e}")
    return False


async def _abrir_desplegable_territorios(page: Page) -> bool:
    """Abre el desplegable de navegación por territorios."""
    try:
        btn = page.locator('button[aria-label*="Abrir desplegable"]').first
        await btn.wait_for(state="visible", timeout=10000)
        await btn.click()
        await page.wait_for_timeout(SLEEP_POPOVER)
        popover = page.locator('.rt-PopoverContent').first
        await popover.wait_for(state="visible", timeout=5000)
        return True
    except Exception as e:
        logger.debug(f"Error abrir desplegable territorios: {e}")
    return False


async def _seleccionar_departamento(page: Page, departamento: str = "VALLE") -> bool:
    """En el popover abierto, selecciona el departamento."""
    try:
        popover = page.locator('.rt-PopoverContent').first
        await popover.locator('.rt-SelectTrigger').nth(1).click()
        await page.wait_for_timeout(SLEEP_POPOVER)
        clicked = await page.evaluate("""(depto) => {
            const opts = document.querySelectorAll("[role='option']");
            for (const o of opts) {
                if (o.textContent.trim() === depto) { o.click(); return true; }
            }
            return false;
        }""", departamento)
        if not clicked:
            logger.debug(f"Opción departamento '{departamento}' no encontrada en listbox.")
            return False
        await page.wait_for_timeout(SLEEP_POPOVER)
        return True
    except Exception as e:
        logger.debug(f"Error seleccionar departamento {departamento}: {e}")
    return False


async def _seleccionar_primer_municipio(page: Page) -> bool:
    """Tras elegir departamento, selecciona la primera opción de municipio."""
    return await _seleccionar_municipio_por_indice(page, 0)


async def _seleccionar_municipio(page: Page, nombre_municipio: str) -> bool:
    """Tras elegir departamento, selecciona el municipio por nombre (normaliza acentos y mayúsculas)."""
    try:
        popover = page.locator('.rt-PopoverContent').first
        await popover.locator('.rt-SelectTrigger').nth(2).click()
        await page.wait_for_timeout(SLEEP_POPOVER)
        clicked = await page.evaluate("""(muni) => {
            function norm(s) {
                return s.toUpperCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').trim();
            }
            const target = norm(muni);
            const opts = document.querySelectorAll("[role='option']");
            for (const o of opts) {
                if (norm(o.textContent) === target) { o.click(); return true; }
            }
            // Fallback: el target está contenido en la opción o viceversa
            for (const o of opts) {
                const t = norm(o.textContent);
                if (t.includes(target) || target.includes(t)) { o.click(); return true; }
            }
            return false;
        }""", nombre_municipio)
        if not clicked:
            logger.debug(f"Opción municipio '{nombre_municipio}' no encontrada.")
            return False
        await page.wait_for_timeout(SLEEP_POPOVER)
        return True
    except Exception as e:
        logger.debug(f"Seleccionar municipio {nombre_municipio}: {e}")
    return False


async def _seleccionar_municipio_por_indice(page: Page, indice: int) -> bool:
    """Selecciona el municipio por índice en la lista (0 = primero)."""
    try:
        popover = page.locator('.rt-PopoverContent').first
        await popover.locator('.rt-SelectTrigger').nth(2).click()
        await page.wait_for_timeout(SLEEP_POPOVER)
        clicked = await page.evaluate("""(idx) => {
            const opts = document.querySelectorAll("[role='option']");
            if (opts[idx]) { opts[idx].click(); return true; }
            return false;
        }""", indice)
        await page.wait_for_timeout(SLEEP_POPOVER)
        return bool(clicked)
    except Exception as e:
        logger.debug(f"Selector municipio índice {indice}: {e}")
    return False


async def _click_consultar(page: Page) -> bool:
    """En el popover, hace clic en el enlace Consultar."""
    try:
        popover = page.locator('.rt-PopoverContent').first
        consultar = popover.locator('a:has-text("Consultar")').first
        await consultar.wait_for(state="visible", timeout=5000)
        await consultar.click()
        await page.wait_for_timeout(SLEEP_AFTER_CLICK + 1500)
        return True
    except Exception as e:
        logger.debug(f"Error clic Consultar: {e}")
    return False


# ──────────────────────────────────────────────
# Extracción Partido Conservador (lista candidatos + votos)
# ──────────────────────────────────────────────


async def _expandir_partido_conservador(page: Page) -> bool:
    """Expande la tarjeta de PARTIDO CONSERVADOR COLOMBIANO via JS."""
    try:
        result = await page.evaluate("""() => {
            const parrafos = document.querySelectorAll("p.rt-Text");
            for (const p of parrafos) {
                if (p.textContent.includes("CONSERVADOR COLOMBIANO")) {
                    const acordeon = p.closest("[data-orientation='vertical']");
                    if (acordeon) {
                        const boton = acordeon.querySelector("button[aria-expanded]");
                        if (boton) { boton.click(); return true; }
                    }
                }
            }
            return false;
        }""")
        if not result:
            return False
        await page.wait_for_timeout(1000)
        return True
    except Exception as e:
        logger.debug(f"Expandir Partido Conservador: {e}")
    return False


def _normalizar_votos(texto: str) -> int:
    """Convierte '1.636' o '72' a entero."""
    if not texto:
        return 0
    s = re.sub(r"[\s\.]", "", str(texto).strip())
    return int(s) if s.isdigit() else 0


def _normalizar_pct(texto: str) -> str:
    """Mantiene el porcentaje como string legible."""
    return (texto or "").strip().replace("\u00a0", " ")


async def _extraer_candidatos_conservador(page: Page) -> List[dict]:
    """Extrae candidatos y votos del panel abierto del Partido Conservador via JS."""
    try:
        pairs = await page.evaluate("""() => {
            const regions = document.querySelectorAll("[data-state='open'][role='region']");
            for (const el of regions) {
                if (el.innerHTML.length < 200) continue;
                const spans = Array.from(el.querySelectorAll("span.rt-Text"));
                const results = [];
                for (let i = 0; i < spans.length - 1; i++) {
                    const name = spans[i].textContent.trim();
                    const votes = spans[i + 1].textContent.trim();
                    if (name.length > 4 && /^[0-9][0-9.]*$/.test(votes)) {
                        results.push({ candidato: name, votos_txt: votes });
                        i++;
                    }
                }
                if (results.length > 0) return results;
            }
            return [];
        }""")
        return [
            {"candidato": r["candidato"], "votos": _normalizar_votos(r["votos_txt"]), "porcentaje": ""}
            for r in (pairs or [])
        ]
    except Exception as e:
        logger.debug(f"Extraer candidatos Conservador: {e}")
    return []


async def navegar_camara_valle_primer_municipio(
    page: Page,
    departamento: str = "VALLE",
    usar_primer_municipio: bool = True,
) -> Optional[str]:
    """
    Ejecuta el flujo: CAMARA → desplegable → Departamento=VALLE → primer municipio → Consultar.
    Devuelve la URL final, o None si falla.
    """
    current = page.url
    if "/resultados/1/" not in current:
        await page.goto(URL_HOME, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        if not await _click_camara(page):
            logger.warning("No se pudo hacer clic en CAMARA.")
            return None
    else:
        await page.goto(URL_CAMARA, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

    if not await _abrir_desplegable_territorios(page):
        logger.warning("No se pudo abrir el desplegable de territorios.")
        return None
    if not await _seleccionar_departamento(page, departamento=departamento):
        logger.warning(f"No se pudo seleccionar departamento {departamento}.")
        return None
    if usar_primer_municipio:
        await _seleccionar_primer_municipio(page)
    if not await _click_consultar(page):
        logger.warning("No se pudo hacer clic en Consultar.")
        return None

    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeout:
        pass
    await page.wait_for_timeout(2000)
    return page.url


async def navegar_municipio_y_extraer_conservador(
    page: Page,
    departamento: str,
    municipio: str,
) -> List[dict]:
    """
    Navega a URL_CAMARA (resetea estado), luego selecciona departamento y municipio,
    hace Consultar, expande Partido Conservador y extrae candidatos con votos.
    """
    # Siempre partir del nivel Colombia (nivel 00) para tener los dropdowns disponibles
    try:
        await page.goto(URL_CAMARA, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
    except Exception:
        # Reintentar una vez si la navegación falla (ERR_NETWORK_IO_SUSPENDED, timeout, etc.)
        try:
            await page.wait_for_timeout(2000)
            await page.goto(URL_CAMARA, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
        except Exception:
            return []
    if not await _abrir_desplegable_territorios(page):
        return []
    if not await _seleccionar_departamento(page, departamento=departamento):
        return []
    if not await _seleccionar_municipio(page, municipio):
        return []
    if not await _click_consultar(page):
        return []

    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeout:
        pass
    await page.wait_for_timeout(2000)

    if not await _expandir_partido_conservador(page):
        logger.warning(f"  No se pudo expandir Partido Conservador en {municipio}.")
        return []
    return await _extraer_candidatos_conservador(page)


async def run_scraper_resultados_camara(
    departamento: str = "VALLE",
    headless: bool = False,
) -> Optional[str]:
    """
    Abre el navegador, ejecuta el flujo CAMARA → VALLE → primer municipio → Consultar
    y devuelve la URL de la página resultante.
    """
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
        page = await context.new_page()
        try:
            url = await navegar_camara_valle_primer_municipio(
                page,
                departamento=departamento,
                usar_primer_municipio=True,
            )
            return url
        finally:
            await browser.close()


# Departamentos a recorrer por defecto (VALLE, RISARALDA, CALDAS)
DEPARTAMENTOS_OBJETIVO = list(DEPARTAMENTOS) if DEPARTAMENTOS else ["VALLE", "RISARALDA", "CALDAS"]


async def run_scraper_camara_conservador_por_municipios(
    departamentos: Optional[List[str]] = None,
    headless: bool = False,
    csv_path: Optional[Path] = None,
    candidatos_filtrar: Optional[List[str]] = None,
) -> Path:
    """
    Recorre cada municipio de VALLE, RISARALDA y CALDAS (o la lista indicada).
    En cada uno extrae la lista de candidatos a Cámara del Partido Conservador
    (nombre + votos) y guarda en CSV. Si candidatos_filtrar está definido, solo
    se escriben filas para esos candidatos (p. ej. lista de info_para_scrpping_costo_por_voto_juan.txt).
    CSV: DEPARTAMENTO, MUNICIPIO, CANDIDATO, VOTOS, PORCENTAJE, FECHA_EXTRACCION.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = csv_path or CSV_CAMARA_CONSERVADOR
    deptos = departamentos or DEPARTAMENTOS_OBJETIVO
    set_filtrar = set(candidatos_filtrar) if candidatos_filtrar else None

    total_municipios = sum(len(_obtener_municipios(d)) for d in deptos)
    if total_municipios == 0:
        logger.warning("No hay municipios configurados para %s.", deptos)
        return out_path

    # Append si ya existe (permite reanudar tras un crash), overwrite si es nuevo
    existe = out_path.exists()
    f = open(out_path, "a", newline="", encoding="utf-8-sig")
    w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
    if not existe:
        w.writeheader()

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
        page = await context.new_page()
        try:
            await page.goto(URL_CAMARA, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)
            # Verificar que estamos en la página de Cámara
            if "/resultados/1/" not in page.url:
                logger.error("No se pudo cargar la página de CÁMARA.")
                f.close()
                return out_path

            contador = 0
            for departamento in deptos:
                municipios = _obtener_municipios(departamento)
                if not municipios:
                    logger.warning("Sin municipios para %s, se omite.", departamento)
                    continue
                logger.info("=== %s (%d municipios) ===", departamento, len(municipios))
                ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for i, municipio in enumerate(municipios):
                    contador += 1
                    logger.info("[%d/%d] %s / %s ...", contador, total_municipios, departamento, municipio)
                    candidatos = await navegar_municipio_y_extraer_conservador(
                        page, departamento, municipio
                    )
                    for c in candidatos:
                        nombre = c.get("candidato", "")
                        if set_filtrar and not _candidato_coincide(nombre, set_filtrar):
                            continue
                        w.writerow({
                            "DEPARTAMENTO": departamento,
                            "MUNICIPIO": municipio,
                            "CANDIDATO": nombre,
                            "VOTOS": c.get("votos", 0),
                            "PORCENTAJE": c.get("porcentaje", ""),
                            "FECHA_EXTRACCION": ahora,
                        })
                    f.flush()
        finally:
            await browser.close()
            f.close()

    logger.info("CSV guardado: %s", out_path)
    return out_path


def run_sync(departamento: str = "VALLE", headless: bool = False) -> Optional[str]:
    """Versión síncrona (solo navegación al primer municipio)."""
    return asyncio.run(run_scraper_resultados_camara(departamento=departamento, headless=headless))


def run_sync_por_municipios(
    departamentos: Optional[List[str]] = None,
    headless: bool = False,
    csv_path: Optional[Path] = None,
    candidatos_filtrar: Optional[List[str]] = None,
) -> Path:
    """Versión síncrona: extrae candidatos Conservador por cada municipio. Si candidatos_filtrar se omite, se extraen todos; si se pasa, solo esos."""
    return asyncio.run(
        run_scraper_camara_conservador_por_municipios(
            departamentos=departamentos or DEPARTAMENTOS_OBJETIVO,
            headless=headless,
            csv_path=csv_path,
            candidatos_filtrar=candidatos_filtrar,
        )
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Por defecto: VALLE, RISARALDA y CALDAS
    run_sync_por_municipios(headless=False)
