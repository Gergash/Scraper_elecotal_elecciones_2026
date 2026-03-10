"""
Scraper para divulgacione14congreso.registraduria.gov.co/home

Flujo de navegación requerido:
1. Ingresar a https://divulgacione14congreso.registraduria.gov.co/home
2. Localizar app-home (Bienvenido, app-home-header, app-home-body)
3. Dar click en la pestaña SENADO (div.menu .item con texto "SENADO")
4. Buscar en la tabla el departamento (ej. CALDAS) y dar click en el enlace
   <a class="text-center py-2 text-primary" href="/departamento/09"> CALDAS </a>
5. Se carga la sección app-consult con filtros: Corporación, Municipio, Zona, Puesto y botón Consultar

Estructura HTML home:
- app-home > app-home-header (corporations: SENADO, CAMARA, etc.)
- app-home-body > div.menu (.item: SENADO, CAMARA, CONSULTAS, CITREP)
- Tabla: .thead / .tbody .columns.data-row (Departamento, Esperados, Publicados, Avances, Faltantes)
- Paginador: app-custom-paginator .page (01, 02, 03, 04)
- Enlace departamento: .td.departamento a[href="/departamento/XX"]

Página departamento: app-consult con app-custom-select (Corporación, Municipio, Zona, Puesto) y Consultar.
  - Al hacer click en cada select se abre div.dropdown-list > ul > li > p (opciones).
  - Corporación: elegir "SENADO". Municipio/Zona/Puesto: elegir la primera opción de la lista.
  - Botón Consultar: button.custom-button con texto "Consultar". Tras click, esperar 10s y que cargue la tabla.
  - Tabla de mesas: div.card.container-table .body-table con cards div.card.item-table.card-mini (Mesa 1, Mesa 2, ...).
    Cada mesa tiene botón descarga: div.open-pdf[title="Descargar"]. Recorrer Municipio → Zona → Puesto → 96/página → descargar cada mesa.
  - Al completar todo un departamento: buscar app-sidemenu, click en input placeholder "Buscar Departamento",
    se despliega la lista (ej. "24 - RISARALDA"); click en el departamento siguiente; se recargan los 4 filtros para ese departamento y se repite el proceso.
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
# Tras click en Consultar, esperar a que cargue la tabla de resultados
TIMEOUT_TABLA_DESPUES_CONSULTAR_MS = 10_000

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


async def _wait_for_home(page: Page) -> bool:
    """
    Espera a que la página home esté cargada: app-home y tabla de departamentos.
    Selectores: app-home-body, div.menu .item, .tbody .columns.data-row o .thead.
    """
    try:
        await page.wait_for_selector("app-home", timeout=TIMEOUT_MS)
        await page.wait_for_selector("app-home-body div.menu .item", timeout=12000)
        await page.wait_for_selector(".table-container .thead, .tbody .columns.data-row", timeout=8000)
        logger.debug("Home cargado (app-home y tabla de departamentos).")
        return True
    except Exception as e:
        logger.debug(f"Esperando home: {e}")
    return False


async def _click_menu(page: Page, opcion: str) -> bool:
    """
    Click en la pestaña del menú: SENADO, CAMARA, CONSULTAS o CITREP.
    Corresponde a <div class="item select-item"> SENADO </div> / <div class="item"> CAMARA </div> etc.
    """
    target = opcion.strip().upper()
    try:
        await page.wait_for_selector("div.menu .item", timeout=12000)
        items = await page.query_selector_all("div.menu .item")
        for item in items:
            txt = (await item.inner_text() or "").strip().upper()
            if txt == target:
                await item.click()
                await page.wait_for_timeout(int(SLEEP_MENU * 1000))
                logger.debug(f"Menú '{target}' seleccionado.")
                return True
        logger.debug(f"Menú '{target}' no encontrado.")
    except Exception as e:
        logger.debug(f"Error click menú {opcion}: {e}")
    return False


async def _set_departamentos_por_pagina(page: Page, n: int = 20) -> bool:
    """Cambia el select 'Departamentos por página' (5, 10, 15, 20, 40) para mostrar más filas."""
    try:
        select = await page.query_selector("#pageSize")
        if not select:
            return False
        await select.select_option(value=str(n))
        await page.wait_for_timeout(int(SLEEP_MENU * 1000))
        return True
    except Exception as e:
        logger.debug(f"Select pageSize: {e}")
    return False


async def _click_departamento_en_tabla(page: Page, nombre_departamento: str) -> bool:
    """
    Busca en la tabla de departamentos el enlace con el nombre dado (ej. CALDAS)
    y hace click en él. Recorre las páginas del paginador si es necesario.
    El enlace tiene la forma: <a href="/departamento/09" class="text-center py-2 text-primary"> CALDAS </a>
    Tras el click se carga la sección app-consult con los filtros.
    """
    nombre = nombre_departamento.strip().upper()
    try:
        # Opcional: mostrar más filas por página para encontrar antes el departamento
        await _set_departamentos_por_pagina(page, 20)

        pages_el = await page.query_selector_all("app-custom-paginator .page")
        paginas_nums = []
        for p in pages_el:
            txt = (await p.text_content() or "").strip()
            if txt.isdigit():
                paginas_nums.append(txt)

        for num in paginas_nums or ["01"]:
            await _click_pagina(page, num)
            rows = await page.query_selector_all(".tbody .columns.data-row")
            for row in rows:
                link = await row.query_selector(".td.departamento a.text-primary, .td.departamento a[href*='departamento']")
                if not link:
                    link = await row.query_selector(".td.departamento a")
                if not link:
                    continue
                text = (await link.inner_text() or "").strip().upper()
                if text == nombre:
                    await link.click()
                    await page.wait_for_timeout(int(SLEEP_PAGE * 1000))
                    logger.info(f"Click en departamento: {nombre}")
                    return True
        logger.debug(f"Departamento '{nombre}' no encontrado en la tabla.")
    except Exception as e:
        logger.debug(f"Error click departamento {nombre_departamento}: {e}")
    return False


async def _wait_for_consult_filters(page: Page) -> bool:
    """
    Tras hacer click en un departamento, espera a que aparezca la sección de consulta
    con filtros: app-consult, Corporación, Municipio, Zona, Puesto y botón Consultar.
    """
    try:
        await page.wait_for_selector("app-consult", timeout=10000)
        await page.wait_for_selector(
            "app-consult .card-container-g, app-consult app-custom-select, app-consult .consult-btn",
            timeout=8000,
        )
        logger.debug("Sección app-consult (filtros) cargada.")
        return True
    except Exception as e:
        logger.debug(f"Esperando app-consult: {e}")
    return False


# ──────────────────────────────────────────────
# app-sidemenu: cambiar departamento (Buscar Departamento → lista → click ej. RISARALDA)
# ──────────────────────────────────────────────


async def _abrir_sidemenu_y_seleccionar_departamento(page: Page, nombre_departamento: str) -> bool:
    """
    Tras completar un departamento: localiza app-sidemenu, hace click en el input
    placeholder 'Buscar Departamento' (o en el input-container que lo contiene),
    se despliega la lista div.dropdown-list ul li (ej. '24 - RISARALDA'); hace click
    en el elemento que contiene el nombre del departamento (ej. RISARALDA).
    La página recarga los 4 filtros (Corporación, Municipio, Zona, Puesto) para ese departamento.
    """
    try:
        sidemenu = await page.query_selector("app-sidemenu")
        if not sidemenu:
            logger.debug("app-sidemenu no encontrado.")
            return False
        # Input con placeholder "Buscar Departamento" dentro del sidemenu
        input_depto = await sidemenu.query_selector(
            'input.custom-input[placeholder="Buscar Departamento"], '
            'input[placeholder*="Buscar Departamento"]'
        )
        if not input_depto:
            input_container = await sidemenu.query_selector("div.input-container")
            if input_container:
                input_depto = await input_container.query_selector("input.custom-input")
        if not input_depto:
            logger.debug("Input Buscar Departamento no encontrado en sidemenu.")
            return False
        await input_depto.click()
        await page.wait_for_timeout(700)
        await page.wait_for_selector("app-sidemenu div.dropdown-list ul li", timeout=6000)
        items = await page.query_selector_all("app-sidemenu div.dropdown-list ul li")
        nombre = nombre_departamento.strip().upper()
        for li in items:
            p = await li.query_selector("p")
            txt = (await p.inner_text() if p else "").strip().upper()
            if nombre in txt:
                await li.click()
                await page.wait_for_timeout(2000)
                logger.info(f"Sidemenu: seleccionado departamento {nombre}.")
                return True
        logger.debug(f"Departamento '{nombre_departamento}' no encontrado en lista sidemenu.")
    except Exception as e:
        logger.debug(f"Sidemenu seleccionar departamento: {e}")
    return False


# ──────────────────────────────────────────────
# Filtros app-consult: Corporación, Municipio, Zona, Puesto, Consultar
# Dropdown: div.dropdown-list ul li p (texto de la opción)
# ──────────────────────────────────────────────


async def _get_consult_select_inputs(page: Page) -> List:
    """
    Devuelve los 4 inputs de app-custom-select en app-consult, en orden:
    [0] Corporación, [1] Municipio, [2] Zona, [3] Puesto.
    """
    inputs: List = []
    try:
        selects = await page.query_selector_all("app-consult app-custom-select")
        for sel in selects[:4]:
            inp = await sel.query_selector("input.custom-input")
            if inp:
                inputs.append(inp)
    except Exception as e:
        logger.debug(f"Obteniendo inputs consult: {e}")
    return inputs


async def _open_dropdown_and_select(
    page: Page,
    input_el,
    option_text: Optional[str] = None,
    option_index: Optional[int] = None,
) -> bool:
    """
    Hace click en el input del filtro para abrir el dropdown (div.dropdown-list ul li),
    luego selecciona la opción por texto exacto (ej. 'SENADO') o por índice (0 = primera).
    """
    try:
        await input_el.click()
        await page.wait_for_timeout(600)
        await page.wait_for_selector("div.dropdown-list ul li", timeout=5000)
        items = await page.query_selector_all("div.dropdown-list ul li")
        if not items:
            logger.debug("Dropdown sin opciones.")
            return False
        if option_text is not None:
            target = option_text.strip().upper()
            for li in items:
                p = await li.query_selector("p")
                txt = (await p.inner_text() if p else "").strip().upper()
                if txt == target or target in txt:
                    await li.click()
                    await page.wait_for_timeout(400)
                    return True
            logger.debug(f"Opción '{option_text}' no encontrada en dropdown.")
            return False
        if option_index is not None and 0 <= option_index < len(items):
            await items[option_index].click()
            await page.wait_for_timeout(400)
            return True
        # Por defecto primera opción
        await items[0].click()
        await page.wait_for_timeout(400)
        return True
    except Exception as e:
        logger.debug(f"Dropdown select: {e}")
    return False


async def _aplicar_filtros_consultar_y_esperar_tabla(
    page: Page,
    corporacion: str = "SENADO",
) -> bool:
    """
    En la página app-consult:
    1. Click en Corporación → dropdown → seleccionar 'SENADO'
    2. Click en Municipio → dropdown → seleccionar primera opción
    3. Click en Zona → dropdown → seleccionar primera opción
    4. Click en Puesto → dropdown → seleccionar primera opción
    5. Click en botón Consultar (button.custom-button con texto Consultar)
    6. Timeout 10 segundos y esperar a que cargue una tabla (tbody o tabla de resultados)
    """
    try:
        inputs = await _get_consult_select_inputs(page)
        if len(inputs) < 4:
            logger.warning("No se encontraron los 4 filtros en app-consult.")
            return False

        # 1. Corporación → SENADO
        ok = await _open_dropdown_and_select(page, inputs[0], option_text=corporacion)
        if not ok:
            logger.debug("No se pudo seleccionar Corporación SENADO.")
        await page.wait_for_timeout(300)

        # 2. Municipio → primera opción (ej. 004 — AGUADAS (100%))
        await _open_dropdown_and_select(page, inputs[1], option_index=0)
        await page.wait_for_timeout(300)

        # 3. Zona → primera opción (ej. Zona 01)
        await _open_dropdown_and_select(page, inputs[2], option_index=0)
        await page.wait_for_timeout(300)

        # 4. Puesto → primera opción (ej. 01 - BIBLIOTECA MUNICIPAL)
        await _open_dropdown_and_select(page, inputs[3], option_index=0)
        await page.wait_for_timeout(400)

        # 5. Click Consultar: button.custom-button con span "Consultar" o icon consult
        consult_btn = await page.query_selector(
            'app-consult button.custom-button, app-consult .consult-btn button'
        )
        if not consult_btn:
            consult_btn = await page.query_selector('app-consult button:has-text("Consultar")')
        if not consult_btn:
            logger.warning("Botón Consultar no encontrado.")
            return False
        await consult_btn.click()

        # 6. Timeout 10 segundos y esperar tabla de mesas (card container-table, body-table, item-table)
        await page.wait_for_timeout(TIMEOUT_TABLA_DESPUES_CONSULTAR_MS)
        try:
            await page.wait_for_selector(
                ".card.container-table .body-table, .body-table .card.item-table.card-mini, "
                "app-consult .tbody, app-consult table",
                timeout=8000,
            )
            logger.debug("Tabla de resultados/mesas cargada.")
        except Exception:
            logger.debug("Timeout esperando tabla tras Consultar.")

        return True
    except Exception as e:
        logger.debug(f"Aplicar filtros y consultar: {e}")
    return False


# ──────────────────────────────────────────────
# Tabla de mesas: 96 por página, descargar cada mesa (div.open-pdf)
# Tras cada descarga aparece modal "Descarga Exitosa" con botón Aceptar; hay que cerrarlo para continuar.
# ──────────────────────────────────────────────


async def _cerrar_modal_descarga_exitosa(page: Page) -> bool:
    """
    Tras hacer click en el botón de descarga de una mesa, se abre un modal con
    'Descarga Exitosa' y botón 'Aceptar'. Hace click en Aceptar para cerrar el modal
    y poder continuar con la siguiente mesa.
    """
    try:
        await page.wait_for_timeout(600)
        modal = await page.wait_for_selector(".modal-content", timeout=8000)
        if not modal:
            return False
        btn_aceptar = await modal.query_selector("button.custom-button")
        if not btn_aceptar:
            btn_aceptar = await page.query_selector(".modal-content app-custom-button button.custom-button")
        if btn_aceptar:
            await btn_aceptar.click()
            await page.wait_for_timeout(400)
            return True
    except Exception as e:
        logger.debug(f"Cerrar modal Descarga Exitosa: {e}")
    return False


async def _esperar_tabla_mesas(page: Page) -> bool:
    """Espera a que esté visible la tabla de mesas: .card.container-table .body-table y cards .item-table."""
    try:
        await page.wait_for_selector(".card.container-table .body-table", timeout=8000)
        await page.wait_for_selector(".body-table .card.item-table.card-mini, .body-table .item-table", timeout=5000)
        return True
    except Exception as e:
        logger.debug(f"Esperando tabla mesas: {e}")
    return False


async def _seleccionar_mesas_por_pagina(page: Page, texto_opcion: str = "96 mesas por página") -> bool:
    """
    En la tabla de mesas, header-table tiene un app-custom-select con 'X por página' (arrow-bottom).
    Abre ese dropdown y selecciona la opción con el texto indicado (ej. '96 mesas por página').
    """
    try:
        # Segundo app-custom-select dentro de .header-table (el de "12 por página" / "96 por página")
        header = await page.query_selector(".card.container-table .header-table")
        if not header:
            return False
        selects = await header.query_selector_all("app-custom-select")
        if len(selects) < 2:
            return False
        # El segundo es "X por página"
        select_pagina = selects[1]
        btn = await select_pagina.query_selector("button.custom-button")
        if not btn:
            return False
        await btn.click()
        await page.wait_for_timeout(600)
        await page.wait_for_selector("div.dropdown-list ul li", timeout=5000)
        items = await page.query_selector_all("div.dropdown-list ul li")
        target = texto_opcion.strip().lower()
        for li in items:
            p = await li.query_selector("p")
            txt = (await p.inner_text() if p else "").strip()
            txt_lower = txt.lower()
            # Aceptar "96 mesas por página" o "96 por página" (evitar 6, 12, 24, 48)
            if target in txt_lower or ("96" in txt_lower and "página" in txt_lower):
                await li.click()
                await page.wait_for_timeout(800)
                logger.debug(f"Seleccionado: {txt}")
                return True
        if items:
            await items[0].click()
        return False
    except Exception as e:
        logger.debug(f"Seleccionar mesas por página: {e}")
    return False


async def _descargar_mesas_pagina_actual(
    page: Page,
    carpeta: Path,
    max_descargas: int = 500,
    offset_inicio: int = 0,
) -> int:
    """
    En la tabla de mesas actual, obtiene cada card .card.item-table.card-mini,
    hace click en div.open-pdf[title="Descargar"] y guarda el PDF en carpeta.
    Usa page.expect_download() para capturar el archivo. Retorna número de descargas.
    offset_inicio: contador acumulado (ej. total ya descargado en esta carpeta) para no
    sobrescribir archivos entre puestos/zonas; los nombres serán {offset_inicio+0:04d}_...,
    {offset_inicio+1:04d}_..., etc.
    """
    descargados = 0
    try:
        cards = await page.query_selector_all(".body-table .card.item-table.card-mini, .body-table .item-table")
        for i, card in enumerate(cards):
            if descargados >= max_descargas:
                break
            btn_descarga = await card.query_selector('div.open-pdf[title="Descargar"], div.open-pdf')
            if not btn_descarga:
                continue
            try:
                # Índice global en la carpeta para no sobrescribir entre puestos/zonas
                indice = offset_inicio + descargados
                title_el = await card.query_selector(".title h3, h3")
                nombre_mesa = (await title_el.inner_text() if title_el else "").strip() or f"mesa_{i+1}"
                safe_name = re.sub(r"[^\w\s-]", "", nombre_mesa)[:50].strip() or f"mesa_{i+1}"
                if not safe_name.lower().endswith(".pdf"):
                    safe_name += ".pdf"
                path_destino = carpeta / f"{indice:04d}_{safe_name}"

                async with page.expect_download(timeout=15000) as download_info:
                    await btn_descarga.click()
                download = await download_info.value
                await download.save_as(path_destino)
                descargados += 1
                logger.info(f"    Descargado: {path_destino.name}")
                # Cerrar modal "Descarga Exitosa" con click en Aceptar para continuar con la siguiente mesa
                await _cerrar_modal_descarga_exitosa(page)
            except Exception as e:
                logger.debug(f"    Mesa {i+1} descarga: {e}")
            await page.wait_for_timeout(int(SLEEP_DESCARGA * 1000))
    except Exception as e:
        logger.debug(f"Descargar mesas página: {e}")
    return descargados


async def _siguiente_pagina_mesas(page: Page) -> bool:
    """Si hay paginador en la tabla de mesas, hace click en la siguiente página. Retorna True si hubo click."""
    try:
        paginator = await page.query_selector(".card.container-table app-custom-paginator")
        if not paginator:
            return False
        pages = await paginator.query_selector_all(".page")
        current = await paginator.query_selector(".page.select")
        if not current or not pages:
            return False
        current_txt = (await current.text_content() or "").strip()
        idx = next((i for i, p in enumerate(pages) if (await p.text_content() or "").strip() == current_txt), -1)
        if idx < 0 or idx + 1 >= len(pages):
            return False
        next_page = pages[idx + 1]
        await next_page.click()
        await page.wait_for_timeout(1500)
        return True
    except Exception as e:
        logger.debug(f"Siguiente página mesas: {e}")
    return False


async def _obtener_cantidad_opciones_filtro(page: Page, indice_filtro: int) -> int:
    """Abre el dropdown del filtro (0=Corporación, 1=Municipio, 2=Zona, 3=Puesto) y devuelve cantidad de opciones."""
    try:
        inputs = await _get_consult_select_inputs(page)
        if indice_filtro < 0 or indice_filtro >= len(inputs):
            return 0
        await inputs[indice_filtro].click()
        await page.wait_for_timeout(500)
        items = await page.query_selector_all("div.dropdown-list ul li")
        n = len(items)
        # Cerrar dropdown sin cambiar (click fuera o en la primera opción)
        if items:
            await items[0].click()
        await page.wait_for_timeout(300)
        return n
    except Exception as e:
        logger.debug(f"Cantidad opciones filtro {indice_filtro}: {e}")
    return 0


async def _descargar_e14_por_mesas_por_puesto(
    page: Page,
    corp: str,
    fila: FilaDepartamento,
    dir_base: Path,
    inputs_filtros,
    puesto_index: int,
    max_descargas_por_puesto: int = 500,
    offset_carpeta: int = 0,
) -> int:
    """
    Para el puesto en índice puesto_index: selecciona esa opción en el filtro Puesto (4º),
    click Consultar, espera tabla mesas, selecciona 96 por página, descarga cada mesa (todas las páginas).
    offset_carpeta: archivos ya existentes en la carpeta del departamento (para no sobreescribir).
    """
    total = 0
    try:
        # Seleccionar Puesto en índice puesto_index (0 = primero ya aplicado antes)
        await _open_dropdown_and_select(page, inputs_filtros[3], option_index=puesto_index)
        await page.wait_for_timeout(400)
        consult_btn = await page.query_selector('app-consult button.custom-button, app-consult .consult-btn button')
        if not consult_btn:
            return 0
        await consult_btn.click()
        await page.wait_for_timeout(TIMEOUT_TABLA_DESPUES_CONSULTAR_MS)
        if not await _esperar_tabla_mesas(page):
            return 0
        await _seleccionar_mesas_por_pagina(page, "96 mesas por página")
        await page.wait_for_timeout(1000)

        depto_nombre = re.sub(r"[^\w\s-]", "", fila.departamento.strip()).replace(" ", "_")
        carpeta = dir_base / corp.upper().replace(" ", "_") / depto_nombre
        carpeta.mkdir(parents=True, exist_ok=True)

        while True:
            n = await _descargar_mesas_pagina_actual(
                page, carpeta, max_descargas=max_descargas_por_puesto - total,
                offset_inicio=offset_carpeta + total,
            )
            total += n
            if not await _siguiente_pagina_mesas(page):
                break
        return total
    except Exception as e:
        logger.debug(f"Descargar E14 por puesto {puesto_index}: {e}")
    return total


async def _descargar_e14_por_municipio_completo(
    page: Page,
    corp: str,
    fila: FilaDepartamento,
    dir_base: Path,
    inputs,
    municipio_idx: int,
    max_descargas: int,
    offset_carpeta: int = 0,
) -> int:
    """
    Para un Municipio dado (índice): click en filtro Municipio (input placeholder 'seleccione el municipio'),
    seleccionar el elemento en la lista (municipio_idx = 0 primero, 1 segundo, etc.); luego Zona primera opción,
    Puesto primera opción; Consultar; 96 por página; descargar todas las mesas. Después recorrer todos los Puestos
    de la primera Zona, luego todas las Zonas restantes (cada una con todos sus Puestos).
    offset_carpeta: archivos ya existentes en la carpeta del departamento (para no sobreescribir).
    """
    total = 0
    try:
        # Seleccionar Municipio (segundo = index 1, tercero = 2, ...)
        await _open_dropdown_and_select(page, inputs[1], option_index=municipio_idx)
        await page.wait_for_timeout(500)
        # Zona: primera opción
        await _open_dropdown_and_select(page, inputs[2], option_index=0)
        await page.wait_for_timeout(400)
        # Puesto: primera opción
        await _open_dropdown_and_select(page, inputs[3], option_index=0)
        await page.wait_for_timeout(400)

        consult_btn = await page.query_selector('app-consult button.custom-button, app-consult .consult-btn button')
        if not consult_btn:
            return 0
        await consult_btn.click()
        await page.wait_for_timeout(TIMEOUT_TABLA_DESPUES_CONSULTAR_MS)
        if not await _esperar_tabla_mesas(page):
            return 0
        await _seleccionar_mesas_por_pagina(page, "96 por página")
        await page.wait_for_timeout(1000)

        depto_nombre = re.sub(r"[^\w\s-]", "", fila.departamento.strip()).replace(" ", "_")
        carpeta = dir_base / corp.upper().replace(" ", "_") / depto_nombre
        carpeta.mkdir(parents=True, exist_ok=True)

        # Primera Zona, primer Puesto: descargar todas las mesas (todas las páginas)
        while True:
            n = await _descargar_mesas_pagina_actual(
                page, carpeta, max_descargas=max_descargas - total,
                offset_inicio=offset_carpeta + total,
            )
            total += n
            if not await _siguiente_pagina_mesas(page):
                break

        # Resto de Puestos de la primera Zona
        inputs = await _get_consult_select_inputs(page)
        if len(inputs) < 4:
            return total
        await inputs[3].click()
        await page.wait_for_timeout(500)
        opciones_puesto = await page.query_selector_all("div.dropdown-list ul li")
        num_puestos = len(opciones_puesto)
        if opciones_puesto:
            await opciones_puesto[0].click()
        await page.wait_for_timeout(300)

        for puesto_idx in range(1, num_puestos):
            if total >= max_descargas:
                break
            n = await _descargar_e14_por_mesas_por_puesto(
                page, corp, fila, dir_base, inputs, puesto_idx,
                max_descargas_por_puesto=max_descargas - total,
                offset_carpeta=offset_carpeta + total,
            )
            total += n
            inputs = await _get_consult_select_inputs(page)
            if len(inputs) < 4:
                break

        # Resto de Zonas de este Municipio
        if len(inputs) < 4:
            return total
        await inputs[2].click()
        await page.wait_for_timeout(500)
        opciones_zona = await page.query_selector_all("div.dropdown-list ul li")
        num_zonas = len(opciones_zona)
        if opciones_zona:
            await opciones_zona[0].click()
        await page.wait_for_timeout(300)

        for zona_idx in range(1, num_zonas):
            if total >= max_descargas:
                break
            inputs = await _get_consult_select_inputs(page)
            if len(inputs) < 4:
                break
            n = await _descargar_e14_por_zona_y_puestos(
                page, corp, fila, dir_base, inputs, zona_idx,
                max_descargas=max_descargas - total,
                offset_carpeta=offset_carpeta + total,
            )
            total += n
    except Exception as e:
        logger.debug(f"Descargar E14 por municipio {municipio_idx}: {e}")
    return total


async def _descargar_e14_por_zona_y_puestos(
    page: Page,
    corp: str,
    fila: FilaDepartamento,
    dir_base: Path,
    inputs,
    zona_idx: int,
    max_descargas: int,
    offset_carpeta: int = 0,
) -> int:
    """
    Para una Zona dada (índice): selecciona Zona en el filtro, luego Puesto primera opción,
    Consultar, esperar tabla, 96 por página, descargar todas las mesas (todas las páginas).
    Luego para el resto de Puestos de esa Zona: seleccionar Puesto, Consultar, 96/página, descargar.
    offset_carpeta: archivos ya existentes en la carpeta del departamento (para no sobreescribir).
    """
    total = 0
    try:
        # Seleccionar Zona (siguiente después de la primera si zona_idx > 0)
        await _open_dropdown_and_select(page, inputs[2], option_index=zona_idx)
        await page.wait_for_timeout(400)
        # Seleccionar primera opción en Puesto
        await _open_dropdown_and_select(page, inputs[3], option_index=0)
        await page.wait_for_timeout(400)

        consult_btn = await page.query_selector('app-consult button.custom-button, app-consult .consult-btn button')
        if not consult_btn:
            return 0
        await consult_btn.click()
        await page.wait_for_timeout(TIMEOUT_TABLA_DESPUES_CONSULTAR_MS)
        if not await _esperar_tabla_mesas(page):
            return 0
        # 96 por página (acepta "96 mesas por página" o "96 por página")
        await _seleccionar_mesas_por_pagina(page, "96 por página")
        await page.wait_for_timeout(1000)

        depto_nombre = re.sub(r"[^\w\s-]", "", fila.departamento.strip()).replace(" ", "_")
        carpeta = dir_base / corp.upper().replace(" ", "_") / depto_nombre
        carpeta.mkdir(parents=True, exist_ok=True)

        while True:
            n = await _descargar_mesas_pagina_actual(
                page, carpeta, max_descargas=max_descargas - total,
                offset_inicio=offset_carpeta + total,
            )
            total += n
            if not await _siguiente_pagina_mesas(page):
                break

        # Resto de Puestos de esta Zona
        inputs = await _get_consult_select_inputs(page)
        if len(inputs) < 4:
            return total
        await inputs[3].click()
        await page.wait_for_timeout(500)
        opciones_puesto = await page.query_selector_all("div.dropdown-list ul li")
        num_puestos = len(opciones_puesto)
        if opciones_puesto:
            await opciones_puesto[0].click()
        await page.wait_for_timeout(300)

        for puesto_idx in range(1, num_puestos):
            if total >= max_descargas:
                break
            n = await _descargar_e14_por_mesas_por_puesto(
                page, corp, fila, dir_base, inputs, puesto_idx,
                max_descargas_por_puesto=max_descargas - total,
                offset_carpeta=offset_carpeta + total,
            )
            total += n
            inputs = await _get_consult_select_inputs(page)
            if len(inputs) < 4:
                break
    except Exception as e:
        logger.debug(f"Descargar E14 por zona {zona_idx}: {e}")
    return total


async def _descargar_e14_tabla_mesas_completa(
    page: Page,
    corp: str,
    fila: FilaDepartamento,
    dir_base: Path,
    max_descargas: int = 5000,
) -> int:
    """
    Flujo completo tras Consultar (primer Municipio, primera Zona, primer Puesto):
    1) Esperar tabla mesas, 96 por página, descargar todas las mesas (todas las páginas).
    2) Iterar resto de Puestos de la primera Zona; luego resto de Zonas (cada una: primera Zona → todos Puestos).
    3) Al terminar todas las zonas del municipio: click en filtro Municipio (input 'seleccione el municipio'),
       seleccionar el segundo elemento de la lista; Zona primera opción; Puesto primera opción; Consultar;
       96 por página; descargar actas de cada mesa; luego todos los Puestos, luego todas las Zonas del mismo orden.
    4) Repetir 3 para cada Municipio siguiente (tercero, cuarto, ...) hasta completar todo el departamento.
    Orden jerárquico: Municipio → Zona → Puesto → mesas (96/página, descargar open-pdf).
    """
    total_descargados = 0
    try:
        await _esperar_tabla_mesas(page)
        await _seleccionar_mesas_por_pagina(page, "96 por página")
        await page.wait_for_timeout(1000)

        depto_nombre = re.sub(r"[^\w\s-]", "", fila.departamento.strip()).replace(" ", "_")
        carpeta = dir_base / corp.upper().replace(" ", "_") / depto_nombre
        carpeta.mkdir(parents=True, exist_ok=True)

        # Primera Zona, primer Puesto: descargar todas las mesas (todas las páginas)
        while True:
            n = await _descargar_mesas_pagina_actual(
                page, carpeta, max_descargas=max_descargas - total_descargados, offset_inicio=total_descargados
            )
            total_descargados += n
            if not await _siguiente_pagina_mesas(page):
                break

        # Resto de Puestos de la primera Zona
        inputs = await _get_consult_select_inputs(page)
        if len(inputs) < 4:
            return total_descargados
        await inputs[3].click()
        await page.wait_for_timeout(500)
        opciones_puesto = await page.query_selector_all("div.dropdown-list ul li")
        num_puestos = len(opciones_puesto)
        if opciones_puesto:
            await opciones_puesto[0].click()
        await page.wait_for_timeout(300)

        for puesto_idx in range(1, num_puestos):
            if total_descargados >= max_descargas:
                break
            n = await _descargar_e14_por_mesas_por_puesto(
                page, corp, fila, dir_base, inputs, puesto_idx,
                max_descargas_por_puesto=max_descargas - total_descargados,
                offset_carpeta=total_descargados,
            )
            total_descargados += n
            inputs = await _get_consult_select_inputs(page)
            if len(inputs) < 4:
                break

        # Obtener cantidad de Zonas para iterar las siguientes
        if len(inputs) < 4:
            return total_descargados
        await inputs[2].click()
        await page.wait_for_timeout(500)
        opciones_zona = await page.query_selector_all("div.dropdown-list ul li")
        num_zonas = len(opciones_zona)
        if opciones_zona:
            await opciones_zona[0].click()
        await page.wait_for_timeout(300)

        # Desde la segunda Zona en adelante: seleccionar Zona → primer Puesto → Consultar → 96/página → descargar mesas; luego resto de Puestos
        for zona_idx in range(1, num_zonas):
            if total_descargados >= max_descargas:
                break
            inputs = await _get_consult_select_inputs(page)
            if len(inputs) < 4:
                break
            n = await _descargar_e14_por_zona_y_puestos(
                page, corp, fila, dir_base, inputs, zona_idx,
                max_descargas=max_descargas - total_descargados,
                offset_carpeta=total_descargados,
            )
            total_descargados += n

        # Obtener cantidad de Municipios para iterar los siguientes (segundo, tercero, ...)
        inputs = await _get_consult_select_inputs(page)
        if len(inputs) < 4:
            return total_descargados
        # Click en filtro Municipio (input placeholder "seleccione el municipio") y contar opciones
        await inputs[1].click()
        await page.wait_for_timeout(500)
        opciones_municipio = await page.query_selector_all("div.dropdown-list ul li")
        num_municipios = len(opciones_municipio)
        if opciones_municipio:
            await opciones_municipio[0].click()
        await page.wait_for_timeout(300)

        # Desde el segundo Municipio: seleccionar Municipio → primera Zona → primer Puesto → Consultar → 96/página → descargar; luego todos los Puestos y Zonas
        for municipio_idx in range(1, num_municipios):
            if total_descargados >= max_descargas:
                break
            inputs = await _get_consult_select_inputs(page)
            if len(inputs) < 4:
                break
            n = await _descargar_e14_por_municipio_completo(
                page, corp, fila, dir_base, inputs, municipio_idx,
                max_descargas=max_descargas - total_descargados,
                offset_carpeta=total_descargados,
            )
            total_descargados += n

    except Exception as e:
        logger.warning(f"Descargar E14 tabla mesas: {e}")
    return total_descargados


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
    ya_estamos_en_pagina_departamento: bool = False,
) -> int:
    """
    Navega a la página del departamento (URL_BASE + href) y descarga
    todos los E14 encontrados. Si ya_estamos_en_pagina_departamento=True
    (llegamos por click en la tabla), no hace goto. Si seguir_subpaginas=True,
    entra en cada enlace de la tabla (municipio/zona/mesa) y descarga E14 allí.
    """
    if not fila.href or not fila.href.strip():
        return 0
    url_depto = URL_BASE + fila.href if fila.href.startswith("/") else (URL_BASE + "/" + fila.href)
    depto_nombre = re.sub(r"[^\w\s-]", "", fila.departamento.strip()).replace(" ", "_")
    carpeta = dir_base / corp.upper().replace(" ", "_") / depto_nombre
    carpeta.mkdir(parents=True, exist_ok=True)

    descargados = 0
    try:
        if not ya_estamos_en_pagina_departamento:
            logger.info(f"    Navegando a {url_depto} ...")
            await page.goto(url_depto, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(int(SLEEP_PAGE * 1000))
        else:
            logger.info(f"    Ya en página de {fila.departamento} (app-consult).")

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
                accept_downloads=True,
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
            await _wait_for_home(page)

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
                    for idx_fila, fila in enumerate(filas):
                        if idx_fila == 0:
                            # Primer departamento: ir a home, pestaña corporación, click enlace departamento en tabla → app-consult
                            await page.goto(URL_HOME, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
                            await page.wait_for_timeout(2000)
                            await _wait_for_home(page)
                            await _click_menu(page, corp)
                            await page.wait_for_timeout(int(SLEEP_PAGE * 1000))
                            if not await _click_departamento_en_tabla(page, fila.departamento):
                                n = await _descargar_e14_departamento(
                                    page, corp, fila, E14_DESCARGA_DIR,
                                    ya_estamos_en_pagina_departamento=False,
                                )
                            else:
                                await _wait_for_consult_filters(page)
                                await _aplicar_filtros_consultar_y_esperar_tabla(page, corporacion=corp)
                                n = await _descargar_e14_tabla_mesas_completa(page, corp, fila, E14_DESCARGA_DIR)
                        else:
                            # Siguientes departamentos: app-sidemenu → click "Buscar Departamento" → lista → click ej. RISARALDA; se recargan los 4 filtros
                            if await _abrir_sidemenu_y_seleccionar_departamento(page, fila.departamento):
                                await _wait_for_consult_filters(page)
                                await _aplicar_filtros_consultar_y_esperar_tabla(page, corporacion=corp)
                                n = await _descargar_e14_tabla_mesas_completa(page, corp, fila, E14_DESCARGA_DIR)
                            else:
                                n = 0
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
