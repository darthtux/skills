#!/usr/bin/env bash
# Create a project-local virtual environment, install the project's
# dependencies with whatever tool the project already uses, then add the
# check tools (ruff, mypy, yamllint).
#
# Usage: setup_env.sh <project_dir>
# Prints the detected manager and the venv path on the last two lines:
#   MANAGER=<uv|poetry|pip>
#   VENV=<absolute path to .venv>

set -euo pipefail

PROJECT_DIR="$(cd "${1:?usage: setup_env.sh <project_dir>}" && pwd)"
VENV="$PROJECT_DIR/.venv"
cd "$PROJECT_DIR"

have() { command -v "$1" >/dev/null 2>&1; }
log()  { printf '>> %s\n' "$*" >&2; }

uses_poetry() {
  [[ -f poetry.lock ]] && return 0
  [[ -f pyproject.toml ]] && grep -qE '^\[tool\.poetry\]' pyproject.toml
}

# --- pick a manager --------------------------------------------------------
if [[ -f uv.lock ]] && have uv; then
  MANAGER=uv
elif uses_poetry && have poetry; then
  MANAGER=poetry
elif uses_poetry; then
  log "Project uses Poetry but poetry isn't installed; installing it with pip --user"
  python3 -m pip install --user --quiet poetry || python3 -m pip install --user --quiet --break-system-packages poetry
  export PATH="$HOME/.local/bin:$PATH"
  MANAGER=poetry
else
  MANAGER=pip
fi
log "Using $MANAGER"

# --- install project dependencies -----------------------------------------
case "$MANAGER" in
  uv)
    # --all-extras + dev groups so type stubs and plugins are present for mypy
    uv sync --all-extras --dev
    ;;
  poetry)
    # Env var rather than `poetry config --local`, so no poetry.toml is written into the project
    export POETRY_VIRTUALENVS_IN_PROJECT=true
    poetry install --no-interaction --all-extras || poetry install --no-interaction
    ;;
  pip)
    if [[ ! -d "$VENV" ]]; then
      if have uv; then uv venv "$VENV" >&2; else python3 -m venv "$VENV"; fi
    fi
    if have uv; then
      PIP_INSTALL=(uv pip install --quiet --python "$VENV/bin/python")
    else
      "$VENV/bin/python" -m pip install --quiet --upgrade pip
      PIP_INSTALL=("$VENV/bin/python" -m pip install --quiet)
    fi

    installed=0
    if [[ -f pyproject.toml || -f setup.py || -f setup.cfg ]]; then
      # Try with common dev extras first, fall back to the bare package
      for spec in ".[dev,test,typing]" ".[dev]" "."; do
        if "${PIP_INSTALL[@]}" -e "$spec" 2>/dev/null; then
          log "Installed project as $spec"; installed=1; break
        fi
      done
      [[ $installed -eq 1 ]] || log "WARNING: could not install the project package itself"
    fi
    for req in requirements.txt requirements-dev.txt requirements_dev.txt dev-requirements.txt requirements/*.txt; do
      [[ -f "$req" ]] || continue
      log "Installing $req"
      # Keep going if one requirements file fails; the checks are still useful
      "${PIP_INSTALL[@]}" -r "$req" || log "WARNING: some packages in $req failed to install"
      installed=1
    done
    [[ $installed -eq 1 ]] || log "No dependency files found; checking with a bare environment"
    ;;
esac

# --- add the check tools ---------------------------------------------------
# Installed into the project venv so mypy sees the project's real packages.
if have uv; then
  uv pip install --quiet --python "$VENV/bin/python" ruff mypy yamllint
else
  "$VENV/bin/python" -m pip install --quiet ruff mypy yamllint
fi

echo "MANAGER=$MANAGER"
echo "VENV=$VENV"
