"""
Scraper de comparativa - Lista Partido Conservador al Senado 2026
Consulta periódicamente la URL de resultados de la Registraduría,
extrae los votos de cada candidato del Conservador y los acumula
en comparativa.csv para graficar el crecimiento en el tiempo.

URL: https://resultados.registraduria.gov.co/resultados/0/00/0?s=resultados-votes
CSV de salida: backup/comparativa.csv
Columnas: CANDIDATO, VOTOS, HORA_DE_LA_CONSULTA
"""

import asyncio
import csv
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

from .lista_conservador import extraer_candidatos_desde_html, CandidatoLista, _es_juan_camilo
from .config import CONFIG
from .utils import logger

# ──────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────
URL_RESULTADOS = "https://resultados.registraduria.gov.co/resultados/0/00/0?s=resultados-votes"
TIMEOUT_MS    = 30_000

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "backup"
CSV_PATH   = OUTPUT_DIR / "comparativa.csv"
CSV_COLS   = ["CANDIDATO", "VOTOS", "HORA_DE_LA_CONSULTA"]


# ──────────────────────────────────────────────
# CSV
# ──────────────────────────────────────────────

def _inicializar_csv() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=CSV_COLS).writeheader()
        logger.info(f"CSV creado: {CSV_PATH}")


def _guardar_consulta(candidatos: List[CandidatoLista]) -> int:
    hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        for c in candidatos:
            w.writerow({"CANDIDATO": c.nombre, "VOTOS": c.votos, "HORA_DE_LA_CONSULTA": hora})
    return len(candidatos)


# ──────────────────────────────────────────────
# Extracción
# ──────────────────────────────────────────────

async def _extraer_lista_conservador(page: Page) -> Optional[str]:
    """
    Hace click en el botón de expansión del Partido Conservador Colombiano
    y retorna el innerHTML del panel expandido.
    """
    # Esperar carga de la página
    try:
        await page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)
    except PlaywrightTimeout:
        pass
    await page.wait_for_timeout(5000)

    # Click en el botón de expansión via JS (evita problemas de visibilidad)
    resultado = await page.evaluate("""() => {
        const parrafos = document.querySelectorAll('p.rt-Text');
        for (const p of parrafos) {
            if (p.textContent.includes('CONSERVADOR COLOMBIANO')) {
                const acordeon = p.closest('[data-orientation="vertical"]');
                if (acordeon) {
                    const boton = acordeon.querySelector('button[aria-expanded]');
                    if (boton) {
                        boton.click();
                        return { ok: true };
                    }
                }
            }
        }
        return { ok: false };
    }""")

    if not resultado.get("ok"):
        logger.warning("No se encontró el botón de expansión del Partido Conservador")
        return None

    logger.info("Click en Partido Conservador Colombiano realizado")
    await page.wait_for_timeout(4000)

    # Extraer el innerHTML del panel que quedó abierto
    html = await page.evaluate("""() => {
        const abiertos = document.querySelectorAll('[data-state="open"][role="region"]');
        for (const el of abiertos) {
            if (el.innerHTML.length > 500) return el.innerHTML;
        }
        return null;
    }""")

    if not html:
        logger.warning("No se encontró el panel expandido del Conservador")
        return None

    logger.info(f"Panel Conservador extraído: {len(html)} chars")
    return html


# ──────────────────────────────────────────────
# Consulta única
# ──────────────────────────────────────────────

async def consultar_una_vez(headless: bool = False) -> Optional[List[CandidatoLista]]:
    """Abre el navegador, expande el Conservador y retorna los candidatos con votos."""
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
            viewport={"width": 1400, "height": 900},
            locale="es-CO",
        )
        page = await context.new_page()

        logger.info(f"Cargando: {URL_RESULTADOS}")
        try:
            await page.goto(URL_RESULTADOS, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        except PlaywrightTimeout:
            logger.warning("Timeout en carga, continuando...")

        html = await _extraer_lista_conservador(page)
        await browser.close()

    if not html:
        return None

    candidatos = extraer_candidatos_desde_html(html)
    return candidatos if candidatos else None


# ──────────────────────────────────────────────
# Loop periódico
# ──────────────────────────────────────────────

async def run_comparativa(
    intervalo_minutos: int = 5,
    max_consultas: Optional[int] = None,
    headless: bool = False,
) -> None:
    """Loop: consulta cada N minutos y acumula resultados en comparativa.csv."""
    _inicializar_csv()
    consulta_num = 0
    logger.info(f"Loop comparativa — intervalo: {intervalo_minutos} min | CSV: {CSV_PATH}")

    while max_consultas is None or consulta_num < max_consultas:
        consulta_num += 1
        logger.info(f"\n── Consulta #{consulta_num} [{datetime.now().strftime('%H:%M:%S')}] ──")

        try:
            candidatos = await consultar_una_vez(headless=headless)
            if candidatos:
                filas = _guardar_consulta(candidatos)
                logger.info(f"{filas} candidatos guardados en {CSV_PATH.name}")
                jcv = next((c for c in candidatos if _es_juan_camilo(c.nombre)), None)
                if jcv:
                    logger.info(f"Juan Camilo Velez: {jcv.votos:,} votos | Posicion #{jcv.posicion}")
            else:
                logger.warning("Sin datos — omitido del CSV")
        except Exception as e:
            logger.error(f"Error en consulta #{consulta_num}: {e}")

        if max_consultas is not None and consulta_num >= max_consultas:
            break

        logger.info(f"Proxima consulta en {intervalo_minutos} min...")
        await asyncio.sleep(intervalo_minutos * 60)

    logger.info(f"Loop finalizado. {consulta_num} consultas realizadas.")
