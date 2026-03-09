"""
Parser de la lista al Senado del Partido Conservador
Extrae candidatos y votos desde el HTML expandido del portal de resultados.

Estructura real del HTML:
  <span class="rt-Text rt-r-size-3 text-2">NOMBRE CANDIDATO</span>
  <span class="rt-Text">11.557</span>   <- votos
"""

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .utils import logger


@dataclass
class CandidatoLista:
    """Datos de un candidato en la lista al Senado"""
    posicion: int
    nombre: str
    votos: int
    porcentaje: float = 0.0

    def __str__(self):
        return f"#{self.posicion} {self.nombre}: {self.votos:,}"


# Patrón real extraído del HTML del portal de resultados
# <span class="rt-Text rt-r-size-3 text-2">NOMBRE</span><span class="rt-Text">VOTOS</span>
CANDIDATO_VOTOS_PATTERN = re.compile(
    r'<span class="rt-Text rt-r-size-3 text-2">([^<]+)</span>\s*<span class="rt-Text">([\d\.]+)</span>'
)

# Nombre del candidato a trackear
CANDIDATO_JCV_KEYWORDS = {"JUAN", "CAMILO", "VELEZ"}


def _parse_votos(texto: str) -> int:
    """Convierte '11.557' o '70.300' a entero (separador de miles con punto)."""
    limpio = texto.strip().replace(".", "").replace(",", "")
    try:
        return int(limpio)
    except ValueError:
        return 0


def _es_juan_camilo(nombre: str) -> bool:
    """Verifica que el nombre contenga JUAN + CAMILO + VELEZ."""
    nombre_norm = nombre.upper().replace("É", "E").replace("Ñ", "N")
    return all(k in nombre_norm for k in CANDIDATO_JCV_KEYWORDS)


def extraer_candidatos_desde_html(html: str) -> List[CandidatoLista]:
    """
    Extrae todos los candidatos con sus votos del HTML expandido
    del Partido Conservador.
    Retorna lista ordenada por votos descendente con posición asignada.
    """
    candidatos = []

    for match in CANDIDATO_VOTOS_PATTERN.finditer(html):
        nombre = match.group(1).strip()
        votos = _parse_votos(match.group(2))

        # Excluir la fila "SOLO POR LA LISTA"
        if "SOLO POR LA LISTA" in nombre.upper():
            continue

        if nombre:
            candidatos.append(CandidatoLista(posicion=0, nombre=nombre, votos=votos))

    if not candidatos:
        logger.warning("No se extrajeron candidatos del HTML")
        return []

    # Ordenar por votos descendente y asignar posición
    candidatos.sort(key=lambda c: c.votos, reverse=True)
    for i, c in enumerate(candidatos, 1):
        c.posicion = i

    logger.info(f"Candidatos extraídos: {len(candidatos)}")
    return candidatos


def comparar_jcv_con_lista(candidatos: List[CandidatoLista]) -> dict:
    """Compara Juan Camilo Vélez con el resto de la lista."""
    jcv: Optional[CandidatoLista] = None
    otros = []

    for c in candidatos:
        if _es_juan_camilo(c.nombre):
            jcv = c
        else:
            otros.append(c)

    if not jcv:
        logger.warning("No se encontró a Juan Camilo Vélez en la lista")
        return {"encontrado": False, "candidatos_total": len(candidatos)}

    por_encima = [c for c in otros if c.votos > jcv.votos]
    por_debajo = [c for c in otros if c.votos <= jcv.votos]

    return {
        "encontrado": True,
        "jcv": jcv,
        "candidatos_total": len(candidatos),
        "posicion_por_votos": jcv.posicion,
        "votos": jcv.votos,
        "candidatos_por_encima": len(por_encima),
        "candidatos_por_debajo": len(por_debajo),
        "top_5": [c.nombre for c in candidatos[:5]],
    }


def guardar_csv_comparativa(candidatos: List[CandidatoLista], archivo: str) -> Path:
    """Guarda la lista completa en CSV."""
    base_dir = Path(__file__).resolve().parent.parent
    ruta = base_dir / archivo
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Posicion_votos", "Nombre", "Votos", "Es_JCV"])
        for c in candidatos:
            w.writerow([c.posicion, c.nombre, c.votos, _es_juan_camilo(c.nombre)])
    logger.info(f"CSV guardado: {ruta}")
    return ruta


def parsear_y_comparar(html: str, guardar_csv: bool = False) -> dict:
    """Flujo completo: parsea HTML, extrae candidatos, compara JCV."""
    candidatos = extraer_candidatos_desde_html(html)
    if not candidatos:
        return {"error": "No se extrajeron candidatos del HTML"}

    resultado = comparar_jcv_con_lista(candidatos)
    if resultado.get("encontrado"):
        jcv = resultado["jcv"]
        logger.info(f"JCV: {jcv} | Posicion: #{jcv.posicion} de {resultado['candidatos_total']}")

    if guardar_csv:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        guardar_csv_comparativa(candidatos, f"lista_conservador_senado_{ts}.csv")

    return resultado
