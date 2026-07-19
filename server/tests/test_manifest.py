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
