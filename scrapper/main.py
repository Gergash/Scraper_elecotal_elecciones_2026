"""
Punto de entrada principal del scraper de resultados electorales.
Genera backup/resultados_camara_conservador_por_municipio.csv con los votos
de los candidatos a Cámara (lista de info_para_scrpping_costo_por_voto_juan.txt)
en todos los municipios de VALLE, RISARALDA y CALDAS.
"""

import asyncio
from pathlib import Path

from .config import CONFIG, CANDIDATOS_CAMARA
from .scraper import ScraperResultadosElectorales
from .scraper_resultados_camara import (
    run_scraper_camara_conservador_por_municipios,
    _nombres_candidatos_camara_objetivo,
    CSV_CAMARA_CONSERVADOR,
)
from .utils import logger


async def main():
    """Ejecuta la extracción de votos Cámara por municipio y opcionalmente el flujo de correlación."""
    # 1) Generar resultados_camara_conservador_por_municipio.csv (candidatos de la lista en VALLE, RISARALDA, CALDAS)
    candidatos_lista = list(_nombres_candidatos_camara_objetivo())
    logger.info(
        "Extrayendo votos Cámara para %d candidatos en todos los municipios de VALLE, RISARALDA y CALDAS...",
        len(candidatos_lista),
    )
    config_scraper = CONFIG.get("configuracion_scraper", {})
    headless = config_scraper.get("headless", False)
    base_dir = Path(__file__).resolve().parent.parent
    csv_path = base_dir / "backup" / "resultados_camara_conservador_por_municipio.csv"
    await run_scraper_camara_conservador_por_municipios(
        departamentos=None,
        headless=headless,
        csv_path=csv_path,
        candidatos_filtrar=candidatos_lista,
    )
    logger.info("CSV generado: %s", csv_path)

    # 2) Flujo opcional: inversiones, detección URLs, correlación y costo por voto
    INVERSIONES = CONFIG.get("inversiones", {})

    if not INVERSIONES or all(v == 0 for v in INVERSIONES.values()):
        logger.warning("No se encontraron inversiones en la configuracion")
        logger.info("Por favor, edita config_candidatos.json y agrega las inversiones reales")
        INVERSIONES = {}
        for depto, candidatos in (CANDIDATOS_CAMARA or {}).items():
            for c in candidatos:
                nombre = (c.get("nombre_completo", "") if isinstance(c, dict) else str(c)).strip()
                if nombre:
                    INVERSIONES[nombre] = 0.0

    logger.info("Inversiones cargadas para %d candidatos", len(INVERSIONES))

    scraper = ScraperResultadosElectorales(headless=None)
    await scraper.ejecutar_scraping_completo(INVERSIONES)


def run():
    """Ejecuta el main de forma sincrona"""
    asyncio.run(main())
