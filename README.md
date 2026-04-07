# ResonanceForge

An automated mastering / post-production DSP pipeline for independent music
labels. Takes raw stereo mixes and prepares them for high-fidelity streaming
distribution via a standard mastering chain built on
[`pedalboard`](https://github.com/spotify/pedalboard),
[`pyloudnorm`](https://github.com/csteinmetz1/pyloudnorm), and `soundfile`.

## Features

- **Utility**: 30 Hz high-pass (sub-rumble / DC) and 18 kHz low-pass
- **Tone**: subtle tilt EQ around a configurable pivot (default 1 kHz)
- **Harmonic color**: saturation/exciter module with `tube`, `tape`, or
  `exciter` modes, parallel dry/wet mix
- **Stereo image**: M/S matrix with adjustable Side gain (default +10%) and
  bass mono-ization below 120 Hz
- **Dynamics**: 3-band multiband compressor + brickwall limiter at -1.0 dBTP
- **Loudness**: integrated-LUFS normalization (default -14 LUFS for streaming)
- **Batch I/O**: process a single file or an entire directory of WAV/FLAC/etc.
- **Desktop GUI**: Tkinter interface with drag-and-drop, per-file status,
  progress bar, live log, and LUFS/TP reporting

## Signal chain

```
input → HPF 30Hz → LPF 18kHz → Tilt EQ → Saturation
      → M/S stereo (+10% side, bass mono <120Hz)
      → 3-band multiband compression
      → Brickwall limiter (-1.0 dBTP)
      → LUFS normalization (-14 LUFS)
      → True-peak safety ceiling → fades → output
```

## Install

```bash
pip install -e .              # core + CLI
pip install -e .[gui]         # adds drag-and-drop support (tkinterdnd2)
pip install -e .[test]        # adds pytest + scipy for the test suite
```

macOS/Linux: `scripts/setup.sh` bootstraps a `.venv` and installs `[gui,test]`.
Windows: `resonanceforge.bat setup` does the same.

## CLI

Process a single file:

```bash
resonanceforge input.wav output.wav --lufs -14 --tp -1 --width 1.05
```

Batch-process a directory:

```bash
resonanceforge ./mixes ./masters --sat-mode tube --sat-drive 6 --sat-mix 0.25
```

Flags:

| Flag | Default | Description |
| --- | --- | --- |
| `--lufs` | -14 | Target integrated LUFS |
| `--tp` | -1.0 | True-peak ceiling in dBTP |
| `--width` | 1.05 | M/S Side gain (1.05 = +5%) |
| `--sat-mode` | tube | `tube`, `tape`, or `exciter` |
| `--sat-drive` | 6.0 | Saturation drive (dB) |
| `--sat-mix` | 0.25 | Parallel dry/wet mix (0..1) |
| `--preset` | – | Load a `PipelineConfig` JSON preset |
| `--format` | wav | `wav` or `flac` |
| `--bit-depth` | 24 | `16`, `24`, or `32` (float) |
| `--no-dither` | off | Disable TPDF dither on PCM export |
| `--dry-run` | off | Measure + report without writing files |
| `--report` | – | Append one JSON `ProcessReport` per line |
| `--sample-rate` | input | Delivery sample rate (e.g. `44100`, `48000`) |
| `--trim` | off | Trim leading/trailing silence |
| `--auto-fade-tail` | off | Detect decay tail and fade to silence |
| `--notch` | – | `50` or `60` Hz hum notch (with harmonics) |
| `--deesser` | off | Static narrow-band de-ess dip |
| `--gain` | 0.0 | Per-track manual gain offset (dB) |
| `--album` | off | Two-pass album mode: consistent loudness across batch |
| `--no-metadata` | off | Don't carry tags from input to output |

### Presets

Shipped in `resonanceforge/presets/`: `streaming_-14.json`,
`club_-9.json`, `vinyl.json`. Use with `--preset PATH` or
**Load Preset…** in the GUI. CLI flags override preset values.

## GUI

```bash
resonanceforge-gui
```

- Add files via **Add Files…** / **Add Folder…** or drag-and-drop onto the list
- Configure output folder, LUFS, TP, stereo width, and saturation in the
  settings panel
- Click **Start Processing** — the batch runs on a background thread and
  the file list updates with per-track status, LUFS in/out, and true-peak
- Live log shows every step; errors are surfaced inline without stopping the
  batch

## Python API

```python
from resonanceforge import Pipeline, PipelineConfig

cfg = PipelineConfig()
cfg.loudness.target_lufs = -14.0
cfg.loudness.true_peak_db = -1.0
cfg.stereo.width = 1.05
cfg.saturation.mode = "tube"

report = Pipeline(cfg).process("mix.wav", "master.wav")
print(report.lufs_in, "→", report.lufs_out, "TP:", report.true_peak_out_db)
```

All stage parameters live in dataclasses in `resonanceforge/config.py`
(`EQConfig`, `DynamicsConfig`, `StereoConfig`, `SaturationConfig`,
`LoudnessConfig`) so each module can be tuned independently.

## Project layout

```
resonanceforge/
├── __init__.py      # public API: Pipeline, PipelineConfig, process_file
├── config.py        # dataclass configs for every stage
├── modules.py       # DSP building blocks (EQ, multiband, stereo, saturation)
├── pipeline.py      # end-to-end chain + LUFS normalization + I/O
├── cli.py           # argparse CLI (single file or directory)
└── gui.py           # Tkinter GUI with drag-and-drop
```

## Testing

```bash
pip install -e .[test]
pytest -q
```

The smoke suite generates signals in `tmp_path`, runs the full pipeline on
mono and stereo, and asserts LUFS within tolerance, no clipping, no
NaN/Inf, and valid FLAC output. CI runs on push
(`.github/workflows/ci.yml`).

## License

See `LICENSE`.
