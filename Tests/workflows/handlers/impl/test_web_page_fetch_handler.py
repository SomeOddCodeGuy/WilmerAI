import json

import pytest

from Middleware.services.web_page_fetch_service import (
    WebPageFetchError,
    WebPageFetchPolicy,
    WebPageFetchResult,
)
from Middleware.workflows.handlers.impl.web_page_fetch_handler import WebPageFetchHandler
from Middleware.workflows.models.execution_context import ExecutionContext


def make_context(config, stream=False):
    return ExecutionContext(
        request_id="request-1",
        workflow_id="workflow-1",
        discussion_id=None,
        config=config,
        messages=[],
        stream=stream,
    )


@pytest.fixture
def dependencies(mocker):
    variables = mocker.MagicMock()
    variables.apply_variables.side_effect = lambda value, context: value
    service = mocker.MagicMock()
    handler = WebPageFetchHandler(
        workflow_manager=mocker.MagicMock(),
        workflow_variable_service=variables,
        web_page_fetch_service=service,
    )
    return handler, variables, service


def successful_result(body=b"<html><head><title>Hidden</title></head><body>Hello</body></html>"):
    return WebPageFetchResult(
        status_code=200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        body=body,
        url="https://example.com/final",
    )


def test_default_config_builds_default_on_policy_and_strips_html(dependencies):
    handler, _, service = dependencies
    service.fetch.return_value = successful_result()

    result = handler.handle(make_context({"type": "WebPageFetch", "url": "https://example.com"}))

    assert result == "Hello"
    requested_url, fetch_policy = service.fetch.call_args.args
    assert service.fetch.call_args.kwargs == {"request_id": "request-1"}
    assert requested_url == "https://example.com"
    assert fetch_policy == WebPageFetchPolicy()


def test_url_proxy_allowed_hosts_and_ca_bundle_use_variable_substitution(
    dependencies,
    tmp_path,
):
    handler, variables, service = dependencies
    service.fetch.return_value = successful_result(b"ok")
    ca_bundle = tmp_path / "ca.pem"
    ca_bundle.write_text("test certificate", encoding="utf-8")
    replacements = {
        "https://{host}/page": "https://example.com/page",
        "socks5h://{proxy}": "socks5h://proxy.internal:1080",
        "{host}": "example.com",
        "{ca}": str(ca_bundle),
    }
    variables.apply_variables.side_effect = lambda value, context: replacements.get(value, value)
    context = make_context({
        "type": "WebPageFetch",
        "url": "https://{host}/page",
        "proxy": "socks5h://{proxy}",
        "allowedHosts": ["{host}"],
        "allowedPorts": [8443, "9443"],
        "caBundle": "{ca}",
        "outputFormat": "text",
    })

    assert handler.handle(context) == "ok"
    requested_url, fetch_policy = service.fetch.call_args.args
    assert requested_url == "https://example.com/page"
    assert fetch_policy.proxies == {
        "http": "socks5h://proxy.internal:1080",
        "https": "socks5h://proxy.internal:1080",
    }
    assert fetch_policy.allowed_hosts == frozenset({"example.com"})
    assert fetch_policy.allowed_ports == frozenset({8443, 9443})
    assert fetch_policy.verify == str(ca_bundle)


def test_every_policy_control_can_be_explicitly_disabled_or_changed(dependencies):
    handler, _, service = dependencies
    service.fetch.return_value = successful_result(b"plain")
    config = {
        "type": "WebPageFetch",
        "url": "https://example.com",
        "timeout": "12.5",
        "respectRobots": False,
        "failClosedOnRobotsError": False,
        "blockPrivateAddresses": False,
        "restrictPorts": False,
        "enableDomainPacing": False,
        "minimumDelaySeconds": "1.5",
        "maxPacingWaitSeconds": 9,
        "honorCrawlDelay": False,
        "honorRequestRate": False,
        "honorRetryAfter": False,
        "honorForbiddenCooldown": False,
        "robotsCacheSeconds": 10,
        "robotsFailureCacheSeconds": 11,
        "forbiddenCooldownSeconds": 12,
        "retryAfterFallbackSeconds": 13,
        "allowRedirects": False,
        "maxRedirects": "0",
        "enforceContentType": False,
        "allowedContentTypes": ["application/xml"],
        "maxHeaderBytes": "100",
        "maxTransferBytes": 200,
        "maxDecodedBytes": 300,
        "verify": False,
        "outputFormat": "text",
    }

    assert handler.handle(make_context(config)) == "plain"
    fetch_policy = service.fetch.call_args.args[1]
    assert fetch_policy == WebPageFetchPolicy(
        timeout=12.5,
        verify=False,
        respect_robots=False,
        fail_closed_on_robots_error=False,
        block_private_addresses=False,
        restrict_ports=False,
        enable_domain_pacing=False,
        minimum_delay_seconds=1.5,
        max_pacing_wait_seconds=9,
        honor_crawl_delay=False,
        honor_request_rate=False,
        honor_retry_after=False,
        honor_forbidden_cooldown=False,
        robots_cache_seconds=10,
        robots_failure_cache_seconds=11,
        forbidden_cooldown_seconds=12,
        retry_after_fallback_seconds=13,
        allow_redirects=False,
        max_redirects=0,
        enforce_content_type=False,
        allowed_content_types=frozenset({"application/xml"}),
        max_header_bytes=100,
        max_transfer_bytes=200,
        max_decoded_bytes=300,
    )


def test_text_and_full_output_formats(dependencies):
    handler, _, service = dependencies
    service.fetch.return_value = successful_result(b"hello")

    assert handler.handle(make_context({
        "type": "WebPageFetch",
        "url": "https://example.com",
        "outputFormat": "text",
    })) == "hello"

    full = handler.handle(make_context({
        "type": "WebPageFetch",
        "url": "https://example.com",
        "outputFormat": "full",
    }))
    assert json.loads(full) == {
        "status_code": 200,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": "hello",
        "url": "https://example.com/final",
    }


def test_streaming_wraps_formatted_payload(dependencies):
    handler, _, service = dependencies
    service.fetch.return_value = successful_result(b"hello")

    result = handler.handle(make_context({
        "type": "WebPageFetch",
        "url": "https://example.com",
        "outputFormat": "text",
    }, stream=True))

    assert "".join(chunk["token"] for chunk in result) == "hello"


def test_on_error_raise_preserves_service_error(dependencies):
    handler, _, service = dependencies
    error = WebPageFetchError("blocked")
    service.fetch.side_effect = error

    with pytest.raises(WebPageFetchError) as raised:
        handler.handle(make_context({
            "type": "WebPageFetch",
            "url": "https://example.com",
        }))

    assert raised.value is error


def test_on_error_return_supports_text_full_and_streaming(dependencies):
    handler, _, service = dependencies
    service.fetch.side_effect = WebPageFetchError(
        "blocked",
        status_code=403,
        headers={"X-Test": "yes"},
        url="https://example.com/page",
    )
    text_result = handler.handle(make_context({
        "type": "WebPageFetch",
        "url": "https://example.com/page",
        "onError": "return",
    }))
    assert text_result == "blocked"

    full_result = handler.handle(make_context({
        "type": "WebPageFetch",
        "url": "https://example.com/page",
        "onError": "return",
        "outputFormat": "full",
    }, stream=True))
    assert json.loads("".join(chunk["token"] for chunk in full_result)) == {
        "error": "blocked",
        "status_code": 403,
        "headers": {"X-Test": "yes"},
        "body": None,
        "url": "https://example.com/page",
    }


@pytest.mark.parametrize(
    "config, message",
    [
        ({}, "url"),
        ({"url": 123}, "url"),
        ({"url": "https://example.com", "method": "POST"}, "GET"),
        ({"url": "https://example.com", "method": 1}, "GET"),
        ({"url": "https://example.com", "body": ""}, "body"),
        ({"url": "https://example.com", "headers": {"X-Test": "yes"}}, "headers"),
        ({"url": "https://example.com", "transport": "curl"}, "Requests transport"),
        ({"url": "https://example.com", "transport": None}, "Requests transport"),
        ({"url": "https://example.com", "outputFormat": "json"}, "outputFormat"),
        ({"url": "https://example.com", "onError": "ignore"}, "onError"),
    ],
)
def test_hard_invariants_and_enum_validation(dependencies, config, message):
    handler, _, service = dependencies

    with pytest.raises(ValueError, match=message):
        handler.handle(make_context({"type": "WebPageFetch", **config}))

    service.fetch.assert_not_called()


@pytest.mark.parametrize(
    "field",
    [
        "respectRobots",
        "failClosedOnRobotsError",
        "blockPrivateAddresses",
        "restrictPorts",
        "enableDomainPacing",
        "honorCrawlDelay",
        "honorRequestRate",
        "honorRetryAfter",
        "honorForbiddenCooldown",
        "allowRedirects",
        "enforceContentType",
        "verify",
    ],
)
def test_boolean_policy_fields_require_true_or_false(dependencies, field):
    handler, _, service = dependencies

    with pytest.raises(ValueError, match="boolean"):
        handler.handle(make_context({
            "type": "WebPageFetch",
            "url": "https://example.com",
            field: "true",
        }))

    service.fetch.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("minimumDelaySeconds", -1),
        ("maxPacingWaitSeconds", True),
        ("robotsCacheSeconds", "never"),
        ("robotsFailureCacheSeconds", float("nan")),
        ("forbiddenCooldownSeconds", float("inf")),
        ("retryAfterFallbackSeconds", -0.1),
    ],
)
def test_duration_fields_require_finite_nonnegative_numbers(
    dependencies,
    field,
    value,
):
    handler, _, service = dependencies

    with pytest.raises(ValueError, match=field):
        handler.handle(make_context({
            "type": "WebPageFetch",
            "url": "https://example.com",
            field: value,
        }))

    service.fetch.assert_not_called()


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_timeout_must_be_finite(dependencies, value):
    handler, _, service = dependencies

    with pytest.raises(ValueError, match="timeout"):
        handler.handle(make_context({
            "type": "WebPageFetch",
            "url": "https://example.com",
            "timeout": value,
        }))

    service.fetch.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("maxHeaderBytes", 0),
        ("maxTransferBytes", True),
        ("maxDecodedBytes", "many"),
        ("maxDecodedBytes", 1.5),
    ],
)
def test_size_fields_require_positive_integers(dependencies, field, value):
    handler, _, service = dependencies

    with pytest.raises(ValueError, match=field):
        handler.handle(make_context({
            "type": "WebPageFetch",
            "url": "https://example.com",
            field: value,
        }))

    service.fetch.assert_not_called()


@pytest.mark.parametrize("value", [-1, 6, 1.5, True, "many"])
def test_redirect_cap_is_an_integer_between_zero_and_five(dependencies, value):
    handler, _, service = dependencies

    with pytest.raises(ValueError, match="maxRedirects"):
        handler.handle(make_context({
            "type": "WebPageFetch",
            "url": "https://example.com",
            "maxRedirects": value,
        }))

    service.fetch.assert_not_called()


@pytest.mark.parametrize(
    "value",
    ["443", [0], [65536], [True], [1.5], ["bad"]],
)
def test_allowed_ports_requires_valid_integer_list_entries(dependencies, value):
    handler, _, service = dependencies

    with pytest.raises(ValueError, match="allowedPorts"):
        handler.handle(make_context({
            "type": "WebPageFetch",
            "url": "https://example.com",
            "allowedPorts": value,
        }))

    service.fetch.assert_not_called()


@pytest.mark.parametrize(
    "value",
    [[], "text/html", [""], ["text/html; charset=utf-8"], ["html"], [1]],
)
def test_content_type_allowlist_requires_plain_media_types(dependencies, value):
    handler, _, service = dependencies

    with pytest.raises(ValueError, match="allowedContentTypes"):
        handler.handle(make_context({
            "type": "WebPageFetch",
            "url": "https://example.com",
            "allowedContentTypes": value,
        }))

    service.fetch.assert_not_called()


def test_proxy_and_ca_bundle_config_validation(dependencies, tmp_path):
    handler, _, service = dependencies
    base = {"type": "WebPageFetch", "url": "https://example.com"}

    with pytest.raises(ValueError, match="proxy"):
        handler.handle(make_context({**base, "proxy": 123}))
    with pytest.raises(ValueError, match="caBundle"):
        handler.handle(make_context({**base, "caBundle": []}))
    with pytest.raises(ValueError, match="file not found"):
        handler.handle(make_context({**base, "caBundle": str(tmp_path / "missing.pem")}))

    service.fetch.assert_not_called()


def test_empty_resolved_proxy_and_ca_bundle_mean_no_override(dependencies):
    handler, variables, service = dependencies
    service.fetch.return_value = successful_result(b"ok")
    variables.apply_variables.side_effect = lambda value, context: "" if value == "{empty}" else value

    assert handler.handle(make_context({
        "type": "WebPageFetch",
        "url": "https://example.com",
        "proxy": "{empty}",
        "caBundle": "{empty}",
        "outputFormat": "text",
    })) == "ok"

    fetch_policy = service.fetch.call_args.args[1]
    assert fetch_policy.proxies is None
    assert fetch_policy.verify is True


def test_default_singleton_is_used_when_service_is_not_injected(mocker):
    default_service = mocker.MagicMock()
    get_default = mocker.patch(
        "Middleware.workflows.handlers.impl.web_page_fetch_handler.get_default_web_page_fetch_service",
        return_value=default_service,
    )

    handler = WebPageFetchHandler(
        workflow_manager=mocker.MagicMock(),
        workflow_variable_service=mocker.MagicMock(),
    )

    get_default.assert_called_once_with()
    assert handler.web_page_fetch_service is default_service
