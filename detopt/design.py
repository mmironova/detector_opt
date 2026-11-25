"""A detector design point and its rendering into a Delphes card.

The three parameters describe the innermost barrel layer of the IDEA vertex
detector (the first ``VTXLOW`` line of the ``TrackCovariance`` geometry in
``cards/idea_template.tcl``). All other layers stay as in the stock card.

Units and conversions (done here, not in the card)
--------------------------------------------------
The card's geometry table is in SI units. ``card_values`` converts:

==========================  ===============================  ===========================
Design field                Card column                      Conversion
==========================  ===============================  ===========================
``inner_radius_mm``         ``r`` (m)                        ``r_m = r_mm / 1e3``
``material_x0_percent``     ``w``, layer thickness (m)       ``w_m = (pct / 100) * X0_Si``
``hit_resolution_um``       ``reso_up`` and ``reso_down`` (m)  ``sigma_m = sigma_um / 1e6``
==========================  ===============================  ===========================

Material: the card describes a layer by a thickness ``w`` and a radiation
length ``X0``. TrackCovariance uses them only as the ratio ``w / X0`` (multiple
scattering), so the template keeps ``X0 = SILICON_X0_M = 0.0937 m`` fixed and
the design sets ``w``. A percentage of X0 is therefore a silicon-equivalent
thickness: 0.1 % X0 = 93.7 um of silicon.

Resolution: the same value is written to both measurement sides of the layer
(the stock card uses 3 um for both).

Numbers are written with ``CARD_FORMAT`` (9 significant digits, ``%g`` style).
This reproduces the stock card's own spelling ("0.0137", "0.000309", "3e-06"),
so rendering ``BASELINE`` gives back the stock card byte for byte.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

# Radiation length of silicon as used for every silicon layer of the stock
# IDEA card (and kept fixed in cards/idea_template.tcl), in metres.
SILICON_X0_M = 0.0937

CARD_FORMAT = "{:.9g}"

# Allowed range for each parameter: engineering and technology limits of the
# IDEA inner vertex layer. Sources (all read directly; page = PDF page; local
# copies in /global/cfs/cdirs/atlas/mironova/detector_opt/refs/):
#
#   [IDEA]    IDEA detector concept paper, arXiv:2502.21223
#   [VXD]     FCC-ee vertexing requirements/challenges, arXiv:2502.04071
#   [MD3]     ARCADIA MD3 test beam, arXiv:2602.15450
#   [CE65]    CE-65v2 test beam, arXiv:2502.04070
#   [FASTPIX] FASTPIX test beam, arXiv:2306.05938
#   [k4geo]   k4geo 00-24 in Key4hep 2026-04-08, FCCee/IDEA/compact/IDEA_o1_v0{1,3}
#   [fcccfg]  HEP-FCC/FCC-config, branch winter2023, FCCee/Delphes/card_IDEA*.tcl
#             (the official winter2023 IDEA detector variations)
#
# inner_radius_mm: 13.7 to 17.5 mm
#   - Lower: beam pipe outer radius 11.7 mm [VXD p.2] plus the 2 mm radial
#     clearance needed to insert the layer: "To allow 2 mm radial clearance for
#     its insertion, the first layer is located at a radius of 13.7 mm"
#     [IDEA p.8]. (k4geo's comment attributes the move from 12 mm to "cooling
#     issues"; the IDEA paper gives the clearance reason.) Smaller radii, e.g.
#     CLD's 12.5 mm [VXD p.4] or the winter2023 card's 12.0 mm [fcccfg], would
#     need less clearance or a smaller beam pipe and are beyond baseline.
#   - Upper: 17.5 mm, the inner layer of the earlier IDEA design built around a
#     15 mm beam pipe [k4geo, IDEA_o1_v01]. FCC's largest radius variation is
#     17 mm [fcccfg, shiftVXDr_plus500um]. Layer 2 sits at 23.7 mm.
#
# material_x0_percent: 0.075 to 0.66 % X0
#   - Baseline: 0.25 % X0 per layer at normal incidence, about 20 % more on
#     average from stave overlaps [IDEA p.9]; requirement <= 0.3 % X0/layer
#     [VXD p.3]. The stock card has 0.309 mm Si = 0.330 % X0.
#   - Lower: ultra-light (curved, ITS3-like) option, "about 0.075% of X0 at
#     normal incidence" per layer [IDEA p.11]; also FCC's lightest variation,
#     0.075 % X0 [fcccfg, lighterVXD_75pc].
#   - Upper: FCC's heaviest variation doubles the inner-layer material
#     [fcccfg, heavierVTXLOW_100pc]; applied to the stock card, 0.66 % X0.
#
# hit_resolution_um: 2.0 to 6.0 um
#   - Baseline 3 um is the FCC-ee requirement [VXD p.3], not yet achieved by
#     the IDEA reference sensor: ARCADIA and MOSAIX resolutions "are only
#     ~5 um" [VXD p.6]; ARCADIA MD3 minimum residual width 4.6-4.7 um at
#     25 um pitch [MD3 p.6].
#   - Lower: best measured MAPS resolutions, < 2 um at 15 um pitch (CE-65v2
#     standard process) [CE65 p.6] and RMS 1.89 +- 0.04 um at 10 um pitch
#     [FASTPIX p.10]. FCC's 1 um variation [fcccfg] has no measured basis.
#   - Upper: 6 um, FCC's worse-resolution variation [fcccfg,
#     worse_singlehitReso_100pc]; covers today's ARCADIA (~4.7-5 um).
BOUNDS = {
    "inner_radius_mm": (13.7, 17.5),
    "material_x0_percent": (0.075, 0.66),
    "hit_resolution_um": (2.0, 6.0),
}

# Outer limits for "beyond baseline" scan points. A design between BOUNDS and
# EXTENDED_BOUNDS can be built, but evaluate() only runs it when asked to
# (--beyond-baseline), and result.json records beyond_baseline = true.
#
# inner_radius_mm down to 12.5 mm: CLD's first layer radius [VXD p.4]. For
#   IDEA this needs less than the 2 mm insertion clearance or a smaller beam
#   pipe. The vertexing paper's "advanced VXD" table lists a smaller r_min,
#   together with better resolution and a lighter vertex detector and beam
#   pipe, as the way to a "~2 reduction of sigma_d0" [VXD p.5, Table 3].
EXTENDED_BOUNDS = {
    **BOUNDS,
    "inner_radius_mm": (12.5, BOUNDS["inner_radius_mm"][1]),
}


def _within(design: Design, bounds: dict[str, tuple[float, float]]) -> list[str]:
    """Names and values of the parameters outside the given bounds."""
    outside = []
    for name, (low, high) in bounds.items():
        value = getattr(design, name)
        if not low <= value <= high:
            outside.append(f"{name}={value} is outside [{low}, {high}]")
    return outside


@dataclass(frozen=True)
class Design:
    """A design point. Its identity (hash) is the three parameters only."""

    inner_radius_mm: float
    material_x0_percent: float
    hit_resolution_um: float

    def __post_init__(self) -> None:
        outside = _within(self, EXTENDED_BOUNDS)
        if outside:
            raise ValueError("; ".join(outside))

    @property
    def beyond_baseline(self) -> bool:
        """True if any parameter is outside BOUNDS (but inside EXTENDED_BOUNDS)."""
        return bool(_within(self, BOUNDS))

    def check_allowed(self, beyond_baseline: bool = False) -> None:
        """Raise unless the design is within BOUNDS, or beyond_baseline is allowed."""
        outside = _within(self, BOUNDS)
        if outside and not beyond_baseline:
            raise ValueError(
                "; ".join(outside)
                + " (beyond baseline: pass --beyond-baseline to run it anyway)"
            )

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @property
    def hash(self) -> str:
        """Stable identifier, used as the run directory name."""
        text = json.dumps(
            {k: round(float(v), 6) for k, v in self.to_dict().items()}, sort_keys=True
        )
        return hashlib.sha256(text.encode()).hexdigest()[:12]


# The stock IDEA card's innermost layer (r = 0.0137 m, w = 0.000309 m of
# silicon, 3e-06 m resolution) expressed in design units.
BASELINE = Design(
    inner_radius_mm=13.7,
    material_x0_percent=100 * 0.000309 / SILICON_X0_M,  # 0.32977... % X0
    hit_resolution_um=3.0,
)


def card_values(design: Design) -> dict[str, str]:
    """Card text for each placeholder, converted to the card's SI units."""
    si = {
        "inner_radius_mm": design.inner_radius_mm / 1e3,
        "material_x0_percent": design.material_x0_percent / 100 * SILICON_X0_M,
        "hit_resolution_um": design.hit_resolution_um / 1e6,
    }
    return {name: CARD_FORMAT.format(value) for name, value in si.items()}


def render_card(design: Design, template: Path, output: Path) -> Path:
    """Fill the @@name@@ placeholders of a card template and write the card."""
    text = template.read_text()
    values = card_values(design)
    for field in fields(design):
        placeholder = f"@@{field.name}@@"
        if placeholder not in text:
            raise ValueError(f"{template} has no placeholder {placeholder}")
        text = text.replace(placeholder, values[field.name])
    if "@@" in text:
        raise ValueError(f"{template} has placeholders that Design does not fill")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)
    return output
