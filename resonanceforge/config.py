"""Configuration dataclasses for the mastering pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class EQConfig:
    highpass_hz: float = 30.0
    low_shelf_hz: float = 120.0
    low_shelf_db: float = 0.0
    high_shelf_hz: float = 8000.0
    high_shelf_db: float = 0.0


@dataclass
class DynamicsConfig:
    comp_threshold_db: float = -18.0
    comp_ratio: float = 2.0
    comp_attack_ms: float = 15.0
    comp_release_ms: float = 120.0
    limiter_threshold_db: float = -1.0
    limiter_release_ms: float = 100.0


@dataclass
class StereoConfig:
    width: float = 1.0            # 1.0 = unchanged, <1 narrower, >1 wider
    bass_mono_hz: float = 120.0   # mono-ize content below this frequency


@dataclass
class SaturationConfig:
    """Harmonic coloration / tonal warmth.

    Purely a creative mastering effect: adds even/odd harmonics for tonal
    character (tube/tape/exciter flavors). Not tuned against any detector.
    """
    enabled: bool = True
    mode: Literal["tube", "tape", "exciter"] = "tube"
    drive_db: float = 6.0
    mix: float = 0.25              # 0..1 parallel blend
    tilt_hz: float = 2000.0        # pre-emphasis pivot; highs driven harder
    exciter_band_hz: float = 6000.0  # for 'exciter' mode: only drive > this


@dataclass
class LoudnessConfig:
    target_lufs: float = -14.0
    true_peak_db: float = -1.0


@dataclass
class PipelineConfig:
    eq: EQConfig = field(default_factory=EQConfig)
    dynamics: DynamicsConfig = field(default_factory=DynamicsConfig)
    stereo: StereoConfig = field(default_factory=StereoConfig)
    saturation: SaturationConfig = field(default_factory=SaturationConfig)
    loudness: LoudnessConfig = field(default_factory=LoudnessConfig)
    output_format: Literal["wav", "flac", "mp3"] = "wav"
    output_bit_depth: int = 24
    fade_in_ms: float = 10.0
    fade_out_ms: float = 50.0
