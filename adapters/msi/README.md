# adapters/msi — MSI host adapter

Responsibility: Deployment manifest + transport for the MSI worker host (control planes, lane runners, TokenEconomizer). MSI's authority role is UNKNOWN per the Phase 0 census — this adapter treats MSI as a qualified-worker candidate only, never as a spine authority.

Contract dependencies: contracts/host-qualification.md · contracts/identity.md

Status: Phase 1 skeleton — implementation lands in its phase.
