"""Deployment config must at least be parseable by the application it configures."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from aistack.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_compose_environment_is_valid_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    env = {k: str(v) for k, v in compose["x-api"]["environment"].items()}
    for key, value in env.items():
        monkeypatch.setenv(key, value.replace("${AISTACK_LLM_MODE:-fake}", "fake"))
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.cors_origins == ["http://localhost:8080", "http://localhost:5173"]
    assert s.jwks_url == "http://api:8000/idp/jwks.json"
    assert s.mcp_url == "http://mcp:8001/mcp/"


def test_compose_has_no_literal_secrets() -> None:
    text = (ROOT / "docker-compose.yml").read_text()
    assert "sk-" not in text and "AIza" not in text
    compose = yaml.safe_load(text)
    for name in ("api", "mcp"):
        svc = compose["services"][name]
        assert svc["read_only"] is True and svc["cap_drop"] == ["ALL"]


def test_dockerfile_runs_as_non_root() -> None:
    text = (ROOT / "deploy/docker/Dockerfile.api").read_text()
    assert "USER 10001" in text and "HEALTHCHECK" in text


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_helm_configmap_parses_and_rendered_manifest_is_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = subprocess.run(  # noqa: S603
        ["helm", "template", "aistack", str(ROOT / "deploy/helm/aistack")],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert out == (ROOT / "deploy/k8s/aistack.yaml").read_text(), "run `make k8s-render`"
    docs = [d for d in yaml.safe_load_all(out) if d]
    cm = next(d for d in docs if d["kind"] == "ConfigMap")
    for key, value in cm["data"].items():
        monkeypatch.setenv(key, value)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.cors_origins == ["https://copilot.example.com"]
    assert s.oidc_issuer == "https://api.copilot.example.com/idp"
    for d in docs:
        if d["kind"] == "Deployment":
            ctr = d["spec"]["template"]["spec"]["containers"][0]
            assert ctr["securityContext"]["allowPrivilegeEscalation"] is False
            assert ctr["resources"]["limits"]
