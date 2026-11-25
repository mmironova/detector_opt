#!/bin/bash
# Run a command inside the Key4hep container: ./run.sh <command> [args...]
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/setup.sh"

if [ "$KEY4HEP_RELEASE" = "SET-ME" ]; then
    echo "Pin KEY4HEP_RELEASE in setup.sh first." >&2
    exit 1
fi

export PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}"

# Key4hep's setup.sh reports errors (e.g. an unknown release) on stdout, so keep
# its output quiet on success but show it if sourcing fails.
exec shifter --image="$DETOPT_IMAGE" --module=cvmfs /bin/bash -c '
    log=$(mktemp)
    if ! source /cvmfs/sw.hsf.org/key4hep/setup.sh -r "$KEY4HEP_RELEASE" >"$log" 2>&1; then
        echo "Key4hep setup failed for release $KEY4HEP_RELEASE:" >&2
        cat "$log" >&2; rm -f "$log"; exit 1
    fi
    rm -f "$log"
    exec "$@"' bash "$@"
