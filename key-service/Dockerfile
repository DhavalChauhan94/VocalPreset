FROM python:3.11-slim

# ffmpeg decodes uploads; --no-install-recommends and the list cleanup keep the layer small.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
# Prebuilt wheels only (essentia ships manylinux wheels), so no compilers enter the image.
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

COPY app ./app
RUN useradd --system --no-create-home svc
USER svc

ENV PYTHONUNBUFFERED=1 MAX_UPLOAD_MB=50
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
