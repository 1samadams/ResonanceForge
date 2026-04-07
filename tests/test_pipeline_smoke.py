"""Smoke tests for the mastering pipeline."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from resonanceforge.config import PipelineConfig
from resonanceforge.pipeline import Pipeline


SR = 48000


def _write_wav(path: Path, audio: np.ndarray, sr: int = SR) -> None:
    sf.write(str(path), audio.T if audio.ndim == 2 else audio, sr, subtype="PCM_24")


def _pink_stereo(duration_s: float = 2.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(SR * duration_s)
    # White noise → approximate pink via simple 1/f filter
    white = rng.standard_normal((2, n)).astype(np.float32)
    pink = np.zeros_like(white)
    b = np.array([0.049922035, -0.095993537, 0.050612699, -0.004408786], dtype=np.float32)
    a = np.array([1.0, -2.494956002, 2.017265875, -0.522189400], dtype=np.float32)
    from scipy.signal import lfilter  # optional — fallback if unavailable
    try:
        pink[0] = lfilter(b, a, white[0])
        pink[1] = lfilter(b, a, white[1])
    except Exception:
        pink = white
    pink *= 0.2
    return pink.astype(np.float32)


def _sine_stereo(freq: float = 440.0, duration_s: float = 2.0) -> np.ndarray:
    t = np.arange(int(SR * duration_s), dtype=np.float32) / SR
    s = 0.1 * np.sin(2 * math.pi * freq * t).astype(np.float32)
    return np.stack([s, s], axis=0)


@pytest.mark.parametrize("channels", [1, 2])
def test_pipeline_hits_target_lufs(tmp_path: Path, channels: int) -> None:
    audio = _sine_stereo()
    if channels == 1:
        audio = audio[:1]
    src = tmp_path / "in.wav"
    dst = tmp_path / "out.wav"
    _write_wav(src, audio)

    cfg = PipelineConfig()
    cfg.loudness.target_lufs = -14.0
    cfg.loudness.true_peak_db = -1.0
    cfg.saturation.enabled = False  # keep the test signal predictable

    report = Pipeline(cfg).process(src, dst)

    # LUFS within ±1.0 of target (sine is edge-case for meters).
    assert abs(report.lufs_out - cfg.loudness.target_lufs) < 1.0
    # Peak must respect the ceiling.
    assert report.sample_peak_db <= cfg.loudness.true_peak_db + 0.01
    assert not report.clipped

    # Readable output
    data, sr = sf.read(str(dst), always_2d=True)
    assert sr == SR
    assert np.all(np.isfinite(data))


def test_silent_input_does_not_blow_up(tmp_path: Path) -> None:
    src = tmp_path / "silent.wav"
    dst = tmp_path / "out.wav"
    _write_wav(src, np.zeros((2, SR), dtype=np.float32))

    report = Pipeline().process(src, dst)
    assert math.isfinite(report.sample_peak_db)
    assert not report.clipped
    data, _ = sf.read(str(dst))
    assert np.all(np.isfinite(data))


def test_very_short_clip_no_fade_overrun(tmp_path: Path) -> None:
    # 20 ms — shorter than fade_in+fade_out default (60ms).
    n = int(SR * 0.02)
    audio = 0.1 * np.ones((2, n), dtype=np.float32)
    src = tmp_path / "short.wav"
    dst = tmp_path / "out.wav"
    _write_wav(src, audio)

    report = Pipeline().process(src, dst)
    assert math.isfinite(report.sample_peak_db)


def test_flac_output(tmp_path: Path) -> None:
    src = tmp_path / "in.wav"
    dst = tmp_path / "out.flac"
    _write_wav(src, _sine_stereo())

    cfg = PipelineConfig()
    cfg.output_format = "flac"  # type: ignore[assignment]
    cfg.saturation.enabled = False

    Pipeline(cfg).process(src, dst)
    assert dst.exists()
    data, sr = sf.read(str(dst))
    assert sr == SR
    assert len(data) > 0


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    src = tmp_path / "in.wav"
    dst = tmp_path / "out.wav"
    _write_wav(src, _sine_stereo())

    report = Pipeline().process(src, dst, dry_run=True)
    assert not dst.exists()
    assert math.isfinite(report.lufs_out)
