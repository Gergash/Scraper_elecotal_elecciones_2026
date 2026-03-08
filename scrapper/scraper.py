"""
Clase principal del scraper de resultados electorales
Extrae resultados por mesa de votacion y calcula correlaciones con votos al Senado
"""

import asyncio
import re
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
import requests
from playwright.async_api import async_playwright

from .config import CONFIG, CANDIDATOS_CAMARA, CANDIDATO_SENADO, MUNICIPIOS, DEPARTAMENTOS
from .utils import logger, extraer_numero


class ScraperResultadosElectorales:
    """
    Scraper para extraer resultados electorales del Congreso 2026
    por mesa de votacion y calcular correlaciones con votos al Senado
    """

    def __init__(self, headless: Optional[bool] = None, config: Optional[Dict] = None):
        config_scraper = CONFIG.get('configuracion_scraper', {})
        self.headless = headless if headless is not None else config_scraper.get('headless', False)
        self.timeout_pagina = config_scraper.get('timeout_pagina', 30000)
        self.delay_requests = config_scraper.get('delay_entre_requests', 2)
        self.intentos_reintento = config_scraper.get('intentos_reintento', 3)

        self.base_url_registraduria = "https://wapp.registraduria.gov.co/electoral/2026/congreso-de-la-republica/"
        self.base_url_e14 = None
        self.base_url_escrutinios = None
        self.resultados_camara = {}
        self.resultados_senado = {}
        self.resultados_correlacion = []

    async def detectar_urls_resultados(self):
        """Detecta las URLs donde se publicaran los resultados electorales"""
        logger.info("Detectando URLs de resultados electorales...")

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
                        content = await page.content()
                        if any(kw in content.lower() for kw in ['resultado', 'escrutinio', 'mesa', 'votacion']):
                            self.base_url_e14 = url
                            await browser.close()
                            return url
                except Exception as e:
                    logger.debug(f"URL no disponible: {url} - {str(e)}")
                    continue

            await browser.close()
            logger.warning("No se encontraron URLs activas. Los resultados aun no estan publicados.")
            return None

    async def extraer_resultados_api(self, departamento: str, tipo: str = 'camara') -> List[Dict]:
        """Intenta extraer resultados desde una API o endpoint JSON"""
        logger.info(f"Intentando extraer resultados desde API para {departamento} - {tipo}")

        posibles_endpoints = [
            f"{self.base_url_registraduria}api/resultados/{departamento.lower()}/{tipo}",
            f"{self.base_url_registraduria}api/escrutinios/{departamento.lower()}",
            f"https://resultados2026.registraduria.gov.co/api/{departamento.lower()}/{tipo}",
        ]

        for endpoint in posibles_endpoints:
            try:
                response = requests.get(endpoint, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Datos obtenidos desde API: {endpoint}")
                    return self._procesar_datos_api(data, departamento, tipo)
            except Exception as e:
                logger.debug(f"Endpoint no disponible: {endpoint} - {str(e)}")
                continue

        return []

    def _procesar_datos_api(self, data: Dict, departamento: str, tipo: str) -> List[Dict]:
        """Procesa datos obtenidos desde una API"""
        resultados = []

        if isinstance(data, dict):
            resultados_raw = data.get('resultados') or data.get('escrutinios') or data

            for municipio, puestos in resultados_raw.items():
                if isinstance(puestos, dict):
                    for puesto, mesas in puestos.items():
                        if isinstance(mesas, dict):
                            for mesa_num, votos in mesas.items():
                                resultados.append({
                                    'departamento': departamento,
                                    'municipio': municipio,
                                    'puesto_votacion': puesto,
                                    'mesa': mesa_num,
                                    'tipo': tipo,
                                    'votos': votos
                                })

        return resultados

    async def extraer_resultados_e14(self, departamento: str, municipio: str,
                                     puesto: str, mesa: str) -> Optional[Dict]:
        """Extrae resultados desde formularios E-14 escaneados"""
        logger.debug(f"Extrayendo E-14: {departamento} - {municipio} - {puesto} - Mesa {mesa}")

        if not self.base_url_e14:
            return None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                url_e14 = f"{self.base_url_e14}?depto={departamento}&municipio={municipio}&puesto={puesto}&mesa={mesa}"
                await page.goto(url_e14, timeout=15000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                resultados = {}
                tablas = await page.query_selector_all('table')
                if tablas:
                    for tabla in tablas:
                        filas = await tabla.query_selector_all('tr')
                        for fila in filas:
                            celdas = await fila.query_selector_all('td, th')
                            if len(celdas) >= 2:
                                candidato = await celdas[0].inner_text()
                                votos_text = await celdas[1].inner_text()
                                votos = extraer_numero(votos_text)
                                if candidato and votos is not None:
                                    resultados[candidato.strip()] = votos

                if not resultados:
                    elementos_votos = await page.query_selector_all(
                        '[class*="voto"], [class*="resultado"], [id*="voto"]'
                    )
                    for elemento in elementos_votos:
                        texto = await elemento.inner_text()
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
                logger.error(f"Error extrayendo E-14: {str(e)}")
                await browser.close()
                return None

        return None

    async def extraer_resultados_csv(self, departamento: str) -> pd.DataFrame:
        """Intenta descargar y procesar CSV de resultados desde CEDAE o Registraduria"""
        logger.info(f"Intentando descargar CSV de resultados para {departamento}")

        posibles_urls_csv = [
            f"{self.base_url_registraduria}descargas/resultados_{departamento.lower()}.csv",
            f"https://cedae.datasketch.co/datos-democracia/resultados-electorales/descarga-los-datos/",
            f"https://resultados2026.registraduria.gov.co/csv/{departamento.lower()}.csv",
        ]

        for url in posibles_urls_csv:
            try:
                if 'cedae' in url:
                    return await self._descargar_csv_cedae(departamento)
                response = requests.get(url, timeout=30)
                if response.status_code == 200:
                    import os
                    filename = f"resultados_temp_{departamento}.csv"
                    with open(filename, 'wb') as f:
                        f.write(response.content)
                    df = pd.read_csv(filename, encoding='utf-8')
                    logger.info(f"CSV descargado y procesado: {len(df)} registros")
                    return df
            except Exception as e:
                logger.debug(f"CSV no disponible: {url} - {str(e)}")
                continue

        return pd.DataFrame()

    async def _descargar_csv_cedae(self, departamento: str) -> pd.DataFrame:
        """Descarga CSV desde la plataforma CEDAE usando Playwright"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(
                    "https://cedae.datasketch.co/datos-democracia/resultados-electorales/descarga-los-datos/"
                )
                await page.wait_for_timeout(3000)
                await page.select_option('select[name="año"], select[id="año"]', '2026')
                await page.wait_for_timeout(1000)
                await browser.close()
                return pd.DataFrame()
            except Exception as e:
                logger.error(f"Error descargando desde CEDAE: {str(e)}")
                await browser.close()
                return pd.DataFrame()

    async def extraer_resultados_por_departamento(self, departamento: str):
        """Extrae todos los resultados para un departamento usando multiples metodos"""
        logger.info(f"Extrayendo resultados para {departamento}...")

        resultados_api = await self.extraer_resultados_api(departamento, 'camara')
        if resultados_api:
            self.resultados_camara[departamento] = resultados_api
            logger.info(f"Resultados obtenidos desde API: {len(resultados_api)} registros")
            return

        df_csv = await self.extraer_resultados_csv(departamento)
        if not df_csv.empty:
            self.resultados_camara[departamento] = df_csv.to_dict('records')
            logger.info(f"Resultados obtenidos desde CSV: {len(df_csv)} registros")
            return

        logger.info("Extrayendo resultados desde formularios E-14 (puede tardar)...")
        resultados_e14 = []
        municipios = MUNICIPIOS.get(departamento, [])
        for municipio in municipios:
            logger.info(f"  Procesando {municipio}...")
        if resultados_e14:
            self.resultados_camara[departamento] = resultados_e14

    async def extraer_resultados_senado(self, departamento: str):
        """Extrae resultados de Juan Camilo Velez Londono al Senado por departamento"""
        logger.info(f"Extrayendo resultados al Senado para {departamento}...")

        resultados_api = await self.extraer_resultados_api(departamento, 'senado')
        if resultados_api:
            resultados_juan = [
                r for r in resultados_api
                if CANDIDATO_SENADO.lower() in str(r.get('candidato', '')).lower()
            ]
            self.resultados_senado[departamento] = resultados_juan
            return

        logger.warning(f"Resultados al Senado no disponibles aun para {departamento}")

    def calcular_correlacion_votos(self, departamento: str):
        """Calcula la correlacion entre votos de candidatos a Camara y votos de Juan al Senado por mesa"""
        logger.info(f"Calculando correlacion de votos para {departamento}...")

        resultados_camara = self.resultados_camara.get(departamento, [])
        resultados_senado = self.resultados_senado.get(departamento, [])

        if not resultados_camara or not resultados_senado:
            logger.warning(f"Faltan datos para calcular correlacion en {departamento}")
            return

        senado_por_mesa = {}
        for resultado in resultados_senado:
            key = f"{resultado.get('municipio')}_{resultado.get('puesto_votacion')}_{resultado.get('mesa')}"
            senado_por_mesa[key] = resultado.get('votos', 0)

        for resultado_camara in resultados_camara:
            municipio = resultado_camara.get('municipio', '')
            puesto = resultado_camara.get('puesto_votacion', '')
            mesa = resultado_camara.get('mesa', '')
            key_mesa = f"{municipio}_{puesto}_{mesa}"
            votos_senado_juan = senado_por_mesa.get(key_mesa, 0)

            candidatos_votos = resultado_camara.get('resultados', {})
            if isinstance(candidatos_votos, dict):
                candidatos_departamento = CANDIDATOS_CAMARA.get(departamento, [])
                for candidato, votos_camara in candidatos_votos.items():
                    if any(c.lower() in candidato.lower() for c in candidatos_departamento):
                        self.resultados_correlacion.append({
                            'departamento': departamento,
                            'municipio': municipio,
                            'puesto_votacion': puesto,
                            'mesa': mesa,
                            'candidato_camara': candidato,
                            'votos_camara': votos_camara,
                            'votos_senado_juan': votos_senado_juan,
                            'ratio_correlacion': votos_camara / max(votos_senado_juan, 1) if votos_senado_juan > 0 else 0,
                            'fecha_extraccion': datetime.now().isoformat()
                        })

    def calcular_costo_por_voto(self, inversiones: Dict[str, float]) -> pd.DataFrame:
        """Calcula el costo por voto para cada candidato basado en las inversiones"""
        logger.info("Calculando costo por voto...")

        if not self.resultados_correlacion:
            logger.warning("No hay datos de correlacion para calcular costo por voto")
            return pd.DataFrame()

        df = pd.DataFrame(self.resultados_correlacion)
        df['inversion'] = df['candidato_camara'].map(inversiones).fillna(0)
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
        """Genera el CSV final con todos los resultados y analisis"""
        logger.info(f"Generando CSV final: {filename}")

        if not self.resultados_correlacion:
            logger.warning("No hay datos para generar CSV")
            return None

        df_detalle = pd.DataFrame(self.resultados_correlacion)
        df_resumen = self.calcular_costo_por_voto(inversiones)
        df_detalle['inversion_candidato'] = df_detalle['candidato_camara'].map(inversiones).fillna(0)
        df_detalle['costo_por_voto'] = df_detalle['inversion_candidato'] / df_detalle['votos_camara'].replace(0, 1)

        df_detalle.to_csv(filename, index=False, encoding='utf-8-sig')
        logger.info(f"CSV detallado guardado: {filename} ({len(df_detalle)} registros)")

        filename_resumen = filename.replace('.csv', '_resumen.csv')
        df_resumen.to_csv(filename_resumen, index=False, encoding='utf-8-sig')
        logger.info(f"CSV resumen guardado: {filename_resumen}")

        return df_detalle, df_resumen

    async def ejecutar_scraping_completo(self, inversiones: Dict[str, float]):
        """Ejecuta el proceso completo de scraping y analisis"""
        logger.info("Iniciando scraping completo de resultados electorales...")

        url_detectada = await self.detectar_urls_resultados()
        if not url_detectada:
            logger.warning("Los resultados aun no estan publicados. El scraper esta listo para cuando se publiquen.")
            logger.info("Sugerencia: Ejecutar este script despues del 8 de marzo de 2026")
            return

        for departamento in DEPARTAMENTOS:
            await self.extraer_resultados_por_departamento(departamento)
            await self.extraer_resultados_senado(departamento)
            self.calcular_correlacion_votos(departamento)
            await asyncio.sleep(2)

        self.generar_csv_final(inversiones)
        logger.info("Scraping completo finalizado")
