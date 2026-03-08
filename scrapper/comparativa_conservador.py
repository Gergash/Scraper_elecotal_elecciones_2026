"""
Scraper de comparativa - Lista Partido Conservador al Senado 2026
Consulta periódicamente la URL de resultados de la Registraduría,
extrae los votos de cada candidato en la lista del Conservador
y los acumula en comparativa.csv para graficar crecimiento en el tiempo.

URL: https://resultados.registraduria.gov.co/resultados/0/00/0?s=resultados-votes
CSV de salida: backup/comparativa.csv
Columnas: CANDIDATO, VOTOS, HORA_DE_LA_CONSULTA
"""

import asyncio
import csv
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

from .lista_conservador import extraer_candidatos_desde_html, CandidatoLista
from .config import CONFIG
from .utils import logger

# ──────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────
URL_RESULTADOS = "https://resultados.registraduria.gov.co/resultados/0/00/0?s=resultados-votes"
TIMEOUT_MS     = 30_000
WAIT_CARGA_MS  = 5_000

OUTPUT_DIR     = Path(__file__).resolve().parent.parent / "backup"
CSV_PATH       = OUTPUT_DIR / "comparativa.csv"
CSV_COLS       = ["CANDIDATO", "VOTOS", "HORA_DE_LA_CONSULTA"]

# Textos para identificar la fila del Partido Conservador
KEYWORDS_CONSERVADOR = [
    "CONSERVADOR",
    "PARTIDO CONSERVADOR",
    "CONSERVADORA",
]


# ──────────────────────────────────────────────
# CSV de salida (modo append)
# ──────────────────────────────────────────────

def _inicializar_csv() -> None:
    """Crea el CSV con encabezado si no existe."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLS)
            w.writeheader()
        logger.info(f"CSV creado: {CSV_PATH}")


def _guardar_consulta(candidatos: List[CandidatoLista]) -> int:
    """
    Agrega una fila por candidato al CSV con la hora actual.
    Retorna la cantidad de filas escritas.
    """
    hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    filas = 0
    with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        for c in candidatos:
            w.writerow({
                "CANDIDATO": c.nombre,
                "VOTOS": c.votos,
                "HORA_DE_LA_CONSULTA": hora,
            })
            filas += 1
    return filas


# ──────────────────────────────────────────────
# Navegación y extracción
# ──────────────────────────────────────────────

async def _encontrar_fila_conservador(page: Page) -> Optional[str]:
    """
    Busca la fila del Partido Conservador en la tabla de resultados.
    Intenta varias estrategias:
      1. Selector CSS directo con texto "CONSERVADOR"
      2. Buscar en todos los elementos de tabla
      3. Extraer HTML completo y buscar por texto
    Retorna el HTML de la fila party-detail-row o None.
    """
    # Esperar a que cargue la tabla de partidos
    try:
        await page.wait_for_selector(
            "table, [class*='rt-Table'], [class*='partido'], [class*='party']",
            timeout=TIMEOUT_MS,
        )
    except PlaywrightTimeout:
        logger.warning("Timeout esperando tabla de partidos")

    await page.wait_for_timeout(WAIT_CARGA_MS)

    # ── Estrategia 1: buscar fila con texto CONSERVADOR y hacer click ──
    for keyword in KEYWORDS_CONSERVADOR:
        try:
            # Buscar elemento que contenga el texto del partido
            fila_partido = await page.query_selector(
                f"tr:has-text('{keyword}'), [class*='partido']:has-text('{keyword}'), "
                f"[class*='party']:has-text('{keyword}'), td:has-text('{keyword}')"
            )
            if fila_partido:
                logger.info(f"Fila Conservador encontrada con keyword '{keyword}'")
                # Click para expandir si es necesario
                try:
                    await fila_partido.click()
                    await page.wait_for_timeout(2000)
                except Exception:
                    pass
                break
        except Exception as e:
            logger.debug(f"Error buscando '{keyword}': {e}")

    # ── Estrategia 2: buscar party-detail-row directamente ──
    await page.wait_for_timeout(1500)
    try:
        selector_detalle = (
            "tr.party-detail-row, .party-detail-row, "
            "[class*='party-detail-row'], [class*='partyDetail']"
        )
        elemento = await page.query_selector(selector_detalle)
        if elemento:
            html = await elemento.evaluate("el => el.outerHTML")
            if html and len(html) > 100:
                logger.info("party-detail-row extraído correctamente")
                return html
    except Exception as e:
        logger.debug(f"Error en estrategia 2: {e}")

    # ── Estrategia 3: buscar en el HTML completo de la página ──
    try:
        contenido = await page.content()
        if "party-detail-row" in contenido:
            import re
            # Extraer el bloque completo que contiene party-detail-row
            match = re.search(
                r'<tr[^>]*class="[^"]*party-detail-row[^"]*"[^>]*>.*?</tr>',
                contenido,
                re.DOTALL | re.IGNORECASE,
            )
            if match:
                logger.info("party-detail-row extraído desde HTML completo")
                return match.group(0)

        # Estrategia 3b: Si hay rt-Grid con datos de candidatos (sin party-detail-row)
        if "rt-Grid" in contenido and any(k in contenido.upper() for k in KEYWORDS_CONSERVADOR):
            logger.info("Extrayendo desde rt-Grid (sin party-detail-row)")
            # Buscar el bloque del conservador
            idx = -1
            for k in KEYWORDS_CONSERVADOR:
                idx = contenido.upper().find(k)
                if idx != -1:
                    break
            if idx != -1:
                # Extraer los siguientes 50000 caracteres desde el partido
                fragmento = contenido[idx: idx + 50000]
                return fragmento

    except Exception as e:
        logger.debug(f"Error en estrategia 3: {e}")

    logger.warning("No se encontró la fila del Partido Conservador en la página")
    return None


async def consultar_una_vez(headless: bool = False) -> Optional[List[CandidatoLista]]:
    """
    Abre el navegador, va a la URL, extrae la lista del Conservador
    y retorna la lista de candidatos con sus votos.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
            locale="es-CO",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        page = await context.new_page()

        logger.info(f"Cargando: {URL_RESULTADOS}")
        try:
            resp = await page.goto(URL_RESULTADOS, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
            if resp and resp.status != 200:
                logger.warning(f"Status HTTP: {resp.status}")
        except PlaywrightTimeout:
            logger.warning("Timeout en carga, continuando con lo disponible...")

        html_conservador = await _encontrar_fila_conservador(page)
        await browser.close()

    if not html_conservador:
        return None

    candidatos = extraer_candidatos_desde_html(html_conservador)
    if not candidatos:
        logger.warning("No se extrajeron candidatos del HTML encontrado")
    else:
        logger.info(f"Candidatos extraídos: {len(candidatos)}")

    return candidatos if candidatos else None


# ──────────────────────────────────────────────
# Loop de consulta periódica
# ──────────────────────────────────────────────

async def run_comparativa(
    intervalo_minutos: int = 5,
    max_consultas: Optional[int] = None,
    headless: bool = False,
) -> None:
    """
    Loop principal: consulta la URL cada `intervalo_minutos` minutos
    y acumula los resultados en comparativa.csv.

    Args:
        intervalo_minutos: Minutos entre consultas (default: 5).
        max_consultas: Número máximo de consultas. None = infinito.
        headless: Ejecutar sin ventana.
    """
    _inicializar_csv()

    consulta_num = 0
    logger.info(f"Iniciando loop de comparativa — intervalo: {intervalo_minutos} min")
    logger.info(f"CSV de salida: {CSV_PATH}")

    while max_consultas is None or consulta_num < max_consultas:
        consulta_num += 1
        hora = datetime.now().strftime("%H:%M:%S")
        logger.info(f"\n── Consulta #{consulta_num} [{hora}] ──")

        try:
            candidatos = await consultar_una_vez(headless=headless)
            if candidatos:
                filas = _guardar_consulta(candidatos)
                logger.info(f"✓ {filas} candidatos guardados en {CSV_PATH.name}")
                # Log rápido de Juan Camilo
                jcv = next(
                    (c for c in candidatos if "JUAN" in c.nombre.upper() and "VELEZ" in c.nombre.upper().replace("É","E").replace("Ñ","N")),
                    None,
                )
                if jcv:
                    logger.info(f"  Juan Camilo Vélez: {jcv.votos:,} votos ({jcv.porcentaje:.2f}%)")
            else:
                logger.warning("Sin datos en esta consulta — se omite del CSV")
        except Exception as e:
            logger.error(f"Error en consulta #{consulta_num}: {e}")

        if max_consultas is not None and consulta_num >= max_consultas:
            break

        logger.info(f"Próxima consulta en {intervalo_minutos} min...")
        await asyncio.sleep(intervalo_minutos * 60)

    logger.info(f"\nLoop finalizado. {consulta_num} consultas realizadas.")
    logger.info(f"CSV final: {CSV_PATH}")
