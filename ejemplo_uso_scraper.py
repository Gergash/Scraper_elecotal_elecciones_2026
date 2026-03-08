"""
Ejemplo de uso del scraper de resultados electorales
"""

import asyncio
from scrapper import ScraperResultadosElectorales
from utilidades_scraper import validar_configuracion, generar_reporte_resumen, exportar_a_excel
import pandas as pd
import json


async def ejemplo_basico():
    """
    Ejemplo básico de uso del scraper
    """
    print("=" * 80)
    print("EJEMPLO DE USO - SCRAPER RESULTADOS ELECTORALES")
    print("=" * 80)
    
    # Paso 1: Validar configuración
    print("\n1. Validando configuración...")
    resultado_validacion = validar_configuracion()
    
    if not resultado_validacion['valido']:
        print("❌ Errores en configuración:")
        for error in resultado_validacion['errores']:
            print(f"   - {error}")
        print("\n💡 Por favor, corrige los errores antes de continuar")
        return
    
    print("✅ Configuración válida")
    
    # Paso 2: Cargar inversiones
    print("\n2. Cargando inversiones...")
    config = resultado_validacion['config']
    inversiones = config.get('inversiones', {})
    
    if not inversiones or all(v == 0 for v in inversiones.values()):
        print("⚠️ Advertencia: No hay inversiones configuradas")
        print("💡 Edita config_candidatos.json y agrega las inversiones reales")
        print("\nContinuando con valores en cero para demostración...")
    
    # Paso 3: Crear scraper
    print("\n3. Inicializando scraper...")
    scraper = ScraperResultadosElectorales(headless=False)
    
    # Paso 4: Ejecutar scraping
    print("\n4. Ejecutando scraping...")
    print("   (Nota: Si los resultados aún no están publicados, el scraper lo detectará)")
    
    try:
        await scraper.ejecutar_scraping_completo(inversiones)
    except Exception as e:
        print(f"\n❌ Error durante el scraping: {e}")
        print("💡 Esto es normal si los resultados aún no están publicados")
        return
    
    # Paso 5: Generar reportes
    print("\n5. Generando reportes...")
    
    if scraper.resultados_correlacion:
        # Generar CSV (ya se hizo en ejecutar_scraping_completo)
        print("   ✅ CSV generado: resultados_costo_por_voto.csv")
        
        # Generar reporte de texto
        df_detalle = pd.DataFrame(scraper.resultados_correlacion)
        df_resumen = scraper.calcular_costo_por_voto(inversiones)
        
        generar_reporte_resumen(df_detalle, df_resumen)
        print("   ✅ Reporte de texto generado: reporte_analisis_electoral.txt")
        
        # Exportar a Excel
        if exportar_a_excel(df_detalle, df_resumen):
            print("   ✅ Archivo Excel generado: resultados_electorales.xlsx")
    else:
        print("   ⚠️ No hay datos para generar reportes")
        print("   💡 Los resultados estarán disponibles después del 8 de marzo de 2026")
    
    print("\n" + "=" * 80)
    print("PROCESO COMPLETADO")
    print("=" * 80)


async def ejemplo_con_datos_simulados():
    """
    Ejemplo usando datos simulados para pruebas
    """
    print("\n" + "=" * 80)
    print("EJEMPLO CON DATOS SIMULADOS (PARA PRUEBAS)")
    print("=" * 80)
    
    # Crear scraper
    scraper = ScraperResultadosElectorales(headless=False)
    
    # Simular resultados (para pruebas cuando no hay datos reales)
    datos_simulados = [
        {
            'departamento': 'VALLE',
            'municipio': 'Cali',
            'puesto_votacion': 'Puesto 001',
            'mesa': '1',
            'candidato_camara': 'Rigo Vega Cartago',
            'votos_camara': 150,
            'votos_senado_juan': 200,
            'ratio_correlacion': 0.75,
            'fecha_extraccion': '2026-03-09T10:00:00'
        },
        {
            'departamento': 'VALLE',
            'municipio': 'Cali',
            'puesto_votacion': 'Puesto 001',
            'mesa': '2',
            'candidato_camara': 'Adriana Daraviña',
            'votos_camara': 120,
            'votos_senado_juan': 180,
            'ratio_correlacion': 0.67,
            'fecha_extraccion': '2026-03-09T10:00:00'
        },
    ]
    
    scraper.resultados_correlacion = datos_simulados
    
    # Inversiones simuladas
    inversiones_simuladas = {
        'Rigo Vega Cartago': 50000000,
        'Adriana Daraviña': 30000000,
    }
    
    # Generar reportes
    df_detalle = pd.DataFrame(datos_simulados)
    df_resumen = scraper.calcular_costo_por_voto(inversiones_simuladas)
    
    print("\n📊 Resultados simulados procesados:")
    print(df_resumen.to_string())
    
    generar_reporte_resumen(df_detalle, df_resumen, 'reporte_simulado.txt')
    print("\n✅ Reporte simulado generado: reporte_simulado.txt")


if __name__ == "__main__":
    print("\nSelecciona el modo de ejecución:")
    print("1. Ejemplo básico (con datos reales cuando estén disponibles)")
    print("2. Ejemplo con datos simulados (para pruebas)")
    
    # Por defecto ejecutar ejemplo básico
    # Cambiar a ejemplo_con_datos_simulados() para pruebas
    asyncio.run(ejemplo_basico())
    # asyncio.run(ejemplo_con_datos_simulados())
