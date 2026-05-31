# Aspect Resize

A minimal web app for padding uploaded images onto a target aspect-ratio canvas and splitting landscape images into square carousel chunks.

## Features

- Upload PNG, JPEG, or WEBP images up to 50 MB.
- Create a new canvas for popular aspect ratios without resizing the original image.
- Enter a custom ratio such as `5:4`, `2:3`, or `1.25`.
- Choose a manual background color or auto-pick the dominant color from the image.
- Split landscape images into `1:1` carousel chunks, with automatic or manual chunk count.
- Pad carousel images before slicing so the final width matches an exact square multiplier.
- Download individual outputs or a zip containing all generated files.
- Generated files are stored in `/tmp/aspect-resize-results` and cleaned after 20 minutes.

## Run Locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8030
```

Open `http://localhost:8030`.

## Run With Docker Compose

Create a `.env` file with your Cloudflare tunnel token:

```bash
TUNNEL_TOKEN=your-cloudflare-tunnel-token
```

```bash
docker compose up --build
```

The Compose setup runs the FastAPI app and an official Cloudflared tunnel container. In your Cloudflare tunnel/public hostname settings, route the service to:

```text
http://app:8030
```
