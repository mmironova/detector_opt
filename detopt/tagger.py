"""Flavour tagger, retrained for every design point."""

from __future__ import annotations

from pathlib import Path


def train_and_apply(sim_files: list[Path], run_dir: Path, seed: int) -> list[Path]:
    """Train a jet-flavour tagger on this design's simulation and apply it.

    To build:
    - inputs: per-track impact parameters and their significances, plus jet
      kinematics; these are what the vertex detector parameters change
    - a small network that trains in minutes on one GPU; same architecture,
      same seed and same training events for every design
    - split events: train on one part, write scores for the other part only
    - return files with b, c and light scores per jet under run_dir / "tagged"
    """
    raise NotImplementedError("tagger: training step not written yet")
