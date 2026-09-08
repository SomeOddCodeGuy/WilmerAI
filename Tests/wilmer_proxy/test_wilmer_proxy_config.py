from copy import deepcopy

import pytest

from Middleware.wilmer_proxy.config import (
    load_wilmer_proxy_config,
    parse_wilmer_proxy_config,
)


@pytest.mark.parametrize("field", ["connectTimeoutSeconds", "readTimeoutSeconds"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 10 ** 400])
def test_timeouts_must_be_finite(field, value):
    raw = _valid_config()
    raw["upstreams"]["main"][field] = value
    with pytest.raises(ValueError, match=field):
        parse_wilmer_proxy_config("frontend-filter", raw)


def _valid_config():
    return {
        "port": 5051,
        "useFileLogging": True,
        "upstreams": {
            "main": {
                "baseUrl": "http://127.0.0.1:5060",
                "authorizationMode": "passthrough",
                "forwardHeaders": ["X-Idempotency-Key", "X-Trace-Id"],
                "connectTimeoutSeconds": 3,
                "readTimeoutSeconds": 120,
                "verifyTls": False,
            }
        },
        "models": {
            "general": {
                "upstream": "main",
                "targetModel": "chat-ui:general",
            }
        },
    }


def test_parse_wilmer_proxy_config_builds_explicit_upstream_and_model_mapping():
    config = parse_wilmer_proxy_config("frontend-filter", _valid_config())

    assert config.name == "frontend-filter"
    assert config.port == 5051
    assert config.use_file_logging is True
    assert config.upstreams["main"].base_url == "http://127.0.0.1:5060"
    assert config.upstreams["main"].forward_headers == (
        "X-Idempotency-Key", "X-Trace-Id")
    assert config.models["general"].upstream == "main"
    assert config.models["general"].target_model == "chat-ui:general"


def test_parse_wilmer_proxy_config_applies_safe_defaults():
    raw = _valid_config()
    raw.pop("port")
    raw.pop("useFileLogging")
    upstream = raw["upstreams"]["main"]
    upstream.pop("forwardHeaders")
    upstream.pop("connectTimeoutSeconds")
    upstream.pop("readTimeoutSeconds")
    upstream.pop("verifyTls")

    config = parse_wilmer_proxy_config("filter", raw)

    assert config.port == 5050
    assert config.use_file_logging is False
    assert config.upstreams["main"].forward_headers == ("X-Idempotency-Key",)
    assert config.upstreams["main"].connect_timeout_seconds == 10.0
    assert config.upstreams["main"].read_timeout_seconds == 14400.0
    assert config.upstreams["main"].verify_tls is True


@pytest.mark.parametrize("field", ["upstreams", "models"])
def test_parse_wilmer_proxy_config_requires_nonempty_maps(field):
    raw = _valid_config()
    raw[field] = {}

    with pytest.raises(ValueError, match=field):
        parse_wilmer_proxy_config("filter", raw)


def test_parse_wilmer_proxy_config_rejects_unknown_upstream_reference():
    raw = _valid_config()
    raw["models"]["general"]["upstream"] = "missing"

    with pytest.raises(ValueError, match="unknown upstream 'missing'"):
        parse_wilmer_proxy_config("filter", raw)


@pytest.mark.parametrize(
    ("mode", "api_key", "message"),
    [
        ("configured", "", "apiKey is required"),
        ("passthrough", "secret", "apiKey may only be set"),
        ("invalid", "", "authorizationMode must be one of"),
    ],
)
def test_parse_wilmer_proxy_config_validates_authorization_policy(mode, api_key, message):
    raw = _valid_config()
    raw["upstreams"]["main"]["authorizationMode"] = mode
    raw["upstreams"]["main"]["apiKey"] = api_key

    with pytest.raises(ValueError, match=message):
        parse_wilmer_proxy_config("filter", raw)


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://127.0.0.1",
        "http://user:secret@127.0.0.1",
        "http://127.0.0.1?target=x",
        "http://127.0.0.1:invalid",
        "http://local host:5060",
    ],
)
def test_parse_wilmer_proxy_config_rejects_unsafe_or_unsupported_base_urls(base_url):
    raw = _valid_config()
    raw["upstreams"]["main"]["baseUrl"] = base_url

    with pytest.raises(ValueError, match="baseUrl"):
        parse_wilmer_proxy_config("filter", raw)


def test_parse_wilmer_proxy_config_rejects_managed_forward_headers():
    raw = _valid_config()
    raw["upstreams"]["main"]["forwardHeaders"] = ["Authorization"]

    with pytest.raises(ValueError, match="managed by WilmerProxy"):
        parse_wilmer_proxy_config("filter", raw)


def test_parse_wilmer_proxy_config_rejects_unknown_fields():
    raw = _valid_config()
    raw["unexpected"] = True

    with pytest.raises(ValueError, match="unknown field"):
        parse_wilmer_proxy_config("filter", raw)


def test_load_wilmer_proxy_config_uses_named_wilmer_proxy_directory(mocker):
    raw = deepcopy(_valid_config())
    mocker.patch(
        "Middleware.wilmer_proxy.config.config_utils.get_config_path",
        return_value="/configs/WilmerProxy/frontend-filter.json",
    )
    load = mocker.patch(
        "Middleware.wilmer_proxy.config.config_utils.load_config",
        return_value=raw,
    )

    config = load_wilmer_proxy_config("frontend-filter")

    load.assert_called_once_with("/configs/WilmerProxy/frontend-filter.json")
    assert config.name == "frontend-filter"


@pytest.mark.parametrize("name", ["../secret", "nested/filter", "C:\\filter"])
def test_load_wilmer_proxy_config_rejects_nonflat_names(name):
    with pytest.raises(ValueError, match="safe --WilmerProxyConfig name"):
        load_wilmer_proxy_config(name)


def test_shipped_example_wilmer_proxy_config_is_valid():
    config = load_wilmer_proxy_config("_example")

    assert "main" in config.upstreams
    assert config.models["general"].target_model == "chat-ui:general"
