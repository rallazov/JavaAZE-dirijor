# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""Story 9.1 — TerraformAdapter SSH public key env + LocalNoop output guard."""

from __future__ import annotations

import asyncio

import pytest

import supervisor


def test_terraform_validate_reports_do_token_first_when_both_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.delenv("DIGITALOCEAN_TOKEN", raising=False)
    monkeypatch.delenv("DIRIJOR_DO_SSH_PUBLIC_KEY", raising=False)
    tf = supervisor.TerraformAdapter(workspace_root=tmp_path)
    with pytest.raises(supervisor.SpinValidationError) as ei:
        asyncio.run(
            tf.validate(supervisor.SpinRequest(realm_description="x", agent_count=1))
        )
    assert ei.value.code == "adapter_credentials_missing"
    assert "DIGITALOCEAN_TOKEN" in ei.value.message
    assert "DIRIJOR_DO_SSH_PUBLIC_KEY" not in ei.value.message


def test_terraform_validate_ssh_key_message_when_token_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "do_pat_" + "0" * 64)
    monkeypatch.delenv("DIRIJOR_DO_SSH_PUBLIC_KEY", raising=False)
    tf = supervisor.TerraformAdapter(workspace_root=tmp_path)
    with pytest.raises(supervisor.SpinValidationError) as ei:
        asyncio.run(
            tf.validate(supervisor.SpinRequest(realm_description="x", agent_count=1))
        )
    assert ei.value.code == "adapter_credentials_missing"
    assert "DIRIJOR_DO_SSH_PUBLIC_KEY" in ei.value.message


def test_local_noop_provision_outputs_exclude_agent_droplet_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervisor, "PROVISION_DELAY_S", 0)

    async def _run() -> dict:
        ad = supervisor.LocalNoopAdapter()
        job = supervisor.SpinJob(
            job_id="j-noop-droplet",
            realm_id="realm-noop",
            phase="provisioning",
            adapter=ad.name,
            created_at=supervisor._iso_now(),
            status_url="/realms/j-noop-droplet",
            updated_at=supervisor._iso_now(),
            realm_description="x",
            agent_count=2,
            outputs={},
            error=None,
            schema_version=supervisor.SCHEMA_VERSION,
        )
        return await ad.provision(
            supervisor.SpinRequest(realm_description="x", agent_count=2), job
        )

    out = asyncio.run(_run())
    assert "agent_droplet_ids" not in out
    assert "agent_private_ipv4s" not in out
