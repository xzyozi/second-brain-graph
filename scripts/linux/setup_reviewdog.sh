#!/usr/bin/env bash
# Reviewdog Setup Script for Linux / macOS

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${SCRIPT_DIR}/../../tools/bin"

mkdir -p "${BIN_DIR}"

if [ -f "${BIN_DIR}/reviewdog" ]; then
    echo "Reviewdog already exists at ${BIN_DIR}/reviewdog"
    "${BIN_DIR}/reviewdog" -version
    exit 0
fi

echo "=== Installing Reviewdog via official installer ==="
curl -sfL https://raw.githubusercontent.com/reviewdog/reviewdog/master/install.sh | sh -s -- -b "${BIN_DIR}"

echo "✓ Reviewdog installed successfully:"
"${BIN_DIR}/reviewdog" -version
