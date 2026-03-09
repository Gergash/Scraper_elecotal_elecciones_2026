"""
Scraper jerárquico de mesas electorales - Congreso 2026
Navega: Corporación → Departamento → Municipio → Zona → Puesto → Mesa
Extrae votos por candidato (Cámara y Senado) y guarda en CSV.

URL base: https://escrutinioscongreso2026.registraduria.gov.co/actas-e14

Estructura real del portal (selects por índice, sin id/name):
  select[0] = corporacion  (siempre presente)
  select[1] = departamento (siempre presente)
  select[2] = municipio    (siempre presente)
  select[3] = zona         (aparece tras seleccionar corporacion)
  select[4] = puesto       (aparece tras seleccionar corporacion)
  select[5] = mesa         (puede aparecer tras seleccionar puesto)
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

# Índices de cada select en el portal E14
IDX_CORP   = 0
IDX_DEPTO  = 1
IDX_MUNI   = 2
IDX_ZONA   = 3
IDX_PUESTO = 4
IDX_MESA   = 5

# Códigos DANE de departamentos objetivo
CODIGOS_DEPTO = {
    "VALLE":     "32",
    "RISARALDA": "25",
    "CALDAS":    "17",
}

TIMEOUT_MS       = 20_000
SLEEP_SELECT     = 3.0
SLEEP_VARIANZA   = 1.5
SLEEP_MESA       = 2.0

OUTPUT_DIR    = Path(__file__).resolve().parent.parent / "backup"
PROGRESO_FILE = OUTPUT_DIR / "progreso_mesas.json"

CSV_COLS = [
    "DEPARTAMENTO", "MUNICIPIO", "ZONA", "PUESTO", "MESA",
    "CANDIDATO_CAMARA", "NUMERO_DE_VOTOS_CAMARA",
    "CANDIDATO_SENADO", "NUMERO_DE_VOTOS_SENADO",
    "FECHA_EXTRACCION",
]


# ──────────────────────────────────────────────
# Helpers de pausa
# ──────────────────────────────────────────────

def _sleep(base: float = SLEEP_SELECT, varianza: float = SLEEP_VARIANZA) -> None:
    time.sleep(base + random.uniform(0, varianza))


# ──────────────────────────────────────────────
# Operaciones sobre selects por índice
# ──────────────────────────────────────────────

async def _opciones(page: Page, idx: int) -> List[Dict[str, str]]:
    """Devuelve las opciones del select en la posición idx."""
    try:
        return await page.evaluate(f"""() => {{
            const s = document.querySelectorAll('select')[{idx}];
            if (!s) return [];
            return Array.from(s.options)
                .filter(o => o.value && o.value.trim() !== '')
                .map(o => ({{ value: o.value.trim(), text: o.textContent.trim() }}));
        }}""")
    except Exception:
        return []


async def _seleccionar(page: Page, idx: int, value: str) -> bool:
    """Selecciona un valor en el select de índice idx."""
    try:
        await page.evaluate(f"""(val) => {{
            const s = document.querySelectorAll('select')[{idx}];
            if (!s) return;
            s.value = val;
            s.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}""", value)
        await page.wait_for_timeout(500)
        return True
    except Exception as e:
        logger.debug(f"Error seleccionando idx={idx} val={value}: {e}")
        return False


async def _num_selects(page: Page) -> int:
    """Retorna cuántos selects hay actualmente en la página."""
    try:
        return await page.evaluate("() => document.querySelectorAll('select').length")
    except Exception:
        return 0


async def _esperar_selects(page: Page, cantidad: int, max_ms: int = 10000) -> bool:
    """Espera hasta que haya al menos `cantidad` selects en la página."""
    try:
        await page.wait_for_function(
            f"() => document.querySelectorAll('select').length >= {cantidad}",
            timeout=max_ms,
        )
        return True
    except Exception:
        return False


async def _click_consultar(page: Page) -> None:
    """Hace click en el botón Consultar."""
    selectores = [
        "button:has-text('Consultar')",
        "button:has-text('Buscar')",
        "input[type='submit']",
        "button[type='submit']",
    ]
    for sel in selectores:
        try:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                await page.wait_for_timeout(2000)
                return
        except Exception:
            continue


# ──────────────────────────────────────────────
# Extracción de votos
# ──────────────────────────────────────────────

def _normalizar(texto: str) -> str:
    t = texto.lower().strip()
    for a, b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n"),("ü","u")]:
        t = t.replace(a, b)
    return " ".join(t.split())


def _candidato_match(candidato: str, texto: str) -> bool:
    partes = [p for p in _normalizar(candidato).split() if len(p) > 2]
    texto_n = _normalizar(texto)
    return sum(1 for p in partes if p in texto_n) >= min(2, len(partes))


async def _extraer_votos(page: Page, candidatos: List[str]) -> Dict[str, int]:
    """Extrae votos de candidatos desde tablas o texto libre de la página."""
    votos: Dict[str, int] = {}

    # Estrategia 1: tablas
    try:
        tablas = await page.query_selector_all("table")
        for tabla in tablas:
            filas = await tabla.query_selector_all("tr")
            for fila in filas:
                celdas = await fila.query_selector_all("td, th")
                if len(celdas) < 2:
                    continue
                textos = [(await c.inner_text()).strip() for c in celdas]
                for i, texto in enumerate(textos):
                    for cand in candidatos:
                        if _candidato_match(cand, texto):
                            for j, otro in enumerate(textos):
                                if i != j:
                                    nums = re.findall(r'\b\d+\b', otro.replace(",","").replace(".",""))
                                    if nums:
                                        try:
                                            v = int(nums[0])
                                            if cand not in votos or v > votos[cand]:
                                                votos[cand] = v
                                        except ValueError:
                                            pass
    except Exception as e:
        logger.debug(f"Error en tablas: {e}")

    # Estrategia 2: texto libre
    if not votos:
        try:
            body = await page.query_selector("body")
            if body:
                contenido = await body.inner_text()
                for linea in contenido.split("\n"):
                    for cand in candidatos:
                        if _candidato_match(cand, linea):
                            nums = re.findall(r'\b(\d{1,6})\b', linea)
                            if nums:
                                try:
                                    v = max(int(n) for n in nums)
                                    if cand not in votos or v > votos[cand]:
                                        votos[cand] = v
                                except ValueError:
                                    pass
        except Exception as e:
            logger.debug(f"Error en texto libre: {e}")

    return votos


# ──────────────────────────────────────────────
# Progreso y CSV
# ──────────────────────────────────────────────

def _cargar_progreso() -> set:
    if PROGRESO_FILE.exists():
        try:
            with open(PROGRESO_FILE, encoding="utf-8") as f:
                return set(json.load(f).get("mesas_procesadas", []))
        except Exception:
            pass
    return set()


def _guardar_progreso(mesas: set) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROGRESO_FILE, "w", encoding="utf-8") as f:
        json.dump({"mesas_procesadas": list(mesas)}, f, ensure_ascii=False)


def _clave(depto, muni, zona, puesto, mesa):
    return f"{depto}|{muni}|{zona}|{puesto}|{mesa}"


def _abrir_csv(path: Path):
    existe = path.exists()
    f = open(path, "a", newline="", encoding="utf-8-sig")
    w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
    if not existe:
        w.writeheader()
    return f, w


def _escribir_fila(w, depto, muni, zona, puesto, mesa,
                   c_camara, v_camara, c_senado, v_senado):
    w.writerow({
        "DEPARTAMENTO": depto, "MUNICIPIO": muni, "ZONA": zona,
        "PUESTO": puesto, "MESA": mesa,
        "CANDIDATO_CAMARA": c_camara, "NUMERO_DE_VOTOS_CAMARA": v_camara,
        "CANDIDATO_SENADO": c_senado, "NUMERO_DE_VOTOS_SENADO": v_senado,
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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if csv_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = OUTPUT_DIR / f"resultados_mesas_{ts}.csv"

    deptos = departamentos_objetivo or DEPARTAMENTOS
    mesas_procesadas = _cargar_progreso() if reanudar else set()
    candidato_senado = CANDIDATO_SENADO

    logger.info(f"Scraper mesas iniciado | Deptos: {deptos} | CSV: {csv_path}")
    logger.info(f"Mesas previas (reanudación): {len(mesas_procesadas)}")

    csv_file, writer = _abrir_csv(csv_path)

    try:
        async with async_playwright() as p:
            browser: Browser = await p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context: BrowserContext = await browser.new_context(
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

            # ── Cargar portal E14 ──
            logger.info(f"Cargando {URL_E14} ...")
            try:
                await page.goto(URL_E14, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
            except PlaywrightTimeout:
                logger.warning("Timeout en carga inicial, continuando...")
            await page.wait_for_timeout(5000)

            # Verificar estructura inicial
            n_selects = await _num_selects(page)
            logger.info(f"Selects encontrados inicialmente: {n_selects}")
            if n_selects < 2:
                logger.error("El portal no tiene la estructura esperada (< 2 selects).")
                await browser.close()
                return csv_path

            # ── Detectar corporaciones disponibles ──
            opts_corp = await _opciones(page, IDX_CORP)
            logger.info(f"Corporaciones: {opts_corp}")

            corp_camara = next(
                (o["value"] for o in opts_corp if "camara" in _normalizar(o["text"])), None
            )
            corp_senado = next(
                (o["value"] for o in opts_corp if "senado" in _normalizar(o["text"])), None
            )
            logger.info(f"Cámara={corp_camara} | Senado={corp_senado}")

            # ── Seleccionar CÁMARA para activar zona y puesto ──
            if corp_camara:
                await _seleccionar(page, IDX_CORP, corp_camara)
                await _esperar_selects(page, 5)
                await page.wait_for_timeout(2000)

            n_selects = await _num_selects(page)
            logger.info(f"Selects tras seleccionar corporación: {n_selects}")

            # ── Iterar departamentos ──
            opts_depto = await _opciones(page, IDX_DEPTO)
            logger.info(f"Departamentos disponibles: {len(opts_depto)}")

            for depto in deptos:
                candidatos_camara = CANDIDATOS_CAMARA.get(depto, [])
                if not candidatos_camara:
                    logger.warning(f"Sin candidatos Cámara para {depto}, saltando.")
                    continue

                # Buscar código del departamento en las opciones
                depto_opt = next(
                    (o for o in opts_depto
                     if depto.upper() in _normalizar(o["text"]).upper()
                     or o["value"] == CODIGOS_DEPTO.get(depto, "")),
                    None,
                )
                if not depto_opt:
                    logger.warning(f"Departamento {depto} no encontrado. Opciones: {[o['text'] for o in opts_depto[:5]]}")
                    continue

                logger.info(f"\n{'='*60}\nDEPARTAMENTO: {depto} (valor={depto_opt['value']})\n{'='*60}")

                # ── Seleccionar departamento ──
                await _seleccionar(page, IDX_DEPTO, depto_opt["value"])
                _sleep(SLEEP_SELECT, SLEEP_VARIANZA)

                opts_muni = await _opciones(page, IDX_MUNI)
                logger.info(f"  Municipios: {len(opts_muni)}")

                # ── Iterar municipios ──
                for muni_opt in opts_muni:
                    muni_text = muni_opt["text"]
                    muni_val  = muni_opt["value"]
                    logger.info(f"  Municipio: {muni_text}")

                    await _seleccionar(page, IDX_MUNI, muni_val)
                    _sleep(SLEEP_SELECT, SLEEP_VARIANZA)
                    await _esperar_selects(page, 4)

                    opts_zona = await _opciones(page, IDX_ZONA)
                    if not opts_zona:
                        logger.debug(f"    Sin zonas para {muni_text}")
                        continue

                    # ── Iterar zonas ──
                    for zona_opt in opts_zona:
                        zona_text = zona_opt["text"]
                        zona_val  = zona_opt["value"]

                        await _seleccionar(page, IDX_ZONA, zona_val)
                        _sleep(SLEEP_SELECT, SLEEP_VARIANZA)
                        await _esperar_selects(page, 5)

                        opts_puesto = await _opciones(page, IDX_PUESTO)
                        if not opts_puesto:
                            logger.debug(f"    Sin puestos para zona {zona_text}")
                            continue

                        # ── Iterar puestos ──
                        for puesto_opt in opts_puesto:
                            puesto_text = puesto_opt["text"]
                            puesto_val  = puesto_opt["value"]

                            await _seleccionar(page, IDX_PUESTO, puesto_val)
                            _sleep(SLEEP_SELECT, SLEEP_VARIANZA)

                            # Verificar si hay select de mesas
                            await _esperar_selects(page, 6, max_ms=3000)
                            opts_mesa = await _opciones(page, IDX_MESA)

                            if not opts_mesa:
                                # Sin select de mesas: el puesto es la unidad mínima
                                opts_mesa = [{"value": "unica", "text": "Mesa única"}]

                            # ── Iterar mesas ──
                            for mesa_opt in opts_mesa:
                                mesa_text = mesa_opt["text"]
                                mesa_val  = mesa_opt["value"]
                                clave = _clave(depto, muni_text, zona_text, puesto_text, mesa_text)

                                if clave in mesas_procesadas:
                                    continue

                                if mesa_val != "unica":
                                    await _seleccionar(page, IDX_MESA, mesa_val)
                                    _sleep(SLEEP_MESA, 1)

                                await _click_consultar(page)
                                _sleep(SLEEP_MESA, 1)

                                logger.info(
                                    f"    {depto} | {muni_text} | {zona_text} | "
                                    f"{puesto_text} | {mesa_text}"
                                )

                                # ── Votos Cámara ──
                                votos_camara: Dict[str, int] = {}
                                if corp_camara:
                                    await _seleccionar(page, IDX_CORP, corp_camara)
                                    _sleep(1.5, 0.5)
                                    await _click_consultar(page)
                                    _sleep(SLEEP_MESA, 1)
                                    votos_camara = await _extraer_votos(page, candidatos_camara)

                                # ── Votos Senado ──
                                votos_senado = 0
                                if corp_senado:
                                    await _seleccionar(page, IDX_CORP, corp_senado)
                                    _sleep(1.5, 0.5)
                                    # Re-navegar jerarquía
                                    await _seleccionar(page, IDX_DEPTO, depto_opt["value"])
                                    _sleep(2, 0.5)
                                    await _seleccionar(page, IDX_MUNI, muni_val)
                                    _sleep(2, 0.5)
                                    await _esperar_selects(page, 4)
                                    await _seleccionar(page, IDX_ZONA, zona_val)
                                    _sleep(2, 0.5)
                                    await _esperar_selects(page, 5)
                                    await _seleccionar(page, IDX_PUESTO, puesto_val)
                                    _sleep(2, 0.5)
                                    if mesa_val != "unica":
                                        await _esperar_selects(page, 6, max_ms=3000)
                                        await _seleccionar(page, IDX_MESA, mesa_val)
                                        _sleep(1.5, 0.5)
                                    await _click_consultar(page)
                                    _sleep(SLEEP_MESA, 1)
                                    d_senado = await _extraer_votos(page, [candidato_senado])
                                    votos_senado = d_senado.get(candidato_senado, 0)

                                # ── Escribir CSV ──
                                if votos_camara:
                                    for c_cam, v_cam in votos_camara.items():
                                        _escribir_fila(
                                            writer, depto, muni_text, zona_text,
                                            puesto_text, mesa_text,
                                            c_cam, v_cam,
                                            candidato_senado, votos_senado,
                                        )
                                else:
                                    _escribir_fila(
                                        writer, depto, muni_text, zona_text,
                                        puesto_text, mesa_text,
                                        "SIN_DATOS", 0,
                                        candidato_senado, votos_senado,
                                    )

                                csv_file.flush()
                                mesas_procesadas.add(clave)
                                _guardar_progreso(mesas_procesadas)

                                # Volver a Cámara para la siguiente mesa
                                if corp_camara:
                                    await _seleccionar(page, IDX_CORP, corp_camara)
                                    _sleep(1.5, 0.5)
                                    await _seleccionar(page, IDX_DEPTO, depto_opt["value"])
                                    _sleep(2, 0.5)
                                    await _seleccionar(page, IDX_MUNI, muni_val)
                                    _sleep(2, 0.5)
                                    await _esperar_selects(page, 4)
                                    await _seleccionar(page, IDX_ZONA, zona_val)
                                    _sleep(2, 0.5)
                                    await _esperar_selects(page, 5)
                                    await _seleccionar(page, IDX_PUESTO, puesto_val)
                                    _sleep(2, 0.5)

            await browser.close()

    finally:
        csv_file.close()

    logger.info(f"Scraper mesas finalizado | CSV: {csv_path} | Mesas: {len(mesas_procesadas)}")
    return csv_path
