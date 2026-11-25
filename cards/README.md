# Delphes cards

`idea_template.tcl` is not in the repo yet. To create it:

1. Inside the container, copy the stock IDEA card from the Key4hep stack
   (look under `$DELPHES_DIR/cards/`).
2. Run it unchanged once and keep the output as the baseline.
3. In the track-covariance geometry block, replace the values for the innermost
   vertex layer with these placeholders:

| Placeholder | Meaning |
|---|---|
| `@@inner_radius_mm@@` | radius of the innermost vertex layer, mm |
| `@@material_x0_percent@@` | material per vertex layer, % of a radiation length |
| `@@hit_resolution_um@@` | single-hit resolution, µm |

The card may want other units (metres, fractions). Convert in the card or in
`detopt/design.py`, and note which.

Placeholders use `@@...@@` because Tcl already uses `$` and `{}`.
