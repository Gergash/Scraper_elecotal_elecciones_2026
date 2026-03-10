#!/usr/bin/env python3
"""
Script maestro: ejecuta los tres scrapers en paralelo como tareas asyncio.

1. Runner paralelo (ejecutar_scraper): 4 URLs en pestañas, ciclos continuos
2. Comparativa (ejecutar_comparativa): lista Conservador, append a comparativa.csv
3. Scraper mesas (ejecutar_scraper_mesas): navegación jerárquica E-14

Uso:
    python ejecutar_todo.py
    python ejecutar_todo.py --ciclos 10 --consultas 20
    python ejecutar_todo.py --headless
"""

import argparse
import asyncio
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from scrapper.config import CONFIG
from scrapper.runner_paralelo import run_loop_continuo, obtener_urls_desde_config
from scrapper.comparativa_conservador import run_comparativa
from scrapper.scraper_mesas import scrape_mesas
from scrapper.scraper_divulgacion_e14 import scrape_divulgacion_e14
from scrapper.utils import logger



async def _tarea_runner(ciclos=None, pausa=5):
    """Tarea: runner paralelo (4 URLs)"""
    urls = obtener_urls_desde_config()
    if not urls:
        logger.warning("[Runner] No hay URLs en config. Se omite.")
        return
    await run_loop_continuo(urls=urls, max_ciclos=ciclos, pausa_entre_ciclos=pausa)


async def _tarea_comparativa(consultas=None, intervalo=5, headless=False):
    """Tarea: comparativa periódica"""
    await run_comparativa(
        intervalo_minutos=intervalo,
        max_consultas=consultas,
        headless=headless,
    )


async def _tarea_mesas(deptos=None, headless=False, reanudar=True):
    """Tarea: scraper jerárquico de mesas"""
    await scrape_mesas(
        departamentos_objetivo=deptos,
        headless=headless,
        reanudar=reanudar,
        csv_path=None,
    )


async def _tarea_divulgacion(headless=False, descargar_e14=True):
    """Tarea: scraper divulgacione14congreso (SENADO/CAMARA, págs 01/03/04) + descarga E14 por mesa"""
    await scrape_divulgacion_e14(
        corporaciones=["SENADO", "CAMARA"],
        departamentos_objetivo=None,  # usa VALLE, CALDAS, RISARALDA de config
        paginas=["01", "03", "04"],
        headless=headless,
        descargar_e14=descargar_e14,
    )


async def main(args):
    logger.info("=" * 60)
    logger.info("SCRIPT MAESTRO - Scrapers electorales")
    logger.info("  1. Runner paralelo (4 URLs)")
    logger.info("  2. Comparativa (lista Conservador)")
    logger.info("  3. Scraper mesas (E-14 jerárquico)")
    logger.info("  4. Scraper divulgación E14 (VALLE, CALDAS, RISARALDA)")
    logger.info("=" * 60)

    tareas = [
        asyncio.create_task(_tarea_runner(ciclos=args.ciclos, pausa=args.pausa)),
        asyncio.create_task(_tarea_comparativa(
            consultas=args.consultas,
            intervalo=args.intervalo,
            headless=args.headless,
        )),
        asyncio.create_task(_tarea_mesas(
            deptos=args.deptos,
            headless=args.headless,
            reanudar=not args.sin_reanudar,
        )),
    ]
    if not getattr(args, "sin_divulgacion", False):
        tareas.append(asyncio.create_task(_tarea_divulgacion(
            headless=args.headless,
            descargar_e14=not getattr(args, "sin_descargar_e14", False),
        )))

    try:
        await asyncio.gather(*tareas)
    except asyncio.CancelledError:
        logger.info("Tareas canceladas.")
    except Exception as e:
        logger.error(f"Error: {e}")
        for t in tareas:
            t.cancel()
        try:
            await asyncio.gather(*tareas)
        except asyncio.CancelledError:
            pass


def run():
    parser = argparse.ArgumentParser(description="Ejecuta los 3 scrapers en paralelo")
    parser.add_argument("--ciclos", type=int, default=None, help="Máx ciclos del runner (default: infinito)")
    parser.add_argument("--consultas", type=int, default=None, help="Máx consultas comparativa (default: infinito)")
    parser.add_argument("--intervalo", type=int, default=5, help="Minutos entre consultas comparativa (default: 5)")
    parser.add_argument("--pausa", type=int, default=5, help="Segundos entre ciclos del runner (default: 5)")
    parser.add_argument("--deptos", nargs="+", default=None, help="Departamentos para mesas (default: todos)")
    parser.add_argument("--headless", action="store_true", help="Navegador sin ventana")
    parser.add_argument("--sin-reanudar", action="store_true", help="Mesas: empezar desde cero")
    parser.add_argument("--sin-divulgacion", action="store_true", help="No ejecutar scraper divulgación E14")
    parser.add_argument("--sin-descargar-e14", action="store_true", help="Divulgación E14: solo tabla, no descargar PDFs por mesa")
    args = parser.parse_args()

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        logger.info("\nDetenido por el usuario (Ctrl+C).")


if __name__ == "__main__":
    run()
