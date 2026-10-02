"""Opt-in, single-owner profile suggestion. This is not an authenticator."""

import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "camera"
MODELS = {
    "yunet": ("face_detection_yunet_2023mar.onnx",
              "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "sface": ("face_recognition_sface_2021dec.onnx",
              "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
}
MATCH_THRESHOLD = 0.50  # Convenience suggestion only; must be calibrated on the owner's camera.
MIN_FACE_SIZE = 90


def model_path(key, directory=MODEL_DIR):
    filename, digest = MODELS[key]
    path = Path(directory) / filename
    if not path.is_file():
        raise FileNotFoundError(f"Missing {filename}; run packaging/install_camera_models.py")
    hash_value = hashlib.sha256(path.read_bytes()).hexdigest()
    if hash_value != digest:
        raise ValueError(f"Checksum mismatch for {filename}")
    return path


def model_paths(directory=MODEL_DIR):
    return {key: model_path(key, directory) for key in MODELS}


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(value):
    buffer = ctypes.create_string_buffer(value)
    return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _dpapi(value, protect):
    if sys.platform != "win32":
        raise RuntimeError("Face template storage requires Windows DPAPI")
    crypt = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    crypt.argtypes = [ctypes.POINTER(_DataBlob), wintypes.LPCWSTR,
                      ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                      wintypes.DWORD, ctypes.POINTER(_DataBlob)]
    crypt.restype = wintypes.BOOL
    source, source_buffer = _blob(value)
    entropy, entropy_buffer = _blob(b"Alice camera owner template v1")
    output = _DataBlob()
    if not crypt(ctypes.byref(source), "Alice camera owner template" if protect else None,
                 ctypes.byref(entropy), None, None, 0x01, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(ctypes.cast(output.pbData, ctypes.c_void_p))


def _restrict_acl(path):
    """Remove inherited file access and grant the current Windows SID only."""
    result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                            capture_output=True, text=True, check=True)
    match = re.search(r"S-\d-(?:\d+-)+\d+", result.stdout)
    if not match:
        raise RuntimeError("Could not determine Windows account SID")
    subprocess.run(["icacls", str(path), "/grant:r", f"*{match.group(0)}:(F)"],
                   capture_output=True, text=True, check=True)
    subprocess.run(["icacls", str(path), "/inheritance:r"],
                   capture_output=True, text=True, check=True)


class OwnerTemplateStore:
    """DPAPI CurrentUser encrypted embedding; no raw image or plaintext fallback."""

    def __init__(self, path=None):
        local = os.environ.get("LOCALAPPDATA")
        self.path = Path(path) if path else (Path(local) / "Alice" / "camera" /
                                            "owner-face-v1.bin" if local else None)

    def exists(self):
        return bool(self.path and self.path.is_file())

    def load(self):
        if not self.exists():
            return None
        data = json.loads(_dpapi(self.path.read_bytes(), False).decode("utf-8"))
        if data.get("schema") != 1 or data.get("model") != "opencv-sface-2021dec":
            raise ValueError("Face template version is unsupported")
        vector = data.get("embedding")
        if (not isinstance(vector, list) or len(vector) != 128 or
                any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in vector)):
            raise ValueError("Face template has invalid dimensions")
        if not 0.8 <= math.sqrt(sum(x * x for x in vector)) <= 1.2:
            raise ValueError("Face template is not normalized")
        return vector

    def save(self, vector):
        if self.path is None:
            raise RuntimeError("LOCALAPPDATA is unavailable")
        if len(vector) != 128:
            raise ValueError("Face embedding must have 128 dimensions")
        payload = json.dumps({"schema": 1, "model": "opencv-sface-2021dec",
                              "embedding": [float(x) for x in vector]},
                             separators=(",", ":")).encode("utf-8")
        protected = _dpapi(payload, True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".owner-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(protected)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            try:
                _restrict_acl(self.path)
            except Exception:
                self.path.unlink(missing_ok=True)
                raise
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def delete(self):
        if self.path:
            self.path.unlink(missing_ok=True)


def detect_yunet(detector, frame):
    """Handle both OpenCV 4 variable-size DNN and OpenCV 5 fixed-size runtimes."""
    import cv2
    height, width = frame.shape[:2]
    try:
        detector.setInputSize((width, height))
        return detector.detect(frame)[1]
    except cv2.error:
        detector.setInputSize((320, 320))
        small = cv2.resize(frame, (320, 320))
        faces = detector.detect(small)[1]
        if faces is None:
            return None
        faces = faces.copy()
        faces[:, [0, 2, 4, 6, 8, 10, 12]] *= width / 320
        faces[:, [1, 3, 5, 7, 9, 11, 13]] *= height / 320
        return faces


class FaceEngine:
    def __init__(self, directory=MODEL_DIR):
        import cv2
        paths = model_paths(directory)
        self.detector = cv2.FaceDetectorYN.create(str(paths["yunet"]), "", (320, 320),
                                                  score_threshold=0.9, nms_threshold=0.3)
        self.recognizer = cv2.FaceRecognizerSF.create(str(paths["sface"]), "")

    def embedding(self, frame):
        import numpy as np
        faces = detect_yunet(self.detector, frame)
        if faces is None or len(faces) == 0:
            return "no_face", None
        if len(faces) != 1:
            return "multiple_faces", None
        face = faces[0]
        if min(face[2], face[3]) < MIN_FACE_SIZE:
            return "low_quality", None
        aligned = self.recognizer.alignCrop(frame, face)
        feature = self.recognizer.feature(aligned).reshape(-1).astype("float32")
        norm = float(np.linalg.norm(feature))
        if not np.isfinite(norm) or norm <= 0:
            return "low_quality", None
        return "ok", feature / norm


def match_score(a, b):
    import numpy as np
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
