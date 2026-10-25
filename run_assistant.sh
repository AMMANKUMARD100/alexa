#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
exec python3 app.py "$@"
