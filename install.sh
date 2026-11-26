#!/bin/bash
# Set this checkout up so typing `synth-rack` in any terminal starts the app.
# Safe to run again at any time (after a pull, or to repair the link).
set -e
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin="${1:-$HOME/.local/bin}"                  # optional argument: a different folder on PATH
py="$root/.venv/bin/python"

if [ ! -x "$py" ]; then
    echo "Creating $root/.venv ..."
    if command -v uv >/dev/null; then
        uv venv --python 3.12 "$root/.venv" -q
    else
        python3 -m venv "$root/.venv"
    fi
fi
echo "Installing Python packages ..."
if command -v uv >/dev/null; then
    uv pip install -q --python "$py" -r "$root/requirements.txt"
else
    "$py" -m pip install -q -r "$root/requirements.txt"
fi

mkdir -p "$bin"
ln -sf "$root/bin/synth-rack" "$bin/synth-rack"
echo "Linked $bin/synth-rack -> $root/bin/synth-rack"

case ":$PATH:" in
    *":$bin:"*) echo "Done. Type: synth-rack" ;;
    *) echo "Done, but $bin is not on your PATH. Add this line to ~/.zshrc and open a new terminal:"
       echo "    export PATH=\"$bin:\$PATH\"" ;;
esac
