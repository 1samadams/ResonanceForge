"""Test PipelineConfig JSON round-trip."""
from __future__ import annotations

from pathlib import Path

from resonanceforge.config import PipelineConfig


def test_roundtrip_identity(tmp_path: Path) -> None:
    cfg = PipelineConfig()
    cfg.loudness.target_lufs = -9.0
    cfg.stereo.width = 1.2
    cfg.saturation.mode = "tape"  # type: ignore[assignment]
    cfg.saturation.drive_db = 8.0

    path = tmp_path / "preset.json"
    cfg.save(path)
    loaded = PipelineConfig.load(path)

    assert loaded.to_dict() == cfg.to_dict()
    assert loaded.loudness.target_lufs == -9.0
    assert loaded.saturation.mode == "tape"


def test_from_dict_tolerates_missing_keys() -> None:
    loaded = PipelineConfig.from_dict({"loudness": {"target_lufs": -10.0}})
    assert loaded.loudness.target_lufs == -10.0
    # Others fall back to defaults.
    assert loaded.stereo.width == 1.10


def test_shipped_presets_load() -> None:
    presets_dir = Path(__file__).resolve().parent.parent / "resonanceforge" / "presets"
    for name in ("streaming_-14.json", "club_-9.json", "vinyl.json"):
        cfg = PipelineConfig.load(presets_dir / name)
        assert isinstance(cfg, PipelineConfig)
