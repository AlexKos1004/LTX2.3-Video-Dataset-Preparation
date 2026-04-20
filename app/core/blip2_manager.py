from __future__ import annotations

from pathlib import Path
import hashlib
import shutil

try:
    import torch
except Exception:  # pragma: no cover - optional runtime
    torch = None

try:
    from transformers import pipeline
except Exception:  # pragma: no cover - optional runtime
    pipeline = None


class BLIP2Manager:
    MODEL_CANDIDATES = [
        "Salesforce/blip2-opt-2.7b-coco",
        "Salesforce/blip2-flan-t5-xl",
    ]

    def __init__(self, cache_dir: str | Path | None = None) -> None:
        if cache_dir is None:
            cache_dir = Path.home() / ".ltx23_video_editor" / "models" / "blip2"
        self.cache_dir = Path(cache_dir)
        self._captioner = None
        self._model_id = ""

    def is_available(self) -> bool:
        return pipeline is not None and torch is not None

    def is_initialized(self) -> bool:
        return self._captioner is not None

    def ensure_installed(self) -> str:
        if not self.is_available():
            raise RuntimeError(
                "BLIP2 dependencies are missing. Install transformers and torch."
            )
        if self._captioner is not None:
            return self._model_id

        device = "cpu"
        dtype = None
        if torch is not None and torch.cuda.is_available():
            device = 0
            dtype = torch.float16

        for model_id in self.MODEL_CANDIDATES:
            try:
                kwargs = {"model": model_id, "device": device}
                if dtype is not None:
                    kwargs["torch_dtype"] = dtype
                kwargs["model_kwargs"] = {"cache_dir": str(self.cache_dir)}
                self._captioner = pipeline("image-to-text", **kwargs)
                self._model_id = model_id
                return self._model_id
            except Exception:
                continue
        raise RuntimeError("Unable to initialize BLIP2 caption model.")

    def redownload(self) -> str:
        self._captioner = None
        self._model_id = ""
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir, ignore_errors=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.ensure_installed()

    def generate_caption(self, image_path: str | Path) -> str:
        if not self.is_available():
            image_bytes = Path(image_path).read_bytes()
            digest = hashlib.sha1(image_bytes).hexdigest()[:12]
            return f"blip2_auto_{digest}"

        self.ensure_installed()
        result = self._captioner(str(image_path), max_new_tokens=40)
        if not result:
            return ""
        text = str(result[0].get("generated_text", "")).strip()
        return " ".join(text.split())

