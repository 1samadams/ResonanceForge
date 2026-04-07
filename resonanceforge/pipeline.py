"""End-to-end mastering pipeline."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import soundfile as sf
import pyloudnorm as pyln

from .config import PipelineConfig
from .modules import (
    build_eq,
    apply_multiband,
    build_limiter,
    apply_stereo,
    apply_saturation,
    apply_quality,
    ensure_stereo,
    resample_if_needed,
    oversampled_true_peak_db,
    stereo_correlation,
    loudness_range_db,
)


# Supported output formats → soundfile format/subtype mapping.
_SUBTYPES = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}
_FORMATS = {"wav": "WAV", "flac": "FLAC"}


@dataclass
class ProcessReport:
    input_path: str
    output_path: str
    sample_rate: int
    channels: int
    lufs_in: float
    lufs_out: float
    sample_peak_db: float
    true_peak_out_db: float    # 4x oversampled inter-sample peak
    clipped: bool
    lufs_range: float = 0.0    # LRA approximation (95th - 10th percentile)
    stereo_correlation: float = 1.0
    config_snapshot: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        fmt = self.config.output_format.lower()
        if fmt not in _FORMATS:
            raise ValueError(
                f"Unsupported output_format {fmt!r}; supported: {list(_FORMATS)}"
            )
        subtype = _SUBTYPES.get(self.config.output_bit_depth, "PCM_24")
        # FLAC only supports integer PCM.
        if fmt == "flac" and subtype == "FLOAT":
            subtype = "PCM_24"
        sf.write(
            str(path),
            audio.T,
            sr,
            format=_FORMATS[fmt],
            subtype=subtype,
        )

    # ---- helpers ----
    @staticmethod
    def _sanitize(audio: np.ndarray) -> np.ndarray:
        """Replace NaN/Inf with 0 so downstream meters don't blow up."""
        if not np.all(np.isfinite(audio)):
            audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
        return audio

    def _apply_fades(self, audio: np.ndarray, sr: int) -> np.ndarray:
        n = audio.shape[-1]
        if n == 0:
            return audio
        n_in = int(sr * self.config.fade_in_ms / 1000.0)
        n_out = int(sr * self.config.fade_out_ms / 1000.0)
        # Clamp so the ramps can never overlap.
        max_each = max(n // 2, 0)
        n_in = min(n_in, max_each)
        n_out = min(n_out, max_each)
        out = audio.copy()
        if n_in > 0:
            ramp = np.linspace(0.0, 1.0, n_in, dtype=audio.dtype)
            out[:, :n_in] *= ramp
        if n_out > 0:
            ramp = np.linspace(1.0, 0.0, n_out, dtype=audio.dtype)
            out[:, -n_out:] *= ramp
        return out

    @staticmethod
    def _safe_lufs(meter: pyln.Meter, audio: np.ndarray) -> float:
        """pyloudnorm returns -inf for silent signals; clamp to a sane floor."""
        try:
            value = float(meter.integrated_loudness(audio.T))
        except Exception:
            return -120.0
        if not np.isfinite(value):
            return -120.0
        return value

    def _normalize_loudness(
        self, audio: np.ndarray, sr: int
    ) -> tuple[np.ndarray, float, float]:
        meter = pyln.Meter(sr)
        lufs_in = self._safe_lufs(meter, audio)
        target = self.config.loudness.target_lufs
        # Sentinel used by album mode to bypass per-track normalization.
        if target <= -199.0:
            return audio, lufs_in, lufs_in
        if lufs_in <= -70.0:
            # Effectively silent; don't apply huge gain.
            return audio, lufs_in, lufs_in
        gain_db = target - lufs_in
        gain = 10.0 ** (gain_db / 20.0)
        normalized = audio * gain
        lufs_out = self._safe_lufs(meter, normalized)
        return normalized, lufs_in, lufs_out

    @staticmethod
    def _tpdf_dither(shape: tuple[int, ...], bit_depth: int) -> np.ndarray:
        """Triangular-PDF dither at 1 LSB for the target bit depth."""
        lsb = 1.0 / (2 ** (bit_depth - 1))
        rng = np.random.default_rng()
        # TPDF = sum of two uniform [-0.5, 0.5] LSB noises
        a = rng.random(shape, dtype=np.float32) - 0.5
        b = rng.random(shape, dtype=np.float32) - 0.5
        return ((a + b) * lsb).astype(np.float32)

    # ---- main ----
    def process(
        self, input_path: str | Path, output_path: str | Path,
        dry_run: bool = False,
        extra_gain_db: float = 0.0,
    ) -> ProcessReport:
        in_path = Path(input_path)
        out_path = Path(output_path)
        if not dry_run:
            out_path.parent.mkdir(parents=True, exist_ok=True)

        audio, sr = self._read(in_path)
        audio = self._sanitize(audio)
        # Everything downstream assumes stereo.
        audio = ensure_stereo(audio)
        channels = int(audio.shape[0])

        # Optional cleanup / repair stages up-front (trim, notch, de-ess, tail-fade).
        audio = apply_quality(audio, self.config.quality, sr)

        # Manual trim (per-track gain) applied early so EQ/limiter see the level.
        g_db = float(self.config.gain_offset_db) + float(extra_gain_db)
        if g_db != 0.0:
            audio = audio * (10.0 ** (g_db / 20.0))

        # EQ
        eq = build_eq(self.config.eq)
        audio = eq(audio.T.astype(np.float32), sr).T

        # Saturation / harmonic color
        audio = apply_saturation(audio, self.config.saturation, sr)

        # Stereo shaping
        audio = apply_stereo(audio, self.config.stereo, sr)

        # Dynamics: 3-band multiband compression, then brickwall limiter
        audio = apply_multiband(audio, self.config.dynamics, sr)
        limiter = build_limiter(self.config.dynamics)
        audio = limiter(audio.T.astype(np.float32), sr).T

        audio = self._sanitize(audio)

        # Loudness normalization
        audio, lufs_in, lufs_out = self._normalize_loudness(audio, sr)

        # Peak-safety rescale against the configured ceiling (sample peak).
        ceiling_db = self.config.loudness.true_peak_db
        ceiling = 10.0 ** (ceiling_db / 20.0)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > ceiling and peak > 0:
            audio = audio * (ceiling / peak)

        # Optionally re-measure LUFS after the final safety pass so the
        # reported value matches what's actually written to disk.
        if self.config.loudness.remeasure_after_limit:
            meter = pyln.Meter(sr)
            lufs_out = self._safe_lufs(meter, audio)

        # Measurements for the report.
        sample_peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        sample_peak_db = 20.0 * np.log10(max(sample_peak, 1e-12))
        # Real 4× oversampled inter-sample peak.
        true_peak_db = oversampled_true_peak_db(audio, factor=4)
        lra = loudness_range_db(audio, sr)
        corr = stereo_correlation(audio)
        clipped = sample_peak >= 0.9999 or true_peak_db >= ceiling_db + 0.01

        # Fades
        audio = self._apply_fades(audio, sr)

        # Delivery sample-rate conversion (last, after all DSP, before dither).
        target_sr = self.config.quality.target_sample_rate
        out_sr = int(target_sr) if target_sr else sr
        if out_sr != sr:
            audio = resample_if_needed(audio, sr, out_sr)

        # Dither (TPDF) before PCM quantization.
        bd = self.config.output_bit_depth
        if (
            not dry_run
            and self.config.dither
            and bd in (16, 24)
        ):
            audio = audio + self._tpdf_dither(audio.shape, bd)
            # Re-clip just in case dither nudged us over.
            np.clip(audio, -1.0, 1.0, out=audio)

        if not dry_run:
            self._write(out_path, audio, out_sr)
            if self.config.preserve_metadata:
                _try_copy_metadata(in_path, out_path)

        return ProcessReport(
            input_path=str(in_path),
            output_path=str(out_path),
            sample_rate=out_sr,
            channels=channels,
            lufs_in=lufs_in,
            lufs_out=lufs_out,
            sample_peak_db=sample_peak_db,
            true_peak_out_db=true_peak_db,
            clipped=clipped,
            lufs_range=lra,
            stereo_correlation=corr,
            config_snapshot=self.config.to_dict(),
        )

    # ---- album (two-pass) ----
    def process_album(
        self,
        files: list[str | Path],
        output_dir: str | Path,
        ext: str = "wav",
    ) -> list[ProcessReport]:
        """Two-pass album mastering: measure loudness of every track first,
        then apply a per-track gain offset so the loudest track hits the
        configured target and the rest preserve their relative dynamics.

        This keeps inter-track loudness consistent (R128 album mode style).
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Pass 1: integrated loudness of each input (no processing).
        loudness = []
        for f in files:
            audio, sr = self._read(Path(f))
            audio = self._sanitize(ensure_stereo(audio))
            meter = pyln.Meter(sr)
            loudness.append(self._safe_lufs(meter, audio))

        finite = [v for v in loudness if v > -70.0]
        if not finite:
            anchor = self.config.loudness.target_lufs
        else:
            anchor = max(finite)  # align to the loudest track

        target = self.config.loudness.target_lufs
        base_gain = target - anchor

        reports = []
        for f, lufs in zip(files, loudness):
            src = Path(f)
            dest = out_dir / (src.stem + "_mastered." + ext)
            extra = base_gain + (lufs - anchor) if lufs > -70.0 else 0.0
            # Disable per-track normalization inside process() and drive
            # loudness purely via extra_gain_db so the album balance holds.
            prior = self.config.loudness.target_lufs
            self.config.loudness.target_lufs = -200.0  # sentinel: skip norm
            try:
                rep = self.process(src, dest, extra_gain_db=extra)
            finally:
                self.config.loudness.target_lufs = prior
            reports.append(rep)
        return reports


def _try_copy_metadata(src: Path, dst: Path) -> None:
    """Best-effort tag passthrough via mutagen (if installed)."""
    try:
        from mutagen import File as MFile  # type: ignore
    except Exception:
        return
    try:
        s = MFile(str(src))
        d = MFile(str(dst))
        if s is None or d is None or not getattr(s, "tags", None):
            return
        # Use raw tag dict copy where formats match.
        if type(s).__name__ == type(d).__name__ and s.tags is not None:
            d.tags = s.tags
            d.save()
    except Exception:
        pass


def process_file(
    input_path: str | Path,
    output_path: str | Path,
    config: Optional[PipelineConfig] = None,
    dry_run: bool = False,
) -> ProcessReport:
    return Pipeline(config).process(input_path, output_path, dry_run=dry_run)
