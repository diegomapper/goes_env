"""Renderizador institucional del RGB diurno de nieve/niebla GOES.

La función concentra el renderizado ya usado por el Notebook. No rediseña el
carimbo: mantiene lienzo, márgenes, capas, leyenda y posición de logos.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.shapereader as shpreader
import matplotlib.image as mpimg
import matplotlib.patches as mpatches
import matplotlib.patheffects as patheffects
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr


def renderizar_producto_nieve(
    ruta_netcdf: str | Path,
    ruta_salida: str | Path,
    *,
    extent_final: list[float],
    subtitulo_final: str,
    localidades_final: Mapping[str, Mapping[str, object]],
    path_logos: str | Path,
    mostrar: bool = False,
) -> datetime:
    """Renderiza una escena ABI en el carimbo institucional existente.

    Devuelve la hora real de adquisición en UTC para usarla en el nombre de
    archivo y en el orden cronológico de una animación.
    """
    ruta_netcdf = Path(ruta_netcdf)
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    path_logos = Path(path_logos)

    with xr.open_dataset(ruta_netcdf, engine="netcdf4") as ds:
        proyeccion = ds.goes_imager_projection.attrs
        height = proyeccion["perspective_point_height"]
        lon_0 = proyeccion["longitude_of_projection_origin"]
        sweep = proyeccion["sweep_angle_axis"]
        dataprojenv = ccrs.Geostationary(
            central_longitude=lon_0,
            satellite_height=height,
            sweep_axis=sweep,
        )

        ch03_raw = ds["CMI_C03"].values.astype(float)
        ch05_raw = ds["CMI_C05"].values.astype(float)
        ch07_raw = ds["CMI_C07"].values.astype(float)
        ch13_raw = ds["CMI_C13"].values.astype(float)

        ch03_pct = ch03_raw if np.nanmax(ch03_raw) > 1.0 else ch03_raw * 100.0
        ch05_pct = ch05_raw if np.nanmax(ch05_raw) > 1.0 else ch05_raw * 100.0

        rojo = np.power(np.clip(ch03_pct / 100.0, 0, 1), 1.0 / 1.7)
        verde = np.power(np.clip(ch05_pct / 70.0, 0, 1), 1.0 / 1.7)
        azul = np.power(np.clip((ch07_raw - ch13_raw) / 30.0, 0, 1), 1.0 / 1.7)
        rgb_image = np.dstack((rojo, verde, azul))

        x_grid = ds.x.values * height
        y_grid = ds.y.values * height
        fecha_utc = datetime.strptime(
            ds.t.dt.strftime("%Y-%m-%d %H:%M").item(),
            "%Y-%m-%d %H:%M",
        )

    # Configuración del lienzo: idéntica al producto estático.
    fig, ax = plt.subplots(
        figsize=(10, 9.5),
        facecolor="white",
        subplot_kw={"projection": ccrs.PlateCarree()},
    )
    fig.subplots_adjust(left=0.00, right=1.00, top=0.88, bottom=0.06)
    ax.set_extent(extent_final, crs=ccrs.PlateCarree())
    ax.imshow(
        rgb_image,
        origin="upper",
        transform=dataprojenv,
        extent=[x_grid.min(), x_grid.max(), y_grid.min(), y_grid.max()],
        aspect="auto",
        zorder=1,
    )

    color_blanco = "#ffffff"
    borde_nacional = cfeature.NaturalEarthFeature(
        category="cultural", name="admin_0_boundary_lines_land", scale="10m",
        facecolor="none",
    )
    costas = cfeature.NaturalEarthFeature(
        category="physical", name="coastline", scale="10m", facecolor="none",
    )
    ax.add_feature(costas, linestyle="-", edgecolor=color_blanco, linewidth=1.4, zorder=3)
    ax.add_feature(borde_nacional, linestyle="-", edgecolor=color_blanco, linewidth=1.4, zorder=3)

    shapename = shpreader.natural_earth(
        resolution="10m", category="cultural", name="admin_1_states_provinces"
    )
    reader = shpreader.Reader(shapename)
    bolivia_states = [
        estado.geometry for estado in reader.records()
        if estado.attributes["admin"] == "Bolivia"
    ]
    ax.add_geometries(
        bolivia_states, crs=ccrs.PlateCarree(), facecolor="none",
        edgecolor=color_blanco, linestyle=(0, (1, 2)), linewidth=0.9, zorder=4,
    )

    for ciudad, info in localidades_final.items():
        ax.plot(
            info["lon"], info["lat"], marker="o", color="#E50001", markersize=4.5,
            markeredgecolor="white", markeredgewidth=1.0,
            transform=ccrs.PlateCarree(), zorder=10,
        )
        offset_lon = 0.08 if info["pos"] == "right" else (-0.08 if info["pos"] == "left" else 0)
        offset_lat = 0.08 if info["pos"] == "top" else (-0.12 if info["pos"] == "bottom" else -0.03)
        alignment_h = "left" if info["pos"] == "right" else ("right" if info["pos"] == "left" else "center")
        ax.text(
            info["lon"] + offset_lon, info["lat"] + offset_lat, ciudad, color="white",
            fontsize=7.5, fontweight="bold", horizontalalignment=alignment_h,
            transform=ccrs.PlateCarree(), zorder=11,
            path_effects=[patheffects.withStroke(linewidth=2, foreground="black")],
        )

    fecha_bot = fecha_utc - timedelta(hours=4)
    string_utc = fecha_utc.strftime("%d/%m/%Y %H:%M (Hora UTC)")
    string_bot = fecha_bot.strftime("%d/%m/%Y %H:%M (Hora Bolivia)")
    ax.set_title(
        f"Identificación de Nieve — {subtitulo_final} [Fuente: GOES-19]\n"
        f"{string_bot} — {string_utc}",
        fontsize=12.5, fontweight="bold", pad=14, loc="center", linespacing=1.3,
    )

    pos_mapa = ax.get_position()
    ax_leyenda = fig.add_axes([0.00, pos_mapa.y0 - 0.045, 1.00, 0.035])
    ax_leyenda.set_facecolor("#ffffff")
    ax_leyenda.set_xticks([])
    ax_leyenda.set_yticks([])
    parches_leyenda = [
        mpatches.Patch(color="#BE5050", label="Nieve"),
        mpatches.Patch(color="#DD84CE", label="Nube Hielo/Cirrus"),
        mpatches.Patch(color="#D6DCBB", label="Nube Agua/Niebla"),
        mpatches.Patch(color="#8F8A7A", label="Vegetación"),
        mpatches.Patch(color="#6EAE70", label="Suelo descubierto"),
        mpatches.Patch(color="#000000", label="Cuerpos de agua"),
        mpatches.Patch(color="#8E4151", label="Salar"),
    ]
    leyenda = ax_leyenda.legend(
        handles=parches_leyenda, loc="center", ncol=7, frameon=False, fontsize=8.0
    )
    for texto in leyenda.get_texts():
        texto.set_color("black")
        texto.set_weight("bold")

    try:
        ruta_ministerio = path_logos / "logo_ministerio.png"
        ruta_senamhi = path_logos / "logo_senamhi.png"
        if ruta_ministerio.exists() and ruta_senamhi.exists():
            ax_logo_min = fig.add_axes([pos_mapa.x0, pos_mapa.y1 + 0.005, 0.14, 0.07])
            ax_logo_min.imshow(mpimg.imread(ruta_ministerio))
            ax_logo_min.axis("off")
            ax_logo_sen = fig.add_axes([pos_mapa.x1 - 0.14, pos_mapa.y1 + 0.005, 0.14, 0.07])
            ax_logo_sen.imshow(mpimg.imread(ruta_senamhi))
            ax_logo_sen.axis("off")
    except Exception as error:
        print(f"Alerta logos: {error}")

    fig.savefig(ruta_salida, dpi=200, bbox_inches="tight", pad_inches=0.03)
    if mostrar:
        plt.show()
    plt.close(fig)
    return fecha_utc
