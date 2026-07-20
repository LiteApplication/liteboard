"""Tests for image-ref parsing and registry auth resolution."""

import base64
import json

from liteboard.registry.manifest import RegistryAuth, parse_image_ref


def test_parse_docker_hub_official():
    ref = parse_image_ref("nginx:1.25")
    assert ref.registry == "registry-1.docker.io"
    assert ref.repository == "library/nginx"
    assert ref.tag == "1.25"
    assert ref.digest is None


def test_parse_docker_hub_user_image_default_tag():
    ref = parse_image_ref("grafana/grafana")
    assert ref.registry == "registry-1.docker.io"
    assert ref.repository == "grafana/grafana"
    assert ref.tag == "latest"


def test_parse_private_registry_with_port_and_digest():
    ref = parse_image_ref("registry.example.com:5000/team/app:prod@sha256:deadbeef")
    assert ref.registry == "registry.example.com:5000"
    assert ref.repository == "team/app"
    assert ref.tag == "prod"
    assert ref.digest == "sha256:deadbeef"


def test_parse_localhost_registry():
    ref = parse_image_ref("localhost/myimage:dev")
    assert ref.registry == "localhost"
    assert ref.repository == "myimage"


def test_registry_auth_from_config(tmp_path):
    token = base64.b64encode(b"user:pass").decode()
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "auths": {
                    "registry.example.com:5000": {"auth": token},
                    "https://index.docker.io/v1/": {
                        "username": "hubuser",
                        "password": "hubpass",
                    },
                }
            }
        )
    )
    auth = RegistryAuth(str(cfg))
    assert auth.basic_for("registry.example.com:5000") == token
    # Docker Hub aliases normalise together.
    hub = auth.basic_for("registry-1.docker.io")
    assert hub == base64.b64encode(b"hubuser:hubpass").decode()


def test_registry_auth_write_and_merge(tmp_path, monkeypatch):
    # Mock data_dir() to use a temp directory
    monkeypatch.setattr("liteboard.config.data_dir", lambda: tmp_path)
    
    # 1. Create a "secret" config path representing the read-only config
    secret_cfg = tmp_path / "secret_config.json"
    secret_token = base64.b64encode(b"secretuser:secretpass").decode()
    secret_cfg.write_text(json.dumps({
        "auths": {
            "ghcr.io": {"auth": secret_token}
        }
    }))
    
    # 2. Write a credential using RegistryAuth.write_credential to the mutable path
    mutable_cfg = tmp_path / "registry_config.json"
    RegistryAuth.write_credential(str(mutable_cfg), "registry.example.com", "user", "pass")
    
    # 3. Instantiate RegistryAuth and verify it merges both
    auth = RegistryAuth(str(secret_cfg))
    assert auth.basic_for("ghcr.io") == secret_token
    assert auth.basic_for("registry.example.com") == base64.b64encode(b"user:pass").decode()


def test_list_entries_reports_username_and_source(tmp_path, monkeypatch):
    monkeypatch.setattr("liteboard.config.data_dir", lambda: tmp_path)

    secret_cfg = tmp_path / "secret_config.json"
    secret_token = base64.b64encode(b"secretuser:secretpass").decode()
    secret_cfg.write_text(json.dumps({"auths": {"ghcr.io": {"auth": secret_token}}}))

    mutable_cfg = tmp_path / "registry_config.json"
    RegistryAuth.write_credential(str(mutable_cfg), "registry.example.com", "user", "pass")

    auth = RegistryAuth(str(secret_cfg))
    entries = {e["registry"]: e for e in auth.list_entries()}

    assert entries["ghcr.io"]["username"] == "secretuser"
    assert entries["ghcr.io"]["source"] == "secret"
    assert entries["registry.example.com"]["username"] == "user"
    assert entries["registry.example.com"]["source"] == "mutable"


def test_remove_credential(tmp_path):
    mutable_cfg = tmp_path / "registry_config.json"
    RegistryAuth.write_credential(str(mutable_cfg), "registry.example.com", "user", "pass")
    RegistryAuth.write_credential(str(mutable_cfg), "ghcr.io", "user2", "pass2")

    assert RegistryAuth.remove_credential(str(mutable_cfg), "registry.example.com") is True
    # Removing again is a no-op that reports nothing removed.
    assert RegistryAuth.remove_credential(str(mutable_cfg), "registry.example.com") is False

    data = json.loads(mutable_cfg.read_text())
    assert "registry.example.com" not in data["auths"]
    assert "ghcr.io" in data["auths"]


def test_remove_credential_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert RegistryAuth.remove_credential(str(missing), "ghcr.io") is False
