#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Context Builder"
APP_ID="context-builder"
REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_USER="${SUDO_USER:-$(id -un)}"
TARGET_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
[[ -n "$TARGET_HOME" ]] || TARGET_HOME="$HOME"
MAIN_FILE="$REPO_DIR/main.py"
LOGO_FILE="$REPO_DIR/context_builder/logo.svg"
FALLBACK_LOGO_FILE="$REPO_DIR/src/context_builder/logo.svg"
BIN_DIR="$TARGET_HOME/.local/bin"
XDG_DATA_DIR="$TARGET_HOME/.local/share"
APPLICATIONS_DIR="$XDG_DATA_DIR/applications"
ICON_THEME_DIR="$XDG_DATA_DIR/icons/hicolor"
ICON_DIR="$ICON_THEME_DIR/256x256/apps"
WRAPPER_PATH="$BIN_DIR/$APP_ID"
DESKTOP_PATH="$APPLICATIONS_DIR/$APP_ID.desktop"
INSTALLED_ICON_PATH="$ICON_DIR/$APP_ID.svg"
DESKTOP_SHORTCUT_PATH=""

fail() {
    echo "Error: $*" >&2
    exit 1
}

require_file() {
    local path="$1"
    local description="$2"
    [[ -f "$path" ]] || fail "Could not find $description at $path"
}

require_command() {
    local command_name="$1"
    command -v "$command_name" >/dev/null 2>&1 || fail "Required command not found: $command_name"
}

find_desktop_dir() {
    if command -v xdg-user-dir >/dev/null 2>&1; then
        xdg-user-dir DESKTOP 2>/dev/null || true
        return
    fi

    if [[ -n "${XDG_DESKTOP_DIR:-}" ]]; then
        printf '%s\n' "$XDG_DESKTOP_DIR"
        return
    fi

    printf '%s\n' "$TARGET_HOME/Desktop"
}

write_desktop_entry() {
    local target_path="$1"

    cat > "$target_path" <<SH_DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=$APP_NAME
GenericName=Context Bundle Builder
Comment=Build repository-aware context bundles for LLMs
Exec="$WRAPPER_PATH" %F
Path=$REPO_DIR
Icon=$APP_ID
Terminal=false
Categories=Development;Utility;
Keywords=context;builder;llm;ai;repository;
StartupNotify=true
StartupWMClass=$APP_ID
NoDisplay=false
SH_DESKTOP
    chmod +x "$target_path"
}

refresh_desktop_integration() {
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
        echo "Updated desktop database."
    fi

    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f "$ICON_THEME_DIR" >/dev/null 2>&1 || true
        echo "Updated icon cache."
    fi

    if command -v xdg-desktop-menu >/dev/null 2>&1; then
        xdg-desktop-menu forceupdate --mode user >/dev/null 2>&1 || true
        echo "Refreshed desktop menu."
    fi

    if command -v gio >/dev/null 2>&1 && [[ -n "$DESKTOP_SHORTCUT_PATH" ]]; then
        gio set "$DESKTOP_SHORTCUT_PATH" metadata::trusted true >/dev/null 2>&1 || true
    fi
}

if [[ ! -f "$LOGO_FILE" && -f "$FALLBACK_LOGO_FILE" ]]; then
    LOGO_FILE="$FALLBACK_LOGO_FILE"
fi

require_file "$MAIN_FILE" "Context Builder entrypoint"
require_file "$LOGO_FILE" "Context Builder logo"
require_command python3

mkdir -p "$BIN_DIR" "$APPLICATIONS_DIR" "$ICON_DIR"
cp "$LOGO_FILE" "$INSTALLED_ICON_PATH"

printf -v QUOTED_REPO_DIR '%q' "$REPO_DIR"

cat > "$WRAPPER_PATH" <<SH_WRAPPER
#!/usr/bin/env bash
set -euo pipefail

APP_DIR=$QUOTED_REPO_DIR
cd "\$APP_DIR"

if command -v uv >/dev/null 2>&1; then
    exec uv run python main.py "\$@"
fi

exec python3 main.py "\$@"
SH_WRAPPER
chmod +x "$WRAPPER_PATH"

write_desktop_entry "$DESKTOP_PATH"

DESKTOP_DIR="$(find_desktop_dir)"
if [[ -n "$DESKTOP_DIR" && -d "$DESKTOP_DIR" ]]; then
    DESKTOP_SHORTCUT_PATH="$DESKTOP_DIR/$APP_NAME.desktop"
    write_desktop_entry "$DESKTOP_SHORTCUT_PATH"
fi

refresh_desktop_integration

echo "$APP_NAME installed."
echo "Application launcher: $DESKTOP_PATH"
echo "Desktop shortcut: ${DESKTOP_SHORTCUT_PATH:-not created because no Desktop folder was found}"
echo "Command: $WRAPPER_PATH"
echo "Icon name: $APP_ID ($INSTALLED_ICON_PATH)"
echo "The launcher points to this source checkout, so edits to main.py and prompt_builder/ are picked up on next launch."
