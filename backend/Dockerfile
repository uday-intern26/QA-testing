FROM python:3.11-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

RUN mkdir -p /app/models \
    && python -c "import urllib.request; urllib.request.urlretrieve('https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task', '/app/models/face_landmarker.task')" \
    && python -c "import urllib.request; urllib.request.urlretrieve('https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task', '/app/models/hand_landmarker.task')"

COPY app ./app
COPY scripts ./scripts

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DATA_DIR=/app/data \
    DATABASE_URL=sqlite:////app/data/qa.sqlite3 \
    FACE_MODEL_PATH=/app/models/face_landmarker.task \
    HAND_MODEL_PATH=/app/models/hand_landmarker.task

RUN mkdir -p /app/data/applications /app/data/references /app/data/captures \
    /app/data/frames /app/data/results /app/data/reports

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
