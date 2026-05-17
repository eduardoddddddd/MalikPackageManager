# MPM Roadmap

Objetivo final: **paquete AUR instalable con una sola línea** que detecta el host, descarga e instala todas sus dependencias de forma transparente y deja el sistema listo sin intervención manual.

---

## Estado actual — 0.14-mvp ✓

Fork autónomo completo de Malik Store. Operativo en Arch Linux con limitaciones:

- ✅ Backends: flatpak, AUR (con yay/paru)
- ✅ GUI PySide6 funcional
- ✅ CLI `mpm-pkg` con detect / explain / install / uninstall / history / doctor / repair
- ✅ Catálogo curado (9 apps) + búsqueda en 8 fuentes (Flatpak, pacman, AUR, APT, DNF, AppImage, vendor)
- ✅ Bridge Distrobox incluido (`scripts/distrobox/mpm-distrobox-bridge.sh`)
- ⚠️ Backend pacman bloqueado si Snapper no está configurado
- ⚠️ Backends Distrobox requieren contenedores creados manualmente
- ⚠️ `.desktop` asume `konsole` (KDE-only)
- ⚠️ Sin paquete distribuible

---

## 0.15 — Portabilidad de host

**Meta:** MPM funciona correctamente en cualquier Arch Linux sin requisitos implícitos.

### 0.15.1 — Snapper opcional

- Reemplazar el `SystemExit` duro de `ensure_snapper_root_ready` por un flujo de advertencia
- Añadir flag `--no-snapshot` a `mpm-pkg install` y `uninstall`
- Si snapper no está disponible, preguntar al usuario: continuar sin snapshot o cancelar
- Config persistente en `~/.config/mpm/preferences.json`: `"pacman_snapshots": false`

```
mpm-pkg install btop --backend pacman
⚠  Snapper no encontrado. Los cambios no tendrán snapshot de BTRFS.
   Continuar de todas formas? [y/N]
```

### 0.15.2 — Terminal agnóstico

- `mpm-open` detecta el emulador disponible en orden de preferencia:
  `konsole → gnome-terminal → xfce4-terminal → alacritty → xterm`
- `.desktop` cambia a `Terminal=true` eliminando la dependencia explícita de Konsole
- Añadir `X-MPM-RequiresTerminal=true` para que el instalador del paquete lo sepa

### 0.15.3 — Rutas de instalación estándar

- `bin/mpm` y `bin/mpm-pkg` buscan la librería en `/usr/lib/mpm/src` (ya soportado)
- Bridge script instalado en `/usr/lib/mpm/mpm-distrobox-bridge.sh`
- Catálogo y vendor index por defecto en `/usr/share/mpm/`
- Crear `install.sh` standalone para instalación manual sin `make`

---

## 0.16 — Detección inteligente del host

**Meta:** `mpm-pkg setup-host` inspecciona el sistema y configura o guía cada backend.

### 0.16.1 — Comando `setup-host`

Nuevo subcomando de `mpm-pkg` que ejecuta el flujo completo de setup:

```
mpm-pkg setup-host
```

Detecta y reporta:

| Componente | Comando de comprobación | Acción si falta |
|---|---|---|
| Python ≥ 3.11 | `python --version` | Error — MPM no puede funcionar |
| PySide6 | `python -c "import PySide6"` | Instalar via pacman |
| flatpak | `which flatpak` | Instalar + añadir Flathub |
| AUR helper | `which yay \|\| which paru` | Ofrecer instalar yay desde AUR |
| snapper | `which snapper` | Instalar + guiar configuración root |
| distrobox | `which distrobox` | Instalar via pacman |
| Contenedores Distrobox | `distrobox list` | Crear con bootstrap automático |
| `konsole` / terminal | `which konsole` | Detectar alternativa disponible |

### 0.16.2 — Instalación silenciosa de dependencias pacman

Para las dependencias disponibles en los repositorios oficiales, `setup-host` las instala directamente:

```python
PACMAN_DEPS = {
    "flatpak":   ("flatpak", ["sudo", "pacman", "-S", "--noconfirm", "flatpak"]),
    "pyside6":   ("python-pyside6", ["sudo", "pacman", "-S", "--noconfirm", "python-pyside6"]),
    "snapper":   ("snapper", ["sudo", "pacman", "-S", "--noconfirm", "snapper"]),
    "distrobox": ("distrobox", ["sudo", "pacman", "-S", "--noconfirm", "distrobox"]),
}
```

Para snapper, después de instalarlo configura automáticamente el config root:
```bash
sudo snapper -c root create-config /
sudo systemctl enable --now snapper-timeline.timer snapper-cleanup.timer
```

### 0.16.3 — Informe de estado del host

```
mpm-pkg setup-host --check   # solo informa, no modifica nada
```

Salida legible:

```
MPM Host Status
───────────────────────────────────
python        3.14.0      ✓
python-pyside6             ✓
flatpak       1.15.10     ✓  Flathub configurado
yay           12.4.2      ✓
snapper                   ✗  instalar: sudo pacman -S snapper
distrobox     1.8.1       ✓
  mpm-ubuntu-apps         ✗  ejecutar: mpm-pkg setup-host --bootstrap-containers
  mpm-debian-apps         ✗
  mpm-fedora-apps         ✗

Backends disponibles: flatpak, aur
Backends no disponibles: pacman (snapper), distrobox-deb, distrobox-rpm, distrobox-apt, distrobox-dnf
```

---

## 0.17 — Bootstrap automático de contenedores Distrobox

**Meta:** `mpm-pkg setup-host --bootstrap-containers` crea los tres contenedores sin intervención.

### 0.17.1 — Bootstrap desde el bridge

El script `mpm-distrobox-bridge.sh bootstrap` ya existe. Hay que:

- Exponerlo desde `mpm-pkg setup-host --bootstrap-containers`
- Mostrar progreso en tiempo real (stdout streaming del proceso distrobox)
- Manejar el caso de contenedor ya existente (skip silencioso)
- Instalar paquetes base necesarios dentro de cada contenedor:
  - Ubuntu: `apt`, `dpkg`, libasound2t64, libfuse2
  - Fedora: `dnf`, `rpm`, alsa-lib

### 0.17.2 — Contenedores lazy (creación bajo demanda)

En lugar de exigir que los contenedores existan antes de usar el backend, crearlos la primera vez que se necesiten:

```
mpm-pkg install /path/to/app.deb --backend distrobox-deb
→ Contenedor mpm-ubuntu-apps no encontrado.
  Crear ahora? Esto descargará ~500 MB. [y/N]
  [████████████░░░░░░░░] Descargando ubuntu:24.04...
```

---

## 0.18 — PKGBUILD y publicación en AUR

**Meta:** `yay -S mpm` instala MPM completo con todas sus dependencias.

### 0.18.1 — Estructura del PKGBUILD

```bash
# Maintainer: Eduardo <eduardo76@gmail.com>
pkgname=mpm
pkgver=0.18
pkgrel=1
pkgdesc="Malik Package Manager — gestor de apps unificado para Arch Linux"
arch=('any')
url="https://github.com/usuario/MalikPackageManager"
license=('custom')

depends=(
  'python>=3.11'
  'python-pyside6'
)

optdepends=(
  'flatpak: backend Flatpak (Flathub)'
  'yay: backend AUR'
  'paru: backend AUR (alternativa a yay)'
  'snapper: snapshots BTRFS antes de installs con pacman'
  'distrobox: backends DEB/RPM en contenedores'
)

source=("$pkgname-$pkgver.tar.gz::https://github.com/usuario/MalikPackageManager/archive/v$pkgver.tar.gz")

package() {
  install -dm755 "$pkgdir/usr/lib/mpm/src"
  cp -r src/mpm "$pkgdir/usr/lib/mpm/src/"
  install -dm755 "$pkgdir/usr/lib/mpm"
  install -m755 scripts/distrobox/mpm-distrobox-bridge.sh "$pkgdir/usr/lib/mpm/"

  install -dm755 "$pkgdir/usr/bin"
  install -m755 bin/mpm bin/mpm-pkg bin/mpm-open bin/mpm-host-open-url "$pkgdir/usr/bin/"

  install -dm755 "$pkgdir/usr/share/mpm"
  install -m644 configs/mpm/catalog.json configs/mpm/vendor_index.json "$pkgdir/usr/share/mpm/"

  install -dm755 "$pkgdir/usr/share/applications"
  install -m644 configs/desktop/mpm.desktop configs/desktop/mpm-package-installer.desktop \
    "$pkgdir/usr/share/applications/"
}
```

### 0.18.2 — Post-install hook

Script `mpm.install` que se ejecuta tras `pacman -S mpm`:

```bash
post_install() {
  echo "==> MPM instalado. Ejecuta 'mpm-pkg setup-host' para configurar backends."
  echo "    O lanza 'mpm' para abrir la interfaz gráfica."
}
```

### 0.18.3 — Ruta de búsqueda de librería actualizada

`bin/mpm` ya busca en `/usr/lib/mpm/src` — verificar que el PKGBUILD instala exactamente ahí.

---

## 0.19 — Instalador gráfico de primer uso

**Meta:** Al abrir MPM por primera vez, un asistente visual configura el sistema.

- Ventana de bienvenida con lista de backends y su estado (verde/amarillo/rojo)
- Botón "Configurar" por cada backend no disponible
- Progreso en tiempo real de cada paso (pacman install, distrobox create, etc.)
- Posibilidad de omitir backends opcionales
- Al terminar, guardar `~/.config/mpm/setup-complete: true`

---

## 1.0 — Release estable

**Meta:** MPM es un paquete AUR mantenido, estable y usable por cualquier usuario de Arch.

### Requisitos para 1.0

- [ ] `mpm-pkg setup-host` completo y probado
- [ ] Bootstrap de contenedores Distrobox automatizado
- [ ] PKGBUILD publicado en AUR
- [ ] Backend pacman con snapper opcional
- [ ] Terminal agnóstico (`.desktop` sin dependencia de Konsole)
- [ ] Test suite pasando en CI (GitHub Actions)
- [ ] Catálogo ampliado (≥ 25 apps curadas)
- [ ] Documentación de usuario completa (README + man page básica)
- [ ] Vendor index con ≥ 3 rutas de apps de terceros (Cursor, OpenCode, etc.)

---

## Backlog (post-1.0)

| Feature | Descripción |
|---|---|
| Actualizaciones | `mpm-pkg update` — comprueba nuevas versiones por backend |
| Auto-update de catálogo | Fetch periódico de catálogo remoto (JSON firmado) |
| Advisor LLM | Integración real con Ollama para sugerencias de policy |
| Plugin de backends | API pública para añadir backends de terceros |
| GUI de preferencias | Configurar backends, cajas Distrobox, proxy, etc. desde la UI |
| Soporte pacman hooks | `mpm-pkg` como hook de pacman para apps que saltan por encima |
| Firma GPG del catálogo | Verificar integridad del catálogo curado |
