#!/bin/zsh
set -eu
cd -- "${0:A:h}"
uv run --locked --python 3.12 --group build python -m scripts.build_macos
