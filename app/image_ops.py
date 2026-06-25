from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageCms, ImageOps


SUPPORTED_FORMATS = {"PNG", "JPEG"}

SRGB_PROFILE = ImageCms.createProfile("sRGB")
SRGB_PROFILE_BYTES = ImageCms.ImageCmsProfile(SRGB_PROFILE).tobytes()


@dataclass(frozen=True)
class ProcessedImage:
    filename: str
    image: Image.Image


def get_icc_profile(image: Image.Image) -> bytes | None:
    return image.info.get("icc_profile")


def attach_icc_profile(
    image: Image.Image,
    icc_profile: bytes | None,
) -> Image.Image:
    if icc_profile:
        image.info["icc_profile"] = icc_profile
    else:
        image.info.pop("icc_profile", None)

    return image


def _profile_from_bytes(icc_profile: bytes) -> ImageCms.ImageCmsProfile:
    return ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))


def normalize_image(image: Image.Image) -> Image.Image:
    icc_profile = get_icc_profile(image)
    has_alpha = "A" in image.getbands()
    output_mode = "RGBA" if has_alpha else "RGB"

    if image.mode in {"RGB", "RGBA"}:
        if image.mode != output_mode:
            image = image.convert(output_mode)

        return attach_icc_profile(image, icc_profile or SRGB_PROFILE_BYTES)

    if icc_profile:
        try:
            source_profile = _profile_from_bytes(icc_profile)
            target_profile = _profile_from_bytes(SRGB_PROFILE_BYTES)

            image = ImageCms.profileToProfile(
                image,
                source_profile,
                target_profile,
                outputMode=output_mode,
            )

            return attach_icc_profile(image, SRGB_PROFILE_BYTES)

        except Exception:
            image = image.convert(output_mode)
            return attach_icc_profile(image, SRGB_PROFILE_BYTES)

    image = image.convert(output_mode)
    return attach_icc_profile(image, SRGB_PROFILE_BYTES)


def convert_image_to_profile(
    image: Image.Image,
    target_icc_profile: bytes,
) -> Image.Image:
    
    image = normalize_image(image)

    source_icc_profile = get_icc_profile(image) or SRGB_PROFILE_BYTES

    if source_icc_profile == target_icc_profile:
        return attach_icc_profile(image, target_icc_profile)

    has_alpha = "A" in image.getbands()
    alpha = image.getchannel("A") if has_alpha else None

    rgb_image = image.convert("RGB")

    try:
        source_profile = _profile_from_bytes(source_icc_profile)
        target_profile = _profile_from_bytes(target_icc_profile)

        converted = ImageCms.profileToProfile(
            rgb_image,
            source_profile,
            target_profile,
            outputMode="RGB",
        )

    except Exception:
        converted = rgb_image

    if alpha is not None:
        converted.putalpha(alpha)

    return attach_icc_profile(converted, target_icc_profile)


@lru_cache(maxsize=64)
def _build_srgb_to_target_transform(
    target_icc_profile: bytes,
) -> ImageCms.ImageCmsTransform:
    source_profile = _profile_from_bytes(SRGB_PROFILE_BYTES)
    target_profile = _profile_from_bytes(target_icc_profile)

    return ImageCms.buildTransformFromOpenProfiles(
        source_profile,
        target_profile,
        "RGB",
        "RGB",
    )


def convert_srgb_color_to_profile(
    color: tuple[int, int, int],
    target_icc_profile: bytes | None,
) -> tuple[int, int, int]:
    """
    Treat a hex/RGB background color as sRGB, then convert it into the
    image's ICC color space.

    Example:
    #ff0000 is interpreted as sRGB red.
    If the image is Display P3, the returned tuple is Display P3-equivalent red.
    """
    if not target_icc_profile:
        return color

    if target_icc_profile == SRGB_PROFILE_BYTES:
        return color

    try:
        swatch = Image.new("RGB", (1, 1), color)
        swatch.info["icc_profile"] = SRGB_PROFILE_BYTES

        transform = _build_srgb_to_target_transform(target_icc_profile)
        converted = ImageCms.applyTransform(swatch, transform)

        return converted.getpixel((0, 0))

    except Exception:
        return color


def convert_image_to_srgb(image: Image.Image) -> Image.Image:
    image = normalize_image(image)
    return convert_image_to_profile(image, SRGB_PROFILE_BYTES)


def open_image(file_bytes: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(file_bytes))
    image.load()

    image = ImageOps.exif_transpose(image)

    return normalize_image(image)


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

    sample = convert_image_to_srgb(image).convert("RGBA")
    sample.thumbnail((160, 160))

    colors: dict[tuple[int, int, int], int] = {}

    for red, green, blue, alpha in sample.getdata():
        if alpha < 16:
            continue

        key = (
            red // 16 * 16,
            green // 16 * 16,
            blue // 16 * 16,
        )

        colors[key] = colors.get(key, 0) + 1

    if not colors:
        return (255, 255, 255)

    red, green, blue = max(colors.items(), key=lambda item: item[1])[0]

    return (
        min(red + 8, 255),
        min(green + 8, 255),
        min(blue + 8, 255),
    )


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    cleaned = value.strip().lstrip("#")

    if len(cleaned) != 6:
        raise ValueError("Background color must be a 6-digit hex value.")

    return tuple(int(cleaned[i : i + 2], 16) for i in (0, 2, 4))


def new_rgb_canvas(
    size: tuple[int, int],
    background: tuple[int, int, int],
    icc_profile: bytes | None = None,
) -> Image.Image:

    working_icc_profile = icc_profile or SRGB_PROFILE_BYTES
    converted_background = convert_srgb_color_to_profile(
        background,
        working_icc_profile,
    )

    canvas = Image.new("RGB", size, converted_background)

    return attach_icc_profile(canvas, working_icc_profile)


def paste_with_alpha(
    canvas: Image.Image,
    image: Image.Image,
    box: tuple[int, int],
) -> None:
    canvas_icc_profile = get_icc_profile(canvas) or SRGB_PROFILE_BYTES

    source = convert_image_to_profile(image, canvas_icc_profile).convert("RGBA")

    canvas.paste(source, box, source)


def canvas_for_aspect(
    image: Image.Image,
    target_ratio: float,
    background: tuple[int, int, int],
) -> Image.Image:
    image = normalize_image(image)

    working_icc_profile = get_icc_profile(image) or SRGB_PROFILE_BYTES

    original_width, original_height = image.size
    original_ratio = original_width / original_height

    if original_ratio > target_ratio:
        canvas_width = original_width
        canvas_height = math.ceil(original_width / target_ratio)
    else:
        canvas_height = original_height
        canvas_width = math.ceil(original_height * target_ratio)

    canvas = new_rgb_canvas(
        (canvas_width, canvas_height),
        background,
        working_icc_profile,
    )

    x = (canvas_width - original_width) // 2
    y = (canvas_height - original_height) // 2

    paste_with_alpha(canvas, image, (x, y))

    return attach_icc_profile(canvas, working_icc_profile)


def square_chunks(
    image: Image.Image,
    background: tuple[int, int, int],
    count: int | None = None,
    padding_mode: str = "long_edge",
) -> list[Image.Image]:
    image = normalize_image(image)

    working_icc_profile = get_icc_profile(image) or SRGB_PROFILE_BYTES

    width, height = image.size

    if width <= height:
        raise ValueError(
            "Carousel chunks require a landscape image where width is greater than height."
        )

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

        prepared = new_rgb_canvas(
            (prepared_width, height),
            background,
            working_icc_profile,
        )

        paste_with_alpha(
            prepared,
            image,
            ((prepared_width - width) // 2, 0),
        )

    elif padding_mode == "full_canvas":
        prepared_width = count * square_size

        prepared = new_rgb_canvas(
            (prepared_width, square_size),
            background,
            working_icc_profile,
        )

        paste_with_alpha(
            prepared,
            image,
            (
                (prepared_width - width) // 2,
                (square_size - height) // 2,
            ),
        )

    chunks: list[Image.Image] = []

    for index in range(count):
        start = min(index * square_size, prepared.width)
        end = min(start + square_size, prepared.width)

        crop = prepared.crop((start, 0, end, prepared.height))
        crop = attach_icc_profile(crop, working_icc_profile)

        canvas = new_rgb_canvas(
            (square_size, square_size),
            background,
            working_icc_profile,
        )

        paste_with_alpha(
            canvas,
            crop,
            (0, (square_size - crop.height) // 2),
        )

        chunks.append(attach_icc_profile(canvas, working_icc_profile))

    return chunks


def encode_image(
    image: Image.Image,
    output_format: str,
) -> bytes:
    normalized = output_format.upper()

    if normalized not in SUPPORTED_FORMATS:
        raise ValueError("Unsupported output format.")

    image = normalize_image(image)

    working_icc_profile = get_icc_profile(image) or SRGB_PROFILE_BYTES

    buffer = io.BytesIO()

    if normalized == "JPEG":
        if "A" in image.getbands():
            background = new_rgb_canvas(
                image.size,
                (255, 255, 255),
                working_icc_profile,
            )
            paste_with_alpha(background, image, (0, 0))
            image = background
        else:
            image = image.convert("RGB")
            image = attach_icc_profile(image, working_icc_profile)

        image.save(
            buffer,
            format="JPEG",
            quality=100,
            subsampling=0,
            optimize=True,
            icc_profile=working_icc_profile,
        )

    else:
        image.save(
            buffer,
            format="PNG",
            optimize=False,
            icc_profile=working_icc_profile,
        )

    return buffer.getvalue()


def write_images(
    images: Iterable[ProcessedImage],
    output_dir: Path,
    output_format: str,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []

    for item in images:
        path = output_dir / item.filename
        path.write_bytes(encode_image(item.image, output_format))
        paths.append(path)

    return paths


def write_zip(
    paths: Iterable[Path],
    zip_path: Path,
) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, arcname=path.name)
