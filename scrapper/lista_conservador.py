"""
Parser de la lista al Senado del Partido Conservador
Busca la seccion HTML party-detail-row y extrae resultados para comparar
el crecimiento de Juan Camilo Vélez Londoño vs el resto de miembros de la lista.
"""

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from .utils import logger


@dataclass
class CandidatoLista:
    """Datos de un candidato en la lista al Senado"""
    posicion: int
    nombre: str
    votos: int
    porcentaje: float

    def __str__(self):
        return f"#{self.posicion} {self.nombre}: {self.votos:,} ({self.porcentaje:.2f}%)"


# Selector/patron para identificar la fila de detalle del partido
PARTY_DETAIL_ROW_CLASS = "party-detail-row"
CANDIDATO_PATTERN = re.compile(
    r'<span class="rt-Text">(\d+)\s*-\s*</span>\s*<span class="rt-Text">([^<]+)</span>'
)
VOTOS_PATTERN = re.compile(
    r'<div class="text-center">([\d.]+)</div>'
)
PORCENTAJE_PATTERN = re.compile(
    r'<div class="flex-1 text-center">([\d,]+)%</div>'
)

# Nombre del candidato a trackear (variaciones para matching)
CANDIDATO_JCV = "JUAN CAMILO VELEZ LONDOÑO"
CANDIDATO_JCV_VARIACIONES = [
    "JUAN CAMILO VELEZ LONDOÑO",
    "JUAN CAMILO VELEZ LONDONO",
    "JUAN CAMILO VÉLEZ LONDOÑO",
]


def _parse_int_votos(texto: str) -> int:
    """Convierte '1.078' o '10.690' a entero (formato miles con punto)"""
    if not texto:
        return 0
    limpio = texto.strip().replace(".", "").replace(",", "")
    try:
        return int(limpio)
    except ValueError:
        return 0


def _parse_porcentaje(texto: str) -> float:
    """Convierte '0,10' o '1,00' a float"""
    if not texto:
        return 0.0
    limpio = texto.strip().replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return 0.0


def _es_juan_camilo(nombre: str) -> bool:
    """Verifica si el nombre corresponde a Juan Camilo Vélez"""
    nombre_upper = nombre.upper().strip()
    nombre_norm = nombre_upper.replace("Ñ", "N").replace("É", "E")
    for var in CANDIDATO_JCV_VARIACIONES:
        var_norm = var.replace("Ñ", "N").replace("É", "E")
        if var_norm in nombre_norm or nombre_norm in var_norm:
            return True
    # Match por palabras clave
    palabras = {"JUAN", "CAMILO", "VELEZ", "VELÉZ", "LONDOÑO", "LONDONO"}
    tiene = sum(1 for p in palabras if p in nombre_upper)
    return tiene >= 3


def extraer_candidatos_desde_html(html: str) -> List[CandidatoLista]:
    """
    Extrae todos los candidatos de la seccion party-detail-row del HTML.
    Busca bloques rt-Grid y parsea posicion, nombre, votos y porcentaje.
    """
    candidatos = []
    vistos = set()  # Evitar duplicados por (pos, nombre)

    # Buscar la fila party-detail-row
    if PARTY_DETAIL_ROW_CLASS not in html:
        logger.warning("No se encontro la seccion party-detail-row en el HTML")
        # Intentar igual si hay rt-Grid
        if "rt-Grid" not in html:
            return candidatos

    # Estrategia: buscar cada aparicion de "N - " seguido del nombre en rt-Text
    # Luego buscar votos (text-center) y porcentaje (flex-1 text-center) en el bloque
    for m in CANDIDATO_PATTERN.finditer(html):
        pos = int(m.group(1))
        nombre = m.group(2).strip()
        if not nombre:
            continue
        # Saltar "SOLO POR LA LISTA"
        if pos == 0 and "SOLO" in nombre.upper() and "LISTA" in nombre.upper():
            continue
        key = (pos, nombre)
        if key in vistos:
            continue
        vistos.add(key)

        # Buscar votos y porcentaje en los proximos 500 caracteres
        idx = m.end()
        fragmento = html[idx : idx + 500]
        votos_m = VOTOS_PATTERN.search(fragmento)
        pct_m = PORCENTAJE_PATTERN.search(fragmento)
        votos = _parse_int_votos(votos_m.group(1)) if votos_m else 0
        pct = _parse_porcentaje(pct_m.group(1)) if pct_m else 0.0

        candidatos.append(CandidatoLista(
            posicion=pos,
            nombre=nombre,
            votos=votos,
            porcentaje=pct
        ))

    return candidatos


def comparar_jcv_con_lista(candidatos: List[CandidatoLista]) -> dict:
    """
    Compara Juan Camilo Vélez con el resto de la lista.
    Retorna un dict con metricas de comparacion.
    """
    jcv = None
    otros = []

    for c in candidatos:
        if _es_juan_camilo(c.nombre):
            jcv = c
        else:
            otros.append(c)

    if not jcv:
        logger.warning("No se encontro a Juan Camilo Vélez en la lista")
        return {"encontrado": False, "candidatos_total": len(candidatos)}

    total_votos = sum(c.votos for c in candidatos)
    votos_solo_candidatos = sum(c.votos for c in otros)  # sin "solo lista"

    # Ranking por votos (entre candidatos individuales)
    ranking_votos = sorted(otros, key=lambda x: x.votos, reverse=True)
    posicion_jcv_votos = next((i + 1 for i, c in enumerate(ranking_votos) if c.nombre == jcv.nombre), None)
    if posicion_jcv_votos is None:
        posicion_jcv_votos = len(ranking_votos) + 1

    # Candidatos con mas votos que JCV
    por_encima = [c for c in ranking_votos if c.votos > jcv.votos]
    por_debajo = [c for c in ranking_votos if c.votos <= jcv.votos]

    return {
        "encontrado": True,
        "jcv": jcv,
        "candidatos_total": len(candidatos),
        "total_votos_lista": total_votos,
        "posicion_en_lista": jcv.posicion,
        "posicion_por_votos": posicion_jcv_votos,
        "votos": jcv.votos,
        "porcentaje": jcv.porcentaje,
        "candidatos_por_encima": len(por_encima),
        "candidatos_por_debajo": len(por_debajo),
        "top_5": [c.nombre for c in ranking_votos[:5]],
        "comparativa": [
            {
                "nombre": c.nombre,
                "posicion": c.posicion,
                "votos": c.votos,
                "porcentaje": c.porcentaje,
                "diferencia_votos_vs_jcv": c.votos - jcv.votos,
                "ratio_vs_jcv": round(c.votos / jcv.votos, 2) if jcv.votos > 0 else 0,
            }
            for c in ranking_votos[:20]  # Top 20 para comparar
        ],
    }


def guardar_csv_comparativa(candidatos: List[CandidatoLista], archivo: str) -> Path:
    """Guarda la lista completa y la comparativa con JCV en CSV."""
    resultado = comparar_jcv_con_lista(candidatos)
    base_dir = Path(__file__).resolve().parent.parent
    ruta = base_dir / archivo

    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Posicion", "Nombre", "Votos", "Porcentaje", "Es_JCV", "Diferencia_vs_JCV", "Ranking_votos"])
        jcv = resultado.get("jcv")
        jcv_votos = jcv.votos if jcv else 0

        ranking = sorted(candidatos, key=lambda x: x.votos, reverse=True)
        rank_map = {c.nombre: i + 1 for i, c in enumerate(ranking)}

        for c in candidatos:
            es_jcv = _es_juan_camilo(c.nombre)
            diff = c.votos - jcv_votos if jcv_votos else 0
            r = rank_map.get(c.nombre, "-")
            w.writerow([c.posicion, c.nombre, c.votos, f"{c.porcentaje:.2f}", es_jcv, diff, r])

    logger.info(f"CSV guardado: {ruta}")
    return ruta


def parsear_y_comparar(html: str, guardar_csv: bool = True) -> dict:
    """
    Flujo completo: parsea HTML, extrae candidatos, compara JCV y opcionalmente guarda CSV.
    """
    candidatos = extraer_candidatos_desde_html(html)
    if not candidatos:
        return {"error": "No se extrajeron candidatos del HTML", "candidatos": []}

    resultado = comparar_jcv_con_lista(candidatos)
    logger.info(f"Extraidos {len(candidatos)} candidatos. JCV: {'Encontrado' if resultado.get('encontrado') else 'No encontrado'}")

    if resultado.get("encontrado"):
        jcv = resultado["jcv"]
        logger.info(f"  -> {jcv}")
        logger.info(f"  -> Posicion por votos: {resultado.get('posicion_por_votos')} de {resultado.get('candidatos_total')}")
        logger.info(f"  -> Candidatos con mas votos: {resultado.get('candidatos_por_encima')}")

    if guardar_csv:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        guardar_csv_comparativa(candidatos, f"lista_conservador_senado_{ts}.csv")

    return resultado
