import json

from pathlib import Path

class Config:
    def __init__(self, path: str):
        self.base_path = Path(path)
        self.webhooks = self.load_json((self.base_path / "webhooks.json"))
        self.char_map = self.load_json((self.base_path / "char_map.json"))
        self.series_map = self.load_json((self.base_path / "series_map.json"))
        self.safety_map = self.load_json((self.base_path / "safety_map.json"))
        self.target_series = self.load_set((self.base_path / "target_series.json"))
        self.skip_tags = self.load_set((self.base_path / "skip_tags.json"))
        self.manual_overrides = self.load_dict((self.base_path / "manual_overrides.json"))

    def load_json(self, path: Path):
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:

                return {}
        else:
            return {}

    def reload_char_map(self) -> None:
        self.char_map = self.load_json((self.base_path / "char_map.json"))

    def load_set(self, path: Path) -> set[str]:
        data = self.load_json(path)
        return set(data) if isinstance(data, list) else set()

    def load_dict(self, path: Path) -> dict:
        data = self.load_json(path)
        return data if isinstance(data, dict) else {}