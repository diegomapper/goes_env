"""Utilidades temporales para animaciones de productos ABI GOES-19.

No renderiza mapas ni contiene elementos gráficos. Su responsabilidad es
encontrar, ordenar y descargar escenas MCMIP Full Disk de NOAA.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import s3fs


_PATRON_INICIO = re.compile(
    r"_s(?P<year>\d{4})(?P<doy>\d{3})(?P<hour>\d{2})"
    r"(?P<minute>\d{2})(?P<second>\d{2})\d"
)


@dataclass(frozen=True, order=True)
class EscenaGOES:
    """Una escena MCMIPF y su instante de inicio en UTC."""

    inicio_utc: datetime
    ruta_s3: str

    @property
    def nombre_archivo(self) -> str:
        return self.ruta_s3.rsplit("/", maxsplit=1)[-1]


def _como_utc(fecha: datetime) -> datetime:
    """Interpreta una fecha sin zona horaria como UTC."""
    if fecha.tzinfo is None:
        return fecha.replace(tzinfo=timezone.utc)
    return fecha.astimezone(timezone.utc)


def _inicio_desde_nombre(ruta_s3: str) -> datetime | None:
    coincidencia = _PATRON_INICIO.search(ruta_s3)
    if coincidencia is None:
        return None
    datos = coincidencia.groupdict()
    return datetime.strptime(
        "{year}{doy}{hour}{minute}{second}".format(**datos),
        "%Y%j%H%M%S",
    ).replace(tzinfo=timezone.utc)


def _horas_entre(inicio: datetime, fin: datetime) -> Iterable[datetime]:
    cursor = inicio.replace(minute=0, second=0, microsecond=0)
    while cursor <= fin:
        yield cursor
        cursor += timedelta(hours=1)


def listar_escenas_mcmipf(
    fecha_fin: datetime,
    duracion_horas: int,
    *,
    fs: s3fs.S3FileSystem | None = None,
    satelite: str = "goes19",
) -> list[EscenaGOES]:
    """Devuelve las escenas Full Disk disponibles en una ventana temporal.

    ``fecha_fin`` es UTC; puede ser naive y se interpretará como UTC. La ventana
    incluye ambas puntas. No supone que haya una escena cada diez minutos: usa
    solamente lo publicado por NOAA y las ordena por su hora real de inicio.
    """
    if duracion_horas <= 0:
        raise ValueError("duracion_horas debe ser un entero positivo.")

    fin = _como_utc(fecha_fin)
    inicio = fin - timedelta(hours=duracion_horas)
    filesystem = fs or s3fs.S3FileSystem(anon=True)

    rutas: set[str] = set()
    for hora in _horas_entre(inicio, fin):
        carpeta = (
            f"noaa-{satelite}/ABI-L2-MCMIPF/"
            f"{hora:%Y}/{hora:%j}/{hora:%H}/"
        )
        try:
            rutas.update(ruta for ruta in filesystem.ls(carpeta) if ruta.endswith(".nc"))
        except FileNotFoundError:
            # NOAA puede aún no haber publicado una hora reciente; se omite.
            continue

    escenas = [
        EscenaGOES(instante, ruta)
        for ruta in rutas
        if (instante := _inicio_desde_nombre(ruta)) is not None
        and inicio <= instante <= fin
    ]
    return sorted(escenas)


def descargar_escenas(
    escenas: Iterable[EscenaGOES],
    directorio_destino: str | Path,
    *,
    fs: s3fs.S3FileSystem | None = None,
) -> list[Path]:
    """Descarga solo escenas que no estén ya disponibles en disco."""
    destino = Path(directorio_destino)
    destino.mkdir(parents=True, exist_ok=True)
    filesystem = fs or s3fs.S3FileSystem(anon=True)
    locales: list[Path] = []

    for escena in escenas:
        archivo_local = destino / escena.nombre_archivo
        if not archivo_local.exists():
            filesystem.get(escena.ruta_s3, str(archivo_local))
        locales.append(archivo_local)

    return locales


def obtener_escena_mas_cercana(
    fecha_objetivo: datetime,
    directorio_destino: str | Path,
    *,
    fs: s3fs.S3FileSystem | None = None,
    satelite: str = "goes19",
) -> tuple[EscenaGOES, Path]:
    """Descarga la escena publicada más próxima a una hora objetivo UTC."""
    objetivo = _como_utc(fecha_objetivo)
    escenas = listar_escenas_mcmipf(
        objetivo + timedelta(minutes=30),
        2,
        fs=fs,
        satelite=satelite,
    )
    if not escenas:
        raise FileNotFoundError(
            f"NOAA no tiene escenas MCMIPF cercanas a {objetivo:%Y-%m-%d %H:%M UTC}."
        )
    escena = min(escenas, key=lambda item: abs(item.inicio_utc - objetivo))
    ruta_local = descargar_escenas([escena], directorio_destino, fs=fs)[0]
    return escena, ruta_local
