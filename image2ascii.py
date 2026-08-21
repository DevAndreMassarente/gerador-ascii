#!/usr/bin/env python3
"""Gerador de arte ASCII/ANSI, half-block e Braille a partir de imagens."""

from __future__ import annotations

import argparse
import html
import io
import math
import os
import re
import sys
import tempfile
import unicodedata
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

try:
    from PIL import (
        Image,
        ImageChops,
        ImageColor,
        ImageEnhance,
        ImageFilter,
        ImageOps,
        ImageStat,
        UnidentifiedImageError,
    )
except ImportError as exc:  # Permite que --help/--version funcionem.
    PILLOW_IMPORT_ERROR: ImportError | None = exc
else:
    PILLOW_IMPORT_ERROR = None


VERSION = "2.0.0"
RESET = "\x1b[0m"
RESET_FG = "\x1b[39m"
RESET_BG = "\x1b[49m"

DEFAULT_WIDTH = 100
MAX_GRID_DIMENSION = 10_000
MAX_GRID_CELLS = 2_000_000
MAX_INPUT_PIXELS = 80_000_000

RGB = tuple[int, int, int]

CHARSETS = {
    "standard": " .:-=+*#%@",
    "dense": " .'`^\",:;Il!i~+_-?][}{1)(|\\/*tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
    "simple": " .:-=+*#@",
    "minimal": " .:+#@",
    "blocks": " ░▒▓█",
    "binary": " @",
}

STYLE_DEFAULTS = {
    "normal": {"contrast": 1.10, "brightness": 1.00, "gamma": 1.00, "edges": 0.12},
    "photo": {"contrast": 1.05, "brightness": 1.00, "gamma": 1.00, "edges": 0.06},
    "logo": {"contrast": 1.28, "brightness": 1.00, "gamma": 0.95, "edges": 0.22},
    "lineart": {"contrast": 1.42, "brightness": 1.02, "gamma": 0.90, "edges": 0.34},
}

STYLE_CHARSETS = {
    "normal": "dense",
    "photo": "dense",
    "logo": "standard",
    "lineart": "standard",
}


@dataclass(frozen=True, slots=True)
class Cell:
    """Uma celula renderizada, ainda independente do formato de saida."""

    char: str = " "
    fg: RGB | None = None
    bg: RGB | None = None


@dataclass(slots=True)
class Artwork:
    """Grade final e cor usada para compor transparencias."""

    rows: list[list[Cell]]
    background: RGB

    @property
    def width(self) -> int:
        return max((len(row) for row in self.rows), default=0)

    @property
    def height(self) -> int:
        return len(self.rows)


def parse_size(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", value)
    if not match:
        raise argparse.ArgumentTypeError("use COLUNASxLINHAS, por exemplo 100x50 ou 70x35")
    width, height = int(match.group(1)), int(match.group(2))
    if width < 1 or height < 1:
        raise argparse.ArgumentTypeError("largura e altura devem ser maiores que zero")
    return width, height


def parse_rgb(value: str) -> RGB:
    """Aceita nomes CSS/Pillow, #RRGGBB, #RGB e rgb(...)."""

    if PILLOW_IMPORT_ERROR is not None:
        raise argparse.ArgumentTypeError(
            "a leitura de cores requer Pillow; instale com: pip install Pillow"
        )
    try:
        rgb = ImageColor.getrgb(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            f"cor invalida: {value!r}. Exemplos: red, #ff2020, rgb(255,32,32)"
        ) from exc
    return tuple(int(channel) for channel in rgb[:3])


def parse_background(value: str) -> str | RGB:
    if value.strip().lower() == "auto":
        return "auto"
    return parse_rgb(value)


def positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use um numero inteiro") from exc
    if result < 1:
        raise argparse.ArgumentTypeError("o valor deve ser maior que zero")
    return result


def nonnegative_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use um numero inteiro") from exc
    if result < 0:
        raise argparse.ArgumentTypeError("o valor nao pode ser negativo")
    return result


def finite_positive(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use um numero real") from exc
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("o valor deve ser finito e maior que zero")
    return result


def finite_nonnegative(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use um numero real") from exc
    if not math.isfinite(result) or result < 0:
        raise argparse.ArgumentTypeError("o valor deve ser finito e nao negativo")
    return result


def unit_float(value: str) -> float:
    result = finite_nonnegative(value)
    if result > 1:
        raise argparse.ArgumentTypeError("o valor deve estar entre 0 e 1")
    return result


def byte_value(value: str) -> int:
    result = nonnegative_int(value)
    if result > 255:
        raise argparse.ArgumentTypeError("o valor deve estar entre 0 e 255")
    return result


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def image_data(image: Image.Image):
    """Compatibilidade entre Pillow 10/11 e a API nova do Pillow 12+."""

    flattened = getattr(image, "get_flattened_data", None)
    return flattened() if flattened is not None else image.getdata()


def validate_charset(charset: str) -> str:
    if len(charset) < 2:
        raise ValueError("o charset precisa ter pelo menos 2 caracteres")
    for char in charset:
        category = unicodedata.category(char)
        if (
            category.startswith("C")
            or (category.startswith("Z") and char != " ")
            or char in "\r\n\t\x1b"
        ):
            raise ValueError("o charset nao pode conter controles, ANSI ou quebras de linha")
        if unicodedata.combining(char) or unicodedata.east_asian_width(char) in {"W", "F"}:
            raise ValueError(f"o caractere {char!r} nao ocupa exatamente uma coluna de terminal")
    return charset


def border_mean_luma(image: Image.Image) -> float:
    grayscale = image.convert("L")
    width, height = grayscale.size
    border_width = max(1, min(width // 20, 8))
    border_height = max(1, min(height // 20, 8))
    pieces = [
        grayscale.crop((0, 0, width, border_height)),
        grayscale.crop((0, height - border_height, width, height)),
        grayscale.crop((0, 0, border_width, height)),
        grayscale.crop((width - border_width, 0, width, height)),
    ]
    return sum(ImageStat.Stat(piece).mean[0] for piece in pieces) / len(pieces)


def visible_mean_luma(image_rgba: Image.Image) -> float | None:
    """Media de brilho ponderada pelo alpha, amostrada para manter custo baixo."""

    sample = image_rgba.copy()
    sample.thumbnail((160, 160), Image.Resampling.BOX)
    weighted_luma = 0.0
    alpha_sum = 0
    for red, green, blue, alpha in image_data(sample):
        if alpha:
            weighted_luma += (0.2126 * red + 0.7152 * green + 0.0722 * blue) * alpha
            alpha_sum += alpha
    return weighted_luma / alpha_sum if alpha_sum else None


def transparency_fraction(image_rgba: Image.Image) -> float:
    """Fracao media de transparencia, amostrada para ignorar alpha acidental."""

    alpha = image_rgba.getchannel("A")
    alpha.thumbnail((160, 160), Image.Resampling.BOX)
    values = image_data(alpha)
    missing_opacity = sum(255 - value for value in values)
    pixel_count = alpha.width * alpha.height
    return missing_opacity / (255 * pixel_count) if pixel_count else 0.0


def choose_background(
    image_rgba: Image.Image,
    polarity: str = "auto",
    background: str | RGB = "auto",
) -> RGB:
    if background != "auto":
        return background
    if polarity == "light":
        return (255, 255, 255)
    if polarity == "dark":
        return (0, 0, 0)

    if transparency_fraction(image_rgba) >= 0.01:
        visible_luma = visible_mean_luma(image_rgba)
        if visible_luma is None:
            return (0, 0, 0)
        return (255, 255, 255) if visible_luma < 128 else (0, 0, 0)

    return (255, 255, 255) if border_mean_luma(image_rgba.convert("RGB")) >= 145 else (0, 0, 0)


def flatten_alpha(image_rgba: Image.Image, background: str | RGB) -> Image.Image:
    if isinstance(background, str):
        color = (255, 255, 255) if background == "white" else (0, 0, 0)
    else:
        color = background
    canvas = Image.new("RGBA", image_rgba.size, (*color, 255))
    canvas.alpha_composite(image_rgba)
    return canvas.convert("RGB")


def as_rgba(image: Image.Image) -> Image.Image:
    return image if image.mode == "RGBA" else image.convert("RGBA")


def resize_rgba(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Redimensiona em alpha pre-multiplicado para evitar halos coloridos."""

    if image.size == size:
        return image.copy()
    premultiplied = image.convert("RGBa")
    return premultiplied.resize(size, Image.Resampling.LANCZOS).convert("RGBA")


def resolve_grid(
    src_width: int,
    src_height: int,
    size: tuple[int, int] | None,
    width: int | None,
    height: int | None,
    aspect: float,
) -> tuple[int, int]:
    if size:
        return size
    if width and height:
        return width, height
    if width:
        return width, max(1, round(width * (src_height / src_width) * aspect))
    if height:
        return max(1, round(height * (src_width / src_height) / aspect)), height
    width = DEFAULT_WIDTH
    return width, max(1, round(width * (src_height / src_width) * aspect))


def validate_grid(
    cols: int,
    rows: int,
    allow_large: bool = False,
    sample_multiplier: int = 1,
) -> None:
    if cols < 1 or rows < 1:
        raise ValueError("a grade precisa ter dimensoes positivas")
    if sample_multiplier < 1:
        raise ValueError("o multiplicador de amostras deve ser positivo")
    if allow_large:
        return
    if cols > MAX_GRID_DIMENSION or rows > MAX_GRID_DIMENSION:
        raise ValueError(
            f"cada dimensao deve ter no maximo {MAX_GRID_DIMENSION:,} (use --allow-large para liberar)"
        )
    if cols * rows * sample_multiplier > MAX_GRID_CELLS:
        raise ValueError(
            f"a renderizacao excede {MAX_GRID_CELLS:,} amostras "
            "(reduza a grade ou use --allow-large)"
        )


def fit_dimensions(
    src_width: int,
    src_height: int,
    cols: int,
    rows: int,
    aspect: float,
    fit: str,
) -> tuple[int, int]:
    if fit in {"stretch", "cover"}:
        return cols, rows
    source_ratio = src_width / src_height
    rows_at_full_width = cols * aspect / source_ratio
    if rows_at_full_width <= rows:
        draw_cols = cols
        draw_rows = max(1, round(rows_at_full_width))
    else:
        draw_rows = rows
        draw_cols = max(1, round(rows * source_ratio / aspect))
    return min(cols, draw_cols), min(rows, draw_rows)


def crop_for_cover(
    image: Image.Image,
    cols: int,
    rows: int,
    aspect: float,
) -> Image.Image:
    target_ratio = (cols * aspect) / rows
    width, height = image.size
    source_ratio = width / height
    if math.isclose(source_ratio, target_ratio, rel_tol=1e-9):
        return image
    if source_ratio > target_ratio:
        new_width = max(1, round(height * target_ratio))
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    new_height = max(1, round(width / target_ratio))
    top = (height - new_height) // 2
    return image.crop((0, top, width, top + new_height))


def apply_gamma(image_l: Image.Image, gamma: float) -> Image.Image:
    gamma = max(0.05, gamma)
    inverse = 1.0 / gamma
    table = [round((value / 255.0) ** inverse * 255.0) for value in range(256)]
    return image_l.point(table)


def process_luma(
    image_rgb: Image.Image,
    contrast: float,
    brightness: float,
    gamma: float,
    edges: float,
    invert: bool,
) -> Image.Image:
    """Produz densidade: 0 e vazio, 255 e o glifo mais pesado."""

    luminance = ImageOps.grayscale(image_rgb)
    luminance = ImageEnhance.Contrast(luminance).enhance(contrast)
    luminance = ImageEnhance.Brightness(luminance).enhance(brightness)
    luminance = apply_gamma(luminance, gamma)
    density = ImageOps.invert(luminance) if invert else luminance
    amount = clamp(edges, 0.0, 1.0)
    if amount and luminance.width > 2 and luminance.height > 2:
        edge_image = luminance.filter(ImageFilter.FIND_EDGES)
        edge_image.paste(0, (0, 0, edge_image.width, 1))
        edge_image.paste(0, (0, edge_image.height - 1, edge_image.width, edge_image.height))
        edge_image.paste(0, (0, 0, 1, edge_image.height))
        edge_image.paste(0, (edge_image.width - 1, 0, edge_image.width, edge_image.height))
        _, high = edge_image.getextrema()
        if high > 12:
            # Corte fixo evita transformar ringing/ruido minimo em contorno forte.
            edge_image = edge_image.point(
                [0 if value <= 12 else round((value - 12) * 255 / 243) for value in range(256)]
            )
            edge_image = ImageEnhance.Contrast(edge_image).enhance(1.25)
            detailed = ImageChops.lighter(density, edge_image)
            density = Image.blend(density, detailed, amount)
    return density


def auto_invert(image_rgb: Image.Image, polarity: str) -> bool:
    if polarity == "dark":
        return False
    if polarity == "light":
        return True
    return border_mean_luma(image_rgb) >= 145


def quantize_density(
    density: Image.Image,
    levels: int,
    dither: str,
    threshold: int,
    alpha: Image.Image | None = None,
    alpha_threshold: int = 0,
    binary_cutoff: bool = False,
) -> list[int]:
    """Retorna indices de nivel; -1 representa uma celula transparente/vazia."""

    width, height = density.size
    values = [float(value) for value in image_data(density)]
    if binary_cutoff and dither == "floyd-steinberg":
        if threshold >= 255:
            values = [0.0] * len(values)
        else:
            scale = 255.0 / (255 - threshold)
            values = [
                0.0 if value <= threshold else (value - threshold) * scale for value in values
            ]
    alphas = list(image_data(alpha)) if alpha is not None else [255] * len(values)
    result = [-1] * len(values)
    step = 255.0 / max(1, levels - 1)
    bayer = (
        (0, 8, 2, 10),
        (12, 4, 14, 6),
        (3, 11, 1, 9),
        (15, 7, 13, 5),
    )
    for y in range(height):
        for x in range(width):
            index = y * width + x
            if alphas[index] == 0 or alphas[index] < alpha_threshold:
                continue
            value = values[index]
            if dither == "ordered" and not binary_cutoff:
                offset = ((bayer[y % 4][x % 4] + 0.5) / 16.0 - 0.5) * step
                value = clamp(value + offset, 0.0, 255.0)
            if binary_cutoff:
                if dither == "ordered" and value > threshold and threshold < 255:
                    coverage = (value - threshold) / (255 - threshold)
                    active = coverage > (bayer[y % 4][x % 4] + 0.5) / 16.0
                elif dither == "floyd-steinberg":
                    active = value >= 127.5
                else:
                    active = value > threshold
                quantized = 255 if active else 0
                result[index] = 1 if active else -1
            elif value <= threshold:
                quantized = 0
                result[index] = -1
            else:
                level = max(0, min(levels - 1, round(value / step)))
                quantized = level * step
                result[index] = level
            if dither != "floyd-steinberg":
                continue
            error = value - quantized
            for dx, dy, weight in (
                (1, 0, 7 / 16),
                (-1, 1, 3 / 16),
                (0, 1, 5 / 16),
                (1, 1, 1 / 16),
            ):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and ny < height:
                    neighbor = ny * width + nx
                    if alphas[neighbor] > 0 and alphas[neighbor] >= alpha_threshold:
                        values[neighbor] = clamp(values[neighbor] + error * weight, 0, 255)
    return result


def tint_by_luma(base: RGB, luma: int, floor: float = 0.10) -> RGB:
    factor = floor + (1.0 - floor) * (luma / 255.0)
    return tuple(max(0, min(255, round(channel * factor))) for channel in base)


def _style_values(
    style: str,
    contrast: float | None,
    brightness: float | None,
    gamma: float | None,
    edges: float | None,
) -> tuple[float, float, float, float]:
    defaults = STYLE_DEFAULTS[style]
    return (
        defaults["contrast"] if contrast is None else contrast,
        defaults["brightness"] if brightness is None else brightness,
        defaults["gamma"] if gamma is None else gamma,
        defaults["edges"] if edges is None else edges,
    )


def _prepare_image(
    original: Image.Image,
    size: tuple[int, int],
    *,
    background: RGB,
    style: str,
    contrast: float | None,
    brightness: float | None,
    gamma: float | None,
    edges: float | None,
    polarity: str,
    invert_flag: bool,
    disable_auto_invert: bool,
) -> tuple[Image.Image, Image.Image, Image.Image]:
    resized = resize_rgba(original, size)
    color_rgb = flatten_alpha(resized, background)
    contrast_value, brightness_value, gamma_value, edge_value = _style_values(
        style, contrast, brightness, gamma, edges
    )
    invert = invert_flag
    if polarity == "auto":
        if not disable_auto_invert:
            invert ^= auto_invert(color_rgb, polarity)
    else:
        invert ^= polarity == "light"
    density = process_luma(
        color_rgb,
        contrast_value,
        brightness_value,
        gamma_value,
        edge_value,
        invert,
    )
    return resized, color_rgb, density


def _padding(cols: int, rows: int, draw_cols: int, draw_rows: int) -> tuple[int, int, int, int]:
    left = (cols - draw_cols) // 2
    right = cols - draw_cols - left
    top = (rows - draw_rows) // 2
    bottom = rows - draw_rows - top
    return left, right, top, bottom


def _with_padding(
    content: list[list[Cell]],
    cols: int,
    rows: int,
    draw_cols: int,
    draw_rows: int,
) -> list[list[Cell]]:
    left, right, top, bottom = _padding(cols, rows, draw_cols, draw_rows)
    blank_row = [Cell()] * cols
    padded = [blank_row.copy() for _ in range(top)]
    padded.extend([[Cell()] * left + row + [Cell()] * right for row in content])
    padded.extend([blank_row.copy() for _ in range(bottom)])
    return padded


def render_ascii_art(
    original: Image.Image,
    *,
    cols: int,
    rows: int,
    aspect: float,
    fit: str,
    charset: str,
    color_mode: str,
    mono_color: RGB,
    style: str,
    contrast: float | None,
    brightness: float | None,
    gamma: float | None,
    edges: float | None,
    polarity: str,
    threshold: int,
    alpha_threshold: int,
    invert_flag: bool,
    disable_auto_invert: bool,
    dither: str = "none",
    background: str | RGB = "auto",
    mono_shading: bool = False,
) -> Artwork:
    original = as_rgba(original)
    draw_cols, draw_rows = fit_dimensions(original.width, original.height, cols, rows, aspect, fit)
    source = crop_for_cover(original, draw_cols, draw_rows, aspect) if fit == "cover" else original
    background_rgb = choose_background(original, polarity, background)
    resized, color_rgb, density = _prepare_image(
        source,
        (draw_cols, draw_rows),
        background=background_rgb,
        style=style,
        contrast=contrast,
        brightness=brightness,
        gamma=gamma,
        edges=edges,
        polarity=polarity,
        invert_flag=invert_flag,
        disable_auto_invert=disable_auto_invert,
    )
    alpha = resized.getchannel("A")
    levels = quantize_density(density, len(charset), dither, threshold, alpha, alpha_threshold)
    colors = color_rgb.load()
    density_pixels = density.load()
    content: list[list[Cell]] = []
    for y in range(draw_rows):
        row: list[Cell] = []
        for x in range(draw_cols):
            level = levels[y * draw_cols + x]
            if level < 0 or charset[level] == " ":
                row.append(Cell())
                continue
            if color_mode == "image":
                pixel = colors[x, y]
                foreground: RGB | None = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
            elif color_mode == "mono":
                foreground = (
                    tint_by_luma(mono_color, int(density_pixels[x, y]))
                    if mono_shading
                    else mono_color
                )
            else:
                foreground = None
            row.append(Cell(charset[level], foreground))
        content.append(row)
    return Artwork(_with_padding(content, cols, rows, draw_cols, draw_rows), background_rgb)


def render_halfblock_art(
    original: Image.Image,
    *,
    cols: int,
    rows: int,
    aspect: float,
    fit: str,
    color_mode: str,
    mono_color: RGB,
    style: str = "normal",
    contrast: float | None = None,
    brightness: float | None = None,
    gamma: float | None = None,
    edges: float | None = None,
    polarity: str = "auto",
    threshold: int = 128,
    alpha_threshold: int = 12,
    invert_flag: bool = False,
    disable_auto_invert: bool = False,
    dither: str = "none",
    background: str | RGB = "auto",
    mono_shading: bool = False,
) -> Artwork:
    original = as_rgba(original)
    draw_cols, draw_rows = fit_dimensions(original.width, original.height, cols, rows, aspect, fit)
    source = crop_for_cover(original, draw_cols, draw_rows, aspect) if fit == "cover" else original
    background_rgb = choose_background(original, polarity, background)
    raster_size = (draw_cols, draw_rows * 2)
    if color_mode == "image":
        # Cada metade preserva a amostra RGB; densidade e dither seriam descartados.
        resized = resize_rgba(source, raster_size)
        color_rgb = flatten_alpha(resized, background_rgb)
        density = None
    else:
        resized, color_rgb, density = _prepare_image(
            source,
            raster_size,
            background=background_rgb,
            style=style,
            contrast=contrast,
            brightness=brightness,
            gamma=gamma,
            edges=edges,
            polarity=polarity,
            invert_flag=invert_flag,
            disable_auto_invert=disable_auto_invert,
        )
    alpha = resized.getchannel("A")
    binary = (
        None
        if density is None
        else quantize_density(
            density,
            2,
            dither,
            threshold,
            alpha,
            alpha_threshold,
            binary_cutoff=True,
        )
    )
    alpha_pixels = alpha.load()
    color_pixels = color_rgb.load()
    density_pixels = density.load() if density is not None else None

    def is_visible(x: int, y: int) -> bool:
        if alpha_pixels[x, y] == 0 or alpha_pixels[x, y] < alpha_threshold:
            return False
        if color_mode == "image":
            return True
        assert binary is not None
        return binary[y * draw_cols + x] == 1

    def pixel_color(x: int, y: int) -> RGB:
        if color_mode == "image":
            pixel = color_pixels[x, y]
            return int(pixel[0]), int(pixel[1]), int(pixel[2])
        if mono_shading:
            assert density_pixels is not None
            return tint_by_luma(mono_color, int(density_pixels[x, y]))
        return mono_color

    content: list[list[Cell]] = []
    for row_index in range(draw_rows):
        top_y = row_index * 2
        bottom_y = top_y + 1
        row: list[Cell] = []
        for x in range(draw_cols):
            top_visible = is_visible(x, top_y)
            bottom_visible = is_visible(x, bottom_y)
            if not top_visible and not bottom_visible:
                row.append(Cell())
            elif color_mode == "none":
                char = "█" if top_visible and bottom_visible else "▀" if top_visible else "▄"
                row.append(Cell(char))
            elif top_visible and bottom_visible:
                top_color = pixel_color(x, top_y)
                bottom_color = pixel_color(x, bottom_y)
                row.append(
                    Cell("█", top_color)
                    if top_color == bottom_color
                    else Cell("▀", top_color, bottom_color)
                )
            elif top_visible:
                row.append(Cell("▀", pixel_color(x, top_y)))
            else:
                row.append(Cell("▄", pixel_color(x, bottom_y)))
        content.append(row)
    return Artwork(_with_padding(content, cols, rows, draw_cols, draw_rows), background_rgb)


BRAILLE_BITS = {
    (0, 0): 0x01,
    (0, 1): 0x02,
    (0, 2): 0x04,
    (1, 0): 0x08,
    (1, 1): 0x10,
    (1, 2): 0x20,
    (0, 3): 0x40,
    (1, 3): 0x80,
}


def render_braille_art(
    original: Image.Image,
    *,
    cols: int,
    rows: int,
    aspect: float,
    fit: str,
    color_mode: str,
    mono_color: RGB,
    style: str,
    contrast: float | None,
    brightness: float | None,
    gamma: float | None,
    edges: float | None,
    polarity: str,
    braille_threshold: int,
    alpha_threshold: int,
    invert_flag: bool,
    disable_auto_invert: bool,
    dither: str = "none",
    background: str | RGB = "auto",
    mono_shading: bool = False,
) -> Artwork:
    original = as_rgba(original)
    draw_cols, draw_rows = fit_dimensions(original.width, original.height, cols, rows, aspect, fit)
    source = crop_for_cover(original, draw_cols, draw_rows, aspect) if fit == "cover" else original
    background_rgb = choose_background(original, polarity, background)
    pixel_width, pixel_height = draw_cols * 2, draw_rows * 4
    resized, color_rgb, density = _prepare_image(
        source,
        (pixel_width, pixel_height),
        background=background_rgb,
        style=style,
        contrast=contrast,
        brightness=brightness,
        gamma=gamma,
        edges=edges,
        polarity=polarity,
        invert_flag=invert_flag,
        disable_auto_invert=disable_auto_invert,
    )
    alpha = resized.getchannel("A")
    binary = quantize_density(
        density,
        2,
        dither,
        braille_threshold,
        alpha,
        alpha_threshold,
        binary_cutoff=True,
    )
    color_pixels = color_rgb.load()
    density_pixels = density.load()
    content: list[list[Cell]] = []
    for cell_y in range(draw_rows):
        row: list[Cell] = []
        for cell_x in range(draw_cols):
            bits = 0
            active_colors: list[RGB] = []
            active_luma: list[int] = []
            for dot_y in range(4):
                for dot_x in range(2):
                    x, y = cell_x * 2 + dot_x, cell_y * 4 + dot_y
                    if binary[y * pixel_width + x] != 1:
                        continue
                    bits |= BRAILLE_BITS[(dot_x, dot_y)]
                    pixel = color_pixels[x, y]
                    active_colors.append((int(pixel[0]), int(pixel[1]), int(pixel[2])))
                    active_luma.append(int(density_pixels[x, y]))
            if not bits:
                row.append(Cell())
                continue
            if color_mode == "image":
                foreground = tuple(
                    round(sum(color[channel] for color in active_colors) / len(active_colors))
                    for channel in range(3)
                )
            elif color_mode == "mono":
                foreground = (
                    tint_by_luma(mono_color, round(sum(active_luma) / len(active_luma)))
                    if mono_shading
                    else mono_color
                )
            else:
                foreground = None
            row.append(Cell(chr(0x2800 + bits), foreground))
        content.append(row)
    return Artwork(_with_padding(content, cols, rows, draw_cols, draw_rows), background_rgb)


ANSI16 = (
    (0, 0, 0, 30),
    (205, 49, 49, 31),
    (13, 188, 121, 32),
    (229, 229, 16, 33),
    (36, 114, 200, 34),
    (188, 63, 188, 35),
    (17, 168, 205, 36),
    (229, 229, 229, 37),
    (102, 102, 102, 90),
    (241, 76, 76, 91),
    (35, 209, 139, 92),
    (245, 245, 67, 93),
    (59, 142, 234, 94),
    (214, 112, 214, 95),
    (41, 184, 219, 96),
    (255, 255, 255, 97),
)


def _xterm_palette() -> tuple[tuple[int, int, int, int], ...]:
    # ANSI16 guarda codigos SGR (30..37/90..97); ANSI-256 usa indices 0..15.
    palette = [(*color[:3], index) for index, color in enumerate(ANSI16)]
    levels = (0, 95, 135, 175, 215, 255)
    for red_index, red in enumerate(levels):
        for green_index, green in enumerate(levels):
            for blue_index, blue in enumerate(levels):
                code = 16 + 36 * red_index + 6 * green_index + blue_index
                palette.append((red, green, blue, code))
    palette.extend(
        (value, value, value, 232 + index) for index, value in enumerate(range(8, 239, 10))
    )
    return tuple(palette)


ANSI256_PALETTE = _xterm_palette()
XTERM_LEVELS = (0, 95, 135, 175, 215, 255)
XTERM_NEAREST_LEVELS = tuple(
    tuple(sorted(range(6), key=lambda index: abs(value - XTERM_LEVELS[index]))[:2])
    for value in range(256)
)


def _color_distance(left: RGB, right: RGB) -> float:
    red_mean = (left[0] + right[0]) / 2
    red_delta = left[0] - right[0]
    green_delta = left[1] - right[1]
    blue_delta = left[2] - right[2]
    return (
        (2 + red_mean / 256) * red_delta * red_delta
        + 4 * green_delta * green_delta
        + (2 + (255 - red_mean) / 256) * blue_delta * blue_delta
    )


@lru_cache(maxsize=65_536)
def ansi256_code(red: int, green: int, blue: int) -> int:
    rgb = (red, green, blue)
    # O mais proximo so pode estar nos niveis vizinhos do cubo, na escala de
    # cinza ou nas 16 cores base. Isso preserva a busca perceptual e evita uma
    # varredura de 256 entradas para cada RGB unico.
    candidates = list(ANSI256_PALETTE[:16])
    for red_index in XTERM_NEAREST_LEVELS[red]:
        for green_index in XTERM_NEAREST_LEVELS[green]:
            for blue_index in XTERM_NEAREST_LEVELS[blue]:
                code = 16 + 36 * red_index + 6 * green_index + blue_index
                candidates.append(
                    (
                        XTERM_LEVELS[red_index],
                        XTERM_LEVELS[green_index],
                        XTERM_LEVELS[blue_index],
                        code,
                    )
                )
    candidates.extend(ANSI256_PALETTE[232:])
    return min(candidates, key=lambda color: _color_distance(rgb, color[:3]))[3]


@lru_cache(maxsize=65_536)
def ansi16_code(red: int, green: int, blue: int) -> int:
    rgb = (red, green, blue)
    return min(ANSI16, key=lambda color: _color_distance(rgb, color[:3]))[3]


def fg_escape(rgb: RGB, ansi: str) -> str:
    red, green, blue = rgb
    if ansi == "truecolor":
        return f"\x1b[38;2;{red};{green};{blue}m"
    if ansi == "ansi256":
        return f"\x1b[38;5;{ansi256_code(red, green, blue)}m"
    return f"\x1b[{ansi16_code(red, green, blue)}m"


def bg_escape(rgb: RGB, ansi: str) -> str:
    red, green, blue = rgb
    if ansi == "truecolor":
        return f"\x1b[48;2;{red};{green};{blue}m"
    if ansi == "ansi256":
        return f"\x1b[48;5;{ansi256_code(red, green, blue)}m"
    return f"\x1b[{ansi16_code(red, green, blue) + 10}m"


def _trim_row(row: Sequence[Cell], keep_trailing_spaces: bool) -> Sequence[Cell]:
    if keep_trailing_spaces:
        return row
    end = len(row)
    while end and row[end - 1] == Cell():
        end -= 1
    return row[:end]


def artwork_to_terminal_lines(
    artwork: Artwork,
    ansi: str = "truecolor",
    keep_trailing_spaces: bool = False,
    paint_background: bool = False,
) -> list[str]:
    lines: list[str] = []
    for complete_row in artwork.rows:
        row = complete_row if paint_background else _trim_row(complete_row, keep_trailing_spaces)
        parts: list[str] = []
        current_fg: str | None = None
        current_bg: str | None = None
        for cell in row:
            target_fg = fg_escape(cell.fg, ansi) if cell.fg is not None else None
            background = cell.bg
            if background is None and paint_background:
                background = artwork.background
            target_bg = bg_escape(background, ansi) if background is not None else None
            if target_fg != current_fg:
                parts.append(target_fg if target_fg is not None else RESET_FG)
                current_fg = target_fg
            if target_bg != current_bg:
                parts.append(target_bg if target_bg is not None else RESET_BG)
                current_bg = target_bg
            parts.append(cell.char)
        if current_fg is not None or current_bg is not None:
            parts.append(RESET)
        lines.append("".join(parts))
    return lines


def artwork_to_text_lines(artwork: Artwork, keep_trailing_spaces: bool = False) -> list[str]:
    return [
        "".join(cell.char for cell in _trim_row(row, keep_trailing_spaces)) for row in artwork.rows
    ]


def _css_color(color: RGB) -> str:
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"


def artwork_to_html(
    artwork: Artwork,
    *,
    title: str = "Arte ASCII",
    keep_trailing_spaces: bool = False,
) -> str:
    background = artwork.background
    foreground = (245, 245, 245) if sum(background) < 384 else (20, 20, 20)
    rendered_lines: list[str] = []
    for complete_row in artwork.rows:
        row = list(_trim_row(complete_row, keep_trailing_spaces))
        parts: list[str] = []
        index = 0
        while index < len(row):
            cell = row[index]
            end = index + 1
            while end < len(row) and row[end].fg == cell.fg and row[end].bg == cell.bg:
                end += 1
            content = html.escape("".join(item.char for item in row[index:end]))
            styles = []
            if cell.fg is not None:
                styles.append(f"color:{_css_color(cell.fg)}")
            if cell.bg is not None:
                styles.append(f"background:{_css_color(cell.bg)}")
            if styles:
                parts.append(f'<span style="{";".join(styles)}">{content}</span>')
            else:
                parts.append(content)
            index = end
        rendered_lines.append("".join(parts))
    safe_title = html.escape(title)
    art = "\n".join(rendered_lines)
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{ color-scheme: light dark; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; overflow: auto;
      background: {_css_color(background)}; color: {_css_color(foreground)}; }}
    pre {{ margin: 0; padding: 1.5rem; font: 14px/1 ui-monospace, SFMono-Regular, Menlo,
      Monaco, Consolas, "Liberation Mono", monospace; letter-spacing: 0; font-variant-ligatures: none; }}
  </style>
</head>
<body>
  <pre role="img" aria-label="{safe_title}"><i hidden></i>{art}</pre>
</body>
</html>
"""


def render_ascii(
    original: Image.Image,
    *,
    cols: int,
    rows: int,
    aspect: float,
    fit: str,
    charset: str,
    color_mode: str,
    mono_color: RGB,
    ansi: str,
    style: str,
    contrast: float | None,
    brightness: float | None,
    gamma: float | None,
    edges: float | None,
    polarity: str,
    threshold: int,
    alpha_threshold: int,
    invert_flag: bool,
    disable_auto_invert: bool,
) -> list[str]:
    artwork = render_ascii_art(
        original,
        cols=cols,
        rows=rows,
        aspect=aspect,
        fit=fit,
        charset=charset,
        color_mode=color_mode,
        mono_color=mono_color,
        style=style,
        contrast=contrast,
        brightness=brightness,
        gamma=gamma,
        edges=edges,
        polarity=polarity,
        threshold=threshold,
        alpha_threshold=alpha_threshold,
        invert_flag=invert_flag,
        disable_auto_invert=disable_auto_invert,
    )
    return artwork_to_terminal_lines(artwork, ansi, keep_trailing_spaces=True)


def render_halfblock(
    original: Image.Image,
    *,
    cols: int,
    rows: int,
    aspect: float,
    fit: str,
    color_mode: str,
    mono_color: RGB,
    ansi: str,
    alpha_threshold: int,
) -> list[str]:
    artwork = render_halfblock_art(
        original,
        cols=cols,
        rows=rows,
        aspect=aspect,
        fit=fit,
        color_mode=color_mode,
        mono_color=mono_color,
        alpha_threshold=alpha_threshold,
    )
    return artwork_to_terminal_lines(artwork, ansi, keep_trailing_spaces=True)


def load_image(source: str, frame: int = 0, allow_large: bool = False) -> tuple[Image.Image, int]:
    stream: str | io.BytesIO
    if source == "-":
        data = sys.stdin.buffer.read()
        if not data:
            raise ValueError("nenhum dado de imagem recebido em stdin")
        stream = io.BytesIO(data)
    else:
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(f"imagem nao encontrada: {path}")
        stream = str(path)
    try:
        previous_pixel_limit = Image.MAX_IMAGE_PIXELS
        try:
            if allow_large:
                Image.MAX_IMAGE_PIXELS = None
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                opened = Image.open(stream)
        finally:
            Image.MAX_IMAGE_PIXELS = previous_pixel_limit
        with opened:
            frame_count = int(getattr(opened, "n_frames", 1))
            if frame >= frame_count:
                raise ValueError(
                    f"frame {frame} inexistente; a imagem possui {frame_count} frame(s)"
                )
            opened.seek(frame)
            if not allow_large and opened.width * opened.height > MAX_INPUT_PIXELS:
                raise ValueError(
                    f"imagem excede {MAX_INPUT_PIXELS:,} pixels (use --allow-large para liberar)"
                )
            oriented = ImageOps.exif_transpose(opened)
            image = oriented.convert("RGBA")
            image.load()
    except UnidentifiedImageError as exc:
        raise ValueError("o arquivo nao e uma imagem reconhecida pelo Pillow") from exc
    except Image.DecompressionBombError as exc:
        raise ValueError(
            "a imagem excede o limite seguro de pixels (use --allow-large para liberar)"
        ) from exc
    except (OSError, SyntaxError) as exc:
        raise ValueError(f"nao foi possivel decodificar a imagem: {exc}") from exc
    return image, frame_count


def _same_file(input_name: str, output: Path) -> bool:
    if input_name == "-":
        return False
    input_path = Path(input_name)
    try:
        return output.exists() and os.path.samefile(input_path, output)
    except OSError:
        return input_path.resolve() == output.resolve()


def atomic_write_text(output: Path, text: str, force: bool) -> None:
    parent = output.parent
    if not parent.is_dir():
        raise OSError(f"diretorio de saida nao existe: {parent}")
    if output.exists() and not force:
        raise FileExistsError(f"arquivo ja existe: {output} (use --force para substituir)")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o644)
        if force:
            os.replace(temporary_name, output)
            temporary_name = None
        else:
            try:
                os.link(temporary_name, output)
            except FileExistsError as exc:
                raise FileExistsError(
                    f"arquivo ja existe: {output} (use --force para substituir)"
                ) from exc
            os.unlink(temporary_name)
            temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Converte imagens em ASCII, ANSI, half-block ou Braille com alta fidelidade.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""Exemplos:
  %(prog)s foto.jpg 100x40 --style photo --dither floyd-steinberg
  %(prog)s logo.png 80x30 --style logo --color-mode mono --mono-color '#ff365d'
  %(prog)s foto.jpg 100x35 --mode halfblock --color-mode image
  %(prog)s desenho.png 90x30 --mode braille --dither ordered
  %(prog)s foto.jpg 120x45 --color-mode image -o arte.html
  cat foto.png | %(prog)s - 80x30 --color-mode image
""",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("image", help="imagem de entrada, ou - para stdin")
    parser.add_argument(
        "size_pos",
        nargs="?",
        type=parse_size,
        metavar="COLSxROWS",
        help="tamanho, por exemplo 100x50",
    )

    group = parser.add_argument_group("tamanho")
    group.add_argument("-s", "--size", type=parse_size, help="tamanho COLSxROWS")
    group.add_argument("-w", "--width", type=positive_int, help="largura em caracteres")
    group.add_argument("-H", "--height", type=positive_int, help="altura em linhas")
    group.add_argument(
        "--aspect",
        type=finite_positive,
        default=0.50,
        help="largura/altura visual do caractere (padrao: 0.50)",
    )
    group.add_argument(
        "--fit",
        choices=["contain", "stretch", "cover"],
        default="contain",
        help="contain preserva; stretch deforma; cover recorta",
    )
    group.add_argument(
        "--allow-large",
        action="store_true",
        help="libera grades/imagens acima dos limites de seguranca",
    )

    group = parser.add_argument_group("aparencia")
    group.add_argument(
        "--mode",
        choices=["ascii", "halfblock", "braille"],
        default="ascii",
        help="ascii classico; halfblock colorido; braille de alta resolucao",
    )
    group.add_argument("--style", choices=sorted(STYLE_DEFAULTS), default="normal")
    group.add_argument(
        "--charset",
        choices=sorted(CHARSETS),
        help="rampa de glifos (padrao automatico conforme --style)",
    )
    group.add_argument("--chars", help="charset customizado, do vazio ao mais denso")
    group.add_argument(
        "--dither",
        choices=["none", "floyd-steinberg", "ordered"],
        default="none",
        help="preserva gradientes com pontilhamento",
    )
    group.add_argument(
        "--polarity",
        choices=["auto", "dark", "light"],
        default="auto",
        help="polaridade do fundo da imagem",
    )
    group.add_argument("--invert", action="store_true", help="inverte a densidade final")
    group.add_argument("--no-auto-invert", action="store_true", help="desliga deteccao de fundo")

    group = parser.add_argument_group("cores")
    group.add_argument(
        "--color-mode",
        choices=["none", "mono", "image"],
        default=None,
        help="none = sem cor; mono = uma cor; image = cores originais",
    )
    group.add_argument(
        "--mono-color",
        type=parse_rgb,
        default=(255, 32, 32),
        metavar="COR",
        help="nome, HEX ou rgb(...); padrao: #ff2020",
    )
    group.add_argument(
        "--mono-shading",
        action="store_true",
        help="varia a intensidade da cor mono conforme a densidade",
    )
    group.add_argument(
        "--background",
        type=parse_background,
        default="auto",
        metavar="AUTO|COR",
        help="cor para compor transparencia (padrao: auto)",
    )
    group.add_argument(
        "--ansi",
        choices=["truecolor", "ansi256", "ansi16"],
        default="truecolor",
        help="precisao de cor da saida ANSI",
    )
    group.add_argument(
        "--paint-background",
        action="store_true",
        help="pinta o matte em toda a grade ANSI (util para fundos claros)",
    )
    group.add_argument(
        "--color",
        dest="legacy_color",
        choices=["truecolor", "ansi256", "ansi16"],
        help=argparse.SUPPRESS,
    )

    group = parser.add_argument_group("ajuste fino")
    group.add_argument("--contrast", type=finite_nonnegative, help="fator >= 0")
    group.add_argument("--brightness", type=finite_nonnegative, help="fator >= 0")
    group.add_argument("--gamma", type=finite_positive, help="fator > 0")
    group.add_argument("--edges", type=unit_float, help="contornos entre 0 e 1")
    group.add_argument("--threshold", type=byte_value, default=4, help="corte de ruido 0..255")
    group.add_argument(
        "--halfblock-threshold",
        type=byte_value,
        default=128,
        help="limiar dos pixels half-block 0..255 (padrao: 128)",
    )
    group.add_argument(
        "--braille-threshold",
        type=byte_value,
        default=128,
        help="limiar dos pontos Braille 0..255 (padrao: 128)",
    )
    group.add_argument(
        "--alpha-threshold", type=byte_value, default=12, help="corte de alpha 0..255"
    )

    group = parser.add_argument_group("entrada e saida")
    group.add_argument("--frame", type=nonnegative_int, default=0, help="frame de GIF/APNG/WebP")
    group.add_argument("-o", "--output", help="arquivo de saida, ou - para stdout")
    group.add_argument(
        "--format",
        dest="output_format",
        choices=["auto", "text", "ansi", "html"],
        default="auto",
        help="auto detecta .html; os demais formatos sao explicitos",
    )
    group.add_argument("--keep-trailing-spaces", action="store_true")
    group.add_argument("--force", action="store_true", help="substitui arquivo de saida existente")
    group.add_argument("--quiet", action="store_true", help="omite mensagens informativas")
    return parser


def _resolve_output_format(
    requested: str,
    output: str | None,
    color_mode: str,
    paint_background: bool = False,
) -> str:
    if requested != "auto":
        return requested
    if output and output != "-" and Path(output).suffix.lower() in {".html", ".htm"}:
        return "html"
    return "ansi" if color_mode != "none" or paint_background else "text"


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if PILLOW_IMPORT_ERROR is not None:
        print(
            "erro: Pillow nao esta instalado. Use 'python -m pip install Pillow' "
            "ou 'pip install -e .'.",
            file=sys.stderr,
        )
        return 1
    if args.size and args.size_pos:
        parser.error("use o tamanho posicional OU --size, nao os dois")
    if (args.size or args.size_pos) and (args.width is not None or args.height is not None):
        parser.error("use COLSxROWS/--size OU --width/--height, nao ambos")
    if args.mode != "ascii" and args.chars is not None:
        parser.error("--chars se aplica apenas ao modo ascii")

    if args.legacy_color:
        args.ansi = args.legacy_color
        if args.color_mode is None:
            args.color_mode = "image"
        if not args.quiet:
            print("aviso: --color esta obsoleto; use --color-mode e --ansi", file=sys.stderr)
    if args.color_mode is None:
        args.color_mode = "none"

    try:
        original, frame_count = load_image(args.image, args.frame, args.allow_large)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    if frame_count > 1 and not args.quiet:
        print(
            f"aviso: imagem com {frame_count} frames; usando frame {args.frame} (selecione com --frame)",
            file=sys.stderr,
        )

    size = args.size or args.size_pos
    cols, rows = resolve_grid(
        original.width, original.height, size, args.width, args.height, args.aspect
    )
    try:
        sample_multiplier = {"ascii": 1, "halfblock": 2, "braille": 8}[args.mode]
        validate_grid(cols, rows, args.allow_large, sample_multiplier)
        charset_name = args.charset or STYLE_CHARSETS[args.style]
        charset = validate_charset(args.chars if args.chars is not None else CHARSETS[charset_name])
    except ValueError as exc:
        parser.error(str(exc))

    shared = dict(
        cols=cols,
        rows=rows,
        aspect=args.aspect,
        fit=args.fit,
        color_mode=args.color_mode,
        mono_color=args.mono_color,
        style=args.style,
        contrast=args.contrast,
        brightness=args.brightness,
        gamma=args.gamma,
        edges=args.edges,
        polarity=args.polarity,
        alpha_threshold=args.alpha_threshold,
        invert_flag=args.invert,
        disable_auto_invert=args.no_auto_invert,
        dither=args.dither,
        background=args.background,
        mono_shading=args.mono_shading,
    )
    try:
        if args.mode == "ascii":
            artwork = render_ascii_art(
                original, charset=charset, threshold=args.threshold, **shared
            )
        elif args.mode == "halfblock":
            artwork = render_halfblock_art(original, threshold=args.halfblock_threshold, **shared)
        else:
            artwork = render_braille_art(
                original, braille_threshold=args.braille_threshold, **shared
            )
    except (MemoryError, OSError, ValueError) as exc:
        print(f"erro durante a renderizacao: {exc}", file=sys.stderr)
        return 1

    output_format = _resolve_output_format(
        args.output_format,
        args.output,
        args.color_mode,
        args.paint_background,
    )
    if output_format == "html":
        title = f"Arte ASCII de {Path(args.image).name}" if args.image != "-" else "Arte ASCII"
        text = artwork_to_html(artwork, title=title, keep_trailing_spaces=args.keep_trailing_spaces)
    else:
        lines = (
            artwork_to_terminal_lines(
                artwork,
                args.ansi,
                args.keep_trailing_spaces,
                args.paint_background,
            )
            if output_format == "ansi"
            else artwork_to_text_lines(artwork, args.keep_trailing_spaces)
        )
        text = "\n".join(lines) + "\n"

    if args.output and args.output != "-":
        output = Path(args.output)
        if _same_file(args.image, output):
            print("erro: a saida nao pode sobrescrever a imagem de entrada", file=sys.stderr)
            return 1
        try:
            atomic_write_text(output, text, args.force)
        except OSError as exc:
            print(f"erro ao gravar {output}: {exc}", file=sys.stderr)
            return 1
        if not args.quiet:
            print(
                f"OK: {output} | {cols}x{rows} | mode={args.mode} | "
                f"style={args.style} | fit={args.fit} | color={args.color_mode} | "
                f"format={output_format}",
                file=sys.stderr,
            )
    else:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except BrokenPipeError:
            try:
                sys.stdout.close()
            except BrokenPipeError:
                pass
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
