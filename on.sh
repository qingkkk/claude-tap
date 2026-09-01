#!/usr/bin/env bash
exec python3 "$(dirname "$0")/toggle.py" on "${1:-$PWD}"
