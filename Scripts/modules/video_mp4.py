"""Exportación de secuencias de cuadros PNG a video MP4.

No interviene en la composición cartográfica ni en el diseño del producto.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np


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

    primer_cuadro = imageio.imread(rutas[0])
    alto, ancho = primer_cuadro.shape[:2]

    def cuadro_con_dimensiones_pares(imagen: np.ndarray) -> np.ndarray:
        """Añade borde blanco técnico sin escalar la imagen institucional."""
        if imagen.shape[:2] != (alto, ancho):
            raise ValueError(
                "Todos los cuadros deben tener las mismas dimensiones. "
                f"Se esperaba {ancho}x{alto} y se recibió "
                f"{imagen.shape[1]}x{imagen.shape[0]}."
            )
        relleno_vertical = alto % 2
        relleno_horizontal = ancho % 2
        if not relleno_vertical and not relleno_horizontal:
            return imagen

        # Se conserva cada píxel del cuadro original. El borde blanco añadido
        # mide como máximo un píxel y cumple la restricción yuv420p de H.264.
        relleno = [(0, relleno_vertical), (0, relleno_horizontal)]
        relleno.extend([(0, 0)] * (imagen.ndim - 2))
        return np.pad(imagen, relleno, mode="constant", constant_values=255)

    with imageio.get_writer(
        salida,
        fps=fps,
        codec="libx264",
        pixelformat="yuv420p",
        macro_block_size=1,
    ) as video:
        video.append_data(cuadro_con_dimensiones_pares(primer_cuadro))
        for cuadro in rutas[1:]:
            video.append_data(cuadro_con_dimensiones_pares(imageio.imread(cuadro)))

    return salida
