#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: bash scripts/generate_ifu_yuh.sh <année> [--transactions-folder <dossier>] [--cache <fichier_fx>] [-s|-f|-ff]" >&2
    echo "  ex:  bash scripts/generate_ifu_yuh.sh 2024" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT"
python src/yuh_csv_ifu.py "$@"
