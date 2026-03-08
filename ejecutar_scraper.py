#!/usr/bin/env python3
"""
Punto de entrada para iniciar el scraper en modo paralelo.

Caracteristicas:
- Timeout de 10 segundos por pagina
- Múltiples ventanas/pestañas en paralelo
- Loop: ejecutar -> guardar en backup -> refrescar -> repetir
- Todos los archivos generados se guardan en ./backup

Uso:
    python ejecutar_scraper.py [--ciclos N] [--urls URL1,URL2,...]

    --ciclos N     : numero de ciclos (default: infinito, Ctrl+C para detener)
    --urls         : URLs separadas por coma (override config)
"""
import argparse
import asyncio
import sys
from pathlib import Path

# Agregar directorio al path
BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from scrapper.config import cargar_configuracion
from scrapper.runner_paralelo import run_loop_continuo, obtener_urls_desde_config
from scrapper.utils import logger


def main():
    parser = argparse.ArgumentParser(description="Scraper paralelo - resultados electorales / lista conservador")
    parser.add_argument("--ciclos", type=int, default=None,
                        help="Numero maximo de ciclos (default: infinito)")
    parser.add_argument("--urls", type=str, default=None,
                        help="URLs separadas por coma (override config)")
    parser.add_argument("--pausa", type=int, default=5,
                        help="Segundos de pausa entre ciclos (default: 5)")
    args = parser.parse_args()

    # Cargar URLs
    if args.urls:
        urls = [u.strip() for u in args.urls.split(",") if u.strip()]
        logger.info(f"URLs desde argumento: {len(urls)}")
    else:
        urls = obtener_urls_desde_config()
        if not urls:
            logger.error("No hay URLs configuradas.")
            logger.info("Agrega 'urls_scraper' en config_candidatos.json o usa --urls URL1,URL2")
            logger.info("Ejemplo: python ejecutar_scraper.py --urls https://ejemplo.com/resultados")
            return 1

    logger.info(f"URLs a scrapear: {urls}")

    try:
        asyncio.run(run_loop_continuo(
            urls=urls,
            max_ciclos=args.ciclos,
            pausa_entre_ciclos=args.pausa
        ))
    except KeyboardInterrupt:
        logger.info("Detenido por el usuario (Ctrl+C)")
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
