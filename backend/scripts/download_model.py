"""Download MediaPipe face and hand landmarker models used by Jewelry QA."""

from pathlib import Path
import urllib.request

MODELS = {
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task"
    ),
    "hand_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
        "hand_landmarker/float16/1/hand_landmarker.task"
    ),
}


def main() -> None:
    models_dir = Path(__file__).resolve().parents[1] / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    for filename, url in MODELS.items():
        destination = models_dir / filename
        if destination.is_file() and destination.stat().st_size > 0:
            print(f"Model already present at {destination}")
            continue
        print(f"Downloading {url}")
        urllib.request.urlretrieve(url, destination)
        print(f"Saved {destination}")


if __name__ == "__main__":
    main()
