# Generator level only: write every Pythia particle (with its production
# vertex) to the Particle branch. Used once per Pythia8 sample by
# detopt/generate.py; each design then reads these files with DelphesROOT_EDM4HEP.
set ExecutionPath { TreeWriter }
module TreeWriter TreeWriter {
  add Branch Delphes/allParticles Particle GenParticle
}
