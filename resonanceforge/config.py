"""Configuration dataclasses for the mastering pipeline."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict, fields, is_dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass
class EQConfig:
    highpass_hz: float = 30.0
    lowpass_hz: float = 18000.0
    # Tilt EQ: symmetric low-cut / high-boost around `tilt_pivot_hz`.
    tilt_pivot_hz: float = 1000.0
    tilt_db: float = 0.5


@dataclass
class MultibandBand:
    threshold_db: float
    ratio: float
    attack_ms: float
    release_ms: float


@dataclass
class DynamicsConfig:
    # Crossovers for a 3-band split (low/mid/high). Linkwitz–Riley 4th-order.
    low_mid_crossover_hz: float = 200.0
    mid_high_crossover_hz: float = 2500.0
    low_band: MultibandBand = field(default_factory=lambda: MultibandBand(-20.0, 2.0, 30.0, 200.0))
    mid_band: MultibandBand = field(default_factory=lambda: MultibandBand(-18.0, 2.0, 15.0, 150.0))
    high_band: MultibandBand = field(default_factory=lambda: MultibandBand(-20.0, 1.8, 5.0, 100.0))
    limiter_threshold_db: float = -1.0
    limiter_release_ms: float = 100.0


@dataclass
class StereoConfig:
    width: float = 1.10              # +10% Side by default
    bass_mono_hz: float = 120.0


@dataclass
class SaturationConfig:
    """Harmonic coloration / tonal warmth (tube/tape/exciter)."""
    enabled: bool = True
    mode: Literal["tube", "tape", "exciter"] = "tube"
    drive_db: float = 6.0
    mix: float = 0.25
    tilt_hz: float = 2000.0
    exciter_band_hz: float = 6000.0


@dataclass
class LoudnessConfig:
    target_lufs: float = -14.0
    true_peak_db: float = -1.0
    remeasure_after_limit: bool = True


@dataclass
class QualityConfig:
    """Optional cleanup / repair stages and delivery conversion."""
    # Silence handling
    trim_silence: bool = False
    trim_threshold_db: float = -60.0
    auto_fade_tail: bool = False         # if true, detect decay tail and fade
    # Hum removal
    hum_notch_hz: Optional[int] = None   # 50 or 60 (None disables)
    hum_notch_q: float = 30.0
    hum_notch_depth_db: float = -24.0
    # Static de-esser (narrow-band dip around harsh frequency)
    deesser_enabled: bool = False
    deesser_freq_hz: float = 6500.0
    deesser_depth_db: float = -3.0
    deesser_q: float = 3.0
    # Delivery sample-rate conversion (None = keep input SR)
    target_sample_rate: Optional[int] = None


@dataclass
class PipelineConfig:
    eq: EQConfig = field(default_factory=EQConfig)
    dynamics: DynamicsConfig = field(default_factory=DynamicsConfig)
    stereo: StereoConfig = field(default_factory=StereoConfig)
    saturation: SaturationConfig = field(default_factory=SaturationConfig)
    loudness: LoudnessConfig = field(default_factory=LoudnessConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    output_format: Literal["wav", "flac"] = "wav"
    output_bit_depth: int = 24
    dither: bool = True              # TPDF dither on 16/24-bit PCM output
    fade_in_ms: float = 10.0
    fade_out_ms: float = 50.0
    preserve_metadata: bool = True   # carry tags through when possible
    album_mode: bool = False         # two-pass consistent loudness across batch
    gain_offset_db: float = 0.0      # manual per-track trim

    # ---- serialization ----
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineConfig":
        return _from_dict(cls, data)

    @classmethod
    def load(cls, path: str | Path) -> "PipelineConfig":
        return cls.from_dict(json.loads(Path(path).read_text()))


def _from_dict(klass, data):
    """Recursive dataclass loader tolerant of missing/extra keys."""
    import typing
    if not is_dataclass(klass) or not isinstance(data, dict):
        return data
    try:
        hints = typing.get_type_hints(klass)
    except Exception:
        hints = {f.name: f.type for f in fields(klass)}
    kwargs = {}
    for f in fields(klass):
        if f.name not in data:
            continue
        raw = data[f.name]
        t = hints.get(f.name, f.type)
        if is_dataclass(t) and isinstance(raw, dict):
            kwargs[f.name] = _from_dict(t, raw)
        else:
            kwargs[f.name] = raw
    return klass(**kwargs)
