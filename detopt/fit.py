"""Histograms -> expected uncertainty on the H->cc signal strength."""

from __future__ import annotations

from pathlib import Path


def expected_uncertainty(histograms: Path) -> dict[str, float]:
    """Fit the Asimov dataset and return the expected uncertainty.

    To build:
    - simultaneous fit of the H->bb, H->cc and H->gg signal strengths
    - return {"sigma_mu_hcc": ..., "sigma_mu_hcc_mcstat": ...}; the second
      entry is the Monte Carlo statistical error on the first, needed to tell
      a real design effect from noise
    """
    raise NotImplementedError("fit: statistical model not written yet")
