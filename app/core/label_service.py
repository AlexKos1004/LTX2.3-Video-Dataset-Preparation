from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.blip2_manager import BLIP2Manager
from app.core.wd14_manager import WD14Manager


@dataclass
class LabelResult:
    manual_keywords: list[str]
    auto_tags: list[str]

    @property
    def final_line(self) -> str:
        dedup: list[str] = []
        for tag in [*self.manual_keywords, *self.auto_tags]:
            normalized = tag.strip()
            if normalized and normalized not in dedup:
                dedup.append(normalized)
        return ", ".join(dedup)


class LabelService:
    def __init__(self, wd14_manager: WD14Manager, blip2_manager: BLIP2Manager) -> None:
        self.wd14_manager = wd14_manager
        self.blip2_manager = blip2_manager

    def generate(
        self,
        preview_frame_path: str | Path | None,
        manual_keywords_line: str,
        tagger: str,
    ) -> LabelResult:
        manual_keywords = [
            token.strip()
            for token in manual_keywords_line.split(",")
            if token.strip()
        ]
        auto_tags: list[str] = []
        if tagger == "wd14" and preview_frame_path:
            self.wd14_manager.ensure_installed()
            auto_tags = self.wd14_manager.infer_tags(preview_frame_path)
        elif tagger == "blip2" and preview_frame_path:
            self.blip2_manager.ensure_installed()
            caption = self.blip2_manager.generate_caption(preview_frame_path)
            if caption:
                auto_tags = [caption]
        return LabelResult(manual_keywords=manual_keywords, auto_tags=auto_tags)

