"""DSP building blocks used by the pipeline."""
from __future__ import annotations

import numpy as np
from pedalboard import (
    Pedalboard,
    HighpassFilter,
    LowShelfFilter,
    HighShelfFilter,
    Compressor,
    Limiter,
    Distortion,
    Gain,
)

from .config import (
    EQConfig,
    DynamicsConfig,
    StereoConfig,
    SaturationConfig,
)


def build_eq(cfg: EQConfig) -> Pedalboard:
    return Pedalboard([
        HighpassFilter(cutoff_frequency_hz=cfg.highpass_hz),
        LowShelfFilter(cutoff_frequency_hz=cfg.low_shelf_hz, gain_db=cfg.low_shelf_db),
        HighShelfFilter(cutoff_frequency_hz=cfg.high_shelf_hz, gain_db=cfg.high_shelf_db),
    ])


def build_dynamics(cfg: DynamicsConfig) -> Pedalboard:
    return Pedalboard([
        Compressor(
            threshold_db=cfg.comp_threshold_db,
            ratio=cfg.comp_ratio,
            attack_ms=cfg.comp_attack_ms,
            release_ms=cfg.comp_release_ms,
        ),
        Limiter(
            threshold_db=cfg.limiter_threshold_db,
            release_ms=cfg.limiter_release_ms,
        ),
    ])


def apply_stereo(audio: np.ndarray, cfg: StereoConfig, sample_rate: float) -> np.ndarray:
    """Mid/Side width control + bass mono-ization.

    `audio` shape: (channels, samples). Mono passes through unchanged.
    """
    if audio.ndim == 1 or audio.shape[0] == 1:
        return audio

    left, right = audio[0], audio[1]
    mid = 0.5 * (left + right)
    side = 0.5 * (left - right)
    side *= float(cfg.width)

    # Bass mono-ization: remove low-frequency content from the side channel.
    if cfg.bass_mono_hz > 0:
        side = _highpass_1pole(side, cfg.bass_mono_hz, sample_rate)

    out_left = mid + side
    out_right = mid - side
    return np.stack([out_left, out_right], axis=0).astype(audio.dtype, copy=False)


def _highpass_1pole(x: np.ndarray, cutoff_hz: float, sr: float) -> np.ndarray:
    """Simple 1-pole highpass (used for M/S bass mono-ization)."""
    if cutoff_hz <= 0 or cutoff_hz >= sr * 0.5:
        return x
    rc = 1.0 / (2.0 * np.pi * cutoff_hz)
    dt = 1.0 / sr
    alpha = rc / (rc + dt)
    y = np.empty_like(x)
    prev_x = 0.0
    prev_y = 0.0
    for i, xi in enumerate(x):
        yi = alpha * (prev_y + xi - prev_x)
        y[i] = yi
        prev_x = xi
        prev_y = yi
    return y


def apply_saturation(
    audio: np.ndarray,
    cfg: SaturationConfig,
    sample_rate: float,
) -> np.ndarray:
    """Harmonic coloration: tube/tape/exciter flavors via parallel drive.

    Implementation notes:
    - `tube`: broadband Distortion with modest drive, full-range.
    - `tape`: broadband drive with a gentle high-shelf cut on the wet path
      to emulate tape HF rolloff.
    - `exciter`: only frequencies above `exciter_band_hz` are driven; lows
      pass through dry so the low end stays clean.
    """
    if not cfg.enabled or cfg.mix <= 0.0:
        return audio

    # pedalboard expects (samples, channels) float32 for process()
    work = audio.T.astype(np.float32, copy=False)

    if cfg.mode == "exciter":
        wet_chain = Pedalboard([
            HighShelfFilter(cutoff_frequency_hz=cfg.exciter_band_hz, gain_db=6.0),
            Distortion(drive_db=cfg.drive_db),
            HighShelfFilter(cutoff_frequency_hz=cfg.exciter_band_hz, gain_db=-6.0),
            Gain(gain_db=-cfg.drive_db * 0.5),
        ])
    elif cfg.mode == "tape":
        wet_chain = Pedalboard([
            LowShelfFilter(cutoff_frequency_hz=cfg.tilt_hz, gain_db=-2.0),
            Distortion(drive_db=cfg.drive_db),
            HighShelfFilter(cutoff_frequency_hz=8000.0, gain_db=-2.0),
            Gain(gain_db=-cfg.drive_db * 0.5),
        ])
    else:  # "tube"
        wet_chain = Pedalboard([
            LowShelfFilter(cutoff_frequency_hz=cfg.tilt_hz, gain_db=-1.5),
            Distortion(drive_db=cfg.drive_db),
            Gain(gain_db=-cfg.drive_db * 0.5),
        ])

    wet = wet_chain(work, sample_rate)
    mix = float(np.clip(cfg.mix, 0.0, 1.0))
    blended = (1.0 - mix) * work + mix * wet
    return blended.T.astype(audio.dtype, copy=False)
