"""Utilidades temporales para animaciones de productos ABI GOES-19.

No renderiza mapas ni contiene elementos gráficos. Su responsabilidad es
encontrar, ordenar y descargar escenas MCMIP Full Disk de NOAA.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import s3fs
import xarray as xr


_PATRON_INICIO = re.compile(
    r"_s(?P<year>\d{4})(?P<doy>\d{3})(?P<hour>\d{2})"
    r"(?P<minute>\d{2})(?P<second>\d{2})\d"
)


def _crear_s3fs() -> s3fs.S3FileSystem:
    """Crea una conexión NOAA tolerante a descargas Full Disk extensas."""
    return s3fs.S3FileSystem(
        anon=True,
        config_kwargs={
            "connect_timeout": 30,
            "read_timeout": 300,
            "retries": {"max_attempts": 5, "mode": "standard"},
        },
    )


def _es_escena_abi_valida(archivo: Path) -> bool:
    """Comprueba que un archivo local sea un NetCDF4 ABI abrible por xarray."""
    try:
        with xr.open_dataset(archivo, engine="netcdf4") as dataset:
            bandas_requeridas = {"CMI_C03", "CMI_C05", "CMI_C07", "CMI_C13"}
            return bandas_requeridas.issubset(dataset.variables)
    except Exception:
        return False


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
    filesystem = fs or _crear_s3fs()

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
    reintentos: int = 4,
    pausa_inicial_segundos: int = 8,
) -> list[Path]:
    """Descarga escenas completas y reintenta ante fallos transitorios de red.

    Cada descarga usa un archivo temporal ``.part``. Solo se convierte en el
    NetCDF final después de validar su tamaño contra el objeto publicado por
    NOAA, por lo que una descarga interrumpida no queda como archivo reutilizable.
    """
    if reintentos < 1:
        raise ValueError("reintentos debe ser al menos 1.")
    destino = Path(directorio_destino)
    destino.mkdir(parents=True, exist_ok=True)
    filesystem = fs or _crear_s3fs()
    locales: list[Path] = []

    for escena in escenas:
        archivo_local = destino / escena.nombre_archivo
        tamano_remoto = filesystem.info(escena.ruta_s3).get("size")
        archivo_completo = (
            archivo_local.exists()
            and (tamano_remoto is None or archivo_local.stat().st_size == tamano_remoto)
            and _es_escena_abi_valida(archivo_local)
        )

        if not archivo_completo:
            archivo_temporal = archivo_local.with_suffix(archivo_local.suffix + ".part")

            for intento in range(1, reintentos + 1):
                archivo_temporal.unlink(missing_ok=True)
                try:
                    print(
                        f"Descargando {escena.nombre_archivo} "
                        f"(intento {intento}/{reintentos})..."
                    )
                    filesystem.get(escena.ruta_s3, str(archivo_temporal))

                    if tamano_remoto is not None and archivo_temporal.stat().st_size != tamano_remoto:
                        raise IOError(
                            "La descarga terminó con un tamaño distinto al publicado por NOAA."
                        )
                    if not _es_escena_abi_valida(archivo_temporal):
                        raise IOError(
                            "La descarga no contiene una escena NetCDF4 ABI válida."
                        )

                    archivo_temporal.replace(archivo_local)
                    break
                except Exception as error:
                    archivo_temporal.unlink(missing_ok=True)
                    if intento == reintentos:
                        raise ConnectionError(
                            f"No se pudo descargar {escena.nombre_archivo} tras "
                            f"{reintentos} intentos."
                        ) from error

                    espera = pausa_inicial_segundos * (2 ** (intento - 1))
                    print(f"Descarga interrumpida; reintentando en {espera} segundos...")
                    time.sleep(espera)
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
