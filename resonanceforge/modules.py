"""DSP building blocks used by the pipeline."""
from __future__ import annotations

import numpy as np
from pedalboard import (
    Pedalboard,
    HighpassFilter,
    LowpassFilter,
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
    """Utility HPF + tilt EQ (symmetric low-cut / high-boost around pivot)."""
    return Pedalboard([
        HighpassFilter(cutoff_frequency_hz=cfg.highpass_hz),
        LowpassFilter(cutoff_frequency_hz=cfg.lowpass_hz),
        LowShelfFilter(cutoff_frequency_hz=cfg.tilt_pivot_hz, gain_db=-cfg.tilt_db),
        HighShelfFilter(cutoff_frequency_hz=cfg.tilt_pivot_hz, gain_db=+cfg.tilt_db),
    ])


def _lr4_lowpass(cutoff_hz: float) -> Pedalboard:
    """Linkwitz–Riley 4th-order lowpass = two cascaded Butterworth 2nd-order."""
    return Pedalboard([
        LowpassFilter(cutoff_frequency_hz=cutoff_hz),
        LowpassFilter(cutoff_frequency_hz=cutoff_hz),
    ])


def _lr4_highpass(cutoff_hz: float) -> Pedalboard:
    return Pedalboard([
        HighpassFilter(cutoff_frequency_hz=cutoff_hz),
        HighpassFilter(cutoff_frequency_hz=cutoff_hz),
    ])


def _compressor(band: "MultibandBand") -> Compressor:  # type: ignore[name-defined]
    return Compressor(
        threshold_db=band.threshold_db,
        ratio=band.ratio,
        attack_ms=band.attack_ms,
        release_ms=band.release_ms,
    )


def apply_multiband(audio: np.ndarray, cfg: DynamicsConfig, sample_rate: float) -> np.ndarray:
    """3-band multiband compressor with Linkwitz–Riley 4th-order crossovers.

    Bands are split with cascaded Butterworth pairs (LR4) at the two
    crossover frequencies so that summing the bands is phase-coherent at
    the crossover points. Each band is compressed independently, then the
    three bands are summed back to the master bus.
    """
    work = audio.T.astype(np.float32, copy=False)
    sr = float(sample_rate)
    f_lo = float(cfg.low_mid_crossover_hz)
    f_hi = float(cfg.mid_high_crossover_hz)

    low = _lr4_lowpass(f_lo)(work, sr)
    mid_hp = _lr4_highpass(f_lo)(work, sr)
    mid = _lr4_lowpass(f_hi)(mid_hp, sr)
    high = _lr4_highpass(f_hi)(work, sr)

    low = Pedalboard([_compressor(cfg.low_band)])(low, sr)
    mid = Pedalboard([_compressor(cfg.mid_band)])(mid, sr)
    high = Pedalboard([_compressor(cfg.high_band)])(high, sr)

    summed = low + mid + high
    return summed.T.astype(audio.dtype, copy=False)


def build_limiter(cfg: DynamicsConfig) -> Pedalboard:
    return Pedalboard([
        Limiter(
            threshold_db=cfg.limiter_threshold_db,
            release_ms=cfg.limiter_release_ms,
        ),
    ])


def ensure_stereo(audio: np.ndarray) -> np.ndarray:
    """Upmix mono to stereo by duplicating; passthrough for stereo."""
    if audio.ndim == 1:
        return np.stack([audio, audio], axis=0)
    if audio.shape[0] == 1:
        return np.repeat(audio, 2, axis=0)
    return audio


def apply_stereo(audio: np.ndarray, cfg: StereoConfig, sample_rate: float) -> np.ndarray:
    """Mid/Side width control + bass mono-ization.

    `audio` shape: (channels, samples). Mono is upmixed to stereo first.
    """
    audio = ensure_stereo(audio)

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
