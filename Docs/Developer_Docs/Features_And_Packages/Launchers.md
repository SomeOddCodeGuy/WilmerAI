# Installation launchers

`run_macos.sh` and `run_windows.bat` delegate to the standard-library-only `Scripts/launch.py`. The shell wrapper
selects `run_eventlet.py`; the batch wrapper selects `run_waitress.py`. Both invoke the helper with Python's `-I`
flag and forward application arguments. The helper derives the installation root from its own file location and
uses that root as the working directory for environment creation, dependency installation, and the server.
Relative application CLI paths therefore resolve against the installation. Startup messages identify environment
creation, validation, pip configuration inspection, dependency installation, and server startup.

## Environment setup and validation

The initial interpreter is `python3` on macOS/Linux or `python` on Windows from PATH. The launchers do not select
`.python-version` automatically. The Python version used for development is recorded in `.python-version`.

For a missing installation-local `venv`, the helper exclusively creates the directory and uses the selected
interpreter's standard-library venv module with copied executables. It never reruns environment creation over an
existing directory and does not delete environments. Existing environments are reused. No ownership marker is
required or written; an existing `.wilmer-launcher.json` file is ignored and left unchanged.

The helper requires a regular, unlinked `pyvenv.cfg` with `include-system-site-packages = false` and the platform's
Python executable. It rejects a linked environment root, including Windows junctions and other name-surrogate
reparse points. Other reparse tags are not automatically treated as links. The executable directory and the
`Lib`, `lib`, and `lib64` paths must resolve inside the environment. Internal links such as `lib64 -> lib` are allowed.
Individual package files are not scanned. Hard-linked package files, interpreter aliases, and interpreter or DLL
file symlinks are permitted, including links to the base Python installation.

The helper probes the trusted environment's Python with `-I` and a sixty-second timeout. The interpreter must
report this environment as `sys.prefix`, distinct from `sys.base_prefix`, and have an importable pip module.
Its resolved `purelib`, `platlib`, `scripts`, and `data` installation paths must stay within the environment.
A tagged JSON record allows ordinary startup messages before the probe result. Missing pip and startup failures
produce diagnostics that direct users to manual checks or setup.

These are environment health and destination checks. They do not establish provenance or sandbox Python,
pip, packages, or application code. Python's `-I` ignores PYTHON* settings and the user site directory but still
processes environment site initialization, including `.pth` files and `sitecustomize`. Installation files,
requirements, configured package sources, and the existing interpreter remain trusted inputs. File changes
between validation and installation are not locked out. Pip caches and temporary build files follow normal pip
configuration and may be outside `venv`.

For installation and server subprocesses, the helper prepends the validated interpreter's directory to PATH,
sets VIRTUAL_ENV to the environment directory, and removes PYTHONHOME. Other caller settings remain available.
The caller's own environment is unchanged. Configured subprocess commands therefore resolve against the local
environment first; explicitly configured executable paths retain their meaning. Activation scripts themselves
are not sourced, so custom activation hooks do not run. Existing PATH entries remain available as fallbacks.
Windows executable lookup can also consult locations before PATH; this setting is not a universal command
resolution guarantee.

## Pip configuration and installation

The environment's Python runs `Scripts/install_requirements.py` with `-I` and the absolute requirements path.
The helper uses the public `python -I -m pip config list` command for a conservative conflict check. It neither
imports pip internals nor reconstructs installation options. An explicitly configured non-null `PIP_CONFIG_FILE`
must be a readable regular file. Other configuration discovery and parsing follow the installed pip version.

Automated setup rejects nonempty destination or output settings for `target`, `prefix`, `root`, `python`, `log`,
`report`, and `src` (including `source`, `source-dir`, and `source-directory` aliases). It also rejects an enabled
`user` setting; empty values and false values `0`, `false`, `no`, and `off` are allowed. Conflicts are checked in
PIP_* environment variables and the `global` and `install` configuration sections. Because `config list` is not
an API for fully parsed effective install options, this check also rejects conflicting global settings overridden
by an install-section or environment setting. The error names settings without displaying their values. Remove
the conflicting setting for automated setup or use manual installation for a deliberately different layout.

The inspection subprocess alone receives controls to keep its interpreter selection local, send logging to the
null device, disable version checks, and neutralize scope, isolated, quiet, and verbose settings that could obscure
its output. PIP_PYTHON selects the current executable, and `--log` plus PIP_LOG select the null device. PYTHONHOME
and PYTHONPATH are removed from this inspection environment because pip may re-execute its selected interpreter.
The original environment is checked for conflicts before these inspection controls are supplied. The parser
requires the expected inspection settings in pip's output, ignores unrelated startup messages, and reads string
values using `ast.literal_eval`. Failure or unexpected output stops setup. Captured output is never printed,
because configuration values can contain credentials. Inspection has a sixty-second timeout.

After a successful check, the helper invokes ordinary `python -I -m pip install --disable-pip-version-check -r`
with the absolute requirements path. It inherits the original configuration and environment. Pip retains its
normal precedence and validation for package indexes, offline sources, constraints, binary/source restrictions,
build isolation, build options, caches, proxies, certificates, and retries. Only pip version checking is disabled
for installation. Requirements and pip policies can authorize package downloads and builds as in manual pip use;
these helpers add no separate downloader, runtime installer, telemetry, or remote script execution step.

A failed dependency installation prevents server startup. The server starts through the same environment
interpreter and its exit status is returned through the wrapper. No automatic cleanup runs after setup failure.
An incomplete environment remains in place for manual repair or preservation before replacement. Ignoring a stale
marker does not make virtual environments portable: moved environments can still contain absolute paths and may
need rebuilding using the intended base interpreter.

## Validation and platform limits

See the [launcher testing guidance](Unit_Tests.md#testsscripts) for isolated environment and pip checks.
Native macOS and Windows execution and additional Python/pip versions require platform validation;
Linux fixtures do not replace those checks.

The batch wrapper disables delayed expansion. The shell wrapper locates the helper beside the invoked script;
a standalone symlink to the shell script outside the installation is not supported. Interactive console interrupt
behavior depends on the platform and server. The helper does not manage descendant process groups for supervisors
that terminate only the launcher PID.
