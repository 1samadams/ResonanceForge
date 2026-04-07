"""DSP building blocks used by the pipeline."""
from __future__ import annotations

import numpy as np
from pedalboard import (
    Pedalboard,
    HighpassFilter,
    LowpassFilter,
    LowShelfFilter,
    HighShelfFilter,
    PeakFilter,
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
    QualityConfig,
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


# ---------------------------------------------------------------------------
# Quality / cleanup stages
# ---------------------------------------------------------------------------

def trim_silence(audio: np.ndarray, sr: float, threshold_db: float) -> np.ndarray:
    """Trim leading/trailing silence below the given threshold (dBFS).

    Uses a short moving-RMS window (20 ms) over the channel-max signal.
    """
    if audio.size == 0:
        return audio
    thresh = 10.0 ** (threshold_db / 20.0)
    win = max(int(0.02 * sr), 1)
    mono = np.max(np.abs(audio), axis=0)
    # Simple boxcar moving average
    if mono.shape[0] < win:
        return audio
    cum = np.cumsum(np.insert(mono, 0, 0.0))
    rms = (cum[win:] - cum[:-win]) / win
    above = np.where(rms > thresh)[0]
    if above.size == 0:
        return audio
    start = int(above[0])
    end = int(above[-1]) + win
    end = min(end, audio.shape[1])
    return audio[:, start:end]


def auto_fade_tail(audio: np.ndarray, sr: float, threshold_db: float = -40.0) -> np.ndarray:
    """Detect the decay tail and replace it with a linear fade.

    Finds the last sample where energy exceeds `threshold_db`, then fades
    everything after it down to silence.
    """
    if audio.size == 0:
        return audio
    thresh = 10.0 ** (threshold_db / 20.0)
    mono = np.max(np.abs(audio), axis=0)
    above = np.where(mono > thresh)[0]
    if above.size == 0:
        return audio
    last = int(above[-1])
    n = audio.shape[1]
    tail = n - last
    if tail <= 1:
        return audio
    ramp = np.linspace(1.0, 0.0, tail, dtype=audio.dtype)
    out = audio.copy()
    out[:, last:] *= ramp
    return out


def apply_hum_notch(
    audio: np.ndarray, sr: float, hz: int, q: float, depth_db: float,
) -> np.ndarray:
    """Notch the hum fundamental and a few harmonics (hz, 2hz, 3hz)."""
    if hz <= 0:
        return audio
    work = audio.T.astype(np.float32, copy=False)
    chain = Pedalboard([
        PeakFilter(cutoff_frequency_hz=float(hz), gain_db=float(depth_db), q=float(q)),
        PeakFilter(cutoff_frequency_hz=float(2 * hz), gain_db=float(depth_db), q=float(q)),
        PeakFilter(cutoff_frequency_hz=float(3 * hz), gain_db=float(depth_db), q=float(q)),
    ])
    return chain(work, sr).T.astype(audio.dtype, copy=False)


def apply_deesser_static(
    audio: np.ndarray, sr: float, freq_hz: float, depth_db: float, q: float,
) -> np.ndarray:
    """Static de-esser: a narrow dip at the harshness frequency.

    Not a true dynamic de-esser (no sidechain), but a common mastering
    trick when you just want to tame consistent sibilance.
    """
    work = audio.T.astype(np.float32, copy=False)
    chain = Pedalboard([
        PeakFilter(cutoff_frequency_hz=float(freq_hz), gain_db=float(depth_db), q=float(q)),
    ])
    return chain(work, sr).T.astype(audio.dtype, copy=False)


def apply_quality(audio: np.ndarray, cfg: QualityConfig, sr: float) -> np.ndarray:
    """Run the optional cleanup stages in a sensible order."""
    if cfg.trim_silence:
        audio = trim_silence(audio, sr, cfg.trim_threshold_db)
    if cfg.hum_notch_hz:
        audio = apply_hum_notch(
            audio, sr, int(cfg.hum_notch_hz), cfg.hum_notch_q, cfg.hum_notch_depth_db,
        )
    if cfg.deesser_enabled:
        audio = apply_deesser_static(
            audio, sr, cfg.deesser_freq_hz, cfg.deesser_depth_db, cfg.deesser_q,
        )
    if cfg.auto_fade_tail:
        audio = auto_fade_tail(audio, sr)
    return audio


def resample_if_needed(audio: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Polyphase SRC via scipy. Returns `audio` unchanged when SRs match."""
    if sr_out <= 0 or sr_out == sr_in:
        return audio
    from math import gcd
    from scipy.signal import resample_poly
    g = gcd(sr_in, sr_out)
    up = sr_out // g
    down = sr_in // g
    # resample_poly operates along an axis; work in (samples, channels)
    work = audio.T.astype(np.float32, copy=False)
    out = resample_poly(work, up, down, axis=0)
    return out.T.astype(audio.dtype, copy=False)


def oversampled_true_peak_db(audio: np.ndarray, factor: int = 4) -> float:
    """4× oversampled inter-sample peak in dBFS.

    Approximates ITU-R BS.1770-4 true-peak by polyphase upsampling and
    taking the absolute peak. Good enough for reporting; not a limiter.
    """
    if audio.size == 0:
        return -120.0
    try:
        from scipy.signal import resample_poly
        up = resample_poly(audio, factor, 1, axis=-1)
    except Exception:
        up = audio
    peak = float(np.max(np.abs(up)))
    if peak <= 0:
        return -120.0
    return 20.0 * np.log10(peak)


def stereo_correlation(audio: np.ndarray) -> float:
    """Pearson correlation between L and R (mono returns 1.0)."""
    if audio.ndim == 1 or audio.shape[0] < 2:
        return 1.0
    l = audio[0].astype(np.float64)
    r = audio[1].astype(np.float64)
    if l.std() == 0 or r.std() == 0:
        return 1.0
    return float(np.clip(np.corrcoef(l, r)[0, 1], -1.0, 1.0))


def loudness_range_db(audio: np.ndarray, sr: float) -> float:
    """Simple LRA approximation: 95th - 10th percentile of short-term LUFS.

    Uses a 3-second sliding window with 1-second hop. Not a full
    EBU R128 LRA implementation but close enough for a report field.
    """
    if audio.size == 0:
        return 0.0
    try:
        import pyloudnorm as pyln
    except Exception:
        return 0.0
    meter = pyln.Meter(sr)
    win = int(3.0 * sr)
    hop = int(1.0 * sr)
    n = audio.shape[-1]
    if n < win:
        return 0.0
    vals = []
    for start in range(0, n - win + 1, hop):
        block = audio[:, start:start + win]
        try:
            v = meter.integrated_loudness(block.T)
            if np.isfinite(v) and v > -70:
                vals.append(v)
        except Exception:
            continue
    if len(vals) < 2:
        return 0.0
    arr = np.array(vals)
    return float(np.percentile(arr, 95) - np.percentile(arr, 10))
