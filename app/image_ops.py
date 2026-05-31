from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps


SUPPORTED_FORMATS = {"PNG", "JPEG"}


@dataclass(frozen=True)
class ProcessedImage:
    filename: str
    image: Image.Image


def open_image(file_bytes: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(file_bytes))
    image.load()
    return ImageOps.exif_transpose(image)


def parse_ratio(value: str) -> float:
    cleaned = value.strip().lower().replace(" ", "")
    if ":" in cleaned:
        left, right = cleaned.split(":", 1)
        width = float(left)
        height = float(right)
        if width <= 0 or height <= 0:
            raise ValueError("Aspect ratio values must be positive.")
        return width / height

    ratio = float(cleaned)
    if ratio <= 0:
        raise ValueError("Aspect ratio must be positive.")
    return ratio


def common_color(image: Image.Image) -> tuple[int, int, int]:
    sample = image.convert("RGBA")
    sample.thumbnail((160, 160))

    colors: dict[tuple[int, int, int], int] = {}
    for red, green, blue, alpha in sample.getdata():
        if alpha < 16:
            continue
        key = (red // 16 * 16, green // 16 * 16, blue // 16 * 16)
        colors[key] = colors.get(key, 0) + 1

    if not colors:
        return (255, 255, 255)

    red, green, blue = max(colors.items(), key=lambda item: item[1])[0]
    return (min(red + 8, 255), min(green + 8, 255), min(blue + 8, 255))


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    cleaned = value.strip().lstrip("#")
    if len(cleaned) != 6:
        raise ValueError("Background color must be a 6-digit hex value.")
    return tuple(int(cleaned[i : i + 2], 16) for i in (0, 2, 4))


def paste_with_alpha(canvas: Image.Image, image: Image.Image, box: tuple[int, int]) -> None:
    source = image.convert("RGBA")
    canvas.paste(source, box, source)


def canvas_for_aspect(image: Image.Image, target_ratio: float, background: tuple[int, int, int], ) -> Image.Image:
    original_width, original_height = image.size
    original_ratio = original_width / original_height

    if original_ratio > target_ratio:
        canvas_width = original_width
        canvas_height = math.ceil(original_width / target_ratio)
    else:
        canvas_height = original_height
        canvas_width = math.ceil(original_height * target_ratio)

    canvas = Image.new("RGB", (canvas_width, canvas_height), background)
    x = (canvas_width - original_width) // 2
    y = (canvas_height - original_height) // 2
    paste_with_alpha(canvas, image, (x, y))
    return canvas


def square_chunks(image: Image.Image, background: tuple[int, int, int], count: int | None = None, padding_mode: str = "long_edge", ) -> list[Image.Image]:
    width, height = image.size
    if width <= height:
        raise ValueError("Carousel chunks require a landscape image where width is greater than height.")

    if count is None:
        count = max(1, math.ceil(width / height))
    if count < 1 or count > 20:
        raise ValueError("Chunk count must be between 1 and 20.")

    if padding_mode not in {"none", "long_edge", "full_canvas"}:
        raise ValueError("Unknown carousel padding mode.")

    min_exact_count = math.ceil(width / height)
    prepared = image
    square_size = max(height, math.ceil(width / count))

    if padding_mode == "long_edge":
        if count < min_exact_count:
            raise ValueError(
                f"Use at least {min_exact_count} chunks to pad only the long edge without cropping."
            )
        square_size = height
        prepared_width = count * square_size
        prepared = Image.new("RGB", (prepared_width, height), background)
        paste_with_alpha(prepared, image, ((prepared_width - width) // 2, 0))
    elif padding_mode == "full_canvas":
        prepared_width = count * square_size
        prepared = Image.new("RGB", (prepared_width, square_size), background)
        paste_with_alpha(prepared, image, ((prepared_width - width) // 2, (square_size - height) // 2))

    chunks: list[Image.Image] = []
    for index in range(count):
        start = min(index * square_size, prepared.width)
        end = min(start + square_size, prepared.width)
        crop = prepared.crop((start, 0, end, prepared.height))

        canvas = Image.new("RGB", (square_size, square_size), background)
        paste_with_alpha(canvas, crop, (0, (square_size - crop.height) // 2))
        chunks.append(canvas)

    return chunks


def encode_image(image: Image.Image, output_format: str) -> bytes:
    normalized = output_format.upper()
    if normalized not in SUPPORTED_FORMATS:
        raise ValueError("Unsupported output format.")

    buffer = io.BytesIO()
    save_kwargs = {}
    if normalized == "JPEG":
        image = image.convert("RGB")
        save_kwargs = {"quality": 100, "optimize": True}

    image.save(buffer, format=normalized, **save_kwargs)
    return buffer.getvalue()


def write_images(images: Iterable[ProcessedImage], output_dir: Path, output_format: str, ) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for item in images:
        path = output_dir / item.filename
        path.write_bytes(encode_image(item.image, output_format))
        paths.append(path)
    return paths


def write_zip(paths: Iterable[Path], zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, arcname=path.name)
