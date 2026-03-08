"""
Scraper de la lista al Senado del Partido Conservador
Busca la seccion HTML party-detail-row para extraer y comparar el crecimiento
de Juan Camilo Vélez Londoño vs el resto de miembros de la lista.

Uso:
  1. Pega el HTML de la fila party-detail-row en el archivo HTML_SAMPLE
  2. Ejecuta: python scraper_lista_conservador.py

O desde codigo:
  from scrapper.lista_conservador import parsear_y_comparar, extraer_candidatos_desde_html
  resultado = parsear_y_comparar(html)
"""

import sys
from pathlib import Path

# Agregar directorio padre al path
BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from scrapper.lista_conservador import (
    extraer_candidatos_desde_html,
    comparar_jcv_con_lista,
    parsear_y_comparar,
    guardar_csv_comparativa,
)
from scrapper.utils import logger


# Ruta donde guardar/leer el HTML - pega aqui la seccion party-detail-row
HTML_INPUT_FILE = BASE / "lista_conservador_sample.html"


def main():
    """Lee HTML desde archivo o stdin y ejecuta parseo y comparacion."""
    html = None

    if HTML_INPUT_FILE.exists():
        logger.info(f"Leyendo HTML desde {HTML_INPUT_FILE}")
        html = HTML_INPUT_FILE.read_text(encoding="utf-8", errors="replace")
    elif not sys.stdin.isatty():
        logger.info("Leyendo HTML desde stdin")
        html = sys.stdin.read()
    else:
        # Crear archivo de ejemplo con instrucciones
        sample = """<!-- Pega aqui el HTML completo de la fila party-detail-row 
        (tr class="rt-TableRow party-detail-row") y sus td/div internos -->
"""
        HTML_INPUT_FILE.write_text(sample, encoding="utf-8")
        logger.info(f"Creado archivo de ejemplo: {HTML_INPUT_FILE}")
        logger.info("Pega el HTML de la seccion party-detail-row en ese archivo y vuelve a ejecutar.")
        return

    if not html or len(html.strip()) < 100:
        logger.error("HTML vacio o muy corto. Verifica el contenido.")
        return 1

    resultado = parsear_y_comparar(html, guardar_csv=True)

    if resultado.get("error"):
        logger.error(resultado["error"])
        return 1

    if resultado.get("encontrado"):
        jcv = resultado["jcv"]
        print("\n" + "=" * 60)
        print("JUAN CAMILO VÉLEZ LONDOÑO - Comparativa en lista Conservador")
        print("=" * 60)
        print(f"  Posicion en lista: #{jcv.posicion}")
        print(f"  Posicion por votos: #{resultado.get('posicion_por_votos')} de {resultado.get('candidatos_total')}")
        print(f"  Votos: {jcv.votos:,}")
        print(f"  Porcentaje: {jcv.porcentaje:.2f}%")
        print(f"  Candidatos con mas votos: {resultado.get('candidatos_por_encima')}")
        print(f"  Candidatos con menos votos: {resultado.get('candidatos_por_debajo')}")
        print("\n  Top 5 por votos:")
        for i, n in enumerate(resultado.get("top_5", [])[:5], 1):
            print(f"    {i}. {n}")
        print("=" * 60)
    else:
        print("\nJuan Camilo Vélez no encontrado en la lista extraida.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
