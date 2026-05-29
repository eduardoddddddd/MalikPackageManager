#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PREFIX="${PREFIX:-"$HOME/.local"}"
BINDIR="${BINDIR:-"$PREFIX/bin"}"
LIBDIR="${LIBDIR:-"$PREFIX/lib/mpm"}"
SHAREDIR="${SHAREDIR:-"$PREFIX/share/mpm"}"
CFGDIR="${CFGDIR:-"${XDG_CONFIG_HOME:-"$HOME/.config"}/mpm"}"
APPDIR="${APPDIR:-"$PREFIX/share/applications"}"
WITH_VENV="${MPM_WITH_VENV:-0}"
VENV_DIR="${MPM_VENV_DIR:-"$LIBDIR/venv"}"
LIB_BINDIR="$LIBDIR/bin"

install -d "$BINDIR" "$LIBDIR/src" "$SHAREDIR" "$CFGDIR" "$APPDIR" "$LIB_BINDIR"

if [ "$WITH_VENV" = "1" ]; then
  python -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip
  "$VENV_DIR/bin/python" -m pip install PySide6
  install -m 755 "$ROOT_DIR/bin/mpm" "$LIB_BINDIR/mpm"
  install -m 755 "$ROOT_DIR/bin/mpm-pkg" "$LIB_BINDIR/mpm-pkg"
  cat > "$BINDIR/mpm" <<EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/python" "$LIB_BINDIR/mpm" "\$@"
EOF
  cat > "$BINDIR/mpm-pkg" <<EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/python" "$LIB_BINDIR/mpm-pkg" "\$@"
EOF
  chmod 755 "$BINDIR/mpm"
  chmod 755 "$BINDIR/mpm-pkg"
else
  install -m 755 "$ROOT_DIR/bin/mpm" "$BINDIR/mpm"
  install -m 755 "$ROOT_DIR/bin/mpm-pkg" "$BINDIR/mpm-pkg"
fi
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

sed "s|^Exec=mpm\$|Exec=$BINDIR/mpm|" "$ROOT_DIR/configs/desktop/mpm.desktop" > "$APPDIR/mpm.desktop"
sed "s|^Exec=mpm-open %f\$|Exec=$BINDIR/mpm-open %f|" "$ROOT_DIR/configs/desktop/mpm-package-installer.desktop" > "$APPDIR/mpm-package-installer.desktop"
chmod 644 "$APPDIR/mpm.desktop" "$APPDIR/mpm-package-installer.desktop"

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

if [ "$WITH_VENV" = "1" ]; then
  printf '  venv:    %s\n' "$VENV_DIR"
fi
