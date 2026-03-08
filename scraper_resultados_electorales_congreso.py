"""
Scraper de Resultados Electorales - Congreso de la República 2026
Extrae resultados por mesa de votación para análisis de costo por voto
"""

import asyncio
import pandas as pd
import requests
from playwright.async_api import async_playwright
import json
import time
from typing import Dict, List, Optional
import logging
from datetime import datetime
import re
import os

# Importar utilidades (manejar si no están disponibles)
try:
    from utilidades_scraper import buscar_candidato_por_variaciones, normalizar_nombre_candidato
except ImportError:
    # Funciones auxiliares si no se puede importar
    def normalizar_nombre_candidato(nombre: str) -> str:
        nombre = nombre.lower()
        nombre = nombre.replace('á', 'a').replace('é', 'e').replace('í', 'i')
        nombre = nombre.replace('ó', 'o').replace('ú', 'u').replace('ñ', 'n')
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

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper_electoral.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# CARGA DE CONFIGURACIÓN DESDE JSON
# ============================================================================

def cargar_configuracion(config_path: str = 'config_candidatos.json') -> Dict:
    """Carga la configuración desde archivo JSON"""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_file = os.path.join(script_dir, config_path)
        
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        logger.info(f"Configuración cargada desde {config_file}")
        return config
    except FileNotFoundError:
        logger.warning(f"Archivo de configuración no encontrado: {config_path}")
        logger.info("Usando configuración por defecto")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error parseando JSON: {e}")
        return {}

# Cargar configuración
CONFIG = cargar_configuracion()

# Extraer datos de configuración
CANDIDATOS_CAMARA = {}
if CONFIG.get('candidatos_camara'):
    for depto, candidatos in CONFIG['candidatos_camara'].items():
        CANDIDATOS_CAMARA[depto] = [
            c['nombre_completo'] if isinstance(c, dict) else c 
            for c in candidatos
        ]
else:
    # Configuración por defecto si no hay JSON
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

# Puestos de votación y municipios desde configuración
PUESTOS_VOTACION = {}
MUNICIPIOS = {}
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

# ============================================================================
# CLASE PRINCIPAL DEL SCRAPER
# ============================================================================

class ScraperResultadosElectorales:
    """
    Scraper para extraer resultados electorales del Congreso 2026
    por mesa de votación y calcular correlaciones con votos al Senado
    """
    
    def __init__(self, headless: Optional[bool] = None, config: Optional[Dict] = None):
        # Usar configuración del JSON si está disponible
        config_scraper = CONFIG.get('configuracion_scraper', {})
        self.headless = headless if headless is not None else config_scraper.get('headless', False)
        self.timeout_pagina = config_scraper.get('timeout_pagina', 30000)
        self.delay_requests = config_scraper.get('delay_entre_requests', 2)
        self.intentos_reintento = config_scraper.get('intentos_reintento', 3)
        
        self.base_url_registraduria = "https://wapp.registraduria.gov.co/electoral/2026/congreso-de-la-republica/"
        self.base_url_e14 = None  # Se determinará cuando se publiquen los resultados
        self.base_url_escrutinios = None  # Se determinará cuando se publiquen los resultados
        self.resultados_camara = {}
        self.resultados_senado = {}
        self.resultados_correlacion = []
        
    async def detectar_urls_resultados(self):
        """
        Detecta las URLs donde se publicarán los resultados electorales
        Basado en patrones históricos de la Registraduría
        """
        logger.info("Detectando URLs de resultados electorales...")
        
        # Patrones posibles basados en elecciones anteriores
        posibles_urls = [
            "https://e14_congreso_2026.registraduria.gov.co/",
            "https://congreso2026.registraduria.gov.co/",
            "https://escrutinios2026.registraduria.gov.co/",
            "https://resultados2026.registraduria.gov.co/",
            f"{self.base_url_registraduria}resultados/",
            f"{self.base_url_registraduria}escrutinios/",
            f"{self.base_url_registraduria}preconteo/",
        ]
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context()
            page = await context.new_page()
            
            for url in posibles_urls:
                try:
                    response = await page.goto(url, timeout=10000, wait_until="domcontentloaded")
                    if response and response.status == 200:
                        logger.info(f"URL activa encontrada: {url}")
                        # Verificar si contiene datos de resultados
                        content = await page.content()
                        if any(keyword in content.lower() for keyword in ['resultado', 'escrutinio', 'mesa', 'votación']):
                            self.base_url_e14 = url
                            await browser.close()
                            return url
                except Exception as e:
                    logger.debug(f"❌ URL no disponible: {url} - {str(e)}")
                    continue
            
            await browser.close()
            logger.warning("No se encontraron URLs activas. Los resultados aún no están publicados.")
            return None
    
    async def extraer_resultados_api(self, departamento: str, tipo: str = 'camara') -> List[Dict]:
        """
        Intenta extraer resultados desde una API o endpoint JSON
        """
        logger.info(f"Intentando extraer resultados desde API para {departamento} - {tipo}")
        
        # Posibles endpoints de API
        posibles_endpoints = [
            f"{self.base_url_registraduria}api/resultados/{departamento.lower()}/{tipo}",
            f"{self.base_url_registraduria}api/escrutinios/{departamento.lower()}",
            f"https://resultados2026.registraduria.gov.co/api/{departamento.lower()}/{tipo}",
        ]
        
        resultados = []
        
        for endpoint in posibles_endpoints:
            try:
                response = requests.get(endpoint, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Datos obtenidos desde API: {endpoint}")
                    return self._procesar_datos_api(data, departamento, tipo)
            except Exception as e:
                logger.debug(f"❌ Endpoint no disponible: {endpoint} - {str(e)}")
                continue
        
        return resultados
    
    def _procesar_datos_api(self, data: Dict, departamento: str, tipo: str) -> List[Dict]:
        """
        Procesa datos obtenidos desde una API
        """
        resultados = []
        
        # Estructura esperada: data['resultados'][departamento][municipio][puesto][mesa]
        if isinstance(data, dict):
            # Intentar diferentes estructuras posibles
            if 'resultados' in data:
                resultados_raw = data['resultados']
            elif 'escrutinios' in data:
                resultados_raw = data['escrutinios']
            else:
                resultados_raw = data
            
            # Procesar según estructura
            for municipio, puestos in resultados_raw.items():
                if isinstance(puestos, dict):
                    for puesto, mesas in puestos.items():
                        if isinstance(mesas, dict):
                            for mesa_num, votos in mesas.items():
                                resultado = {
                                    'departamento': departamento,
                                    'municipio': municipio,
                                    'puesto_votacion': puesto,
                                    'mesa': mesa_num,
                                    'tipo': tipo,
                                    'votos': votos
                                }
                                resultados.append(resultado)
        
        return resultados
    
    async def extraer_resultados_e14(self, departamento: str, municipio: str, 
                                     puesto: str, mesa: str) -> Optional[Dict]:
        """
        Extrae resultados desde formularios E-14 escaneados
        """
        logger.debug(f"📄 Extrayendo E-14: {departamento} - {municipio} - {puesto} - Mesa {mesa}")
        
        if not self.base_url_e14:
            return None
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context()
            page = await context.new_page()
            
            try:
                # Construir URL del E-14
                url_e14 = f"{self.base_url_e14}?depto={departamento}&municipio={municipio}&puesto={puesto}&mesa={mesa}"
                await page.goto(url_e14, timeout=15000, wait_until="domcontentloaded")
                
                # Esperar a que cargue el formulario
                await page.wait_for_timeout(2000)
                
                # Extraer datos del formulario E-14
                # Esto dependerá de la estructura HTML real cuando se publique
                resultados = {}
                
                # Buscar tabla de resultados o elementos con datos
                tablas = await page.query_selector_all('table')
                if tablas:
                    for tabla in tablas:
                        filas = await tabla.query_selector_all('tr')
                        for fila in filas:
                            celdas = await fila.query_selector_all('td, th')
                            if len(celdas) >= 2:
                                candidato = await celdas[0].inner_text()
                                votos_text = await celdas[1].inner_text()
                                votos = self._extraer_numero(votos_text)
                                if candidato and votos is not None:
                                    resultados[candidato.strip()] = votos
                
                # Si no hay tablas, buscar divs o spans con datos
                if not resultados:
                    elementos_votos = await page.query_selector_all('[class*="voto"], [class*="resultado"], [id*="voto"]')
                    for elemento in elementos_votos:
                        texto = await elemento.inner_text()
                        # Intentar extraer nombre de candidato y votos
                        match = re.search(r'(.+?)\s*:\s*(\d+)', texto)
                        if match:
                            candidato = match.group(1).strip()
                            votos = int(match.group(2))
                            resultados[candidato] = votos
                
                await browser.close()
                
                if resultados:
                    return {
                        'departamento': departamento,
                        'municipio': municipio,
                        'puesto_votacion': puesto,
                        'mesa': mesa,
                        'resultados': resultados
                    }
                
            except Exception as e:
                logger.error(f"❌ Error extrayendo E-14: {str(e)}")
                await browser.close()
                return None
    
    def _extraer_numero(self, texto: str) -> Optional[int]:
        """Extrae número de un texto"""
        match = re.search(r'(\d{1,3}(?:\.\d{3})*)', texto.replace(',', '.'))
        if match:
            return int(match.group(1).replace('.', ''))
        return None
    
    async def extraer_resultados_csv(self, departamento: str) -> pd.DataFrame:
        """
        Intenta descargar y procesar CSV de resultados desde CEDAE o Registraduría
        """
        logger.info(f"Intentando descargar CSV de resultados para {departamento}")
        
        posibles_urls_csv = [
            f"{self.base_url_registraduria}descargas/resultados_{departamento.lower()}.csv",
            f"https://cedae.datasketch.co/datos-democracia/resultados-electorales/descarga-los-datos/",
            f"https://resultados2026.registraduria.gov.co/csv/{departamento.lower()}.csv",
        ]
        
        for url in posibles_urls_csv:
            try:
                if 'cedae' in url:
                    # CEDAE requiere interacción con la página
                    return await self._descargar_csv_cedae(departamento)
                else:
                    response = requests.get(url, timeout=30)
                    if response.status_code == 200:
                        # Guardar CSV temporalmente
                        filename = f"resultados_temp_{departamento}.csv"
                        with open(filename, 'wb') as f:
                            f.write(response.content)
                        
                        df = pd.read_csv(filename, encoding='utf-8')
                        logger.info(f"CSV descargado y procesado: {len(df)} registros")
                        return df
            except Exception as e:
                logger.debug(f"❌ CSV no disponible: {url} - {str(e)}")
                continue
        
        return pd.DataFrame()
    
    async def _descargar_csv_cedae(self, departamento: str) -> pd.DataFrame:
        """
        Descarga CSV desde la plataforma CEDAE usando Playwright
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context()
            page = await context.new_page()
            
            try:
                await page.goto("https://cedae.datasketch.co/datos-democracia/resultados-electorales/descarga-los-datos/")
                await page.wait_for_timeout(3000)
                
                # Seleccionar año 2026
                await page.select_option('select[name="año"], select[id="año"]', '2026')
                await page.wait_for_timeout(1000)
                
                # Seleccionar nivel "camara" o "senado"
                # Esto requiere interacción con los filtros
                
                # Esperar a que se genere el CSV y descargarlo
                # (implementar según la estructura real de la página)
                
                await browser.close()
                return pd.DataFrame()
            except Exception as e:
                logger.error(f"❌ Error descargando desde CEDAE: {str(e)}")
                await browser.close()
                return pd.DataFrame()
    
    async def extraer_resultados_por_departamento(self, departamento: str):
        """
        Extrae todos los resultados para un departamento usando múltiples métodos
        """
        logger.info(f"Extrayendo resultados para {departamento}...")
        
        # Método 1: Intentar API
        resultados_api = await self.extraer_resultados_api(departamento, 'camara')
        if resultados_api:
            self.resultados_camara[departamento] = resultados_api
            logger.info(f"Resultados obtenidos desde API: {len(resultados_api)} registros")
            return
        
        # Método 2: Intentar CSV
        df_csv = await self.extraer_resultados_csv(departamento)
        if not df_csv.empty:
            self.resultados_camara[departamento] = df_csv.to_dict('records')
            logger.info(f"Resultados obtenidos desde CSV: {len(df_csv)} registros")
            return
        
        # Método 3: Extraer E-14 por mesa (más lento pero más completo)
        logger.info(f"📄 Extrayendo resultados desde formularios E-14 (puede tardar)...")
        resultados_e14 = []
        
        municipios = MUNICIPIOS.get(departamento, [])
        for municipio in municipios:
            # En una implementación real, necesitarías iterar sobre puestos y mesas
            # Por ahora, esto es un esqueleto que se completará cuando se publiquen los resultados
            logger.info(f"  Procesando {municipio}...")
            # resultados_municipio = await self._extraer_todas_mesas_municipio(departamento, municipio)
            # resultados_e14.extend(resultados_municipio)
        
        if resultados_e14:
            self.resultados_camara[departamento] = resultados_e14
    
    async def extraer_resultados_senado(self, departamento: str):
        """
        Extrae resultados de Juan Camilo Velez Londoño al Senado por departamento
        """
        logger.info(f"Extrayendo resultados al Senado para {departamento}...")
        
        # Similar a extraer_resultados_por_departamento pero para Senado
        resultados_api = await self.extraer_resultados_api(departamento, 'senado')
        if resultados_api:
            # Filtrar solo votos de Juan Camilo Velez Londoño
            resultados_juan = [
                r for r in resultados_api 
                if CANDIDATO_SENADO.lower() in str(r.get('candidato', '')).lower()
            ]
            self.resultados_senado[departamento] = resultados_juan
            return
        
        # Si no hay API, usar otros métodos similares
        logger.warning(f"Resultados al Senado no disponibles aún para {departamento}")
    
    def calcular_correlacion_votos(self, departamento: str):
        """
        Calcula la correlación entre votos de candidatos a Cámara y votos de Juan al Senado
        por mesa de votación
        """
        logger.info(f"Calculando correlación de votos para {departamento}...")
        
        resultados_camara = self.resultados_camara.get(departamento, [])
        resultados_senado = self.resultados_senado.get(departamento, [])
        
        if not resultados_camara or not resultados_senado:
            logger.warning(f"Faltan datos para calcular correlación en {departamento}")
            return
        
        # Crear diccionario de resultados al Senado por mesa
        senado_por_mesa = {}
        for resultado in resultados_senado:
            key = f"{resultado.get('municipio')}_{resultado.get('puesto_votacion')}_{resultado.get('mesa')}"
            senado_por_mesa[key] = resultado.get('votos', 0)
        
        # Calcular correlación por mesa
        for resultado_camara in resultados_camara:
            municipio = resultado_camara.get('municipio', '')
            puesto = resultado_camara.get('puesto_votacion', '')
            mesa = resultado_camara.get('mesa', '')
            key_mesa = f"{municipio}_{puesto}_{mesa}"
            
            votos_senado_juan = senado_por_mesa.get(key_mesa, 0)
            
            # Obtener votos de cada candidato a Cámara en esta mesa
            candidatos_votos = resultado_camara.get('resultados', {})
            if isinstance(candidatos_votos, dict):
                for candidato, votos_camara in candidatos_votos.items():
                    # Verificar si es uno de nuestros candidatos
                    candidatos_departamento = CANDIDATOS_CAMARA.get(departamento, [])
                    if any(c.lower() in candidato.lower() for c in candidatos_departamento):
                        correlacion = {
                            'departamento': departamento,
                            'municipio': municipio,
                            'puesto_votacion': puesto,
                            'mesa': mesa,
                            'candidato_camara': candidato,
                            'votos_camara': votos_camara,
                            'votos_senado_juan': votos_senado_juan,
                            'ratio_correlacion': votos_camara / max(votos_senado_juan, 1) if votos_senado_juan > 0 else 0,
                            'fecha_extraccion': datetime.now().isoformat()
                        }
                        self.resultados_correlacion.append(correlacion)
    
    def calcular_costo_por_voto(self, inversiones: Dict[str, float]) -> pd.DataFrame:
        """
        Calcula el costo por voto para cada candidato basado en las inversiones
        """
        logger.info("Calculando costo por voto...")
        
        if not self.resultados_correlacion:
            logger.warning("No hay datos de correlación para calcular costo por voto")
            return pd.DataFrame()
        
        df = pd.DataFrame(self.resultados_correlacion)
        
        # Agregar inversiones
        df['inversion'] = df['candidato_camara'].map(inversiones).fillna(0)
        
        # Calcular métricas por candidato
        resumen = df.groupby('candidato_camara').agg({
            'votos_camara': 'sum',
            'votos_senado_juan': 'sum',
            'inversion': 'first',
            'ratio_correlacion': 'mean'
        }).reset_index()
        
        resumen['costo_por_voto'] = resumen['inversion'] / resumen['votos_camara'].replace(0, 1)
        resumen['costo_por_voto_correlacionado'] = resumen['inversion'] / resumen['votos_senado_juan'].replace(0, 1)
        resumen['aporte_relativo'] = (resumen['votos_senado_juan'] / resumen['votos_senado_juan'].sum()) * 100
        
        return resumen.sort_values('aporte_relativo', ascending=False)
    
    def generar_csv_final(self, inversiones: Dict[str, float], 
                         filename: str = 'resultados_costo_por_voto.csv'):
        """
        Genera el CSV final con todos los resultados y análisis
        """
        logger.info(f"Generando CSV final: {filename}")
        
        if not self.resultados_correlacion:
            logger.warning("No hay datos para generar CSV")
            return
        
        df_detalle = pd.DataFrame(self.resultados_correlacion)
        df_resumen = self.calcular_costo_por_voto(inversiones)
        
        # Agregar inversiones al detalle
        df_detalle['inversion_candidato'] = df_detalle['candidato_camara'].map(inversiones).fillna(0)
        df_detalle['costo_por_voto'] = df_detalle['inversion_candidato'] / df_detalle['votos_camara'].replace(0, 1)
        
        # Guardar CSV detallado
        df_detalle.to_csv(filename, index=False, encoding='utf-8-sig')
        logger.info(f"CSV detallado guardado: {filename} ({len(df_detalle)} registros)")
        
        # Guardar resumen
        filename_resumen = filename.replace('.csv', '_resumen.csv')
        df_resumen.to_csv(filename_resumen, index=False, encoding='utf-8-sig')
        logger.info(f"CSV resumen guardado: {filename_resumen}")
        
        return df_detalle, df_resumen
    
    async def ejecutar_scraping_completo(self, inversiones: Dict[str, float]):
        """
        Ejecuta el proceso completo de scraping y análisis
        """
        logger.info("Iniciando scraping completo de resultados electorales...")
        
        # Paso 1: Detectar URLs de resultados
        url_detectada = await self.detectar_urls_resultados()
        if not url_detectada:
            logger.warning("Los resultados aún no están publicados. El scraper está listo para cuando se publiquen.")
            logger.info("Sugerencia: Ejecutar este script después del 8 de marzo de 2026")
            return
        
        # Paso 2: Extraer resultados por departamento
        for departamento in DEPARTAMENTOS:
            await self.extraer_resultados_por_departamento(departamento)
            await self.extraer_resultados_senado(departamento)
            self.calcular_correlacion_votos(departamento)
            await asyncio.sleep(2)  # Pausa entre departamentos
        
        # Paso 3: Generar CSV final
        self.generar_csv_final(inversiones)
        
        logger.info("Scraping completo finalizado")


# ============================================================================
# FUNCIÓN PRINCIPAL
# ============================================================================

async def main():
    """
    Función principal para ejecutar el scraper
    """
    # Cargar inversiones desde configuración
    INVERSIONES = CONFIG.get('inversiones', {})
    
    # Si no hay inversiones en el JSON, usar valores por defecto
    if not INVERSIONES or all(v == 0 for v in INVERSIONES.values()):
        logger.warning("No se encontraron inversiones en la configuración")
        logger.info("Por favor, edita config_candidatos.json y agrega las inversiones reales")
        
        # Crear diccionario con todos los candidatos
        INVERSIONES = {}
        for depto, candidatos in CANDIDATOS_CAMARA.items():
            for candidato in candidatos:
                INVERSIONES[candidato] = 0.0
    
    logger.info(f"Inversiones cargadas para {len(INVERSIONES)} candidatos")
    
    scraper = ScraperResultadosElectorales(headless=None)  # Usará configuración del JSON
    await scraper.ejecutar_scraping_completo(INVERSIONES)


if __name__ == "__main__":
    asyncio.run(main())
