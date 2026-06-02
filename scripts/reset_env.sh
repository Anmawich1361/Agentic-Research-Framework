#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR=".venv"

venv_exists() {
    [ -e "$VENV_DIR" ] || [ -L "$VENV_DIR" ]
}

deactivate_active_venv() {
    if command -v deactivate >/dev/null 2>&1; then
        deactivate || true
    fi
}

repair_venv_permissions() {
    echo "Clearing macOS flags, extended attributes, and permissions on $VENV_DIR"

    if command -v chflags >/dev/null 2>&1; then
        chflags -R nouchg,noschg,nohidden "$VENV_DIR" 2>/dev/null || true
    fi

    if command -v xattr >/dev/null 2>&1; then
        xattr -cr "$VENV_DIR" 2>/dev/null || true
    fi

    chmod -R u+rwX "$VENV_DIR" 2>/dev/null || true
    find "$VENV_DIR" -name ".DS_Store" -type f -delete 2>/dev/null || true
}

clear_venv_hidden_flags() {
    if ! venv_exists; then
        return
    fi

    if command -v chflags >/dev/null 2>&1; then
        echo "Clearing macOS hidden flags on $VENV_DIR"
        chflags -R nohidden "$VENV_DIR" 2>/dev/null || true
    fi
}

site_packages_dir() {
    for candidate in "$VENV_DIR"/lib/python*/site-packages; do
        if [ -d "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

ensure_editable_import_fallback() {
    if ! venv_exists; then
        return
    fi

    local site_packages=""
    if ! site_packages="$(site_packages_dir)"; then
        return
    fi

    local target="$ROOT_DIR/src/agentic_research"
    local fallback="$site_packages/agentic_research"
    if [ -d "$target" ] && { [ -L "$fallback" ] || [ ! -e "$fallback" ]; }; then
        echo "Creating direct editable import fallback for src/agentic_research"
        ln -sfn "$target" "$fallback"
        if command -v chflags >/dev/null 2>&1; then
            chflags -R nohidden "$fallback" 2>/dev/null || true
        fi
    fi
}

verify_venv_removed() {
    if ! venv_exists; then
        return
    fi

    echo "Unable to remove .venv." >&2
    echo "Close shells, editors, or file-sync processes using .venv, then run 'make reset-env' again." >&2
    echo "Remaining .venv entries:" >&2
    find "$VENV_DIR" -maxdepth 5 -print 2>/dev/null | sed "s/^/  /" >&2 || true
    exit 1
}

remove_venv() {
    if ! venv_exists; then
        return
    fi

    echo "Removing .venv"
    rm -rf "$VENV_DIR" 2>/dev/null || true

    if venv_exists; then
        echo "Initial .venv removal did not complete; retrying after cleanup"
        repair_venv_permissions
        rm -rf "$VENV_DIR" 2>/dev/null || true
    fi

    verify_venv_removed
    echo "Verified .venv was removed"
}

deactivate_active_venv
remove_venv

echo "Creating .venv with python3"
python3 -m venv .venv
clear_venv_hidden_flags

echo "Upgrading pip, setuptools, and wheel"
.venv/bin/python -m pip install --upgrade pip setuptools wheel

echo "Installing agentic-research-framework in editable mode with dev extras"
.venv/bin/python -m pip install -e ".[dev]"
clear_venv_hidden_flags
ensure_editable_import_fallback

echo "Environment reset complete. Run 'make doctor' next."
