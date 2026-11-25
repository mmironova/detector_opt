"""The one command: design parameters in, physics number out.

    python -m detopt.evaluate --inner-radius-mm 13.7 \
        --material-x0-percent 0.3 --hit-resolution-um 3
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import analysis, fit, simulate, tagger
from .design import Design, render_card

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = REPO / "cards" / "idea_template.tcl"


def runs_root() -> Path:
    return Path(os.environ.get("DETOPT_RUNS", REPO / "runs"))


def evaluate(
    design: Design,
    n_events: int = 100,
    seed: int = 1,
    template: Path = DEFAULT_TEMPLATE,
    root: Path | None = None,
) -> dict:
    """Run the full chain for one design, or return the cached result."""
    run_dir = (root or runs_root()) / design.hash
    result_file = run_dir / "result.json"

    if result_file.exists():
        cached = json.loads(result_file.read_text())
        if cached["n_events"] == n_events and cached["seed"] == seed:
            return cached

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "design.json").write_text(json.dumps(design.to_dict(), indent=2))

    card = render_card(design, template, run_dir / "card.tcl")
    sim_files = simulate.simulate(card, run_dir, n_events, seed)
    tagged = tagger.train_and_apply(sim_files, run_dir, seed)
    histograms = analysis.make_histograms(tagged, run_dir)
    numbers = fit.expected_uncertainty(histograms)

    result = {
        "design": design.to_dict(),
        "hash": design.hash,
        "n_events": n_events,
        "seed": seed,
        **numbers,
    }
    result_file.write_text(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inner-radius-mm", type=float, required=True)
    parser.add_argument("--material-x0-percent", type=float, required=True)
    parser.add_argument("--hit-resolution-um", type=float, required=True)
    parser.add_argument("--n-events", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    design = Design(
        inner_radius_mm=args.inner_radius_mm,
        material_x0_percent=args.material_x0_percent,
        hit_resolution_um=args.hit_resolution_um,
    )
    print(json.dumps(evaluate(design, args.n_events, args.seed), indent=2))


if __name__ == "__main__":
    main()
