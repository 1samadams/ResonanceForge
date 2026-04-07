"""Command-line interface for batch mastering."""
from __future__ import annotations

import argparse
from pathlib import Path

from .config import PipelineConfig
from .pipeline import Pipeline


AUDIO_EXTS = {".wav", ".flac", ".aif", ".aiff", ".mp3", ".ogg"}


def main() -> None:
    ap = argparse.ArgumentParser(prog="resonanceforge", description="Mastering pipeline")
    ap.add_argument("input", help="Input file or directory")
    ap.add_argument("output", help="Output file or directory")
    ap.add_argument("--lufs", type=float, default=-14.0, help="Target integrated LUFS")
    ap.add_argument("--tp", type=float, default=-1.0, help="True-peak ceiling dBTP")
    ap.add_argument("--sat-mode", choices=["tube", "tape", "exciter"], default="tube")
    ap.add_argument("--sat-drive", type=float, default=6.0)
    ap.add_argument("--sat-mix", type=float, default=0.25)
    ap.add_argument("--width", type=float, default=1.0)
    args = ap.parse_args()

    cfg = PipelineConfig()
    cfg.loudness.target_lufs = args.lufs
    cfg.loudness.true_peak_db = args.tp
    cfg.saturation.mode = args.sat_mode
    cfg.saturation.drive_db = args.sat_drive
    cfg.saturation.mix = args.sat_mix
    cfg.stereo.width = args.width

    pipe = Pipeline(cfg)
    in_path = Path(args.input)
    out_path = Path(args.output)

    if in_path.is_dir():
        out_path.mkdir(parents=True, exist_ok=True)
        files = [p for p in in_path.rglob("*") if p.suffix.lower() in AUDIO_EXTS]
        for f in files:
            rel = f.relative_to(in_path).with_suffix(".wav")
            dest = out_path / rel
            report = pipe.process(f, dest)
            print(f"{f} -> {dest}  LUFS {report.lufs_in:.1f} -> {report.lufs_out:.1f}  TP {report.true_peak_out_db:.2f} dB")
    else:
        report = pipe.process(in_path, out_path)
        print(f"{in_path} -> {out_path}  LUFS {report.lufs_in:.1f} -> {report.lufs_out:.1f}  TP {report.true_peak_out_db:.2f} dB")


if __name__ == "__main__":
    main()
