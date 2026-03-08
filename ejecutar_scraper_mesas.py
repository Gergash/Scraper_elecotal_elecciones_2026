#!/usr/bin/env python3
"""
Punto de entrada del scraper jerárquico de mesas electorales.

Navega: Departamento → Municipio → Zona → Puesto → Mesa
Extrae votos de candidatos a Cámara y Senado por cada mesa.

Uso:
    python ejecutar_scraper_mesas.py
    python ejecutar_scraper_mesas.py --deptos VALLE RISARALDA
    python ejecutar_scraper_mesas.py --deptos CALDAS --headless
    python ejecutar_scraper_mesas.py --sin-reanudar       # empieza desde cero
    python ejecutar_scraper_mesas.py --salida mi_archivo.csv
"""

import argparse
import asyncio
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from scrapper.scraper_mesas import scrape_mesas
from scrapper.config import DEPARTAMENTOS
from scrapper.utils import logger


def main():
    parser = argparse.ArgumentParser(
        description="Scraper jerárquico de mesas - Congreso 2026"
    )
    parser.add_argument(
        "--deptos",
        nargs="+",
        default=None,
        metavar="DEPTO",
        help=f"Departamentos a procesar (default: todos). Opciones: {', '.join(DEPARTAMENTOS)}",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Ejecutar sin ventana del navegador (default: visible)",
    )
    parser.add_argument(
        "--sin-reanudar",
        action="store_true",
        default=False,
        help="Empezar desde cero sin usar progreso previo",
    )
    parser.add_argument(
        "--salida",
        type=str,
        default=None,
        help="Ruta del CSV de salida (default: backup/resultados_mesas_TIMESTAMP.csv)",
    )
    args = parser.parse_args()

    deptos = [d.upper() for d in args.deptos] if args.deptos else None
    csv_path = Path(args.salida) if args.salida else None

    logger.info("=" * 60)
    logger.info("Scraper jerárquico de mesas - Congreso 2026")
    logger.info(f"Departamentos: {deptos or 'Todos'}")
    logger.info(f"Headless: {args.headless}")
    logger.info(f"Reanudar progreso: {not args.sin_reanudar}")
    logger.info("=" * 60)

    try:
        csv_generado = asyncio.run(
            scrape_mesas(
                departamentos_objetivo=deptos,
                headless=args.headless,
                reanudar=not args.sin_reanudar,
                csv_path=csv_path,
            )
        )
        logger.info(f"\nCSV final: {csv_generado}")

    except KeyboardInterrupt:
        logger.info("\nDetenido por el usuario (Ctrl+C). El progreso fue guardado.")
        logger.info("Ejecuta de nuevo para reanudar desde donde se detuvo.")
        sys.exit(0)


if __name__ == "__main__":
    main()
