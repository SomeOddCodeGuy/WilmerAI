"""Launcher safety checks with synthetic environments and no package operations."""

import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
from types import SimpleNamespace

import pytest

from Scripts import launch


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "installation with spaces"
    root.mkdir()
    (root / "requirements.txt").write_text("", encoding="utf-8")
    (root / "run_eventlet.py").write_text("", encoding="utf-8")
    (root / "run_waitress.py").write_text("", encoding="utf-8")
    return root


@pytest.fixture
def valid_interpreter(monkeypatch):
    calls = []
    monkeypatch.setattr(launch, "_validate_interpreter", lambda *args: calls.append(args))
    return calls


def populate_environment(environment):
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    executable.parent.mkdir()
    executable.write_bytes(b"synthetic interpreter; never executed")
    (environment / "pyvenv.cfg").write_text("include-system-site-packages = false\n", encoding="utf-8")
    return executable


def mark_owned(root):
    (root / "venv" / ".wilmer-launcher.json").write_text(
        json.dumps({"installation": str(root), "version": 1}), encoding="utf-8",
    )


@pytest.mark.parametrize("server", ["run_eventlet.py", "run_waitress.py"])
def test_setup_and_start_are_anchored_without_touching_caller(installation, tmp_path, monkeypatch, server, valid_interpreter):
    caller = tmp_path / "other-project"
    caller.mkdir()
    (caller / "venv").mkdir()
    sentinel = caller / "venv" / "unrelated.txt"
    sentinel.write_bytes(b"Preserve other environment")
    monkeypatch.chdir(caller)
    monkeypatch.setenv("PIP_TARGET", str(caller))
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if "venv" in command:
            populate_environment(installation / "venv")
        return SimpleNamespace(returncode=7 if command[1] == str(installation / server) else 0)

    monkeypatch.setattr(launch.subprocess, "run", run)
    arguments = ["--PublicDirectory", str(tmp_path / "storage with spaces"), "--User", "chat-ui"]
    assert launch.launch(installation, server, arguments) == 7
    assert len(calls) == 3
    assert calls[0][0] == [sys.executable, "-I", "-m", "venv", "--copies", str(installation / "venv")]
    executable = str(installation / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    assert calls[1][0][:3] == [executable, "-I", str(Path(launch.__file__).with_name("install_requirements.py"))]
    assert calls[1][0][-1] == str(installation / "requirements.txt")
    # The installer reads configuration before rejecting conflicting pip options.
    assert calls[1][1]["env"]["PIP_TARGET"] == str(caller)
    assert calls[2][0] == [executable, str(installation / server), *arguments]
    assert all(call[1]["cwd"] == installation for call in calls)
    assert sentinel.read_bytes() == b"Preserve other environment"
    assert sorted(p.relative_to(caller).as_posix() for p in caller.rglob("*")) == ["venv", "venv/unrelated.txt"]


def test_unrecognized_environment_is_untouched(installation, monkeypatch):
    environment = installation / "venv"
    environment.mkdir()
    sentinel = environment / "notes.txt"
    sentinel.write_bytes(b"Unrelated data")
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: pytest.fail("Must not execute setup"))
    with pytest.raises(ValueError, match="pyvenv.cfg"):
        launch.launch(installation, "run_eventlet.py", [])
    assert sentinel.read_bytes() == b"Unrelated data"
    assert list(environment.iterdir()) == [sentinel]


@pytest.mark.parametrize("link_type", ["environment", "child_directory"])
def test_linked_environment_cannot_modify_external_files(installation, tmp_path, monkeypatch, link_type):
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "notes.txt"
    sentinel.write_bytes(b"Retain this")
    environment = installation / "venv"
    try:
        if link_type == "environment":
            environment.symlink_to(external, target_is_directory=True)
        else:
            environment.mkdir()
            populate_environment(environment)
            mark_owned(installation)
            if link_type == "child_directory":
                (environment / "lib").symlink_to(external, target_is_directory=True)
            else:
                (environment / "linked.txt").hardlink_to(sentinel)
    except OSError as exc:
        pytest.skip(f"Link creation unavailable: {exc}")
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: pytest.fail("Must not execute setup"))
    with pytest.raises(ValueError):
        launch.launch(installation, "run_eventlet.py", [])
    assert sentinel.read_bytes() == b"Retain this"
    assert list(external.iterdir()) == [sentinel]


@pytest.mark.parametrize("marked", [False, True])
def test_existing_environment_is_reused_without_recreation(installation, monkeypatch, valid_interpreter, marked):
    environment = installation / "venv"
    environment.mkdir()
    populate_environment(environment)
    if marked:
        mark_owned(installation)
    original = {p.relative_to(environment): p.read_bytes() for p in environment.rglob("*") if p.is_file()}
    calls = []
    monkeypatch.setattr(launch.subprocess, "run", lambda command, **kwargs: (
        calls.append(command) or SimpleNamespace(returncode=0)))
    assert launch.launch(installation, "run_eventlet.py", []) == 0
    assert len(calls) == 2
    assert all("venv" not in command for command in calls)

    assert valid_interpreter == [(environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python"), environment)]
    assert {p.relative_to(environment): p.read_bytes() for p in environment.rglob("*") if p.is_file()} == original


def test_install_failure_does_not_start_server(installation, monkeypatch, valid_interpreter):
    environment = installation / "venv"
    environment.mkdir()
    populate_environment(environment)
    mark_owned(installation)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(launch.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        launch.launch(installation, "run_eventlet.py", [])
    assert len(calls) == 1
    assert Path(calls[0][2]).name == "install_requirements.py"


def test_creation_failure_is_not_adopted_on_retry(installation, monkeypatch):
    calls = []

    def fail_creation(command, **kwargs):
        calls.append(command)
        (installation / "venv" / "partial.txt").write_bytes(b"Preserve partial setup")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(launch.subprocess, "run", fail_creation)
    with pytest.raises(subprocess.CalledProcessError):
        launch.launch(installation, "run_eventlet.py", [])
    with pytest.raises(ValueError, match="pyvenv.cfg"):
        launch.launch(installation, "run_eventlet.py", [])
    assert len(calls) == 1
    assert (installation / "venv" / "partial.txt").read_bytes() == b"Preserve partial setup"


def test_stale_marker_does_not_prevent_reuse(installation, monkeypatch, valid_interpreter):
    environment = installation / "venv"
    environment.mkdir()
    populate_environment(environment)
    marker = environment / ".wilmer-launcher.json"
    marker.write_text(json.dumps({"installation": "another-installation", "version": 1}), encoding="utf-8")
    original = marker.read_bytes()
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    assert launch.launch(installation, "run_eventlet.py", []) == 0
    assert marker.read_bytes() == original


@pytest.mark.parametrize("tag, redirected", [(0xA0000003, True), (0xA000000C, True), (0x80000015, False)])
def test_windows_reparse_tags(tmp_path, monkeypatch, tag, redirected):
    monkeypatch.setattr(Path, "lstat", lambda self: SimpleNamespace(st_mode=0o40755, st_reparse_tag=tag))
    assert launch._is_redirected(tmp_path / "directory") is redirected


def test_documentation_example_does_not_write(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "Docs/Custom_Python_Node_Example_Script/MyTestModule.py"
    namespace = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)

    def deny_write(*args, **kwargs):
        pytest.fail("The example must not open files or create directories")

    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", deny_write)
        patch.setattr(os, "makedirs", deny_write)
        assert namespace["Invoke"]("Example text") == "Example text"
    with pytest.raises(ValueError, match="single string"):
        namespace["Invoke"](123)


@pytest.mark.skipif(os.name == "nt", reason="Shell wrapper requires bash")
def test_shell_wrapper_from_other_directory_preserves_arguments(tmp_path):
    root = Path(__file__).resolve().parents[2]
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    trace = tmp_path / "arguments.txt"
    stub = stubs / "python3"
    stub.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$LAUNCH_TRACE"\nexit 7\n', encoding="utf-8")
    stub.chmod(0o700)
    result = subprocess.run(
        ["/bin/bash", str(root / "run_macos.sh"), "--PublicDirectory", "path with spaces"],
        cwd=tmp_path, env={**os.environ, "PATH": str(stubs) + os.pathsep + os.defpath, "LAUNCH_TRACE": str(trace)},
        capture_output=True, timeout=5,
    )
    assert result.returncode == 7
    assert trace.read_text().splitlines() == [
        "-I", str(root / "Scripts/launch.py"), "run_eventlet.py", "--PublicDirectory", "path with spaces",
    ]
    assert not (tmp_path / "venv").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX venv interpreter links")
def test_legacy_interpreter_symlinks_are_allowed(installation, tmp_path, valid_interpreter):
    environment = installation / "venv"
    environment.mkdir()
    executable = populate_environment(environment)
    base_python = tmp_path / "base-python"
    base_python.write_bytes(b"synthetic base interpreter")
    executable.unlink()
    executable.symlink_to(base_python)
    (executable.parent / "python3").symlink_to("python")
    (executable.parent / "python3.14").symlink_to(base_python)
    assert launch._validate_environment(environment, installation) == executable
    assert valid_interpreter == [(executable, environment)]
    assert not (environment / ".wilmer-launcher.json").exists()
    assert base_python.read_bytes() == b"synthetic base interpreter"


@pytest.mark.skipif(os.name == "nt", reason="POSIX venv interpreter aliases")
@pytest.mark.parametrize("alias", ["𝜋thon", "python-alias", "python3.13t", "python3.14t"])
def test_additional_alias_to_environment_interpreter_is_allowed(installation, tmp_path, valid_interpreter, alias):
    environment = installation / "venv"
    environment.mkdir()
    executable = populate_environment(environment)
    base_python = tmp_path / "base-python"
    base_python.write_bytes(b"Synthetic base interpreter")
    executable.unlink()
    executable.symlink_to(base_python)
    (executable.parent / "python3").symlink_to("python")
    alias_path = executable.parent / alias
    alias_path.symlink_to("python3")

    assert launch._validate_environment(environment, installation) == executable
    assert valid_interpreter == [(executable, environment)]
    assert alias_path.is_symlink()
    assert alias_path.readlink() == Path("python3")
    assert base_python.read_bytes() == b"Synthetic base interpreter"
    assert not (environment / ".wilmer-launcher.json").exists()


@pytest.mark.parametrize("filename", ["pythonw.exe", "python314.dll", "package.py"])
def test_additional_file_links_and_hardlinks_are_allowed(installation, tmp_path, valid_interpreter, filename):
    environment = installation / "venv"
    environment.mkdir()
    executable = populate_environment(environment)
    target = tmp_path / "shared-file"
    target.write_bytes(b"Preserve shared content")
    try:
        (executable.parent / filename).symlink_to(target)
        (environment / "package-hardlink.py").hardlink_to(target)
    except OSError as exc:
        pytest.skip(f"Link creation unavailable: {exc}")
    assert launch._validate_environment(environment, installation) == executable
    assert target.read_bytes() == b"Preserve shared content"


def test_internal_library_link_is_allowed(installation, valid_interpreter):
    environment = installation / "venv"
    environment.mkdir()
    executable = populate_environment(environment)
    (environment / "lib").mkdir()
    try:
        (environment / "lib64").symlink_to("lib", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Link creation unavailable: {exc}")
    assert launch._validate_environment(environment, installation) == executable


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired("python", 60), subprocess.CalledProcessError(1, "python")])
def test_interpreter_startup_failure_has_recovery_message(tmp_path, monkeypatch, failure):
    def run(*args, **kwargs):
        raise failure
    monkeypatch.setattr(launch.subprocess, "run", run)
    with pytest.raises(ValueError, match="Check it manually"):
        launch._validate_interpreter(tmp_path / "python", tmp_path)


@pytest.mark.parametrize("defect", [None, "prefix", "base_prefix", "purelib", "platlib", "scripts", "data", "malformed", "missing_pip"])
def test_interpreter_installation_paths(installation, tmp_path, monkeypatch, defect):
    environment = installation / "venv"
    environment.mkdir()
    executable = populate_environment(environment)
    configuration = {
        "prefix": str(environment), "base_prefix": str(tmp_path), "pip_available": defect != "missing_pip",
        "paths": {key: str(environment / key) for key in ("purelib", "platlib", "scripts", "data")},
    }
    if defect == "prefix":
        configuration["prefix"] = str(tmp_path)
    elif defect == "base_prefix":
        configuration["base_prefix"] = str(environment)
    elif defect in configuration["paths"]:
        configuration["paths"][defect] = str(tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="Startup hook message\n" + launch._PROBE_PREFIX + ("{}" if defect == "malformed" else json.dumps(configuration)))

    monkeypatch.setattr(launch.subprocess, "run", run)
    if defect:
        with pytest.raises(ValueError):
            launch._validate_environment(environment, installation)
    else:
        assert launch._validate_environment(environment, installation) == executable
    assert len(calls) == 1
    assert calls[0][0][:3] == [str(executable), "-I", "-c"]
    assert calls[0][1]["check"] is True
    assert calls[0][1]["timeout"] == 60


def test_linked_legacy_configuration_is_rejected_before_execution(installation, tmp_path, monkeypatch):
    environment = installation / "venv"
    environment.mkdir()
    populate_environment(environment)
    external = tmp_path / "external.cfg"
    external.write_text("include-system-site-packages = false\n", encoding="utf-8")
    configuration = environment / "pyvenv.cfg"
    configuration.unlink()
    try:
        configuration.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"Link creation unavailable: {exc}")
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: pytest.fail("Must not execute setup"))
    with pytest.raises(ValueError, match="pyvenv.cfg"):
        launch.launch(installation, "run_eventlet.py", [])


@pytest.mark.parametrize("server", ["run_eventlet.py", "run_waitress.py"])
def test_server_and_installer_use_environment_for_child_commands(installation, tmp_path, monkeypatch,
                                                              valid_interpreter, server):
    environment = installation / "venv"
    environment.mkdir()
    executable = populate_environment(environment)
    executable.chmod(0o700)
    caller_bin = tmp_path / "caller-bin"
    caller_bin.mkdir()
    caller_python = caller_bin / executable.name
    caller_python.write_bytes(b"Another Python")
    caller_python.chmod(0o700)
    monkeypatch.setenv("PATH", str(caller_bin))
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "other-environment"))
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "other-python"))
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("EXAMPLE_SETTING", "retained")
    original = dict(os.environ)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        child_env = kwargs["env"]
        assert child_env["PATH"].split(os.pathsep) == [str(executable.parent), str(caller_bin)]
        assert shutil.which(executable.name, path=child_env["PATH"]) == str(executable)
        assert child_env["VIRTUAL_ENV"] == str(environment)
        assert "PYTHONHOME" not in child_env
        assert child_env["EXAMPLE_SETTING"] == "retained"
        assert child_env["PIP_NO_INDEX"] == "1"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launch.subprocess, "run", run)
    assert launch.launch(installation, server, []) == 0
    assert len(calls) == 2
    assert dict(os.environ) == original
