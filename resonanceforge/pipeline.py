"""End-to-end mastering pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import pyloudnorm as pyln

from .config import PipelineConfig
from .modules import (
    build_eq,
    build_dynamics,
    apply_stereo,
    apply_saturation,
)


@dataclass
class ProcessReport:
    input_path: str
    output_path: str
    sample_rate: int
    lufs_in: float
    lufs_out: float
    true_peak_out_db: float


class Pipeline:
    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()

    # ---- audio I/O ----
    @staticmethod
    def _read(path: Path) -> tuple[np.ndarray, int]:
        data, sr = sf.read(str(path), always_2d=True)
        # (samples, channels) -> (channels, samples)
        return data.T.astype(np.float32, copy=False), int(sr)

    def _write(self, path: Path, audio: np.ndarray, sr: int) -> None:
        subtype = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}.get(
            self.config.output_bit_depth, "PCM_24"
        )
        sf.write(str(path), audio.T, sr, subtype=subtype)

    # ---- helpers ----
    def _apply_fades(self, audio: np.ndarray, sr: int) -> np.ndarray:
        n_in = int(sr * self.config.fade_in_ms / 1000.0)
        n_out = int(sr * self.config.fade_out_ms / 1000.0)
        out = audio.copy()
        if n_in > 0:
            ramp = np.linspace(0.0, 1.0, n_in, dtype=audio.dtype)
            out[:, :n_in] *= ramp
        if n_out > 0:
            ramp = np.linspace(1.0, 0.0, n_out, dtype=audio.dtype)
            out[:, -n_out:] *= ramp
        return out

    def _normalize_loudness(self, audio: np.ndarray, sr: int) -> tuple[np.ndarray, float, float]:
        meter = pyln.Meter(sr)
        # pyloudnorm expects (samples, channels)
        lufs_in = meter.integrated_loudness(audio.T)
        target = self.config.loudness.target_lufs
        gain_db = target - lufs_in
        gain = 10.0 ** (gain_db / 20.0)
        normalized = audio * gain
        lufs_out = meter.integrated_loudness(normalized.T)
        return normalized, float(lufs_in), float(lufs_out)

    # ---- main ----
    def process(self, input_path: str | Path, output_path: str | Path) -> ProcessReport:
        in_path = Path(input_path)
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        audio, sr = self._read(in_path)

        # EQ
        eq = build_eq(self.config.eq)
        audio = eq(audio.T.astype(np.float32), sr).T

        # Saturation / harmonic color
        audio = apply_saturation(audio, self.config.saturation, sr)

        # Stereo shaping
        audio = apply_stereo(audio, self.config.stereo, sr)

        # Dynamics (comp + limiter)
        dyn = build_dynamics(self.config.dynamics)
        audio = dyn(audio.T.astype(np.float32), sr).T

        # Loudness normalization
        audio, lufs_in, lufs_out = self._normalize_loudness(audio, sr)

        # Final true-peak safety ceiling
        ceiling = 10.0 ** (self.config.loudness.true_peak_db / 20.0)
        peak = float(np.max(np.abs(audio))) or 1.0
        if peak > ceiling:
            audio = audio * (ceiling / peak)
        true_peak_out = 20.0 * np.log10(max(float(np.max(np.abs(audio))), 1e-12))

        # Fades
        audio = self._apply_fades(audio, sr)

        self._write(out_path, audio, sr)
        return ProcessReport(
            input_path=str(in_path),
            output_path=str(out_path),
            sample_rate=sr,
            lufs_in=lufs_in,
            lufs_out=lufs_out,
            true_peak_out_db=true_peak_out,
        )


def process_file(
    input_path: str | Path,
    output_path: str | Path,
    config: Optional[PipelineConfig] = None,
) -> ProcessReport:
    return Pipeline(config).process(input_path, output_path)
