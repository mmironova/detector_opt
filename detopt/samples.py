"""Signal and background samples for ZH at sqrt(s) = 240 GeV, Z -> ee, mumu, nunu.

Cross-sections are FCC's official winter2023 values, read from
/cvmfs/fcc.cern.ch/FCCDicts/FCCee_procDict_winter2023_IDEA.json (Whizard for
"wzp6_*", Pythia8 for "p8_*"). They are the cross-sections of the unfiltered
processes; for samples generated with a decay filter the effective
cross-section is ``cross_section_pb * filter efficiency``, where the efficiency
is measured during generation and stored in the generator manifest.

Generator-level events come from two sources, both produced once and shared by
every design point (see detopt/generate.py):

- "stdhep": FCC's official winter2023 Whizard+Pythia6 files on EOS,
  root://eospublic.cern.ch//eos/experiment/fcc/ee/generation/stdhep/winter2023/<name>/
- "pythia8": FCC's official winter2023 Pythia8 card (cards/pythia/<name>.cmd,
  copied from HEP-FCC/FCC-config branch winter2023), generated here with fixed
  seeds. FCC kept no generator-level files for these.
"""

from __future__ import annotations

from dataclasses import dataclass

EOS_SERVER = "root://eospublic.cern.ch"
EOS_STDHEP_DIR = "/eos/experiment/fcc/ee/generation/stdhep/winter2023"


@dataclass(frozen=True)
class Sample:
    name: str
    role: str  # "signal" or "background"
    cross_section_pb: float  # unfiltered, from the winter2023 procDict
    source: str  # "stdhep" or "pythia8"
    # pythia8 only: keep events where exactly one of the two bosons with this
    # PDG id decays to quarks (d, u, s, c, b) and the other to leptons or
    # neutrinos (e, mu, tau and their neutrinos).
    filter_boson: int | None = None
    # pythia8 only: Random:seed of chunk k is seed_base + k.
    seed_base: int | None = None
    note: str = ""

    @property
    def eos_dir(self) -> str:
        return f"{EOS_STDHEP_DIR}/{self.name}"


def _wzp6(name: str, xsec: float, role: str, note: str = "") -> Sample:
    return Sample(name, role, xsec, "stdhep", note=note)


SAMPLES: tuple[Sample, ...] = (
    # Signal: ZH with H -> cc, bb, gg; Z -> ee, mumu, nunu (nunu includes WW fusion).
    _wzp6("wzp6_ee_eeH_Hcc_ecm240", 0.000207, "signal"),
    _wzp6("wzp6_ee_mumuH_Hcc_ecm240", 0.0001956, "signal"),
    _wzp6("wzp6_ee_nunuH_Hcc_ecm240", 0.001335, "signal"),
    _wzp6("wzp6_ee_eeH_Hbb_ecm240", 0.004171, "signal"),
    _wzp6("wzp6_ee_mumuH_Hbb_ecm240", 0.00394, "signal"),
    _wzp6("wzp6_ee_nunuH_Hbb_ecm240", 0.0269, "signal"),
    _wzp6("wzp6_ee_eeH_Hgg_ecm240", 0.0005863, "signal"),
    _wzp6("wzp6_ee_mumuH_Hgg_ecm240", 0.0005538, "signal"),
    _wzp6("wzp6_ee_nunuH_Hgg_ecm240", 0.003782, "signal"),
    # Other Higgs decays: inclusive ZH samples; H -> bb, cc, gg events are
    # removed in the analysis using the MC truth, to avoid double counting.
    _wzp6("wzp6_ee_eeH_ecm240", 0.0071611, "background", "veto H->bb/cc/gg in analysis"),
    _wzp6("wzp6_ee_mumuH_ecm240", 0.0067643, "background", "veto H->bb/cc/gg in analysis"),
    _wzp6("wzp6_ee_nunuH_ecm240", 0.046191, "background", "veto H->bb/cc/gg in analysis"),
    # Diboson and two-fermion backgrounds.
    Sample("p8_ee_ZZ_ecm240", "background", 1.35899, "pythia8", filter_boson=23,
           seed_base=230000, note="filtered: one Z -> qq, the other -> ll/tautau/nunu"),
    Sample("p8_ee_WW_ecm240", "background", 16.4385, "pythia8", filter_boson=24,
           seed_base=240000, note="filtered: one W -> qq', the other -> l nu (l = e, mu, tau)"),
    Sample("p8_ee_Zqq_ecm240", "background", 52.6539, "pythia8",
           seed_base=10000, note="Z/gamma* -> qq, unfiltered"),
    _wzp6("wzp6_ee_nuenueZ_ecm240", 0.033274, "background", "nunu channel"),
    # Z/gamma* -> ll (ll channel) and ZH with Z -> qq (here Z -> uu, dd only; nunu channel).
    _wzp6("wzp6_ee_ee_Mee_30_150_ecm240", 8.305, "background", "Z/gamma* -> ee, 30 < m_ee < 150 GeV"),
    _wzp6("wzp6_ee_mumu_ecm240", 5.288, "background", "Z/gamma* -> mumu"),
    _wzp6("wzp6_ee_qqH_Hbb_ecm240", 0.03107, "background", "Z(uu, dd)H, H -> bb"),
    _wzp6("wzp6_ee_qqH_Hcc_ecm240", 0.001542, "background", "Z(uu, dd)H, H -> cc"),
    _wzp6("wzp6_ee_qqH_Hgg_ecm240", 0.004367, "background", "Z(uu, dd)H, H -> gg"),
)

BY_NAME = {s.name: s for s in SAMPLES}


def get(names: list[str] | None = None) -> list[Sample]:
    """Samples by name, in table order; all samples if names is None."""
    if names is None:
        return list(SAMPLES)
    unknown = [n for n in names if n not in BY_NAME]
    if unknown:
        raise KeyError(f"unknown samples: {unknown}")
    return [s for s in SAMPLES if s.name in set(names)]
