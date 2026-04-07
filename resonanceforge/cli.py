"""Command-line interface for batch mastering."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import PipelineConfig
from .pipeline import Pipeline, ProcessReport


AUDIO_EXTS = {".wav", ".flac", ".aif", ".aiff", ".mp3", ".ogg"}


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="resonanceforge", description="Mastering pipeline")
    ap.add_argument("input", help="Input file or directory")
    ap.add_argument("output", help="Output file or directory")
    ap.add_argument("--preset", type=Path, help="Load PipelineConfig JSON preset")
    ap.add_argument("--lufs", type=float, help="Target integrated LUFS")
    ap.add_argument("--tp", type=float, help="True-peak ceiling (dB)")
    ap.add_argument("--width", type=float, help="M/S Side gain (1.10 = +10%%)")
    ap.add_argument("--sat-mode", choices=["tube", "tape", "exciter"])
    ap.add_argument("--sat-drive", type=float)
    ap.add_argument("--sat-mix", type=float)
    ap.add_argument("--format", choices=["wav", "flac"], dest="fmt",
                    help="Output format")
    ap.add_argument("--bit-depth", type=int, choices=[16, 24, 32],
                    dest="bit_depth")
    ap.add_argument("--no-dither", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="Measure & report without writing output files")
    ap.add_argument("--report", type=Path,
                    help="Append one JSON ProcessReport per line to this file")
    # Quality / cleanup
    ap.add_argument("--sample-rate", type=int, dest="sample_rate",
                    help="Delivery sample rate (e.g. 44100, 48000)")
    ap.add_argument("--trim", action="store_true",
                    help="Trim leading/trailing silence")
    ap.add_argument("--auto-fade-tail", action="store_true")
    ap.add_argument("--notch", type=int, choices=[50, 60],
                    help="Hum notch fundamental (Hz)")
    ap.add_argument("--deesser", action="store_true",
                    help="Enable the static de-esser dip")
    ap.add_argument("--gain", type=float, default=0.0,
                    help="Per-track manual gain offset (dB)")
    ap.add_argument("--album", action="store_true",
                    help="Album mode: two-pass consistent loudness across batch")
    ap.add_argument("--no-metadata", action="store_true",
                    help="Do not copy tags from input to output")
    return ap


def _load_config(args: argparse.Namespace) -> PipelineConfig:
    cfg = PipelineConfig.load(args.preset) if args.preset else PipelineConfig()
    if args.lufs is not None:
        cfg.loudness.target_lufs = args.lufs
    if args.tp is not None:
        cfg.loudness.true_peak_db = args.tp
    if args.width is not None:
        cfg.stereo.width = args.width
    if args.sat_mode:
        cfg.saturation.mode = args.sat_mode  # type: ignore[assignment]
    if args.sat_drive is not None:
        cfg.saturation.drive_db = args.sat_drive
    if args.sat_mix is not None:
        cfg.saturation.mix = args.sat_mix
    if args.fmt:
        cfg.output_format = args.fmt  # type: ignore[assignment]
    if args.bit_depth is not None:
        cfg.output_bit_depth = args.bit_depth
    if args.no_dither:
        cfg.dither = False
    if args.sample_rate:
        cfg.quality.target_sample_rate = args.sample_rate
    if args.trim:
        cfg.quality.trim_silence = True
    if args.auto_fade_tail:
        cfg.quality.auto_fade_tail = True
    if args.notch:
        cfg.quality.hum_notch_hz = args.notch
    if args.deesser:
        cfg.quality.deesser_enabled = True
    if args.gain:
        cfg.gain_offset_db = args.gain
    if args.album:
        cfg.album_mode = True
    if args.no_metadata:
        cfg.preserve_metadata = False
    return cfg


def _dest_for(src: Path, out_root: Path, in_root: Path, fmt: str) -> Path:
    rel = src.relative_to(in_root).with_suffix("." + fmt)
    return out_root / rel


def _write_report(path: Path, report: ProcessReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report.to_dict()) + "\n")


def _print(report: ProcessReport) -> None:
    flag = " CLIP" if report.clipped else ""
    print(
        f"{report.input_path} -> {report.output_path}  "
        f"LUFS {report.lufs_in:.1f} -> {report.lufs_out:.1f}  "
        f"TP {report.true_peak_out_db:.2f} dB{flag}"
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    cfg = _load_config(args)
    pipe = Pipeline(cfg)

    in_path = Path(args.input)
    out_path = Path(args.output)
    fmt = cfg.output_format

    if in_path.is_dir():
        out_path.mkdir(parents=True, exist_ok=True)
        files = sorted(p for p in in_path.rglob("*") if p.suffix.lower() in AUDIO_EXTS)
        if not files:
            print(f"No audio files found in {in_path}", file=sys.stderr)
            return 1
        if cfg.album_mode:
            reports = pipe.process_album(files, out_path, ext=fmt)
            for rep in reports:
                _print(rep)
                if args.report:
                    _write_report(args.report, rep)
        else:
            for f in files:
                dest = _dest_for(f, out_path, in_path, fmt)
                report = pipe.process(f, dest, dry_run=args.dry_run)
                _print(report)
                if args.report:
                    _write_report(args.report, report)
    else:
        if out_path.is_dir() or out_path.suffix == "":
            out_path = out_path / (in_path.stem + "_mastered." + fmt)
        report = pipe.process(in_path, out_path, dry_run=args.dry_run)
        _print(report)
        if args.report:
            _write_report(args.report, report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
