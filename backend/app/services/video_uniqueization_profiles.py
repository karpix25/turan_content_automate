import random
from typing import Literal, Optional, TypedDict


UniqueizationMode = Literal["off", "light", "standard", "aggressive", "auto"]


class VideoUniqueizationProfile(TypedDict):
    variant_id: int
    mode: str
    unique_variations_enabled: int
    brightness: float
    contrast: float
    saturation: float
    gamma: float
    speed: float
    zoom: float
    shift_x: int
    shift_y: int
    rotate_degrees: float
    grain_strength: int
    trim_start_seconds: float
    trim_end_seconds: float
    audio_volume: float
    audio_bass_db: float
    audio_treble_db: float
    crf: int
    gop: int
    metadata_tag: str


VALID_UNIQUEIZATION_MODES = {"off", "light", "standard", "aggressive", "auto"}


def normalize_uniqueization_mode(mode: Optional[str]) -> UniqueizationMode:
    normalized = (mode or "auto").strip().lower()
    if normalized not in VALID_UNIQUEIZATION_MODES:
        return "auto"
    return normalized  # type: ignore[return-value]


def resolve_uniqueization_mode(
    mode: Optional[str],
    *,
    force_enabled: bool = False,
    env_enabled: bool = False,
) -> Literal["off", "light", "standard", "aggressive"]:
    normalized = normalize_uniqueization_mode(mode)
    if normalized == "off":
        return "off"
    if normalized in {"light", "standard", "aggressive"}:
        return normalized
    if force_enabled:
        return "standard"
    return "light" if env_enabled else "off"


def build_uniqueization_profile(
    unique_seed: Optional[int],
    *,
    mode: Optional[str] = "auto",
    force_enabled: bool = False,
    env_enabled: bool = False,
) -> VideoUniqueizationProfile:
    resolved_mode = resolve_uniqueization_mode(
        mode,
        force_enabled=force_enabled,
        env_enabled=env_enabled,
    )
    if resolved_mode == "off":
        return _disabled_profile()

    rnd = random.Random(unique_seed if unique_seed is not None else random.randint(1, 10_000_000))
    if resolved_mode == "aggressive":
        return _enabled_profile(
            rnd,
            mode=resolved_mode,
            brightness=(-0.04, 0.04),
            contrast=(0.96, 1.08),
            saturation=(0.94, 1.10),
            gamma=(0.96, 1.05),
            speed=(0.992, 1.008),
            zoom=(1.012, 1.025),
            shift=(-10, 10),
            rotate=(-0.25, 0.25),
            grain=(1, 3),
            trim=(0.0, 0.35),
            audio_volume=(0.985, 1.015),
            audio_bass=(-1.4, 1.4),
            audio_treble=(-1.8, 1.8),
            crf=(18, 21),
            gop=(42, 60),
        )
    if resolved_mode == "standard":
        return _enabled_profile(
            rnd,
            mode=resolved_mode,
            brightness=(-0.03, 0.03),
            contrast=(0.97, 1.06),
            saturation=(0.95, 1.08),
            gamma=(0.97, 1.04),
            speed=(0.994, 1.006),
            zoom=(1.006, 1.015),
            shift=(-6, 6),
            rotate=(0.0, 0.0),
            grain=(0, 1),
            trim=(0.0, 0.18),
            audio_volume=(0.99, 1.01),
            audio_bass=(-0.8, 0.8),
            audio_treble=(-1.0, 1.0),
            crf=(18, 20),
            gop=(45, 58),
        )
    return _enabled_profile(
        rnd,
        mode="light",
        brightness=(-0.02, 0.02),
        contrast=(0.985, 1.035),
        saturation=(0.97, 1.05),
        gamma=(0.985, 1.025),
        speed=(0.996, 1.004),
        zoom=(1.0, 1.0),
        shift=(0, 0),
        rotate=(0.0, 0.0),
        grain=(0, 0),
        trim=(0.0, 0.0),
        audio_volume=(1.0, 1.0),
        audio_bass=(0.0, 0.0),
        audio_treble=(0.0, 0.0),
        crf=(18, 19),
        gop=(48, 54),
    )


def _disabled_profile() -> VideoUniqueizationProfile:
    return {
        "variant_id": 0,
        "mode": "off",
        "unique_variations_enabled": 0,
        "brightness": 0.0,
        "contrast": 1.0,
        "saturation": 1.0,
        "gamma": 1.0,
        "speed": 1.0,
        "zoom": 1.0,
        "shift_x": 0,
        "shift_y": 0,
        "rotate_degrees": 0.0,
        "grain_strength": 0,
        "trim_start_seconds": 0.0,
        "trim_end_seconds": 0.0,
        "audio_volume": 1.0,
        "audio_bass_db": 0.0,
        "audio_treble_db": 0.0,
        "crf": 18,
        "gop": 48,
        "metadata_tag": "off",
    }


def _enabled_profile(
    rnd: random.Random,
    *,
    mode: str,
    brightness: tuple[float, float],
    contrast: tuple[float, float],
    saturation: tuple[float, float],
    gamma: tuple[float, float],
    speed: tuple[float, float],
    zoom: tuple[float, float],
    shift: tuple[int, int],
    rotate: tuple[float, float],
    grain: tuple[int, int],
    trim: tuple[float, float],
    audio_volume: tuple[float, float],
    audio_bass: tuple[float, float],
    audio_treble: tuple[float, float],
    crf: tuple[int, int],
    gop: tuple[int, int],
) -> VideoUniqueizationProfile:
    variant_id = int(rnd.random() * 1_000_000_000)
    return {
        "variant_id": variant_id,
        "mode": mode,
        "unique_variations_enabled": 1,
        "brightness": round(rnd.uniform(*brightness), 4),
        "contrast": round(rnd.uniform(*contrast), 4),
        "saturation": round(rnd.uniform(*saturation), 4),
        "gamma": round(rnd.uniform(*gamma), 4),
        "speed": round(rnd.uniform(*speed), 5),
        "zoom": round(rnd.uniform(*zoom), 5),
        "shift_x": rnd.randint(*shift),
        "shift_y": rnd.randint(*shift),
        "rotate_degrees": round(rnd.uniform(*rotate), 4),
        "grain_strength": rnd.randint(*grain),
        "trim_start_seconds": round(rnd.uniform(*trim), 3),
        "trim_end_seconds": round(rnd.uniform(*trim), 3),
        "audio_volume": round(rnd.uniform(*audio_volume), 4),
        "audio_bass_db": round(rnd.uniform(*audio_bass), 3),
        "audio_treble_db": round(rnd.uniform(*audio_treble), 3),
        "crf": rnd.randint(*crf),
        "gop": rnd.randint(*gop),
        "metadata_tag": f"{mode}-{variant_id:x}",
    }
