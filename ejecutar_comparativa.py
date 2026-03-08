#!/usr/bin/env python3
"""
Scraper de comparativa - Lista Partido Conservador al Senado 2026

Consulta periódicamente la URL de resultados de la Registraduría y acumula
los votos de cada candidato en backup/comparativa.csv para graficar el
crecimiento de Juan Camilo Vélez vs los demás miembros de la lista.

Uso:
    python ejecutar_comparativa.py                     # cada 5 min, infinito
    python ejecutar_comparativa.py --intervalo 10      # cada 10 minutos
    python ejecutar_comparativa.py --consultas 20      # máximo 20 consultas
    python ejecutar_comparativa.py --headless          # sin ventana
    python ejecutar_comparativa.py --una-vez           # solo una consulta
"""

import argparse
import asyncio
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from scrapper.comparativa_conservador import run_comparativa, consultar_una_vez, _inicializar_csv, _guardar_consulta
from scrapper.utils import logger


def main():
    parser = argparse.ArgumentParser(
        description="Comparativa votos lista Conservador - Congreso 2026"
    )
    parser.add_argument(
        "--intervalo",
        type=int,
        default=5,
        metavar="MINUTOS",
        help="Minutos entre consultas (default: 5)",
    )
    parser.add_argument(
        "--consultas",
        type=int,
        default=None,
        metavar="N",
        help="Número máximo de consultas (default: infinito)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Ejecutar sin ventana del navegador",
    )
    parser.add_argument(
        "--una-vez",
        action="store_true",
        default=False,
        help="Hacer solo una consulta y salir",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Comparativa lista Conservador - Congreso 2026")
    logger.info(f"URL: https://resultados.registraduria.gov.co/resultados/0/00/0?s=resultados-votes")
    logger.info(f"CSV: backup/comparativa.csv")
    if args.una_vez:
        logger.info("Modo: una sola consulta")
    else:
        logger.info(f"Intervalo: {args.intervalo} minutos")
        logger.info(f"Consultas: {'Infinitas (Ctrl+C para detener)' if not args.consultas else args.consultas}")
    logger.info("=" * 60)

    try:
        if args.una_vez:
            _inicializar_csv()
            candidatos = asyncio.run(consultar_una_vez(headless=args.headless))
            if candidatos:
                filas = _guardar_consulta(candidatos)
                logger.info(f"\n{filas} candidatos guardados en backup/comparativa.csv")
                for c in sorted(candidatos, key=lambda x: x.votos, reverse=True):
                    marca = " ← JCV" if ("JUAN" in c.nombre.upper() and "VELEZ" in c.nombre.upper()) else ""
                    logger.info(f"  #{c.posicion:2d} {c.nombre:<45} {c.votos:>8,} votos{marca}")
            else:
                logger.error("No se obtuvieron datos. Verifica que la página tenga resultados publicados.")
        else:
            asyncio.run(
                run_comparativa(
                    intervalo_minutos=args.intervalo,
                    max_consultas=args.consultas,
                    headless=args.headless,
                )
            )
    except KeyboardInterrupt:
        logger.info("\nDetenido por el usuario. Los datos guardados en backup/comparativa.csv están disponibles.")
        sys.exit(0)


if __name__ == "__main__":
    main()
