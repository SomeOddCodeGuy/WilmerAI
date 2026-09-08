"""Offline pip CLI checks against temporary configuration and Python's bundled pip."""

import ensurepip
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

from Scripts import install_requirements


@pytest.fixture(scope="module")
def bundled_pip(tmp_path_factory):
    directory = tmp_path_factory.mktemp("bundled-pip")
    wheel = Path(ensurepip.__file__).parent / "_bundled" / f"pip-{ensurepip.version()}-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(directory)
    return directory


@pytest.fixture
def pip_cli(tmp_path, monkeypatch, bundled_pip):
    for key in list(os.environ):
        if key.upper().startswith("PIP_"):
            monkeypatch.delenv(key)
    paths = {kind: tmp_path / f"{kind}.ini" for kind in ("global", "user", "site")}
    real_run = subprocess.run
    # Only the test harness substitutes pip discovery and bypasses interpreter re-execution.
    # Production uses the public CLI; no test invokes an installer or network operation.
    bootstrap = (
        "import json, os, runpy, socket, sys; "
        f"sys.path.insert(0, {str(bundled_pip)!r}); "
        "socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('Network forbidden')); "
        "from pip._internal import configuration; "
        f"configuration.get_configuration_files = lambda: { {kind: [str(path)] for kind, path in paths.items()}!r}; "
        "os.environ['_PIP_RUNNING_IN_SUBPROCESS'] = '1'; "
    )
    calls = []
    parsed = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert command[:4] == [sys.executable, "-I", "-m", "pip"]
        if "config" in command:
            return real_run([sys.executable, "-I", "-c", bootstrap +
                             "sys.argv[0] = 'pip'; runpy.run_module('pip', run_name='__main__')", *command[4:]],
                            **kwargs)
        assert command[4:] == ["install", "--disable-pip-version-check", "-r", str(tmp_path / "requirements.txt")]
        assert kwargs == {}  # Original process environment and files reach pip unchanged.
        probe = real_run([sys.executable, "-I", "-c", bootstrap +
                         "from pip._internal.commands import create_command; "
                         "options, args = create_command('install').parse_args(sys.argv[1:]); "
                         "print(json.dumps(vars(options), default=repr))", *command[5:]],
                         capture_output=True, text=True, timeout=30)
        if probe.returncode == 0:
            parsed.append(json.loads(probe.stdout))
        return SimpleNamespace(returncode=probe.returncode)

    monkeypatch.setattr(install_requirements.subprocess, "run", run)
    return SimpleNamespace(paths=paths, calls=calls, parsed=parsed,
                           requirements=str(tmp_path / "requirements.txt"))


@pytest.mark.parametrize("override", ["none", "environment", "explicit_file", "disabled_files"])
def test_normal_pip_precedence_and_policies_are_preserved(pip_cli, tmp_path, monkeypatch, override):
    pip_cli.paths["global"].write_text("[global]\nindex-url = https://global.invalid/simple\ntimeout = 9\n")
    pip_cli.paths["user"].write_text("[global]\nindex-url = https://user.invalid/simple\n")
    # Pip's negative boolean option uses false in configuration to disable isolation.
    pip_cli.paths["site"].write_text(
        "[global]\nindex-url = https://site.invalid/simple\n"
        "[install]\nindex-url = https://install.invalid/simple\n"
        "extra-index-url = https://extra.invalid/simple\nno-index = true\nfind-links = ./wheelhouse\n"
        "trusted-host = mirror.invalid\nproxy = http://proxy.invalid:8123\n"
        "cert = ./ca.pem\nclient-cert = ./client.pem\nrequire-hashes = true\n"
        "only-binary = :all:\nconstraint = ./constraints.txt\nbuild-constraint = ./build-constraints.txt\n"
        "no-build-isolation = false\nno-cache-dir = true\ncache-dir = ./cache\nretries = 3\n"
        "config-settings = example=value\nprefer-binary = true\n"
        "[download]\nindex-url = https://irrelevant.invalid/simple\n")
    expected_index = "https://install.invalid/simple"
    if override == "environment":
        monkeypatch.setenv("PIP_INDEX_URL", "https://environment.invalid/simple")
        monkeypatch.setenv("PIP_TIMEOUT", "17")
        expected_index = "https://environment.invalid/simple"
    elif override == "explicit_file":
        explicit = tmp_path / "explicit.ini"
        explicit.write_text("[install]\nindex-url = https://explicit.invalid/simple\n")
        monkeypatch.setenv("PIP_CONFIG_FILE", str(explicit))
        expected_index = "https://explicit.invalid/simple"
    elif override == "disabled_files":
        monkeypatch.setenv("PIP_CONFIG_FILE", os.devnull)
        monkeypatch.setenv("PIP_INDEX_URL", "https://environment.invalid/simple")
        monkeypatch.setenv("PIP_NO_INDEX", "true")
        expected_index = "https://environment.invalid/simple"
    original = dict(os.environ)
    assert install_requirements.install(pip_cli.requirements) == 0
    assert dict(os.environ) == original
    assert len(pip_cli.calls) == 2
    options = pip_cli.parsed[0]
    assert options["index_url"] == expected_index
    assert options["no_index"]
    assert options["disable_pip_version_check"]
    if override != "disabled_files":
        assert options["extra_index_urls"] == ["https://extra.invalid/simple"]
        assert options["find_links"] == ["./wheelhouse"]
        assert options["trusted_hosts"] == ["mirror.invalid"]
        assert options["proxy"] == "http://proxy.invalid:8123"
        assert options["cert"] == "./ca.pem"
        assert options["client_cert"] == "./client.pem"
        assert options["require_hashes"]
        assert options["timeout"] == (17 if override == "environment" else 9)
        assert ":all:" in options["format_control"]
        assert options["constraints"] == ["./constraints.txt"]
        assert options["build_constraints"] == ["./build-constraints.txt"]
        assert not options["build_isolation"]
        assert options["cache_dir"] is False
        assert options["retries"] == 3
        assert options["config_settings"] == {"example": "value"}
        assert options["prefer_binary"]


@pytest.mark.parametrize("source", ["environment", "configuration"])
@pytest.mark.parametrize("option", ["target", "prefix", "root", "user", "python", "log", "report", "src"])
def test_destination_conflicts_stop_before_install(pip_cli, tmp_path, monkeypatch, capsys, source, option):
    sentinel = tmp_path / "private-setting"
    sentinel.write_bytes(b"Preserved")
    value = "true" if option == "user" else str(sentinel)
    if source == "environment":
        monkeypatch.setenv("PIP_" + option.upper(), value)
    else:
        pip_cli.paths["site"].write_text(f"[global]\n{option} = {value}\n")
    assert install_requirements.install(pip_cli.requirements) == 1
    assert not pip_cli.parsed
    assert len(pip_cli.calls) == (0 if source == "environment" else 1)
    output = capsys.readouterr()
    assert option.lower() in output.err.lower()
    assert str(sentinel) not in output.err + output.out
    assert sentinel.read_bytes() == b"Preserved"


def test_whitespace_target_stops_before_pip(pip_cli, monkeypatch, capsys):
    monkeypatch.setenv("PIP_TARGET", " ")
    assert install_requirements.install(pip_cli.requirements) == 1
    assert not pip_cli.calls
    assert "PIP_TARGET" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["false", "0", "no", "off", ""])
def test_disabled_user_install_is_accepted(pip_cli, monkeypatch, value):
    monkeypatch.setenv("PIP_USER", value)
    assert install_requirements.install(pip_cli.requirements) == 0


def test_overridden_destination_is_conservatively_rejected(pip_cli):
    pip_cli.paths["site"].write_text("[global]\nuser = true\n[install]\nuser = false\n")
    assert install_requirements.install(pip_cli.requirements) == 1
    assert not pip_cli.parsed


@pytest.mark.parametrize("configuration", ["Invalid config with synthetic secret", "[global]\ntimeout = invalid\n[install]\ntimeout = 5\n"])
def test_invalid_configuration_is_not_rewritten(pip_cli, capsys, configuration):
    pip_cli.paths["site"].write_text(configuration)
    assert install_requirements.install(pip_cli.requirements) == 1
    assert not pip_cli.parsed
    output = capsys.readouterr()
    assert "Cannot inspect pip configuration" in output.err
    assert "synthetic secret" not in output.err + output.out


@pytest.mark.parametrize("kind", ["missing", "directory", "unreadable"])
def test_explicit_configuration_must_be_readable(pip_cli, tmp_path, monkeypatch, kind):
    explicit = tmp_path / "explicit.ini"
    if kind == "directory":
        explicit.mkdir()
    elif kind == "unreadable":
        explicit.write_text("[global]\n")
        original = Path.open
        def deny(path, *args, **kwargs):
            if path == explicit:
                raise PermissionError("Synthetic read error")
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, "open", deny)
    monkeypatch.setenv("PIP_CONFIG_FILE", str(explicit))
    assert install_requirements.install(pip_cli.requirements) == 1
    assert not pip_cli.calls


def test_empty_environment_value_retains_command_section(pip_cli, monkeypatch):
    pip_cli.paths["site"].write_text("[global]\nindex-url = https://global.invalid/simple\n[install]\nindex-url = https://install.invalid/simple\n")
    monkeypatch.setenv("PIP_INDEX_URL", "")
    assert install_requirements.install(pip_cli.requirements) == 0
    assert pip_cli.parsed[0]["index_url"] == "https://install.invalid/simple"


def test_inspection_is_guarded_and_install_keeps_original_settings(pip_cli, monkeypatch):
    monkeypatch.setenv("PIP_NO_BINARY", ":all:")
    monkeypatch.setenv("PIP_CACHE_DIR", "./chosen-cache")
    monkeypatch.setenv("PIP_USE_FEATURE", "truststore")
    monkeypatch.setenv("PIP_USE_DEPRECATED", "legacy-certs")
    monkeypatch.setenv("PYTHONPATH", "/unused")
    assert install_requirements.install(pip_cli.requirements) == 0
    command, kwargs = pip_cli.calls[0]
    assert command[4:] == ["--log", os.devnull, "config", "list"]
    assert kwargs["env"]["PIP_PYTHON"] == sys.executable
    assert kwargs["env"]["PIP_LOG"] == os.devnull
    assert "PYTHONPATH" not in kwargs["env"]
    options = pip_cli.parsed[0]
    assert options["cache_dir"] == "./chosen-cache"
    assert options["features_enabled"] == ["truststore"]
    assert options["deprecated_features_enabled"] == ["legacy-certs"]
    assert ":all:" in options["format_control"]


@pytest.mark.parametrize("output", ["Unexpected output", ":env:.log=123", ":env:.log='unterminated"])
def test_unrecognized_cli_output_stops_setup(monkeypatch, output):
    monkeypatch.setattr(install_requirements.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=output))
    assert install_requirements.install("requirements.txt") == 1
