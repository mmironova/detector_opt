"""Event selection and histograms for ZH, H->cc."""

from __future__ import annotations

from pathlib import Path


def make_histograms(tagged_files: list[Path], run_dir: Path) -> Path:
    """Select ZH candidates and fill the histograms the fit needs.

    To build:
    - follow the published FCC-ee ZH hadronic Higgs analysis for the selection,
      so the baseline number can be compared with it
    - categories in the tagger scores; observable such as the recoil mass
    - normalise each sample to cross-section times integrated luminosity
    - return one file with all histograms under run_dir / "hists"
    """
    raise NotImplementedError("analysis: selection not written yet")
