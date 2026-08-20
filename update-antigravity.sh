#!/usr/bin/env bash

set -Eeuo pipefail

INSTALL_DIR="${ANTIGRAVITY_INSTALL_DIR:-/opt/antigravity-ide}"
DOWNLOAD_PAGE="https://antigravity.google/download"
BACKUP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/antigravity-backups"

case "$(uname -m)" in
  x86_64|amd64) DOWNLOAD_ARCH="x64" ;;
  aarch64|arm64) DOWNLOAD_ARCH="arm" ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

for command_name in curl tar rsync; do
  command -v "$command_name" >/dev/null || {
    echo "Required command not found: $command_name" >&2
    exit 1
  }
done

if [[ ! -d "$INSTALL_DIR" || ! -w "$INSTALL_DIR" ]]; then
  echo "Install directory is missing or not writable: $INSTALL_DIR" >&2
  echo "Run this script as the owner of that directory (or with sudo)." >&2
  exit 1
fi

work_dir="$(mktemp -d /tmp/antigravity-update.XXXXXX)"
cleanup() { rm -rf -- "$work_dir"; }
trap cleanup EXIT

echo "Finding the latest official Antigravity IDE release..."
download_url="$({ curl --compressed -fsSL "$DOWNLOAD_PAGE" || exit; } \
  | grep -Eo 'https://[^" ]+/stable/[^" ]+/linux-(x64|arm)/Antigravity%20IDE\.tar\.gz' \
  | grep "/linux-${DOWNLOAD_ARCH}/" \
  | head -n 1)"

if [[ -z "$download_url" ]]; then
  echo "Could not find the Linux download on $DOWNLOAD_PAGE" >&2
  exit 1
fi

release_version="$(sed -E 's#^.*/stable/([^/-]+)-[^/]+/.*#\1#' <<<"$download_url")"
current_version="$(sed -nE 's/^[[:space:]]*"ideVersion":[[:space:]]*"([^"]+)".*/\1/p' \
  "$INSTALL_DIR/resources/app/product.json" 2>/dev/null | head -n 1 || true)"

echo "Installed version: ${current_version:-unknown}"
echo "Latest version:    $release_version"
if [[ "$current_version" == "$release_version" ]]; then
  echo "Antigravity IDE is already up to date."
  exit 0
fi

echo "Downloading Antigravity IDE $release_version..."
curl -fL --retry 3 --progress-bar "$download_url" -o "$work_dir/antigravity-ide.tar.gz"
tar -tzf "$work_dir/antigravity-ide.tar.gz" >/dev/null
mkdir "$work_dir/extracted"
tar -xzf "$work_dir/antigravity-ide.tar.gz" -C "$work_dir/extracted"

source_dir="$work_dir/extracted/Antigravity IDE"
staged_version="$(sed -nE 's/^[[:space:]]*"ideVersion":[[:space:]]*"([^"]+)".*/\1/p' \
  "$source_dir/resources/app/product.json" | head -n 1)"
if [[ "$staged_version" != "$release_version" ]]; then
  echo "Downloaded version mismatch: expected $release_version, found $staged_version" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
backup_path="$BACKUP_DIR/antigravity-ide-${current_version:-unknown}-$(date +%Y%m%d-%H%M%S).tar.gz"
echo "Backing up the existing installation to $backup_path..."
tar -czf "$backup_path" -C "$(dirname "$INSTALL_DIR")" "$(basename "$INSTALL_DIR")"

echo "Closing the running Antigravity IDE..."
pkill -TERM -f "$INSTALL_DIR/(antigravity|antigravity-ide)" 2>/dev/null || true
for _ in {1..20}; do
  pgrep -f "$INSTALL_DIR/(antigravity|antigravity-ide)" >/dev/null || break
  sleep 0.25
done

# Preserve the root-owned setuid sandbox; replacing it requires sudo and the
# sandbox shipped in the archive is otherwise identical in purpose.
sandbox_backup="$work_dir/chrome-sandbox"
if [[ -e "$INSTALL_DIR/chrome-sandbox" ]]; then
  mv "$INSTALL_DIR/chrome-sandbox" "$sandbox_backup"
fi

rsync -a --delete "$source_dir/" "$INSTALL_DIR/"
if [[ -e "$sandbox_backup" ]]; then
  rm -f "$INSTALL_DIR/chrome-sandbox"
  mv "$sandbox_backup" "$INSTALL_DIR/chrome-sandbox"
fi

installed_version="$(sed -nE 's/^[[:space:]]*"ideVersion":[[:space:]]*"([^"]+)".*/\1/p' \
  "$INSTALL_DIR/resources/app/product.json" | head -n 1)"
[[ "$installed_version" == "$release_version" ]] || {
  echo "Installation verification failed." >&2
  exit 1
}

echo "Antigravity IDE was updated successfully to $installed_version."
echo "Start it normally from your application launcher."
