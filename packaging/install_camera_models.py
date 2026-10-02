"""Explicitly install pinned camera models; never runs at app startup."""

import argparse
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from features.camera.face_auth import MODEL_DIR, MODELS  # noqa: E402
from features.camera.emotion import MODEL_FILE, MODEL_SHA256, MODEL_SOURCE  # noqa: E402
from features.camera.gesture import (MODEL_FILE as GESTURE_MODEL_FILE,
                                     MODEL_SHA256 as GESTURE_MODEL_SHA256,
                                     MODEL_SOURCE as GESTURE_MODEL_SOURCE)  # noqa: E402


def _install_one(key, filename, expected, url):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    destination = MODEL_DIR / filename
    if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == expected:
        print(f"{key}: already verified")
        return
    fd, temporary = tempfile.mkstemp(prefix=".model-", dir=MODEL_DIR)
    try:
        os.close(fd)
        hasher = hashlib.sha256()
        with urlopen(url, timeout=45) as response, open(temporary, "wb") as handle:
            while chunk := response.read(1024 * 1024):
                hasher.update(chunk)
                handle.write(chunk)
        if hasher.hexdigest() != expected:
            raise ValueError(f"Checksum mismatch for {filename}")
        Path(temporary).replace(destination)
        print(f"{key}: installed and verified")
    finally:
        Path(temporary).unlink(missing_ok=True)


def install(include_emotion=False, include_gesture=False):
    for key, (filename, expected) in MODELS.items():
        folder = "face_detection_yunet" if key == "yunet" else "face_recognition_sface"
        url = ("https://huggingface.co/opencv/opencv_zoo/resolve/main/models/"
               f"{folder}/{filename}?download=true")
        _install_one(key, filename, expected, url)
    if include_emotion:
        _install_one("emotion", MODEL_FILE, MODEL_SHA256, MODEL_SOURCE)
    if include_gesture:
        _install_one("gesture", GESTURE_MODEL_FILE, GESTURE_MODEL_SHA256,
                     GESTURE_MODEL_SOURCE)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emotion", action="store_true",
                        help="also install the optional EmotiEffLib ONNX expression model")
    parser.add_argument("--gesture", action="store_true",
                        help="also install the MediaPipe Hand Landmarker task model")
    args = parser.parse_args()
    install(include_emotion=args.emotion, include_gesture=args.gesture)
