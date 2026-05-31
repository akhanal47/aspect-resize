from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.image_ops import *

BASE_DIR = Path(__file__).resolve().parent.parent
UI_DIR = BASE_DIR / "web"
RESULTS_DIR = Path("/tmp/aspect-resize-results")
TTL_MINUTES = 20
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
OUTPUT_EXTENSIONS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}

app = FastAPI(title="Aspect Resize")
app.mount("/web", StaticFiles(directory=UI_DIR), name="web")


def result_url(job_id: str, filename: str) -> str:
    return f"/api/jobs/{job_id}/files/{filename}"


def cleanup_expired_jobs() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=TTL_MINUTES)
    for job_dir in RESULTS_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        modified = datetime.fromtimestamp(job_dir.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            shutil.rmtree(job_dir, ignore_errors=True)


async def cleanup_loop() -> None:
    while True:
        cleanup_expired_jobs()
        await asyncio.sleep(60)


@app.on_event("startup")
async def startup() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.create_task(cleanup_loop())


@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


@app.post("/api/process")
async def process_image(
    image: UploadFile = File(...),
    mode: str = Form(...),
    aspect_ratio: str = Form("1:1"),
    background_mode: str = Form("auto"),
    background_color: str = Form("#ffffff"),
    chunk_count: str = Form("auto"),
    carousel_padding: str = Form("long_edge"),
    output_format: str = Form("PNG"),
) -> dict:
    cleanup_expired_jobs()

    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Please upload an image.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Images must be 50 MB or smaller.")

    try:
        source = open_image(raw)
        output_format = output_format.upper()
        extension = OUTPUT_EXTENSIONS[output_format]
        background = common_color(source) if background_mode == "auto" else hex_to_rgb(background_color)

        stem = Path(image.filename or "image").stem[:80] or "image"
        job_id = uuid.uuid4().hex
        job_dir = RESULTS_DIR / job_id

        if mode == "canvas":
            ratio = parse_ratio(aspect_ratio)
            converted = canvas_for_aspect(source, ratio, background)
            filename = f"{stem}_canvas_{aspect_ratio.replace(':', 'x')}.{extension}"
            processed = [ProcessedImage(filename=filename, image=converted)]
        elif mode == "chunks":
            count = None if chunk_count == "auto" else int(chunk_count)
            chunks = square_chunks(source, background, count=count, padding_mode=carousel_padding)
            processed = [
                ProcessedImage(filename=f"{stem}_carousel_{index + 1:02d}.{extension}", image=chunk)
                for index, chunk in enumerate(chunks)
            ]
        else:
            raise ValueError("Unknown processing mode.")

        paths = write_images(processed, job_dir, output_format)
        zip_name = f"{stem}_aspect_resize.zip"
        write_zip(paths, job_dir / zip_name)
    except KeyError:
        raise HTTPException(status_code=400, detail="Choose PNG, JPEG, or WEBP output.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "jobId": job_id,
        "expiresInMinutes": TTL_MINUTES,
        "background": f"#{background[0]:02x}{background[1]:02x}{background[2]:02x}",
        "files": [
            {
                "name": path.name,
                "url": result_url(job_id, path.name),
                "width": item.image.width,
                "height": item.image.height,
            }
            for path, item in zip(paths, processed)
        ],
        "zip": {"name": zip_name, "url": result_url(job_id, zip_name)},
    }


@app.get("/api/jobs/{job_id}/files/{filename}")
def download(job_id: str, filename: str) -> FileResponse:
    if "/" in job_id or "/" in filename or ".." in job_id or ".." in filename:
        raise HTTPException(status_code=404, detail="File not found.")

    path = RESULTS_DIR / job_id / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found or expired.")

    return FileResponse(path, filename=filename)
