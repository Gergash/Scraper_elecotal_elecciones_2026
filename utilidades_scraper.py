"""
Utilidades y funciones auxiliares para el scraper de resultados electorales
"""

import pandas as pd
import json
import os
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


def validar_configuracion(config_path: str = 'config_candidatos.json') -> Dict:
    """
    Valida que la configuración esté completa y correcta
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(script_dir, config_path)
    
    if not os.path.exists(config_file):
        logger.error(f"❌ Archivo de configuración no encontrado: {config_file}")
        return {'valido': False, 'errores': ['Archivo no encontrado']}
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"❌ Error parseando JSON: {e}")
        return {'valido': False, 'errores': [f'Error JSON: {str(e)}']}
    
    errores = []
    
    # Validar estructura básica
    if 'candidatos_camara' not in config:
        errores.append("Falta 'candidatos_camara' en configuración")
    
    if 'candidato_senado' not in config:
        errores.append("Falta 'candidato_senado' en configuración")
    
    if 'departamentos' not in config:
        errores.append("Falta 'departamentos' en configuración")
    
    # Validar inversiones
    inversiones = config.get('inversiones', {})
    if not inversiones:
        errores.append("⚠️ No se encontraron inversiones (puede estar vacío)")
    else:
        inversiones_cero = [k for k, v in inversiones.items() if v == 0]
        if inversiones_cero:
            logger.warning(f"⚠️ {len(inversiones_cero)} candidatos tienen inversión = 0")
    
    # Validar candidatos por departamento
    candidatos_camara = config.get('candidatos_camara', {})
    for depto, candidatos in candidatos_camara.items():
        if not candidatos:
            errores.append(f"No hay candidatos definidos para {depto}")
    
    resultado = {
        'valido': len(errores) == 0,
        'errores': errores,
        'config': config
    }
    
    if resultado['valido']:
        logger.info("✅ Configuración válida")
    else:
        logger.warning(f"⚠️ Configuración con {len(errores)} problemas")
    
    return resultado


def normalizar_nombre_candidato(nombre: str) -> str:
    """
    Normaliza el nombre de un candidato para comparación
    """
    # Remover tildes y convertir a minúsculas
    nombre = nombre.lower()
    nombre = nombre.replace('á', 'a').replace('é', 'e').replace('í', 'i')
    nombre = nombre.replace('ó', 'o').replace('ú', 'u').replace('ñ', 'n')
    # Remover espacios extras
    nombre = ' '.join(nombre.split())
    return nombre


def buscar_candidato_por_variaciones(nombre_encontrado: str, 
                                     candidatos_esperados: List[str]) -> Optional[str]:
    """
    Busca un candidato por variaciones de nombre
    """
    nombre_normalizado = normalizar_nombre_candidato(nombre_encontrado)
    
    for candidato_esperado in candidatos_esperados:
        candidato_normalizado = normalizar_nombre_candidato(candidato_esperado)
        
        # Coincidencia exacta
        if nombre_normalizado == candidato_normalizado:
            return candidato_esperado
        
        # Coincidencia parcial (contiene)
        palabras_encontradas = set(nombre_normalizado.split())
        palabras_esperadas = set(candidato_normalizado.split())
        
        # Si al menos 2 palabras coinciden
        coincidencias = palabras_encontradas.intersection(palabras_esperadas)
        if len(coincidencias) >= 2:
            return candidato_esperado
    
    return None


def generar_reporte_resumen(df_resultados: pd.DataFrame, 
                            df_resumen: pd.DataFrame,
                            output_file: str = 'reporte_analisis_electoral.txt'):
    """
    Genera un reporte de texto con análisis de resultados
    """
    reporte = []
    reporte.append("=" * 80)
    reporte.append("REPORTE DE ANÁLISIS ELECTORAL - COSTO POR VOTO")
    reporte.append("=" * 80)
    reporte.append(f"\nFecha de generación: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
    reporte.append("\n" + "=" * 80)
    
    # Resumen ejecutivo
    reporte.append("\n📊 RESUMEN EJECUTIVO")
    reporte.append("-" * 80)
    
    if not df_resumen.empty:
        total_votos_camara = df_resumen['votos_camara'].sum()
        total_votos_senado = df_resumen['votos_senado_juan'].sum()
        total_inversion = df_resumen['inversion'].sum()
        
        reporte.append(f"\nTotal de votos a Cámara: {total_votos_camara:,}")
        reporte.append(f"Total de votos correlacionados con Juan al Senado: {total_votos_senado:,}")
        reporte.append(f"Inversión total: ${total_inversion:,.0f}")
        reporte.append(f"Costo promedio por voto correlacionado: ${total_inversion/max(total_votos_senado,1):,.0f}")
    
    # Top candidatos por aporte
    reporte.append("\n\n🏆 TOP CANDIDATOS POR APORTE RELATIVO")
    reporte.append("-" * 80)
    
    if not df_resumen.empty:
        top_candidatos = df_resumen.nlargest(5, 'aporte_relativo')
        for idx, row in top_candidatos.iterrows():
            reporte.append(f"\n{row['candidato_camara']}:")
            reporte.append(f"  - Aporte relativo: {row['aporte_relativo']:.2f}%")
            reporte.append(f"  - Votos correlacionados: {row['votos_senado_juan']:,}")
            reporte.append(f"  - Costo por voto: ${row['costo_por_voto_correlacionado']:,.0f}")
            reporte.append(f"  - Inversión: ${row['inversion']:,.0f}")
    
    # Análisis por departamento
    reporte.append("\n\n🗺️ ANÁLISIS POR DEPARTAMENTO")
    reporte.append("-" * 80)
    
    if not df_resultados.empty:
        por_departamento = df_resultados.groupby('departamento').agg({
            'votos_camara': 'sum',
            'votos_senado_juan': 'sum',
            'inversion_candidato': 'sum'
        }).reset_index()
        
        for _, row in por_departamento.iterrows():
            reporte.append(f"\n{row['departamento']}:")
            reporte.append(f"  - Votos Cámara: {row['votos_camara']:,}")
            reporte.append(f"  - Votos Senado: {row['votos_senado_juan']:,}")
            reporte.append(f"  - Inversión: ${row['inversion_candidato']:,.0f}")
            if row['votos_senado_juan'] > 0:
                costo = row['inversion_candidato'] / row['votos_senado_juan']
                reporte.append(f"  - Costo por voto: ${costo:,.0f}")
    
    reporte.append("\n" + "=" * 80)
    
    # Guardar reporte
    reporte_texto = '\n'.join(reporte)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(reporte_texto)
    
    logger.info(f"✅ Reporte guardado en {output_file}")
    print(reporte_texto)
    
    return reporte_texto


def exportar_a_excel(df_detalle: pd.DataFrame, 
                     df_resumen: pd.DataFrame,
                     filename: str = 'resultados_electorales.xlsx'):
    """
    Exporta resultados a Excel con múltiples hojas
    """
    try:
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            df_detalle.to_excel(writer, sheet_name='Detalle por Mesa', index=False)
            df_resumen.to_excel(writer, sheet_name='Resumen por Candidato', index=False)
            
            # Crear hoja de análisis
            if not df_resumen.empty:
                analisis = df_resumen.nlargest(10, 'aporte_relativo')[['candidato_camara', 'aporte_relativo', 'costo_por_voto_correlacionado']]
                analisis.to_excel(writer, sheet_name='Top 10 Candidatos', index=False)
        
        logger.info(f"✅ Archivo Excel guardado: {filename}")
        return True
    except ImportError:
        logger.warning("⚠️ openpyxl no está instalado. Instala con: pip install openpyxl")
        return False
    except Exception as e:
        logger.error(f"❌ Error exportando a Excel: {e}")
        return False


if __name__ == "__main__":
    # Validar configuración
    resultado = validar_configuracion()
    if resultado['valido']:
        print("✅ Configuración válida")
    else:
        print("❌ Errores encontrados:")
        for error in resultado['errores']:
            print(f"  - {error}")
