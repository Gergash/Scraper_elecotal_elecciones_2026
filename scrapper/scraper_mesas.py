"""
Scraper jerárquico de mesas electorales - Congreso 2026
Navega: Corporación → Departamento → Municipio → Zona → Puesto → Mesa
Extrae votos por candidato (Cámara y Senado) y guarda en CSV.

URL base: https://escrutinioscongreso2026.registraduria.gov.co/actas-e14
"""

import asyncio
import csv
import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeout

from .config import CANDIDATOS_CAMARA, CANDIDATO_SENADO, DEPARTAMENTOS, CONFIG
from .utils import logger

# ──────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────
URL_E14 = "https://escrutinioscongreso2026.registraduria.gov.co/actas-e14"

CORPORACIONES = {
    "CAMARA": None,   # valor se detecta dinámicamente
    "SENADO": None,
}

TIMEOUT_MS = 20_000
SLEEP_NAVEGACION = 3.0   # segundos entre selects
SLEEP_VARIANZA   = 1.5
SLEEP_ENTRE_MESAS = 2.0

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "backup"
PROGRESO_FILE = OUTPUT_DIR / "progreso_mesas.json"

# Columnas del CSV de salida
CSV_COLS = [
    "DEPARTAMENTO", "MUNICIPIO", "ZONA", "PUESTO", "MESA",
    "CANDIDATO_CAMARA", "NUMERO_DE_VOTOS_CAMARA",
    "CANDIDATO_SENADO", "NUMERO_DE_VOTOS_SENADO",
    "FECHA_EXTRACCION",
]

# ──────────────────────────────────────────────
# Helpers de navegación
# ──────────────────────────────────────────────

def _sleep(base: float = SLEEP_NAVEGACION, varianza: float = SLEEP_VARIANZA) -> None:
    t = base + random.uniform(0, varianza)
    time.sleep(t)


async def _opciones_select(page: Page, selector: str) -> List[Dict[str, str]]:
    """Devuelve las opciones de un <select> como lista de {value, text}."""
    try:
        return await page.eval_on_selector(
            selector,
            """el => {
                const s = el.tagName === 'SELECT' ? el : el.querySelector('select');
                if (!s) return [];
                return Array.from(s.options)
                    .filter(o => o.value && o.value.trim() !== '')
                    .map(o => ({ value: o.value.trim(), text: o.textContent.trim() }));
            }"""
        )
    except Exception:
        return []


async def _seleccionar(page: Page, selector: str, value: str) -> bool:
    """Selecciona un valor en un <select>."""
    try:
        await page.select_option(selector, value=value, timeout=8000)
        await page.wait_for_timeout(500)
        return True
    except Exception as e:
        logger.debug(f"Error seleccionando {value} en {selector}: {e}")
        return False


async def _esperar_habilitado(page: Page, selector: str, max_ms: int = 12000) -> bool:
    """Espera a que un select tenga opciones válidas (no vacío/deshabilitado)."""
    try:
        await page.wait_for_function(
            """s => {
                const el = document.querySelector(s);
                if (!el) return false;
                const opts = Array.from(el.options).filter(o => o.value && o.value.trim());
                return opts.length > 0 && !el.disabled;
            }""",
            selector,
            timeout=max_ms,
        )
        return True
    except Exception:
        return False


async def _detectar_selectores(page: Page) -> Dict[str, str]:
    """
    Detecta los selectores de los 5 filtros jerárquicos.
    Orden esperado en la página: corporacion, departamento, municipio, zona, puesto.
    """
    nombres = ["corporacion", "departamento", "municipio", "zona", "puesto"]
    candidatos = {
        "corporacion": [
            "[id*='corporacion']", "[name*='corporacion']",
            "select:nth-of-type(1)",
        ],
        "departamento": [
            "[id*='departamento']", "[name*='departamento']",
            "select:nth-of-type(2)",
        ],
        "municipio": [
            "[id*='municipio']", "[name*='municipio']",
            "select:nth-of-type(3)",
        ],
        "zona": [
            "[id*='zona']", "[name*='zona']",
            "select:nth-of-type(4)",
        ],
        "puesto": [
            "[id*='puesto']", "[name*='puesto']",
            "select:nth-of-type(5)",
        ],
    }
    resultado: Dict[str, str] = {}
    for nombre in nombres:
        for sel in candidatos[nombre]:
            try:
                el = await page.query_selector(sel)
                if el:
                    id_attr = await el.get_attribute("id")
                    resultado[nombre] = f"#{id_attr}" if id_attr else sel
                    break
            except Exception:
                continue
    return resultado


async def _detectar_select_mesas(page: Page) -> Optional[str]:
    """Detecta el selector del select de mesas (aparece después de seleccionar puesto)."""
    candidatos = [
        "[id*='mesa']", "[name*='mesa']",
        "select:nth-of-type(6)",
    ]
    for sel in candidatos:
        try:
            el = await page.query_selector(sel)
            if el:
                id_attr = await el.get_attribute("id")
                return f"#{id_attr}" if id_attr else sel
        except Exception:
            continue
    return None


# ──────────────────────────────────────────────
# Extracción de votos desde la página
# ──────────────────────────────────────────────

def _normalizar(texto: str) -> str:
    """Normaliza un nombre para comparación (minúsculas, sin tildes ni puntos)."""
    t = texto.lower().strip()
    for a, b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n"),("ü","u"),(".","")]:
        t = t.replace(a, b)
    return " ".join(t.split())


def _candidato_en_texto(candidato: str, texto: str) -> bool:
    """Verifica si el candidato está en el texto (comparación flexible)."""
    partes = _normalizar(candidato).split()
    texto_n = _normalizar(texto)
    # Coincide si al menos 2 palabras del nombre están en el texto
    coincidencias = sum(1 for p in partes if p in texto_n and len(p) > 2)
    return coincidencias >= min(2, len(partes))


async def _extraer_votos_tabla(page: Page, candidatos_objetivo: List[str]) -> Dict[str, int]:
    """
    Extrae votos desde tablas HTML en la página.
    Devuelve {nombre_candidato: votos}.
    """
    votos: Dict[str, int] = {}
    try:
        tablas = await page.query_selector_all("table")
        for tabla in tablas:
            filas = await tabla.query_selector_all("tr")
            for fila in filas:
                celdas = await fila.query_selector_all("td, th")
                if len(celdas) < 2:
                    continue
                textos = [(await c.inner_text()).strip() for c in celdas]
                # Buscar columna con nombre y columna con número
                for i, texto in enumerate(textos):
                    for candidato in candidatos_objetivo:
                        if _candidato_en_texto(candidato, texto):
                            # Buscar número en el resto de celdas
                            for j, otro in enumerate(textos):
                                if i != j and re.search(r'\d+', otro):
                                    nums = re.findall(r'[\d\.]+', otro.replace(",", ""))
                                    if nums:
                                        try:
                                            v = int(float(nums[0].replace(".", "")))
                                            if candidato not in votos or v > votos[candidato]:
                                                votos[candidato] = v
                                        except ValueError:
                                            pass
    except Exception as e:
        logger.debug(f"Error extrayendo de tabla: {e}")
    return votos


async def _extraer_votos_texto_libre(page: Page, candidatos_objetivo: List[str]) -> Dict[str, int]:
    """
    Fallback: busca votos en texto libre de la página buscando el nombre del candidato
    seguido o precedido de un número.
    """
    votos: Dict[str, int] = {}
    try:
        body = await page.query_selector("body")
        if not body:
            return votos
        contenido = await body.inner_text()
        lineas = contenido.split("\n")
        for linea in lineas:
            for candidato in candidatos_objetivo:
                if _candidato_en_texto(candidato, linea):
                    nums = re.findall(r'\b(\d{1,6})\b', linea)
                    if nums:
                        try:
                            v = max(int(n) for n in nums)
                            if candidato not in votos or v > votos[candidato]:
                                votos[candidato] = v
                        except ValueError:
                            pass
    except Exception as e:
        logger.debug(f"Error extrayendo de texto libre: {e}")
    return votos


async def _extraer_votos_candidatos(
    page: Page, candidatos: List[str]
) -> Dict[str, int]:
    """Combina extracción de tabla y texto libre."""
    votos = await _extraer_votos_tabla(page, candidatos)
    if not votos:
        votos = await _extraer_votos_texto_libre(page, candidatos)
    return votos


async def _click_consultar(page: Page) -> None:
    """Hace click en el botón Consultar si existe."""
    selectores_boton = [
        "button:has-text('Consultar')",
        "button:has-text('Buscar')",
        "input[type='submit']",
        "[class*='consultar'] button",
        "button[type='submit']",
    ]
    for sel in selectores_boton:
        try:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                await page.wait_for_timeout(2000)
                return
        except Exception:
            continue


# ──────────────────────────────────────────────
# Progreso (reanudación)
# ──────────────────────────────────────────────

def _cargar_progreso() -> set:
    """Carga el set de mesas ya procesadas desde el archivo de progreso."""
    if PROGRESO_FILE.exists():
        try:
            with open(PROGRESO_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("mesas_procesadas", []))
        except Exception:
            pass
    return set()


def _guardar_progreso(mesas_procesadas: set) -> None:
    """Guarda el progreso actual."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROGRESO_FILE, "w", encoding="utf-8") as f:
        json.dump({"mesas_procesadas": list(mesas_procesadas)}, f, ensure_ascii=False)


def _clave_mesa(depto: str, municipio: str, zona: str, puesto: str, mesa: str) -> str:
    return f"{depto}|{municipio}|{zona}|{puesto}|{mesa}"


# ──────────────────────────────────────────────
# CSV de salida
# ──────────────────────────────────────────────

def _abrir_csv(path: Path) -> Tuple[object, object]:
    """Abre (o continúa) el CSV de salida. Devuelve (file_obj, writer)."""
    existe = path.exists()
    f = open(path, "a", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
    if not existe:
        writer.writeheader()
    return f, writer


def _escribir_fila(
    writer,
    depto: str,
    municipio: str,
    zona: str,
    puesto: str,
    mesa: str,
    candidato_camara: str,
    votos_camara: int,
    candidato_senado: str,
    votos_senado: int,
) -> None:
    writer.writerow({
        "DEPARTAMENTO": depto,
        "MUNICIPIO": municipio,
        "ZONA": zona,
        "PUESTO": puesto,
        "MESA": mesa,
        "CANDIDATO_CAMARA": candidato_camara,
        "NUMERO_DE_VOTOS_CAMARA": votos_camara,
        "CANDIDATO_SENADO": candidato_senado,
        "NUMERO_DE_VOTOS_SENADO": votos_senado,
        "FECHA_EXTRACCION": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


# ──────────────────────────────────────────────
# Scraper principal
# ──────────────────────────────────────────────

async def scrape_mesas(
    departamentos_objetivo: Optional[List[str]] = None,
    headless: bool = False,
    reanudar: bool = True,
    csv_path: Optional[Path] = None,
) -> Path:
    """
    Scraper jerárquico principal.

    Recorre depto → municipio → zona → puesto → mesa.
    Para cada mesa hace dos consultas (Cámara y Senado) y guarda en CSV.

    Args:
        departamentos_objetivo: Lista de departamentos a procesar. None = todos.
        headless: Modo sin ventana.
        reanudar: Si True, omite mesas ya procesadas en sesiones anteriores.
        csv_path: Ruta del CSV de salida. Por defecto backup/resultados_mesas_TIMESTAMP.csv

    Returns:
        Path del CSV generado.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if csv_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = OUTPUT_DIR / f"resultados_mesas_{ts}.csv"

    deptos = departamentos_objetivo or DEPARTAMENTOS
    mesas_procesadas = _cargar_progreso() if reanudar else set()
    candidato_senado = CANDIDATO_SENADO

    logger.info(f"Iniciando scraper jerárquico de mesas")
    logger.info(f"Departamentos: {deptos}")
    logger.info(f"CSV de salida: {csv_path}")
    logger.info(f"Mesas ya procesadas (reanudación): {len(mesas_procesadas)}")

    csv_file, writer = _abrir_csv(csv_path)

    try:
        async with async_playwright() as p:
            browser: Browser = await p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context: BrowserContext = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/121.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="es-CO",
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            )
            page = await context.new_page()

            # ── Cargar página base ──
            logger.info(f"Cargando {URL_E14} ...")
            try:
                await page.goto(URL_E14, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
            except PlaywrightTimeout:
                logger.warning("Timeout en carga inicial, continuando...")
            _sleep(4, 2)

            # ── Detectar selectores ──
            sels = await _detectar_selectores(page)
            logger.info(f"Selectores detectados: {sels}")
            if not sels:
                logger.error("No se encontraron selectores. Verifica la estructura de la página.")
                await browser.close()
                return csv_path

            # ── Detectar opciones de corporación ──
            opts_corp = await _opciones_select(page, sels.get("corporacion", "select:nth-of-type(1)"))
            logger.info(f"Corporaciones disponibles: {opts_corp}")

            corp_camara = next(
                (o["value"] for o in opts_corp if "camara" in _normalizar(o["text"])), None
            )
            corp_senado = next(
                (o["value"] for o in opts_corp if "senado" in _normalizar(o["text"])), None
            )
            logger.info(f"Cámara: {corp_camara} | Senado: {corp_senado}")

            # ── Iterar departamentos ──
            for depto in deptos:
                candidatos_camara = CANDIDATOS_CAMARA.get(depto, [])
                if not candidatos_camara:
                    logger.warning(f"No hay candidatos de Cámara configurados para {depto}, saltando.")
                    continue

                logger.info(f"\n{'='*60}\nDepartamento: {depto}\n{'='*60}")

                # Obtener opciones de departamento
                await _seleccionar(page, sels["corporacion"], corp_camara or opts_corp[0]["value"])
                _sleep(3, 1)

                opts_depto = await _opciones_select(page, sels["departamento"])
                depto_opt = next(
                    (o for o in opts_depto if depto.upper() in _normalizar(o["text"]).upper()),
                    None,
                )
                if not depto_opt:
                    logger.warning(f"Departamento {depto} no encontrado en el select. Opciones: {opts_depto}")
                    continue

                # ── Seleccionar departamento ──
                await _seleccionar(page, sels["departamento"], depto_opt["value"])
                _sleep(SLEEP_NAVEGACION, SLEEP_VARIANZA)
                await _esperar_habilitado(page, sels["municipio"])

                opts_muni = await _opciones_select(page, sels["municipio"])
                logger.info(f"  Municipios encontrados: {len(opts_muni)}")

                # ── Iterar municipios ──
                for muni_opt in opts_muni:
                    muni_text = muni_opt["text"]
                    muni_val = muni_opt["value"]
                    logger.info(f"  Municipio: {muni_text}")

                    await _seleccionar(page, sels["municipio"], muni_val)
                    _sleep(SLEEP_NAVEGACION, SLEEP_VARIANZA)
                    await _esperar_habilitado(page, sels["zona"])

                    opts_zona = await _opciones_select(page, sels["zona"])

                    # ── Iterar zonas ──
                    for zona_opt in opts_zona:
                        zona_text = zona_opt["text"]
                        zona_val = zona_opt["value"]

                        await _seleccionar(page, sels["zona"], zona_val)
                        _sleep(SLEEP_NAVEGACION, SLEEP_VARIANZA)
                        await _esperar_habilitado(page, sels["puesto"])

                        opts_puesto = await _opciones_select(page, sels["puesto"])

                        # ── Iterar puestos ──
                        for puesto_opt in opts_puesto:
                            puesto_text = puesto_opt["text"]
                            puesto_val = puesto_opt["value"]

                            await _seleccionar(page, sels["puesto"], puesto_val)
                            _sleep(SLEEP_NAVEGACION, SLEEP_VARIANZA)

                            # Detectar select de mesas (aparece después de seleccionar puesto)
                            sel_mesa = await _detectar_select_mesas(page)
                            if sel_mesa:
                                await _esperar_habilitado(page, sel_mesa)
                                opts_mesa = await _opciones_select(page, sel_mesa)
                            else:
                                # No hay select de mesa: el puesto es la unidad mínima
                                opts_mesa = [{"value": "1", "text": "Mesa única"}]

                            # ── Iterar mesas ──
                            for mesa_opt in opts_mesa:
                                mesa_text = mesa_opt["text"]
                                mesa_val = mesa_opt["value"]
                                clave = _clave_mesa(depto, muni_text, zona_text, puesto_text, mesa_text)

                                if clave in mesas_procesadas:
                                    logger.debug(f"Saltando (ya procesada): {clave}")
                                    continue

                                logger.info(
                                    f"    Mesa: {mesa_text} | Puesto: {puesto_text} | "
                                    f"Zona: {zona_text}"
                                )

                                # ── Paso 1: Votos Cámara ──
                                votos_camara: Dict[str, int] = {}
                                if corp_camara:
                                    await _seleccionar(page, sels["corporacion"], corp_camara)
                                    _sleep(1.5, 0.5)
                                    if sel_mesa:
                                        await _seleccionar(page, sel_mesa, mesa_val)
                                        _sleep(1.5, 0.5)
                                    await _click_consultar(page)
                                    _sleep(SLEEP_ENTRE_MESAS, 1)
                                    votos_camara = await _extraer_votos_candidatos(page, candidatos_camara)

                                # ── Paso 2: Votos Senado ──
                                votos_senado_val = 0
                                if corp_senado:
                                    await _seleccionar(page, sels["corporacion"], corp_senado)
                                    _sleep(1.5, 0.5)
                                    # Re-seleccionar jerarquía (cambia al cambiar corporación)
                                    await _seleccionar(page, sels["departamento"], depto_opt["value"])
                                    _sleep(2, 0.5)
                                    await _seleccionar(page, sels["municipio"], muni_val)
                                    _sleep(2, 0.5)
                                    await _seleccionar(page, sels["zona"], zona_val)
                                    _sleep(2, 0.5)
                                    await _seleccionar(page, sels["puesto"], puesto_val)
                                    _sleep(2, 0.5)
                                    if sel_mesa:
                                        await _seleccionar(page, sel_mesa, mesa_val)
                                        _sleep(1.5, 0.5)
                                    await _click_consultar(page)
                                    _sleep(SLEEP_ENTRE_MESAS, 1)
                                    votos_senado_dict = await _extraer_votos_candidatos(
                                        page, [candidato_senado]
                                    )
                                    votos_senado_val = votos_senado_dict.get(candidato_senado, 0)

                                # ── Escribir filas CSV ──
                                # Una fila por candidato de Cámara
                                if votos_camara:
                                    for c_camara, v_camara in votos_camara.items():
                                        _escribir_fila(
                                            writer,
                                            depto, muni_text, zona_text,
                                            puesto_text, mesa_text,
                                            c_camara, v_camara,
                                            candidato_senado, votos_senado_val,
                                        )
                                else:
                                    # Sin votos de Cámara: registrar fila vacía para la mesa
                                    _escribir_fila(
                                        writer,
                                        depto, muni_text, zona_text,
                                        puesto_text, mesa_text,
                                        "SIN_DATOS", 0,
                                        candidato_senado, votos_senado_val,
                                    )

                                csv_file.flush()
                                mesas_procesadas.add(clave)
                                _guardar_progreso(mesas_procesadas)

                                # Volver a Cámara para la siguiente mesa
                                if corp_camara:
                                    await _seleccionar(page, sels["corporacion"], corp_camara)
                                    _sleep(1.5, 0.5)
                                    await _seleccionar(page, sels["departamento"], depto_opt["value"])
                                    _sleep(2, 0.5)
                                    await _seleccionar(page, sels["municipio"], muni_val)
                                    _sleep(2, 0.5)
                                    await _seleccionar(page, sels["zona"], zona_val)
                                    _sleep(2, 0.5)
                                    await _seleccionar(page, sels["puesto"], puesto_val)
                                    _sleep(2, 0.5)

            await browser.close()

    finally:
        csv_file.close()

    logger.info(f"\nScraping finalizado. CSV guardado en: {csv_path}")
    logger.info(f"Total mesas procesadas: {len(mesas_procesadas)}")
    return csv_path
