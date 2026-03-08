"""
Utilidades del scraper de resultados electorales
Logger, normalizacion de nombres y helpers
"""

import logging
import os
import re
from typing import List, Optional


def setup_logger(name: str = 'scrapper', log_file: Optional[str] = None) -> logging.Logger:
    """Configura y retorna el logger del scraper"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if log_file is None:
        log_file = os.path.join(base_dir, 'scraper_electoral.log')

    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setFormatter(formatter)
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


logger = setup_logger()

# Importar funciones de utilidades_scraper si esta disponible
try:
    import sys
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    from utilidades_scraper import buscar_candidato_por_variaciones, normalizar_nombre_candidato
except ImportError:
    def normalizar_nombre_candidato(nombre: str) -> str:
        nombre = nombre.lower()
        nombre = nombre.replace('\u00e1', 'a').replace('\u00e9', 'e').replace('\u00ed', 'i')
        nombre = nombre.replace('\u00f3', 'o').replace('\u00fa', 'u').replace('\u00f1', 'n')
        return ' '.join(nombre.split())

    def buscar_candidato_por_variaciones(nombre_encontrado: str, candidatos_esperados: List[str]) -> Optional[str]:
        nombre_normalizado = normalizar_nombre_candidato(nombre_encontrado)
        for candidato_esperado in candidatos_esperados:
            candidato_normalizado = normalizar_nombre_candidato(candidato_esperado)
            if nombre_normalizado == candidato_normalizado:
                return candidato_esperado
            palabras_encontradas = set(nombre_normalizado.split())
            palabras_esperadas = set(candidato_normalizado.split())
            coincidencias = palabras_encontradas.intersection(palabras_esperadas)
            if len(coincidencias) >= 2:
                return candidato_esperado
        return None


def extraer_numero(texto: str) -> Optional[int]:
    """Extrae numero de un texto"""
    match = re.search(r'(\d{1,3}(?:\.\d{3})*)', texto.replace(',', '.'))
    if match:
        return int(match.group(1).replace('.', ''))
    return None
