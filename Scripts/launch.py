"""Set up and run a server using this installation's virtual environment."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys


_PROBE_PREFIX = "VENV_CHECK:"


def _validate_interpreter(executable: Path, environment: Path) -> None:
    """Require the interpreter and pip installation paths to use this environment.

    Args:
        executable (Path): Environment interpreter to probe in an isolated subprocess.
        environment (Path): Resolved environment directory expected to contain installation
            paths.

    Raises:
        ValueError: If the probe fails, paths leave the environment, or pip is unavailable.
        OSError: If the interpreter cannot be started or its paths cannot be inspected.
    """
    try:
        result = subprocess.run(
            [str(executable), "-I", "-c",
             "import importlib.util, json, sys, sysconfig; "
             f"print({_PROBE_PREFIX!r} + json.dumps({{'prefix': sys.prefix, 'base_prefix': sys.base_prefix, "
             "'pip_available': importlib.util.find_spec('pip') is not None, "
             "'paths': {k: sysconfig.get_path(k) for k in ('purelib', 'platlib', 'scripts', 'data')}}))"],
            cwd=environment.parent, check=True, capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("The environment's Python startup check timed out. Check it manually before retrying.") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError("The environment's Python could not complete its startup check. "
                         "Check it manually before retrying.") from exc
    try:
        records = [line[len(_PROBE_PREFIX):] for line in result.stdout.splitlines()
                   if line.startswith(_PROBE_PREFIX)]
        configuration = json.loads(records[-1])
        prefix = Path(configuration["prefix"]).resolve(strict=True)
        base_prefix = Path(configuration["base_prefix"]).resolve(strict=True)
        paths = [Path(configuration["paths"][key]).resolve()
                 for key in ("purelib", "platlib", "scripts", "data")]
        pip_available = configuration["pip_available"]
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Cannot verify the environment's Python installation paths.") from exc
    if prefix != environment or prefix == base_prefix or any(
        not path.is_relative_to(environment) for path in paths
    ):
        raise ValueError("The environment's Python would install outside its directory.")
    if pip_available is not True:
        raise ValueError("The environment's Python is missing pip. Repair it using the manual setup instructions.")


def _is_redirected(path: Path) -> bool:
    """Check whether a path redirects through a link or Windows reparse point.

    Args:
        path (Path): Existing path whose own metadata is inspected.

    Returns:
        bool: Whether the path is a symlink or name-surrogate reparse point.

    Raises:
        OSError: If the path metadata cannot be read.
    """
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_reparse_tag", 0) & 0x20000000
    )


def _validate_environment(environment: Path, root: Path) -> Path:
    """Check environment structure and installation directories before setup.

    Args:
        environment (Path): Installation-local environment directory.
        root (Path): Resolved installation directory.

    Returns:
        Path: The environment's Python executable.

    Raises:
        ValueError: If environment structure or installation directories are unsuitable.
        OSError: If environment metadata cannot be inspected.
    """
    if environment != root / "venv" or _is_redirected(environment) or not environment.is_dir():
        raise ValueError("The launcher environment must be a regular directory, not a link.")
    configuration_path = environment / "pyvenv.cfg"
    if not configuration_path.is_file() or _is_redirected(configuration_path):
        raise ValueError("The launcher environment requires a regular pyvenv.cfg file. "
                         "Repair this environment using the manual setup instructions.")
    configuration = configuration_path.read_text(encoding="utf-8")
    settings = dict(line.split("=", 1) for line in configuration.splitlines() if "=" in line)
    if {key.strip().lower(): value.strip().lower() for key, value in settings.items()}.get(
        "include-system-site-packages"
    ) != "false":
        raise ValueError("The launcher environment must isolate system site packages.")
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not executable.is_file():
        raise ValueError("The launcher environment is missing its Python executable.")
    for directory in (executable.parent, environment / "Lib", environment / "lib", environment / "lib64"):
        if not directory.resolve().is_relative_to(environment):
            raise ValueError(f"Environment installation directory leaves its directory: {directory.name}")
    _validate_interpreter(executable, environment)
    return executable


def launch(root: Path, server: str, arguments: list[str]) -> int:
    """Install requirements and start a server from its installation directory.

    Args:
        root (Path): Installation directory containing requirements and entry points.
        server (str): Supported server entry-point filename.
        arguments (list[str]): Application CLI arguments, forwarded unchanged.

    Returns:
        int: Exit status from the server process.

    Raises:
        ValueError: If setup paths or environment structure cannot be verified.
        OSError: If filesystem access fails.
        subprocess.CalledProcessError: If creation or dependency installation fails.
    """
    root = root.resolve(strict=True)
    if server not in ("run_eventlet.py", "run_waitress.py"):
        raise ValueError("Unsupported server entry point.")
    for filename in ("requirements.txt", server):
        path = root / filename
        if _is_redirected(path) or not path.is_file():
            raise ValueError(f"Expected an installation-local file: {filename}")
    environment = root / "venv"
    try:
        environment.lstat()
    except FileNotFoundError:
        print("Creating the installation's virtual environment...", flush=True)
        # Reserve exclusively; never run environment creation over an existing path.
        environment.mkdir()
        subprocess.run(
            [sys.executable, "-I", "-m", "venv", "--copies", str(environment)],
            cwd=root, check=True,
        )
    print("Checking the installation's virtual environment...", flush=True)
    executable = _validate_environment(environment, root)
    process_environment = dict(os.environ)
    process_environment["PATH"] = str(executable.parent) + os.pathsep + process_environment.get("PATH", os.defpath)
    process_environment["VIRTUAL_ENV"] = str(environment)
    process_environment.pop("PYTHONHOME", None)
    subprocess.run(
        [str(executable), "-I", str(Path(__file__).resolve().with_name("install_requirements.py")),
         str(root / "requirements.txt")],
        cwd=root, check=True, env=process_environment,
    )
    print(f"Starting {server}...", flush=True)
    return subprocess.run([str(executable), str(root / server), *arguments],
                          cwd=root, env=process_environment).returncode


def main() -> int:
    """Run the launcher selected by the command-line arguments.

    Returns:
        int: Server exit status, or 1 when setup fails.
    """
    try:
        if len(sys.argv) < 2:
            raise ValueError("A server entry point is required.")
        return launch(Path(__file__).resolve().parent.parent, sys.argv[1], sys.argv[2:])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Launcher stopped: {exc}", file=sys.stderr)
        print("The launcher has not removed your environment. "
              "Resolve the reported error before retrying.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
