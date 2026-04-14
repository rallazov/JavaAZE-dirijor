# Dirijor PRD – Private Agent Network OS
Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

## Vision
Cutting-edge platform for safety and security of LLM agents and humans who use them.  
A user-friendly application where anyone can configure private zero-trust network realms for OpenClaw-style agents across unlimited virtual instances on any private cloud (DigitalOcean, Hetzner, Proxmox, self-hosted, etc.).

## Core Non-Negotiable Requirements
- Drag-and-drop Network Canvas (React Flow) with live topology
- One-click Private Realm provisioning with Headscale/Tailscale mesh + mTLS + Firecracker sandboxing
- LangGraph-based Dirijor Core supervisor with multi-agent consensus (≥95% agreement) + Verified Semantic Cache
- Safety Fortress: debate loops, anomaly auto-quarantine, human-in-the-loop gates, immutable audit export
- Cloud-agnostic IaC (Terraform/Pulumi adapters)
- 100% private — zero public internet exposure by default
- Turns raw OpenClaw agents into safe, orchestrated digital employees

## Success Criteria
- Spin a 10-agent secure realm in <60 seconds
- Zero hallucination on high-stakes outputs via consensus + cache
- Exportable compliance package from any realm
- Works for solo humans and enterprise teams

## Current State
We have v0.1 files: canvas, supervisor stub, OpenClaw wrapper, basic Terraform, docker-compose, mermaid architecture.

## Competitive Landscape Update (April 2026)
Hostinger offers 1-click OpenClaw on VPS with basic container isolation.  
This validates demand but does NOT solve:
- Private network configuration canvas
- Multi-agent orchestration & consensus
- Hallucination-proof safety fortress
- Unlimited isolated realms across any private cloud
Dirijor becomes the missing secure control plane.

