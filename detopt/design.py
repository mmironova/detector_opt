"""A detector design point and its rendering into a Delphes card."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

# Allowed range for each parameter. These are placeholders to be replaced by
# engineering limits (beam pipe radius, achievable material, sensor pitch).
BOUNDS = {
    "inner_radius_mm": (10.0, 30.0),
    "material_x0_percent": (0.05, 1.0),
    "hit_resolution_um": (1.0, 10.0),
}


@dataclass(frozen=True)
class Design:
    inner_radius_mm: float
    material_x0_percent: float
    hit_resolution_um: float

    def __post_init__(self) -> None:
        for name, (low, high) in BOUNDS.items():
            value = getattr(self, name)
            if not low <= value <= high:
                raise ValueError(f"{name}={value} is outside [{low}, {high}]")

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @property
    def hash(self) -> str:
        """Stable identifier, used as the run directory name."""
        text = json.dumps(
            {k: round(float(v), 6) for k, v in self.to_dict().items()}, sort_keys=True
        )
        return hashlib.sha256(text.encode()).hexdigest()[:12]


def render_card(design: Design, template: Path, output: Path) -> Path:
    """Fill the @@name@@ placeholders of a card template and write the card."""
    text = template.read_text()
    for field in fields(design):
        placeholder = f"@@{field.name}@@"
        if placeholder not in text:
            raise ValueError(f"{template} has no placeholder {placeholder}")
        text = text.replace(placeholder, repr(float(getattr(design, field.name))))
    if "@@" in text:
        raise ValueError(f"{template} has placeholders that Design does not fill")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)
    return output
