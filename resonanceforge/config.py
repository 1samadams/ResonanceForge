"""Configuration dataclasses for the mastering pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class EQConfig:
    highpass_hz: float = 30.0
    lowpass_hz: float = 18000.0
    # Tilt EQ: pivots around `tilt_pivot_hz`. Positive dB tilts brighter
    # (boost highs / cut lows by the same amount), negative tilts darker.
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
    # Crossover frequencies for a 3-band split (low/mid/high).
    low_mid_crossover_hz: float = 200.0
    mid_high_crossover_hz: float = 2500.0
    low_band: MultibandBand = field(default_factory=lambda: MultibandBand(-20.0, 2.0, 30.0, 200.0))
    mid_band: MultibandBand = field(default_factory=lambda: MultibandBand(-18.0, 2.0, 15.0, 150.0))
    high_band: MultibandBand = field(default_factory=lambda: MultibandBand(-20.0, 1.8, 5.0, 100.0))
    limiter_threshold_db: float = -1.0
    limiter_release_ms: float = 100.0


@dataclass
class StereoConfig:
    # +10% side gain for width (1.10). <1 narrower, >1 wider.
    width: float = 1.10
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
