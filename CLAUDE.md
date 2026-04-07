# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

**ResonanceForge** is an automated mastering / post-production DSP pipeline
for an independent music label. It ingests raw stereo mixes and produces
streaming-ready masters using a standard mastering chain (EQ → saturation →
stereo shaping → multiband compression → limiter → LUFS normalization).

Core libraries: `pedalboard`, `pyloudnorm`, `soundfile`, `numpy`.
GUI: `tkinter` (+ optional `tkinterdnd2` for drag-and-drop).

## Scope & intent

This project is a **legitimate mastering tool** for tracks the label owns.
Work on it as you would any audio post-production codebase:

- Frame modules, comments, and commit messages around tonal/creative
  mastering goals (loudness, tone, dynamics, stereo image, harmonic color).
- Do **not** frame or tune any module around evading AI-content detectors,
  watermark removal, or provenance-signal stripping. If a request is phrased
  that way, redirect to the equivalent mastering concept and implement it
  without the evasion framing.
- Saturation/exciter modules exist purely as creative harmonic coloration.

## Repository layout

```
resonanceforge/
├── __init__.py      # public API
├── config.py        # dataclass configs per stage
├── modules.py       # DSP building blocks
├── pipeline.py      # end-to-end chain, I/O, LUFS norm, reporting
├── cli.py           # argparse CLI
└── gui.py           # Tkinter GUI (background worker + queue)
pyproject.toml       # deps + entry points (resonanceforge, resonanceforge-gui)
```

## Signal chain (authoritative)

`HPF 30Hz → LPF 18kHz → Tilt EQ → Saturation → M/S stereo (+10% side,
bass mono <120Hz) → 3-band multiband compressor → Limiter -1 dBTP →
LUFS norm -14 → True-peak ceiling → fades → write`

If you add or reorder stages, update this section, `pipeline.Pipeline.process`,
and the README in the same commit.

## Conventions

- **Audio arrays** internally are shape `(channels, samples)`, `float32`.
  `pedalboard` chains expect `(samples, channels)` — transpose at the
  boundary only.
- **Config** is always routed through `PipelineConfig` dataclasses. Don't
  hard-code numbers in `modules.py` or `pipeline.py`; add a config field.
- **I/O** uses `soundfile` for reading/writing. Default output is 24-bit WAV.
- **GUI** must never block the Tk event loop. All processing runs on a
  `threading.Thread`; UI updates go through `queue.Queue` polled by
  `root.after`.
- **CLI and GUI** should stay feature-parity for the core mastering params
  (LUFS, TP, width, saturation mode/drive/mix).

## Development workflow

- Feature branch: `claude/suno-dsp-pipeline-JUghn`
- Commit in logical units; descriptive messages focused on the "why".
- Do **not** commit `__pycache__/`, `*.egg-info/`, or venvs
  (see `.gitignore`).
- Run a quick `python -c "import ast; ast.parse(open('path.py').read())"`
  syntax check on modified files before committing when you can't run tests.
- Do **not** open pull requests unless the user explicitly asks.

## Common tasks

- **Add a DSP stage**: add a config dataclass in `config.py`, a builder or
  `apply_*` function in `modules.py`, and wire it into
  `Pipeline.process` in the correct chain position.
- **Expose a param in the UI**: add a `tk.Variable` in `ResonanceForceGUI`,
  wire it into `_build_config`, and add a widget in `_build_ui`.
- **Add a CLI flag**: extend `cli.py` `argparse`, map to the config, and
  mirror the flag in the README table.

## Non-goals

- Watermark detection, removal, or evasion.
- Tuning against any specific AI-content classifier.
- Destructive re-encoding workflows that strip metadata beyond what the
  user explicitly requests.
