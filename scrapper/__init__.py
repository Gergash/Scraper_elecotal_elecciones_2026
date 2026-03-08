"""
Scrapper modular - Resultados Electorales Congreso 2026
Extrae resultados por mesa de votacion para analisis de costo por voto
"""

from .scraper import ScraperResultadosElectorales
from .config import cargar_configuracion, CONFIG, CANDIDATOS_CAMARA, CANDIDATO_SENADO
from .lista_conservador import (
    extraer_candidatos_desde_html,
    comparar_jcv_con_lista,
    parsear_y_comparar,
    CandidatoLista,
)
from .config import DEPARTAMENTOS, MUNICIPIOS, PUESTOS_VOTACION
from .main import main

__all__ = [
    'ScraperResultadosElectorales',
    'cargar_configuracion',
    'CONFIG',
    'CANDIDATOS_CAMARA',
    'CANDIDATO_SENADO',
    'extraer_candidatos_desde_html',
    'comparar_jcv_con_lista',
    'parsear_y_comparar',
    'CandidatoLista',
    'DEPARTAMENTOS',
    'MUNICIPIOS',
    'PUESTOS_VOTACION',
    'main',
]
