#!/bin/bash

launcher_directory="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 1
exec python3 -I "$launcher_directory/Scripts/launch.py" run_eventlet.py "$@"
