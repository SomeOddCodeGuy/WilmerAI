"""Check conflicting pip destinations, then install with normal pip configuration."""

import ast
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


_DESTINATION_OPTIONS = {
    "target", "prefix", "root", "user", "python", "log", "report",
    "src", "source", "source-dir", "source-directory",
}
_INSPECTION_SETTINGS = {
    "PIP_LOG": os.devnull,
    "PIP_USER": "false", "PIP_GLOBAL": "false", "PIP_SITE": "false",
    "PIP_ISOLATED": "false", "PIP_QUIET": "0", "PIP_VERBOSE": "0",
    "PIP_DISABLE_PIP_VERSION_CHECK": "true",
}


def _conflicts(name: str, value: str) -> bool:
    """Identify a configured destination that automated setup does not accept.

    Args:
        name (str): Normalized pip option name without a section or PIP_ prefix.
        value (str): Configured option value.

    Returns:
        bool: Whether the non-empty option selects a conflicting destination; false values
            of the user option are accepted.
    """
    if name not in _DESTINATION_OPTIONS or not value:
        return False
    return name != "user" or value.strip().lower() not in {"0", "false", "no", "off"}


def _check_configuration() -> None:
    """Check destination conflicts through pip's public config CLI without changing policy.

    Raises:
        ValueError: If configuration conflicts with setup or cannot be inspected.
        OSError: If pip cannot be started.
    """
    conflicts = [key for key, value in os.environ.items()
                 if key.upper().startswith("PIP_")
                 and _conflicts(key[4:].lower().replace("_", "-"), value)]
    if conflicts:
        raise ValueError("Automated setup cannot use " + ", ".join(sorted(conflicts))
                         + ". Unset these settings for this launch or use manual installation.")
    explicit = os.environ.get("PIP_CONFIG_FILE")
    if explicit and os.path.normcase(os.path.abspath(explicit)) != os.path.normcase(os.path.abspath(os.devnull)):
        try:
            path = Path(explicit)
            if not stat.S_ISREG(path.stat().st_mode):
                raise OSError("Not a regular file")
            with path.open("rb") as configuration:
                configuration.read(1)
        except OSError as exc:
            raise ValueError("PIP_CONFIG_FILE must name a readable regular file or the null device. "
                             "Correct that setting before retrying.") from exc

    inspection_environment = {**os.environ, **_INSPECTION_SETTINGS, "PIP_PYTHON": sys.executable}
    # Pip may re-execute itself for --python; keep that inspection in the selected environment.
    inspection_environment.pop("PYTHONHOME", None)
    inspection_environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-I", "-m", "pip", "--log", os.devnull, "config", "list"],
        env=inspection_environment, capture_output=True, text=True, timeout=60,
    )
    if result.returncode:
        raise ValueError("Cannot inspect pip configuration. Check pip and its configuration files, "
                         "or use manual installation. Captured configuration output is not displayed.")
    observed = {}
    for line in result.stdout.splitlines():
        key, separator, raw = line.partition("=")
        if not separator or not re.fullmatch(r"[\w:-]+\.[\w-]+", key):
            continue  # A trusted Python startup hook may print before pip's output.
        try:
            value = ast.literal_eval(raw)
            if not isinstance(value, str):
                raise ValueError("Unexpected configuration value type")
        except (ValueError, SyntaxError) as exc:
            raise ValueError("Cannot interpret pip config list output. Use manual installation.") from exc
        observed[key] = value
        section, name = key.split(".", 1)
        # Environment conflicts were checked before supplying inspection-only controls.
        if section in {"global", "install"} and _conflicts(name, value):
            conflicts.append(key)
    if observed.get(":env:.log") != os.devnull or observed.get(":env:.python") != sys.executable:
        raise ValueError("Pip did not report the expected configuration inspection settings. "
                         "Use manual installation.")
    if conflicts:
        raise ValueError("Automated setup cannot use pip settings " + ", ".join(sorted(set(conflicts)))
                         + ". Remove these settings for this launch or use manual installation. "
                         "This check also rejects overridden destination settings.")


def install(requirements: str) -> int:
    """Install requirements using pip's unchanged acquisition, build, cache, and transport policies.

    Args:
        requirements (str): Installation's absolute requirements path.

    Returns:
        int: Pip's exit status, or 1 if configuration cannot be accepted.
    """
    print("Checking pip configuration for installation conflicts...", flush=True)
    try:
        _check_configuration()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Dependency setup stopped: {exc}", file=sys.stderr)
        return 1
    print("Installing dependencies from requirements.txt with the environment's pip...", flush=True)
    return subprocess.run(
        [sys.executable, "-I", "-m", "pip", "install", "--disable-pip-version-check", "-r", requirements],
    ).returncode


if __name__ == "__main__":
    sys.exit(install(sys.argv[1]))
