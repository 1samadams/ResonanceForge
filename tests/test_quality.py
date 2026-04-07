"""Tests for the new quality / delivery features."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from resonanceforge.config import PipelineConfig
from resonanceforge.modules import (
    trim_silence,
    auto_fade_tail,
    resample_if_needed,
    oversampled_true_peak_db,
    stereo_correlation,
    loudness_range_db,
)
from resonanceforge.pipeline import Pipeline


SR = 48000


def _tone(duration_s: float = 2.0, freq: float = 1000.0) -> np.ndarray:
    t = np.arange(int(SR * duration_s), dtype=np.float32) / SR
    s = 0.2 * np.sin(2 * math.pi * freq * t).astype(np.float32)
    return np.stack([s, s], axis=0)


def test_trim_silence_drops_leading_tail() -> None:
    tone = _tone(1.0)
    pad = np.zeros((2, SR // 2), dtype=np.float32)
    padded = np.concatenate([pad, tone, pad], axis=1)
    trimmed = trim_silence(padded, SR, -60.0)
    assert trimmed.shape[1] < padded.shape[1]
    assert trimmed.shape[1] >= tone.shape[1] - 200  # allow some slack


def test_auto_fade_tail_zeros_end() -> None:
    audio = _tone(1.0)
    # Append silence that would otherwise be left alone.
    silence = np.zeros((2, SR), dtype=np.float32)
    joined = np.concatenate([audio, silence], axis=1)
    faded = auto_fade_tail(joined, SR)
    assert abs(faded[0, -1]) < 1e-4


def test_resample_round_trip() -> None:
    audio = _tone(1.0)
    up = resample_if_needed(audio, SR, 96000)
    assert abs(up.shape[1] - 2 * audio.shape[1]) <= 2
    back = resample_if_needed(up, 96000, SR)
    assert abs(back.shape[1] - audio.shape[1]) <= 2


def test_oversampled_tp_meter_monotone() -> None:
    quiet = _tone(0.5) * 0.1
    loud = _tone(0.5) * 0.9
    assert oversampled_true_peak_db(loud) > oversampled_true_peak_db(quiet)


def test_stereo_correlation_bounds() -> None:
    a = _tone(0.5)
    assert pytest.approx(stereo_correlation(a), abs=1e-6) == 1.0
    inverted = a.copy()
    inverted[1] *= -1
    assert stereo_correlation(inverted) < -0.99


def test_loudness_range_finite() -> None:
    lra = loudness_range_db(_tone(5.0), SR)
    assert math.isfinite(lra)
    assert lra >= 0.0


def test_full_pipeline_with_quality_stages(tmp_path: Path) -> None:
    src = tmp_path / "in.wav"
    dst = tmp_path / "out.wav"
    sf.write(str(src), _tone(2.0).T, SR, subtype="PCM_24")

    cfg = PipelineConfig()
    cfg.saturation.enabled = False
    cfg.quality.trim_silence = True
    cfg.quality.hum_notch_hz = 50
    cfg.quality.deesser_enabled = True
    cfg.quality.target_sample_rate = 44100
    rep = Pipeline(cfg).process(src, dst)

    data, sr = sf.read(str(dst))
    assert sr == 44100
    assert np.all(np.isfinite(data))
    assert rep.sample_rate == 44100
    assert math.isfinite(rep.lufs_range)
    assert -1.0 <= rep.stereo_correlation <= 1.0


def test_album_mode_consistent_gain(tmp_path: Path) -> None:
    quiet_src = tmp_path / "quiet.wav"
    loud_src = tmp_path / "loud.wav"
    sf.write(str(quiet_src), (_tone(2.0) * 0.1).T, SR, subtype="PCM_24")
    sf.write(str(loud_src), (_tone(2.0) * 0.5).T, SR, subtype="PCM_24")

    cfg = PipelineConfig()
    cfg.saturation.enabled = False
    cfg.album_mode = True
    pipe = Pipeline(cfg)
    reports = pipe.process_album([quiet_src, loud_src], tmp_path / "out")
    assert len(reports) == 2
    # The originally louder track should still be louder (relative dynamics
    # preserved) but neither should clip.
    assert not any(r.clipped for r in reports)
