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

exec shifter --image="$DETOPT_IMAGE" --module=cvmfs /bin/bash -c \
    'source /cvmfs/sw.hsf.org/key4hep/setup.sh -r "$KEY4HEP_RELEASE" >/dev/null && exec "$@"' \
    bash "$@"
