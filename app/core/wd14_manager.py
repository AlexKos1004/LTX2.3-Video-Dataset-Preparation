from __future__ import annotations

from pathlib import Path
from urllib.request import urlretrieve
import csv
import hashlib
import shutil
from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover - optional runtime
    np = None

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional runtime
    Image = None

try:
    import onnxruntime as ort
except Exception:  # pragma: no cover - optional runtime
    ort = None


class WD14Manager:
    MODEL_URL = "https://huggingface.co/SmilingWolf/wd-vit-tagger-v3/resolve/main/model.onnx"
    TAGS_URL = "https://huggingface.co/SmilingWolf/wd-vit-tagger-v3/resolve/main/selected_tags.csv"

    def __init__(self, model_dir: str | Path | None = None) -> None:
        if model_dir is None:
            model_dir = Path.home() / ".ltx23_video_editor" / "models" / "wd14"
        self.model_dir = Path(model_dir)
        self.model_path = self.model_dir / "model.onnx"
        self.tags_path = self.model_dir / "selected_tags.csv"
        self._session: Any = None
        self._tags_cache: list[str] | None = None

    def is_installed(self) -> bool:
        return (
            self.model_path.exists()
            and self.model_path.stat().st_size > 0
            and self.tags_path.exists()
            and self.tags_path.stat().st_size > 0
        )

    def ensure_installed(self) -> Path:
        if self.is_installed():
            return self.model_path
        self.model_dir.mkdir(parents=True, exist_ok=True)
        urlretrieve(self.MODEL_URL, self.model_path)
        urlretrieve(self.TAGS_URL, self.tags_path)
        return self.model_path

    def redownload(self) -> Path:
        if self.model_dir.exists():
            shutil.rmtree(self.model_dir, ignore_errors=True)
        self._session = None
        self._tags_cache = None
        return self.ensure_installed()

    def infer_tags(self, image_path: str | Path) -> list[str]:
        if ort is None or np is None or Image is None:
            image_bytes = Path(image_path).read_bytes()
            digest = hashlib.sha1(image_bytes).hexdigest()[:12]
            return [f"wd14_auto_{digest}"]

        self.ensure_installed()
        session = self._get_session()
        input_name = session.get_inputs()[0].name
        input_size = session.get_inputs()[0].shape[1]
        image_array = self._preprocess_image(image_path, int(input_size))
        outputs = session.run(None, {input_name: image_array})[0]
        probabilities = outputs[0]
        tag_names = self._load_tag_names()

        scored = []
        for idx, score in enumerate(probabilities):
            if idx < len(tag_names):
                scored.append((tag_names[idx], float(score)))
        scored.sort(key=lambda item: item[1], reverse=True)
        return [name for name, score in scored if score >= 0.35][:32]

    def _get_session(self):
        if self._session is None:
            providers = ["CPUExecutionProvider"]
            self._session = ort.InferenceSession(str(self.model_path), providers=providers)
        return self._session

    def _load_tag_names(self) -> list[str]:
        if self._tags_cache is not None:
            return self._tags_cache
        tag_names: list[str] = []
        with self.tags_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                tag_names.append(row.get("name", "").strip())
        self._tags_cache = tag_names
        return tag_names

    @staticmethod
    def _preprocess_image(image_path: str | Path, input_size: int) -> np.ndarray:
        if np is None or Image is None:  # pragma: no cover - guarded by caller
            raise RuntimeError("numpy/Pillow is required for WD14 preprocessing")
        image = Image.open(image_path).convert("RGB")
        image = image.resize((input_size, input_size), Image.Resampling.BICUBIC)
        array = np.asarray(image).astype(np.float32)[:, :, ::-1]  # RGB -> BGR
        array = np.expand_dims(array, axis=0)
        return array

