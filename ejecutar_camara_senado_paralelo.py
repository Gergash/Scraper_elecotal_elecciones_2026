"""
Ejecuta en paralelo el scraper de resultados Cámara (Conservador por municipio)
y el scraper de resultados Senado (Juan Camilo Vélez por municipio).

Salidas:
- backup/resultados_camara_conservador_por_municipio.csv
- backup/resultados_senado_conservador_por_municipio.csv

Uso:
    python ejecutar_camara_senado_paralelo.py
    python ejecutar_camara_senado_paralelo.py --headless
    python ejecutar_camara_senado_paralelo.py --deptos VALLE CALDAS
"""

import argparse
import asyncio
import logging

from scrapper.scraper_resultados_camara import (
    run_scraper_camara_conservador_por_municipios,
    DEPARTAMENTOS_OBJETIVO,
)
from scrapper.scraper_resultados_senado import run_scraper_senado_conservador_por_municipios

logger = logging.getLogger(__name__)


async def _ejecutar_paralelo(departamentos, headless: bool):
    """Ejecuta ambos scrapers en paralelo con asyncio.gather."""
    resultados = await asyncio.gather(
        run_scraper_camara_conservador_por_municipios(
            departamentos=departamentos,
            headless=headless,
        ),
        run_scraper_senado_conservador_por_municipios(
            departamentos=departamentos,
            headless=headless,
        ),
        return_exceptions=True,
    )
    path_camara = resultados[0] if not isinstance(resultados[0], Exception) else None
    path_senado = resultados[1] if not isinstance(resultados[1], Exception) else None
    if isinstance(resultados[0], Exception):
        logger.error("Error scraper Cámara: %s", resultados[0])
    if isinstance(resultados[1], Exception):
        logger.error("Error scraper Senado: %s", resultados[1])
    return path_camara, path_senado


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Ejecutar scrapers Cámara y Senado en paralelo")
    parser.add_argument("--headless", action="store_true", help="Ejecutar navegador en modo headless")
    parser.add_argument(
        "--deptos",
        nargs="+",
        default=DEPARTAMENTOS_OBJETIVO,
        help="Departamentos a procesar (default: VALLE RISARALDA CALDAS)",
    )
    args = parser.parse_args()

    logger.info("Ejecutando Cámara y Senado en paralelo (deptos: %s)", args.deptos)
    path_camara, path_senado = asyncio.run(_ejecutar_paralelo(args.deptos, args.headless))
    if path_camara:
        logger.info("Cámara: %s", path_camara)
    if path_senado:
        logger.info("Senado: %s", path_senado)


if __name__ == "__main__":
    main()
