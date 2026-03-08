"""
Scrapper modular - Resultados Electorales Congreso 2026
Extrae resultados por mesa de votacion para analisis de costo por voto
"""

from .scraper import ScraperResultadosElectorales
from .config import cargar_configuracion, CONFIG, CANDIDATOS_CAMARA, CANDIDATO_SENADO
from .config import DEPARTAMENTOS, MUNICIPIOS, PUESTOS_VOTACION
from .main import main

__all__ = [
    'ScraperResultadosElectorales',
    'cargar_configuracion',
    'CONFIG',
    'CANDIDATOS_CAMARA',
    'CANDIDATO_SENADO',
    'DEPARTAMENTOS',
    'MUNICIPIOS',
    'PUESTOS_VOTACION',
    'main',
]
