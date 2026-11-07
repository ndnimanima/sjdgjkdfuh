#!/bin/sh
set -eu

DATA_DIR="${DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"
chown -R rozaneh:rozaneh "$DATA_DIR"

exec gosu rozaneh "$@"
