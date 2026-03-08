"""
Punto de entrada principal del scraper de resultados electorales
"""

import asyncio

from .config import CONFIG, CANDIDATOS_CAMARA
from .scraper import ScraperResultadosElectorales
from .utils import logger


async def main():
    """Funcion principal para ejecutar el scraper"""
    INVERSIONES = CONFIG.get('inversiones', {})

    if not INVERSIONES or all(v == 0 for v in INVERSIONES.values()):
        logger.warning("No se encontraron inversiones en la configuracion")
        logger.info("Por favor, edita config_candidatos.json y agrega las inversiones reales")

        INVERSIONES = {}
        for depto, candidatos in CANDIDATOS_CAMARA.items():
            for candidato in candidatos:
                INVERSIONES[candidato] = 0.0

    logger.info(f"Inversiones cargadas para {len(INVERSIONES)} candidatos")

    scraper = ScraperResultadosElectorales(headless=None)
    await scraper.ejecutar_scraping_completo(INVERSIONES)


def run():
    """Ejecuta el main de forma sincrona"""
    asyncio.run(main())
