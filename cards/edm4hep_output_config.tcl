# Copied unchanged from k4SimDelphes 00-07-06 (Key4hep 2026-04-08): share/k4SimDelphes/edm4hep_output_config.tcl

module EDM4HepOutput EDM4HepOutput {
    add ReconstructedParticleCollections EFlowTrack EFlowPhoton EFlowNeutralHadron
    add GenParticleCollections           Particle
    add JetCollections                   Jet
    add MuonCollections                  Muon
    add ElectronCollections              Electron
    add PhotonCollections                Photon
    add MissingETCollections             MissingET
    add ScalarHTCollections              ScalarHT
    set RecoParticleCollectionName       ReconstructedParticles
    set RecoMCParticleLinkCollectionName  RecoMCLink
}
