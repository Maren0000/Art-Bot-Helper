"""GPU-first, CPU-fallback client for the cl_tagger_v2 HuggingFace spaces."""
from __future__ import annotations

import asyncio
import functools
import html as html_mod
import logging
import re
import time
from dataclasses import dataclass, field

import httpx
from gradio_client import Client as GradioClient

API_NAME = "/_run_predict"

_HEADER_RE = re.compile(
    r'>(Quality|Rating)</div>'
    r'|<summary[^>]*>\s*(Character|Copyright|General|Meta|Model)\s*\(\d+\)</summary>'
)
_BAR_RE = re.compile(
    r'<div class="tag-bar"[^>]*?data-raw="([\d.]+)"[^>]*>.*?title="([^"]*)"',
    re.DOTALL,
)
_RETRY_IN_RE = re.compile(r"(\d+):(\d{2}):(\d{2})")


def parse_result_html(html: str) -> dict[str, list[tuple[str, float]]]:
    events: list[tuple[int, str, str, float]] = []
    for m in _HEADER_RE.finditer(html):
        events.append((m.start(), "header", m.group(1) or m.group(2), 0.0))
    for m in _BAR_RE.finditer(html):
        tag = html_mod.unescape(m.group(2)).strip().replace(" ", "_")
        events.append((m.start(), "tag", tag, float(m.group(1)) / 100.0))
    events.sort(key=lambda e: e[0])

    result: dict[str, list[tuple[str, float]]] = {}
    current: str | None = None
    for _, kind, payload, prob in events:
        if kind == "header":
            current = payload
            result.setdefault(current, [])
        elif current is not None:
            result[current].append((payload, prob))
    return result


@dataclass
class TagResult:
    categories: dict[str, list[tuple[str, float]]]
    instance: str
    space: str
    elapsed: float
    fell_back: bool = False

    def tags(self, category: str) -> list[str]:
        return [tag for tag, _ in self.categories.get(category, [])]

    @property
    def characters(self) -> list[str]:
        return self.tags("Character")

    @property
    def copyrights(self) -> list[str]:
        return self.tags("Copyright")

    @property
    def rating(self) -> str | None:
        ratings = self.tags("Rating")
        return f"rating_{ratings[0]}" if ratings else None


@dataclass
class _Instance:
    client: GradioClient | None = None
    space: str = ""
    loaded_model: tuple[str, str] | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class QuotaExceeded(Exception):
    def __init__(self, message: str, retry_after: float):
        super().__init__(message)
        self.retry_after = retry_after


class TaggerClient:
    def __init__(self, config, token: str | None = None) -> None:
        self.config = config
        self.token = token or None
        self.logger = logging.getLogger(self.__class__.__name__)
        self._instances: dict[str, _Instance] = {"gpu": _Instance(), "cpu": _Instance()}
        self._predict_lock = asyncio.Lock()
        self._gpu_blocked_until: float = 0.0

    async def predict(self, image_input: dict, instance: str | None = None) -> TagResult:
        async with self._predict_lock:
            loop = asyncio.get_running_loop()
            errors: list[Exception] = []
            order = [instance] if instance else self._auto_order()
            for i, inst in enumerate(order):
                try:
                    result = await loop.run_in_executor(
                        None, functools.partial(self._predict_sync, inst, image_input)
                    )
                    result.fell_back = i > 0
                    return result
                except QuotaExceeded as err:
                    self._gpu_blocked_until = time.monotonic() + err.retry_after
                    self.logger.warning(
                        "GPU space quota exhausted (cooldown %.0f min): %s",
                        err.retry_after / 60, err,
                    )
                    errors.append(err)
                except Exception as err:  # noqa: BLE001
                    self.logger.warning("Tagger predict failed on %s space: %s", inst, err)
                    errors.append(err)
            raise errors[-1]

    def gpu_cooldown_remaining(self) -> float:
        return max(0.0, self._gpu_blocked_until - time.monotonic())

    async def close(self) -> None:
        loop = asyncio.get_running_loop()
        for inst in self._instances.values():
            if inst.client is not None:
                try:
                    await loop.run_in_executor(None, inst.client.close)
                except Exception:  # noqa: BLE001
                    pass
                inst.client = None

    def _auto_order(self) -> list[str]:
        if self.gpu_cooldown_remaining() > 0:
            return ["cpu", "gpu"]
        return ["gpu", "cpu"]

    def _space_for(self, instance: str) -> str:
        settings = self.config.tagger_settings
        return settings["gpu_space" if instance == "gpu" else "cpu_space"].strip()

    def _get_client(self, instance: str) -> GradioClient:
        inst = self._instances[instance]
        space = self._space_for(instance)
        if inst.client is None or inst.space != space:
            self.logger.info("Connecting to %s space %s ...", instance, space)
            inst.client = GradioClient(
                space,
                token=self.token,
                httpx_kwargs={"timeout": httpx.Timeout(120.0, connect=15.0)},
            )
            inst.space = space
            inst.loaded_model = None
        return inst.client

    def _ensure_model(self, instance: str, client: GradioClient) -> None:
        settings = self.config.tagger_settings
        version = str(settings.get("model_version", "")).strip()
        if not version:
            return
        series = str(settings.get("model_series", "")).strip() or "cella110n/cl_tagger_v2"
        inst = self._instances[instance]
        if inst.loaded_model == (series, version):
            return
        self.logger.info("Loading model %s/%s on %s space ...", series, version, instance)
        result = client.predict(series=series, version=version, api_name="/_load_and_reset")
        status = str(result[0]) if isinstance(result, (list, tuple)) else str(result)
        if "failed" in status.lower():
            raise RuntimeError(f"Model load on {instance} space failed: {status}")
        inst.loaded_model = (series, version)
        self.logger.info("Model load on %s space: %s", instance, status)

    def _predict_sync(self, instance: str, image_input: dict) -> TagResult:
        settings = self.config.tagger_settings
        per_tag = settings.get("infer_mode", "per-tag") != "fixed"
        start = time.monotonic()
        try:
            client = self._get_client(instance)
            self._ensure_model(instance, client)
            html = client.predict(
                image=image_input,
                threshold_mode="Per Category",
                general_thr=_as_float(settings.get("general_threshold"), 0.5),
                char_thr=_as_float(settings.get("character_threshold"), 0.75),
                infer_mode="Best-thr (per-tag)" if per_tag else "Fixed threshold",
                min_bthr=_as_float(settings.get("min_best_thr"), 0.5),
                min_bf1=_as_float(settings.get("min_best_f1"), 0.2),
                use_ood=_as_bool(settings.get("use_ood"), True),
                api_name=API_NAME,
            )
        except Exception as err:  # noqa: BLE001
            self._instances[instance].client = None
            if instance == "gpu" and "quota" in str(err).lower():
                raise QuotaExceeded(str(err), self._quota_retry_after(str(err))) from err
            raise
        return TagResult(
            categories=parse_result_html(html),
            instance=instance,
            space=self._space_for(instance),
            elapsed=time.monotonic() - start,
        )

    def _quota_retry_after(self, message: str) -> float:
        m = _RETRY_IN_RE.search(message)
        if m:
            hours, minutes, seconds = (int(g) for g in m.groups())
            parsed = hours * 3600 + minutes * 60 + seconds
            if parsed > 0:
                return parsed
        return _as_float(self.config.tagger_settings.get("gpu_cooldown_minutes"), 30.0) * 60


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip():
        return value.strip().lower() not in ("false", "0", "no", "off")
    return default
