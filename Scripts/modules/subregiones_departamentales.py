"""Selección geográfica de macroregiones dentro de departamentos de Bolivia.

Este módulo no dibuja mapas ni modifica el carimbo.  Entrega exclusivamente la
geometría, el encuadre y las localidades que debe recibir el script existente.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Mapping

import geopandas as gpd
from shapely.geometry import Point


@dataclass(frozen=True)
class SubregionSeleccionada:
    """Resultado listo para usar en el generador del producto GOES."""

    departamento: str
    macroregion: str
    geometria: object
    extent: list[float]  # [oeste, este, sur, norte], EPSG:4326

    @property
    def subtitulo(self) -> str:
        return f"{self.macroregion} — {self.departamento}"


def _normalizar(valor: object) -> str:
    """Compara nombres sin depender de mayúsculas, espacios o tildes."""
    texto = unicodedata.normalize("NFKD", str(valor))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.upper().split())


def _buscar_registro(gdf: gpd.GeoDataFrame, columna: str, valor: object,
                     etiqueta: str) -> gpd.GeoDataFrame:
    objetivo = _normalizar(valor)
    mascara = gdf[columna].map(_normalizar).eq(objetivo)
    resultado = gdf.loc[mascara].copy()
    if resultado.empty:
        disponibles = ", ".join(sorted(gdf[columna].dropna().astype(str)))
        raise ValueError(
            f"No existe {etiqueta} '{valor}'. Valores disponibles: {disponibles}."
        )
    return resultado


def _extent_con_aspecto(geometria: object, target_aspect: float = 1.052,
                         buffer_pct: float = 0.08) -> list[float]:
    """Calcula un encuadre geográfico compatible con el lienzo ya existente."""
    minx, miny, maxx, maxy = geometria.bounds
    if minx == maxx or miny == maxy:
        raise ValueError("La subregión no tiene una extensión geográfica válida.")

    centro_x, centro_y = (minx + maxx) / 2, (miny + maxy) / 2
    ancho = (maxx - minx) * (1 + buffer_pct)
    alto = (maxy - miny) * (1 + buffer_pct)

    if ancho / alto < target_aspect:
        ancho = alto * target_aspect
    else:
        alto = ancho / target_aspect

    return [
        centro_x - ancho / 2,
        centro_x + ancho / 2,
        centro_y - alto / 2,
        centro_y + alto / 2,
    ]


def obtener_subregion_departamental(
    path_departamentos: str,
    path_macroregiones: str,
    departamento: str,
    macroregion: str,
    *,
    target_aspect: float = 1.052,
    buffer_pct: float = 0.08,
) -> SubregionSeleccionada:
    """Interseca un departamento con una macroregión y calcula su encuadre.

    Los shapefiles deben contener las columnas ``nom_dep`` y ``MacroRegio``.
    El resultado se lleva a EPSG:4326 para ser usado directamente por Cartopy.
    """
    departamentos = gpd.read_file(path_departamentos)
    macroregiones = gpd.read_file(path_macroregiones)

    for gdf, nombre in ((departamentos, "departamentos"),
                        (macroregiones, "macroregiones")):
        if gdf.crs is None:
            raise ValueError(f"La capa de {nombre} no tiene CRS definido.")

    if "nom_dep" not in departamentos.columns:
        raise KeyError("No se encontró la columna 'nom_dep' en departamentos.")
    if "MacroRegio" not in macroregiones.columns:
        raise KeyError("No se encontró la columna 'MacroRegio' en macroregiones.")

    departamentos = departamentos.to_crs("EPSG:4326")
    macroregiones = macroregiones.to_crs("EPSG:4326")
    dep = _buscar_registro(departamentos, "nom_dep", departamento, "el departamento")
    macro = _buscar_registro(macroregiones, "MacroRegio", macroregion, "la macroregión")

    geometria = dep.geometry.unary_union.intersection(macro.geometry.unary_union)
    if geometria.is_empty:
        raise ValueError(
            f"'{macroregion}' no tiene intersección espacial con '{departamento}'."
        )

    nombre_dep = dep["nom_dep"].iloc[0]
    nombre_macro = macro["MacroRegio"].iloc[0]
    return SubregionSeleccionada(
        departamento=nombre_dep,
        macroregion=nombre_macro,
        geometria=geometria,
        extent=_extent_con_aspecto(geometria, target_aspect, buffer_pct),
    )


def filtrar_localidades(
    localidades: Mapping[str, Mapping[str, object]],
    geometria: object,
    *,
    tolerancia_grados: float = 0.03,
) -> dict[str, Mapping[str, object]]:
    """Devuelve solo localidades que caen dentro de la subregión seleccionada.

    La tolerancia evita perder una localidad que está exactamente sobre el límite
    de un polígono. No altera símbolos, tamaños ni posiciones de las etiquetas.
    """
    area_busqueda = geometria.buffer(tolerancia_grados)
    return {
        nombre: info
        for nombre, info in localidades.items()
        if area_busqueda.covers(Point(float(info["lon"]), float(info["lat"])))
    }
