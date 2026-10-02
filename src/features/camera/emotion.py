"""Debug-only facial expression estimate using a pinned EmotiEffLib ONNX model.

The model describes a visible expression, not a person's internal emotion.
No frame, crop, or inference result is persisted by this module.
"""

import hashlib
from pathlib import Path

from features.camera.face_auth import MIN_FACE_SIZE, MODEL_DIR, detect_yunet, model_path


MODEL_NAME = "enet_b0_8_best_afew"
MODEL_FILE = MODEL_NAME + ".onnx"
MODEL_SHA256 = "7aa2ea31c1311f4f8aa9d3fdb085d418dd4e7a48c4b9ed41df8c044f91d0213f"
MODEL_SOURCE = ("https://raw.githubusercontent.com/sb-ai-lab/EmotiEffLib/main/"
                "models/affectnet_emotions/onnx/" + MODEL_FILE)
LABELS = ("anger", "contempt", "disgust", "fear", "happiness", "neutral",
          "sadness", "surprise")
# Provisional debug cutoff, not a calibrated statement about emotion accuracy.
MIN_CONFIDENCE = 0.50


def emotion_model_path(directory=MODEL_DIR):
    path = Path(directory) / MODEL_FILE
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {MODEL_FILE}; run packaging/install_camera_models.py --emotion")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != MODEL_SHA256:
        raise ValueError(f"Checksum mismatch for {MODEL_FILE}")
    return path


class EmotionEngine:
    """Own YuNet detector and CPU session; caller supplies a BGR webcam frame."""

    def __init__(self, directory=MODEL_DIR):
        import cv2
        import onnxruntime as ort

        self._cv2 = cv2
        self._detector = cv2.FaceDetectorYN.create(
            str(model_path("yunet", directory)), "", (320, 320),
            score_threshold=0.9, nms_threshold=0.3)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.log_severity_level = 4
        self._session = ort.InferenceSession(
            str(emotion_model_path(directory)), sess_options=options,
            providers=["CPUExecutionProvider"])
        inputs, outputs = self._session.get_inputs(), self._session.get_outputs()
        if (len(inputs) != 1 or len(outputs) != 1 or
                inputs[0].shape[-3:] != [3, 224, 224] or outputs[0].shape[-1] != 8):
            raise ValueError("Emotion model has an unexpected input/output shape")
        self._input_name = inputs[0].name
        self._output_name = outputs[0].name

    def estimate(self, frame):
        """Return (quality, label, model probability); `unknown` is not an emotion."""
        import numpy as np

        faces = detect_yunet(self._detector, frame)
        if faces is None or len(faces) == 0:
            return "no_face", "unknown", None
        if len(faces) != 1:
            return "multiple_faces", "unknown", None
        x, y, width, height = (float(v) for v in faces[0][:4])
        if min(width, height) < MIN_FACE_SIZE:
            return "low_quality", "unknown", None

        frame_height, frame_width = frame.shape[:2]
        side = max(width, height) * 1.18
        cx, cy = x + width / 2, y + height / 2
        left = max(0, int(cx - side / 2))
        top = max(0, int(cy - side / 2))
        right = min(frame_width, int(cx + side / 2))
        bottom = min(frame_height, int(cy + side / 2))
        if right <= left or bottom <= top:
            return "low_quality", "unknown", None
        # EmotiEffLib ONNX preprocessing: RGB, 224x224, ImageNet normalization.
        crop = self._cv2.cvtColor(frame[top:bottom, left:right], self._cv2.COLOR_BGR2RGB)
        image = self._cv2.resize(crop, (224, 224)).astype("float32") / 255.0
        image = (image - np.array((0.485, 0.456, 0.406), dtype="float32")) / np.array(
            (0.229, 0.224, 0.225), dtype="float32")
        image = np.ascontiguousarray(image.transpose(2, 0, 1)[None, ...])
        logits = np.asarray(self._session.run(
            [self._output_name], {self._input_name: image})[0]).reshape(-1)
        if logits.size != len(LABELS) or not np.isfinite(logits).all():
            raise ValueError("Emotion model returned invalid scores")
        scores = np.exp(logits - logits.max())
        scores /= scores.sum()
        index = int(scores.argmax())
        confidence = float(scores[index])
        if confidence < MIN_CONFIDENCE:
            return "low_confidence", "unknown", confidence
        return "ok", LABELS[index], confidence
