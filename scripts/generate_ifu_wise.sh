#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: bash scripts/generate_ifu_wise.sh <année> [--transactions-folder <dossier>] [--cache <fichier_fx>] [-s|-f|-ff]" >&2
    echo "  ex:  bash scripts/generate_ifu_wise.sh 2024" >&2
    echo "  ex:  bash scripts/generate_ifu_wise.sh 2024 --transactions-folder transactions -s" >&2
    exit 1
fi

YEAR="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT"
python src/wise_csv_ifu.py "$@"
