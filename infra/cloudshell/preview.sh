#!/usr/bin/env bash
# Cloud Shell: run Rabbit with demo Garmin data on port 8080 for a UI walkthrough
# (Web Preview > Preview on port 8080). Nothing touches the VM or real accounts.
set -euo pipefail
cd "$(dirname "$0")/../.."
command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }
command -v bun >/dev/null || { curl -fsSL https://bun.sh/install | bash; export PATH="$HOME/.bun/bin:$PATH"; }
exec scripts/dev-rabbit.sh cloudshell
