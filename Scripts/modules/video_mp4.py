"""Exportación de secuencias de cuadros PNG a video MP4.

No interviene en la composición cartográfica ni en el diseño del producto.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def crear_mp4(
    cuadros: Iterable[str | Path],
    ruta_salida: str | Path,
    *,
    fps: int = 4,
) -> Path:
    """Crea un MP4 H.264 a partir de una secuencia ordenada de PNG.

    ``cuadros`` debe llegar ya ordenado cronológicamente. Todos los cuadros
    deben compartir ancho y alto, tal como ocurre al reutilizar el mismo
    renderizador del producto institucional.
    """
    if fps <= 0:
        raise ValueError("fps debe ser un entero positivo.")

    rutas = [Path(cuadro) for cuadro in cuadros]
    if not rutas:
        raise ValueError("No hay cuadros para crear el video.")

    inexistentes = [str(ruta) for ruta in rutas if not ruta.is_file()]
    if inexistentes:
        raise FileNotFoundError(
            "No se encontraron estos cuadros: " + ", ".join(inexistentes)
        )

    try:
        import imageio.v2 as imageio
    except ImportError as error:
        raise ImportError(
            "Falta imageio para exportar MP4. Instala: pip install imageio[ffmpeg]"
        ) from error

    salida = Path(ruta_salida)
    salida.parent.mkdir(parents=True, exist_ok=True)

    with imageio.get_writer(
        salida,
        fps=fps,
        codec="libx264",
        pixelformat="yuv420p",
        macro_block_size=1,
    ) as video:
        for cuadro in rutas:
            video.append_data(imageio.imread(cuadro))

    return salida
