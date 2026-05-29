# Maintainer: Eduardo Arias Bravo
pkgname=malik-package-manager
pkgver=1.0.0
pkgrel=1
pkgdesc="Unified app manager for Arch Linux with Flatpak, pacman, AUR, AppImage and Distrobox backends"
arch=('any')
url="https://github.com/eduardoddddddd/MalikPackageManager"
license=('custom')
depends=(
  'python>=3.11'
  'pyside6'
  'flatpak'
)
makedepends=('git')
optdepends=(
  'yay: AUR backend helper'
  'paru: AUR backend helper'
  'snapper: optional Btrfs snapshots before pacman/AUR installs'
  'podman: container runtime for Distrobox DEB/RPM backends'
  'distrobox: DEB/RPM/APT/DNF backends in containers'
)
provides=('mpm')
conflicts=('mpm')
source=("$pkgname::git+$url.git")
sha256sums=('SKIP')

pkgver() {
  cd "$srcdir/$pkgname"
  python - <<'PY'
from pathlib import Path
import re

text = Path("src/mpm/__init__.py").read_text(encoding="utf-8")
match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
version = match.group(1) if match else "0.0.0"
print(version.replace("-", "_"))
PY
}

check() {
  cd "$srcdir/$pkgname"
  make test
  make validate-json
  make lint-shell
}

package() {
  cd "$srcdir/$pkgname"
  make DESTDIR="$pkgdir" PREFIX=/usr install-bin install-system-data install-desktop
}
