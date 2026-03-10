"""
Scraper para resultados.registraduria.gov.co - SENADO por territorio.

Flujo:
1. Ir a https://resultados.registraduria.gov.co/resultados/0/00/0?s=
2. Desplegable territorios: País=COLOMBIA, Departamento=VALLE, Municipio=...
3. Consultar → buscar sección de partidos
4. Expandir PARTIDO CONSERVADOR COLOMBIANO y extraer candidatos al Senado.
5. Filtrar solo Juan Camilo Vélez (ignorar el resto de la lista conservadora).
6. CSV: resultados_senado_conservador_por_municipio.csv
"""

import asyncio
import csv
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set

from playwright.async_api import Page, async_playwright, TimeoutError as PlaywrightTimeout

from scrapper.config import DEPARTAMENTOS, CONFIG, CANDIDATO_SENADO

logger = logging.getLogger(__name__)

URL_BASE = "https://resultados.registraduria.gov.co"
URL_HOME = URL_BASE
URL_SENADO = URL_BASE + "/resultados/0/00/0/?s=resultados-votes"

TIMEOUT_MS = 25_000
SLEEP_AFTER_CLICK = 800
SLEEP_POPOVER = 600

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "backup"

CSV_SENADO_CONSERVADOR = OUTPUT_DIR / "resultados_senado_conservador_por_municipio.csv"
CSV_COLS = ["DEPARTAMENTO", "MUNICIPIO", "CANDIDATO", "VOTOS", "PORCENTAJE", "FECHA_EXTRACCION"]

NOMBRE_PARTIDO_CONSERVADOR = "PARTIDO CONSERVADOR COLOMBIANO"


def _obtener_municipios(depto: str) -> List[str]:
    """Lista de municipios del departamento desde config."""
    if CONFIG.get("departamentos") and depto in CONFIG["departamentos"]:
        return list(CONFIG["departamentos"][depto].get("municipios", []))
    return []


def _es_juan_camilo_velez(nombre_extraido: str) -> bool:
    """
    True si el nombre extraído corresponde a Juan Camilo Vélez.
    Ignora el resto de la lista conservadora.
    """
    ext = (nombre_extraido or "").strip().lower()
    # Variantes: Juan Camilo Vélez, Juan Camilo Velez, Juan Camilo Vélez Londoño, etc.
    if "juan" in ext and "camilo" in ext and "velez" in ext:
        return True
    if "juan camilo vélez" in ext or "juan camilo velez" in ext:
        return True
    return False


def _nombres_senado_objetivo() -> Set[str]:
    """Solo Juan Camilo Vélez. Config CANDIDATO_SENADO como fallback."""
    base = Path(__file__).resolve().parent.parent
    info_file = base / "info_para_scrpping_costo_por_voto_juan.txt"
    if info_file.exists():
        for line in info_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if " - " in line and "SENADO" in line.upper():
                nombre = line.split(" - ")[0].strip()
                if nombre and not nombre.startswith("/"):
                    return {nombre}
    cfg = CANDIDATO_SENADO or "Juan Camilo Vélez"
    return {cfg if isinstance(cfg, str) else str(cfg)}


async def _click_senado(page: Page) -> bool:
    """En la página principal, hace clic en el enlace SENADO (o navega directo a URL_SENADO)."""
    try:
        loc = page.locator('a[href="/resultados/0/00/0"]').first
        await loc.wait_for(state="visible", timeout=10000)
        await loc.click()
        await page.wait_for_timeout(SLEEP_AFTER_CLICK)
        await page.wait_for_url("**/resultados/0/**", timeout=TIMEOUT_MS)
        return True
    except Exception:
        pass
    try:
        await page.goto(URL_SENADO, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(SLEEP_AFTER_CLICK)
        return "/resultados/0/" in page.url
    except Exception as e:
        logger.debug(f"Error navegar a SENADO: {e}")
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
            return False
        await page.wait_for_timeout(SLEEP_POPOVER)
        return True
    except Exception as e:
        logger.debug(f"Error seleccionar departamento {departamento}: {e}")
    return False


async def _seleccionar_municipio(page: Page, nombre_municipio: str) -> bool:
    """Tras elegir departamento, selecciona el municipio por nombre."""
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
            for (const o of opts) {
                const t = norm(o.textContent);
                if (t.includes(target) || target.includes(t)) { o.click(); return true; }
            }
            return false;
        }""", nombre_municipio)
        if not clicked:
            return False
        await page.wait_for_timeout(SLEEP_POPOVER)
        return True
    except Exception as e:
        logger.debug(f"Seleccionar municipio {nombre_municipio}: {e}")
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


async def _expandir_partido_conservador(page: Page) -> bool:
    """Expande la tarjeta de PARTIDO CONSERVADOR COLOMBIANO."""
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
    if not texto:
        return 0
    s = re.sub(r"[\s\.]", "", str(texto).strip())
    return int(s) if s.isdigit() else 0


async def _extraer_candidatos_conservador(page: Page) -> List[dict]:
    """Extrae candidatos y votos del panel abierto del Partido Conservador."""
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


async def navegar_municipio_y_extraer_senado(
    page: Page,
    departamento: str,
    municipio: str,
) -> List[dict]:
    """
    Navega a URL_SENADO, selecciona departamento y municipio, Consultar,
    expande Partido Conservador y extrae candidatos. Solo devuelve los que
    coinciden con Juan Camilo Vélez.
    """
    try:
        await page.goto(URL_SENADO, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
    except Exception:
        try:
            await page.wait_for_timeout(2000)
            await page.goto(URL_SENADO, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
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
        return []
    todos = await _extraer_candidatos_conservador(page)
    # Solo Juan Camilo Vélez
    return [c for c in todos if _es_juan_camilo_velez(c.get("candidato", ""))]


DEPARTAMENTOS_OBJETIVO = list(DEPARTAMENTOS) if DEPARTAMENTOS else ["VALLE", "RISARALDA", "CALDAS"]


async def run_scraper_senado_conservador_por_municipios(
    departamentos: Optional[List[str]] = None,
    headless: bool = False,
    csv_path: Optional[Path] = None,
) -> Path:
    """
    Recorre cada municipio de VALLE, RISARALDA y CALDAS (o la lista indicada).
    En cada uno extrae votos de Juan Camilo Vélez (Senado, Partido Conservador)
    y guarda en CSV. Ignora el resto de la lista conservadora.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = csv_path or CSV_SENADO_CONSERVADOR
    deptos = departamentos or DEPARTAMENTOS_OBJETIVO

    total_municipios = sum(len(_obtener_municipios(d)) for d in deptos)
    if total_municipios == 0:
        logger.warning("No hay municipios configurados para %s.", deptos)
        return out_path

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
            await page.goto(URL_SENADO, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)
            if "/resultados/0/" not in page.url:
                logger.error("No se pudo cargar la página de SENADO.")
                f.close()
                return out_path

            contador = 0
            for departamento in deptos:
                municipios = _obtener_municipios(departamento)
                if not municipios:
                    continue
                logger.info("=== SENADO %s (%d municipios) ===", departamento, len(municipios))
                ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for i, municipio in enumerate(municipios):
                    contador += 1
                    logger.info("[%d/%d] %s / %s (Juan Camilo Vélez) ...", contador, total_municipios, departamento, municipio)
                    candidatos = await navegar_municipio_y_extraer_senado(
                        page, departamento, municipio
                    )
                    for c in candidatos:
                        w.writerow({
                            "DEPARTAMENTO": departamento,
                            "MUNICIPIO": municipio,
                            "CANDIDATO": c.get("candidato", ""),
                            "VOTOS": c.get("votos", 0),
                            "PORCENTAJE": c.get("porcentaje", ""),
                            "FECHA_EXTRACCION": ahora,
                        })
                    f.flush()
        finally:
            await browser.close()
            f.close()

    logger.info("CSV Senado guardado: %s", out_path)
    return out_path


def run_sync_senado_por_municipios(
    departamentos: Optional[List[str]] = None,
    headless: bool = False,
    csv_path: Optional[Path] = None,
) -> Path:
    """Versión síncrona."""
    return asyncio.run(
        run_scraper_senado_conservador_por_municipios(
            departamentos=departamentos or DEPARTAMENTOS_OBJETIVO,
            headless=headless,
            csv_path=csv_path,
        )
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_sync_senado_por_municipios(headless=False)
