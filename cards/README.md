# Delphes cards

| File | What it is |
|---|---|
| `delphes_card_IDEA.stock.tcl` | Unchanged copy of `delphes/cards/delphes_card_IDEA.tcl` from Key4hep 2026-04-08 (md5 `f6d0ca7e419560013d9d37a39c0cc3b5`). Reference only. |
| `edm4hep_output_config.tcl` | EDM4hep output settings, copied from k4SimDelphes 00-07-06. |
| `generator_only.tcl` | Delphes card that only writes generator particles; used once per Pythia8 sample. |
| `count_events.tcl` | Delphes card that writes nothing; used to count events in stdhep files. |
| `pythia/*.cmd` | FCC-config winter2023 Pythia8 cards for ZZ, WW and Z/γ*→qq. |
| `idea_template.tcl` | The stock card with the innermost vertex layer replaced by placeholders. Rendered per design by `detopt.design.render_card`. |

The template differs from the stock card in one line: the first `VTXLOW` layer
of the `TrackCovariance` `DetectorGeometry` table.

```
stock:    1 VTXLOW -0.0965 0.0965 0.0137 0.000309 0.0937 2 0 1.5708 3e-06 3e-06 1
template: 1 VTXLOW -0.0965 0.0965 @@inner_radius_mm@@ @@material_x0_percent@@ 0.0937 2 0 1.5708 @@hit_resolution_um@@ @@hit_resolution_um@@ 1
```

| Placeholder | Meaning (design units) | Card column (SI) |
|---|---|---|
| `@@inner_radius_mm@@` | radius of the innermost vertex layer, mm | `r`, m |
| `@@material_x0_percent@@` | material of the innermost vertex layer, % X0 | `w`, m of silicon (X0 = 0.0937 m kept fixed) |
| `@@hit_resolution_um@@` | single-hit resolution, µm (both sides) | `reso_up`, `reso_down`, m |

Unit conversions are done in `detopt/design.py` (`card_values`), not in the
card. Only the innermost layer changes; the other two `VTXLOW` layers, their
z extent (±96.5 mm for layer 1) and every other subsystem stay as in the stock
card.

`detopt.design.BASELINE` (13.7 mm, 0.32978 % X0 = 0.309 mm Si, 3 µm) renders
back to `delphes_card_IDEA.stock.tcl` byte for byte; `tests/test_design.py`
checks this.

Placeholders use `@@...@@` because Tcl already uses `$` and `{}`.

Delphes' Tcl reader aborts on `source`, so a card that adds settings (for
example `set MaxEvents`) has to be the full card text plus the extra lines.
