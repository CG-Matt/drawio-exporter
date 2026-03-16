#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE=""

print_help() {
  cat <<'USAGE'
Usage:
  ./setup.sh [--mode venv|global]

Options:
  --mode <venv|global>  Choose installation mode.
                        If omitted, script prompts interactively when possible.
  -h, --help            Show this help.

Modes:
  venv    Create/use .venv and install playwright + chromium there.
  global  Install playwright for global python (user site) and create
          .venv/bin/python shim so existing script shebangs still work.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      if [[ -z "$MODE" ]]; then
        echo "Missing value for --mode" >&2
        exit 1
      fi
      shift 2
      ;;
    -h|--help)
      print_help
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      print_help >&2
      exit 1
      ;;
  esac
done

if [[ -z "$MODE" ]]; then
  if [[ -t 0 ]]; then
    echo "Select setup mode:"
    echo "  1) venv (recommended)"
    echo "  2) global"
    read -r -p "Enter choice [1/2]: " choice

    case "$choice" in
      1|"") MODE="venv" ;;
      2) MODE="global" ;;
      *)
        echo "Invalid choice: $choice" >&2
        exit 1
        ;;
    esac
  else
    MODE="venv"
  fi
fi

case "$MODE" in
  venv)
    echo "[setup] Creating/updating .venv"
    python3 -m venv "$ROOT_DIR/.venv"

    echo "[setup] Installing Playwright into .venv"
    "$ROOT_DIR/.venv/bin/python" -m pip install --upgrade pip
    "$ROOT_DIR/.venv/bin/python" -m pip install playwright
    "$ROOT_DIR/.venv/bin/python" -m playwright install chromium
    ;;

  global)
    echo "[setup] Installing Playwright into global python (user site)"
    python3 -m pip install --user --upgrade pip
    python3 -m pip install --user playwright
    python3 -m playwright install chromium

    echo "[setup] Creating .venv python shim for relative shebang compatibility"
    mkdir -p "$ROOT_DIR/.venv/bin"

    cat > "$ROOT_DIR/.venv/bin/python" <<'SHIM'
#!/usr/bin/env bash
exec python3 "$@"
SHIM

    cat > "$ROOT_DIR/.venv/bin/python3" <<'SHIM'
#!/usr/bin/env bash
exec python3 "$@"
SHIM

    chmod +x "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/.venv/bin/python3"
    ;;

  *)
    echo "Invalid mode: $MODE (expected venv or global)" >&2
    exit 1
    ;;
esac

echo "[setup] Done"
