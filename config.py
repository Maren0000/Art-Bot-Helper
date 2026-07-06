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
        self.api_settings = self.load_dict((self.base_path / "api_settings.json"))

    @property
    def poster_role_id(self) -> int | None:
        try:
            return int(self.api_settings.get("poster_role_id", "")) or None
        except (TypeError, ValueError):
            return None

    @property
    def token_expiry_days(self) -> int | None:
        """Days before userscript API tokens expire; None/0 means never."""
        try:
            return int(self.api_settings.get("token_expiry_days", "0")) or None
        except (TypeError, ValueError):
            return None

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

    def reload_all(self) -> None:
        self.webhooks = self.load_json(self.base_path / "webhooks.json")
        self.char_map = self.load_json(self.base_path / "char_map.json")
        self.series_map = self.load_json(self.base_path / "series_map.json")
        self.safety_map = self.load_json(self.base_path / "safety_map.json")
        self.target_series = self.load_set(self.base_path / "target_series.json")
        self.skip_tags = self.load_set(self.base_path / "skip_tags.json")
        self.manual_overrides = self.load_dict(self.base_path / "manual_overrides.json")
        self.api_settings = self.load_dict(self.base_path / "api_settings.json")

    def load_set(self, path: Path) -> set[str]:
        data = self.load_json(path)
        return set(data) if isinstance(data, list) else set()

    def load_dict(self, path: Path) -> dict:
        data = self.load_json(path)
        return data if isinstance(data, dict) else {}