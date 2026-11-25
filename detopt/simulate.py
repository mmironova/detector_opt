"""Generator-level events -> Delphes fast simulation -> EDM4hep files."""

from __future__ import annotations

from pathlib import Path


def simulate(card: Path, run_dir: Path, n_events: int, seed: int) -> list[Path]:
    """Run Delphes with this card on the signal and background samples.

    To build:
    - decide the samples (ZH with H->cc, H->bb, H->gg, and the main backgrounds)
      and where the generator-level files live; generate once, reuse for every
      design, so that design points share the same events
    - call the Delphes EDM4hep executable from the Key4hep stack with `card`
    - return the EDM4hep output files written under run_dir / "sim"
    """
    raise NotImplementedError("simulate: Delphes step not written yet")
