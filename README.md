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
pip install -e .           # core + CLI
pip install -e .[gui]      # adds drag-and-drop support (tkinterdnd2)
```

## CLI

Process a single file:

```bash
resonanceforge input.wav output.wav --lufs -14 --tp -1 --width 1.10
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
| `--width` | 1.0 | M/S Side gain (1.10 = +10%) |
| `--sat-mode` | tube | `tube`, `tape`, or `exciter` |
| `--sat-drive` | 6.0 | Saturation drive (dB) |
| `--sat-mix` | 0.25 | Parallel dry/wet mix (0..1) |

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
cfg.stereo.width = 1.10
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

## License

See `LICENSE`.
