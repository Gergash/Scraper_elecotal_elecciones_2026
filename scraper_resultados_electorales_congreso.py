"""
Punto de entrada para el scraper de resultados electorales - Congreso 2026
Redirige a la version modular en scrapper/
"""

import asyncio

from scrapper import main


if __name__ == "__main__":
    asyncio.run(main())
