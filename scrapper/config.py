"""
Configuracion del scraper de resultados electorales
Carga y expone configuracion desde config_candidatos.json
"""

import json
import logging
import os
from typing import Dict

logger = logging.getLogger(__name__)


def _get_base_dir() -> str:
    """Directorio base: Web_Scrapping (parente de scrapper)"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cargar_configuracion(config_path: str = 'config_candidatos.json') -> Dict:
    """Carga la configuracion desde archivo JSON"""
    try:
        base_dir = _get_base_dir()
        config_file = os.path.join(base_dir, config_path)

        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        logger.info(f"Configuracion cargada desde {config_file}")
        return config
    except FileNotFoundError:
        logger.warning(f"Archivo de configuracion no encontrado: {config_path}")
        logger.info("Usando configuracion por defecto")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error parseando JSON: {e}")
        return {}


# Cargar configuracion al importar
CONFIG = cargar_configuracion()

# Extraer datos de configuracion
CANDIDATOS_CAMARA: Dict[str, list] = {}
if CONFIG.get('candidatos_camara'):
    for depto, candidatos in CONFIG['candidatos_camara'].items():
        CANDIDATOS_CAMARA[depto] = [
            c['nombre_completo'] if isinstance(c, dict) else c
            for c in candidatos
        ]
else:
    CANDIDATOS_CAMARA = {
        'VALLE': [
            'Rigo Vega Cartago', 'Adriana Daraviña', 'Luz Angela Pulido',
            'Liliana Solano', 'Alvaro Pollo Cardona', 'Jorge Andres Gonzales',
            'Cristian Hernandez', 'Cristian Viveros'
        ],
        'RISARALDA': ['Atenea Castro'],
        'CALDAS': ['Yuliana Giraldo', 'Juan Esteban Tejada']
    }

CANDIDATO_SENADO = CONFIG.get('candidato_senado', {}).get('nombre_completo', 'Juan Camilo Velez Londoño')

DEPARTAMENTOS = list(CANDIDATOS_CAMARA.keys())

PUESTOS_VOTACION: Dict[str, int] = {}
MUNICIPIOS: Dict[str, list] = {}
if CONFIG.get('departamentos'):
    for depto, info in CONFIG['departamentos'].items():
        PUESTOS_VOTACION[depto] = info.get('puestos_votacion', 0)
        MUNICIPIOS[depto] = info.get('municipios', [])
else:
    PUESTOS_VOTACION = {'VALLE': 1152, 'RISARALDA': 226, 'CALDAS': 339}
    MUNICIPIOS = {
        'VALLE': [
            'Andalucía', 'Buga', 'Bugalagrande', 'Calima-El Darién', 'El Cerrito',
            'Ginebra', 'Guacarí', 'Restrepo', 'Riofrío', 'San Pedro', 'Trujillo',
            'Yotoco', 'Alcalá', 'Ansermanuevo', 'Argelia', 'Bolívar', 'Caicedonia',
            'Cartago', 'El Águila', 'El Cairo', 'El Dovio', 'La Unión',
            'La Victoria', 'Obando', 'Roldanillo', 'Sevilla', 'Toro', 'Ulloa',
            'Versalles', 'Zarzal', 'Cali', 'Candelaria', 'Jamundí', 'La Cumbre',
            'Palmira', 'Pradera', 'Vijes', 'Yumbo', 'Buenaventura', 'Dagua', 'Florida', 'Tuluá'
        ],
        'RISARALDA': [
            'Pereira', 'Dosquebradas', 'Santa Rosa de Cabal', 'Marsella', 'Apía',
            'Balboa', 'Belén de Umbría', 'Guática', 'La Celia', 'La Virginia',
            'Quinchía', 'Santuario', 'Mistrató', 'Pueblo Rico'
        ],
        'CALDAS': [
            'Manizales', 'Aguadas', 'Anserma', 'Aranzazu', 'Belalcázar', 'Chinchiná',
            'Filadelfia', 'La Dorada', 'La Merced', 'Manzanares', 'Marmato',
            'Marquetalia', 'Marulanda', 'Neira', 'Norcasia', 'Pácora', 'Palestina',
            'Pensilvania', 'Riosucio', 'Risaralda', 'Salamina', 'Samaná',
            'San José', 'Supía', 'Victoria', 'Villamaría', 'Viterbo'
        ]
    }
