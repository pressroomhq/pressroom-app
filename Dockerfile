FROM python:3.12-slim

WORKDIR /app

# ── System deps: Chrome for Remotion + Node for renderer + build tools ─────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Chrome / Chromium (Remotion uses this to render)
    chromium \
    chromium-driver \
    fonts-liberation \
    fonts-noto-color-emoji \
    # Node.js for Remotion renderer
    nodejs \
    npm \
    # ffmpeg for footage duration detection + video processing
    ffmpeg \
    # Build tools
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Tell Remotion where Chrome is
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV CHROME_EXECUTABLE_PATH=/usr/bin/chromium

# ── Python deps ────────────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Remotion renderer ──────────────────────────────────────────────────────────
# Copy renderer source and install deps
COPY remotion-renderer/ /app/remotion-renderer/
RUN cd /app/remotion-renderer && npm install --prefer-offline

# Pre-create output directory
RUN mkdir -p /app/remotion-renderer/out

# ── App source ─────────────────────────────────────────────────────────────────
COPY . .

# ── Frontend build ─────────────────────────────────────────────────────────────
RUN cd frontend && npm install && npm run build && rm -rf node_modules

# ── Runtime config ─────────────────────────────────────────────────────────────
# Remotion renderer path — matches _RENDERER_DIR in youtube.py
ENV REMOTION_RENDERER_DIR=/app/remotion-renderer

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
