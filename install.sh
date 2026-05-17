#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PREFIX="${PREFIX:-"$HOME/.local"}"
BINDIR="${BINDIR:-"$PREFIX/bin"}"
LIBDIR="${LIBDIR:-"$PREFIX/lib/mpm"}"
SHAREDIR="${SHAREDIR:-"$PREFIX/share/mpm"}"
CFGDIR="${CFGDIR:-"${XDG_CONFIG_HOME:-"$HOME/.config"}/mpm"}"
APPDIR="${APPDIR:-"$PREFIX/share/applications"}"

install -d "$BINDIR" "$LIBDIR/src" "$SHAREDIR" "$CFGDIR" "$APPDIR"

install -m 755 "$ROOT_DIR/bin/mpm" "$BINDIR/mpm"
install -m 755 "$ROOT_DIR/bin/mpm-pkg" "$BINDIR/mpm-pkg"
install -m 755 "$ROOT_DIR/bin/mpm-open" "$BINDIR/mpm-open"
install -m 755 "$ROOT_DIR/bin/mpm-host-open-url" "$BINDIR/mpm-host-open-url"

rm -rf "$LIBDIR/src/mpm"
cp -R "$ROOT_DIR/src/mpm" "$LIBDIR/src/mpm"
install -m 755 "$ROOT_DIR/scripts/distrobox/mpm-distrobox-bridge.sh" "$LIBDIR/mpm-distrobox-bridge.sh"

install -m 644 "$ROOT_DIR/configs/mpm/catalog.json" "$SHAREDIR/catalog.json"
install -m 644 "$ROOT_DIR/configs/mpm/vendor_index.json" "$SHAREDIR/vendor_index.json"

if [ ! -e "$CFGDIR/catalog.json" ]; then
  install -m 644 "$ROOT_DIR/configs/mpm/catalog.json" "$CFGDIR/catalog.json"
fi

if [ ! -e "$CFGDIR/vendor_index.json" ]; then
  install -m 644 "$ROOT_DIR/configs/mpm/vendor_index.json" "$CFGDIR/vendor_index.json"
fi

install -m 644 "$ROOT_DIR/configs/desktop/mpm.desktop" "$APPDIR/mpm.desktop"
install -m 644 "$ROOT_DIR/configs/desktop/mpm-package-installer.desktop" "$APPDIR/mpm-package-installer.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPDIR" 2>/dev/null || true
fi

cat <<EOF
MPM installed.
  bin:     $BINDIR
  lib:     $LIBDIR
  data:    $SHAREDIR
  config:  $CFGDIR
  desktop: $APPDIR
EOF
