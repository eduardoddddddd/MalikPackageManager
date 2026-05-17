# MPM — Malik Package Manager

Versión **0.17-dev setup-host seguro** · Host primario Arch Linux · Python 3 + PySide6

Gestor de aplicaciones unificado para Arch Linux. Instala y gestiona apps a través de múltiples backends — Flatpak, pacman, AUR, AppImage y paquetes DEB/RPM en contenedores Distrobox — bajo una política consistente y con registro completo de historial.

**Objetivo de desarrollo:** MPM estable, instalable y honesto operacionalmente. El paquete AUR sigue siendo un objetivo, pero antes se priorizan preflight, seguridad AUR, Snapper opcional, terminal/sudo fiable, manifiestos post-install y Distrobox robusto. Ver [docs/roadmap.md](docs/roadmap.md).

---

## Arquitectura

MPM tiene dos componentes que trabajan juntos:

| Componente | Binario | Rol |
|---|---|---|
| Frontend GUI | `mpm` | Ventana PySide6 — búsqueda, instalación, desinstalación, reparación |
| Backend CLI | `mpm-pkg` | Instalador headless + estado SQLite; usable de forma independiente |

La GUI delega todas las operaciones de paquetes a `mpm-pkg`. Ambos son utilizables por separado.

---

## Principio de seguridad

MPM no reemplaza el estado real de los gestores existentes. Actúa como orquestador y registro, pero el estado vive en `pacman`, AUR helper, Flatpak, AppImages, launchers XDG, contenedores Distrobox y SQLite local.

Cada backend debe ser honesto sobre:

- qué gestor toca
- si modifica el host
- si requiere `sudo`
- si hay snapshot
- qué datos elimina y cuáles conserva
- qué estado ha verificado y qué estado solo ha registrado

Distrobox mantiene DEB/RPM fuera del gestor Arch, pero **no es un sandbox de seguridad fuerte**: las apps pueden compartir HOME, sesión gráfica y D-Bus según la configuración de Distrobox.

---

## Backends

| Backend | Qué instala | Requiere |
|---|---|---|
| `flatpak` | Flatpak de usuario (Flathub) | `flatpak` |
| `pacman` | Paquetes del host Arch | `pacman` + preflight host |
| `aur` | Paquetes AUR vía `yay`/`paru` | helper AUR |
| `appimage` | Bundles AppImage de vendor | checksum recomendado |
| `distrobox-deb` | Archivos `.deb` en contenedor Ubuntu | `distrobox` + caja `mpm-ubuntu-apps` |
| `distrobox-rpm` | Archivos `.rpm` en contenedor Fedora | `distrobox` + caja `mpm-fedora-apps` |
| `distrobox-apt` | Búsqueda APT en contenedor Ubuntu | `discovery-only` |
| `distrobox-dnf` | Búsqueda DNF en contenedor Fedora | `discovery-only` |

> `pacman`/AUR hacen preflight host, exigen confirmación explícita con `--yes` para instalar de verdad y crean snapshot Snapper si está disponible. Sin Snapper, MPM cancela por defecto; continuar requiere `--no-snapshot` o preferencia explícita `pacman_snapshots: false`.

> AUR sigue siendo comunitario. MPM no usa `paru --skipreview` por defecto ni auto-responde prompts peligrosos de `yay`; `--aur-skip-review` es un override avanzado explícito.

> En hosts no-Arch, `pacman` y AUR se bloquean con un mensaje claro. Flatpak, AppImage y Distrobox siguen siendo rutas portables; Distrobox se considera disponible si existen `podman` y `distrobox`.

---

## Estado actual de portabilidad

| Componente | Estado actual |
|---|---|
| `flatpak` backend | ✅ Operativo con `flatpak` instalado |
| `aur` backend | ✅ Operativo con `yay` o `paru` |
| GUI búsqueda y exploración | ✅ Validado con PySide6 en venv y Qt offscreen |
| Catálogo/vendor index | ✅ JSON validado; vendor index incluye rutas Cursor |
| `pacman` backend | ✅ Preflight host, confirmación `--yes`, Snapper explícito |
| `distrobox-deb/rpm` | ⚠️ Requiere contenedores creados; se endurece en 0.18 |
| `distrobox-apt/dnf` | ⚠️ Búsqueda solamente; instalación no implementada |
| Integración `.desktop` | ✅ Handler externo sin dependencia directa de Konsole; `mpm-open` elige terminal disponible |
| Host no-Arch | ✅ Flatpak/AppImage/Distrobox degradan como portables; pacman/AUR son Arch-only con error claro |

---

## Estructura del proyecto

```
MalikPackageManager/
├── bin/
│   ├── mpm                      # Punto de entrada GUI (Python)
│   ├── mpm-pkg                  # Backend CLI (Python, ~1760 líneas)
│   ├── mpm-open                 # Abrir .deb/.rpm desde el gestor de archivos
│   └── mpm-host-open-url        # Abrir URLs/archivos en el host (bridge Distrobox)
├── src/mpm/
│   ├── __init__.py
│   ├── main.py                  # GUI PySide6 (MPMWindow)
│   ├── catalog.py               # Cargador y validador de catálogo
│   ├── catalog_providers.py     # 8 proveedores de búsqueda
│   ├── search.py                # Modelos de datos y motor de scoring
│   ├── workflow.py              # Helpers de confirmación de UI
│   └── advisor.py               # Advisor de política local (LLM opcional)
├── scripts/
│   └── distrobox/
│       └── mpm-distrobox-bridge.sh  # Bridge para operaciones en contenedores
├── configs/
│   ├── mpm/
│   │   ├── catalog.json         # Catálogo curado (9 apps)
│   │   └── vendor_index.json    # Rutas vendor/AppImage
│   └── desktop/
│       ├── mpm.desktop
│       └── mpm-package-installer.desktop
├── tests/
│   ├── fixtures/                # JSON fixtures para tests de providers
│   ├── test_advisor.py
│   ├── test_catalog.py
│   ├── test_catalog_providers.py
│   ├── test_mpm_pkg_cli.py
│   ├── test_search.py
│   ├── test_syntax.py
│   └── test_workflow.py
├── docs/
│   └── roadmap.md               # Hoja de ruta hasta 1.0
└── Makefile
```

---

## Requisitos

**Obligatorios:**
- Python ≥ 3.11
- `python-pyside6` — para la GUI

**Por backend (opcionales):**
- `flatpak` — backend Flatpak; añadir Flathub: `flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo`
- `yay` o `paru` — backend AUR
- `snapper` con config root — snapshots BTRFS automáticos para `pacman`/AUR; se puede desactivar explícitamente
- `distrobox` — backends DEB/RPM/APT/DNF

**Contenedores Distrobox** (opcionales, bootstrap robusto en 0.18):
- `mpm-ubuntu-apps` — Ubuntu LTS para .deb y APT
- `mpm-debian-apps` — Debian estable
- `mpm-fedora-apps` — Fedora para .rpm y DNF

---

## Instalación

### Desde el repositorio (método actual)

```bash
git clone https://github.com/usuario/MalikPackageManager
cd MalikPackageManager
make install
```

Instalación equivalente sin `make`:

```bash
./install.sh
```

Instala en `~/.local/`:

```
~/.local/bin/mpm
~/.local/bin/mpm-pkg
~/.local/bin/mpm-open
~/.local/bin/mpm-host-open-url
~/.local/lib/mpm/src/mpm/
~/.local/lib/mpm/mpm-distrobox-bridge.sh
~/.local/share/mpm/catalog.json
~/.local/share/mpm/vendor_index.json
~/.local/share/applications/mpm.desktop
~/.local/share/applications/mpm-package-installer.desktop
~/.config/mpm/catalog.json         (solo si no existe)
~/.config/mpm/vendor_index.json    (solo si no existe)
```

`~/.local/bin` debe estar en `PATH`.

### Desinstalar

```bash
make uninstall
```

Config (`~/.config/mpm/`) y datos (`~/.local/share/mpm/`) se conservan.

### Desde AUR (objetivo 0.19)

```bash
yay -S mpm
```

---

## Uso

### GUI

```bash
mpm
```

Lanza la ventana MPM. Usa la barra de búsqueda para encontrar apps en todas las fuentes. Pulsa **Instalar** para delegar en `mpm-pkg`.

### CLI

```bash
# Detectar tipo de target
mpm-pkg detect org.mozilla.firefox
mpm-pkg detect /ruta/app.AppImage
mpm-pkg detect https://vendor.example/app.deb

# Explicar qué hará MPM antes de instalar
mpm-pkg explain org.mozilla.firefox --backend flatpak
mpm-pkg explain btop --backend pacman

# Instalar
mpm-pkg install org.mozilla.firefox --backend flatpak
mpm-pkg install btop --backend pacman --dry-run
mpm-pkg install btop --backend pacman --yes
mpm-pkg install /ruta/vendor.deb --backend distrobox-deb
mpm-pkg install paquete-aur --backend aur --aur-skip-review --dry-run

# Dry run (muestra comandos, no ejecuta)
mpm-pkg install btop --backend pacman --dry-run
mpm-pkg install https://vendor.example/app.deb --backend distrobox-deb --dry-run

# Overrides avanzados de seguridad host/vendor
mpm-pkg install paquete --backend pacman --yes --no-snapshot
mpm-pkg install /ruta/app.AppImage --backend appimage --sha256 HASH --icon app

# Listar apps instaladas
mpm-pkg list-installed

# Desinstalar por record ID
mpm-pkg uninstall 3
mpm-pkg uninstall 3 --dry-run

# Historial completo (JSON lines)
mpm-pkg history

# Detectar capacidades del host
mpm-pkg host-info
mpm-pkg host-info --json

# Diagnosticar un launcher roto
mpm-pkg doctor org.mozilla.firefox
mpm-pkg doctor /ruta/app.AppImage

# Reparar un launcher
mpm-pkg repair-app org.mozilla.firefox

# Refrescar integración desktop/menú
mpm-pkg repair-desktop

# Alias legacy compatible
mpm-pkg repair-kde
```

### Abrir paquete desde el gestor de archivos

```bash
mpm-open /ruta/paquete.deb
```

El archivo `mpm-package-installer.desktop` registra MPM como handler de `.deb` y `.rpm`. `mpm-open` detecta `konsole`, `gnome-terminal`, `xfce4-terminal`, `alacritty`, `kitty` o `xterm` cuando necesita abrir una terminal para explicar e instalar a través de la política MPM.

---

## Catálogo

El catálogo curado vive en `configs/mpm/catalog.json`. Tras `make install-config` se copia a `~/.config/mpm/catalog.json` donde puede editarse libremente.

Cada entrada especifica un backend preferido:

```json
{
  "name": "Firefox",
  "target": "org.mozilla.firefox",
  "backend": "flatpak",
  "source": "Flathub",
  "summary": "Navegador web instalado como Flatpak de usuario.",
  "tags": ["browser", "web", "flatpak", "tested"]
}
```

Apps curadas por defecto: Firefox, VLC, OBS Studio, Krita, GIMP, Inkscape, LibreOffice, Blender, btop.

### Vendor / AppImage index

`configs/mpm/vendor_index.json` define rutas para apps que distribuyen su propio instalador. El índice empaquetado incluye Cursor con rutas AppImage, DEB y RPM.

Cada ruta puede incluir:

- URL del artefacto
- backend recomendado
- caja Distrobox
- `app_id`
- `sha256`
- política de actualización
- política de desinstalación

Si una ruta vendor no tiene `sha256`, MPM avisa antes de descargar o instalar. La verificación estricta depende de que el índice o la CLI aporten el hash.

---

## Fuentes de búsqueda

La GUI busca en 8 proveedores en paralelo:

| Proveedor | Fuente |
|---|---|
| `CuratedProvider` | `catalog.json` local |
| `FlatpakProvider` | Salida de `flatpak search` |
| `PacmanProvider` | Salida de `pacman -Ss` |
| `AURProvider` | AUR JSON RPC (`aur.archlinux.org`) |
| `AptProvider` | APT dentro del contenedor `mpm-ubuntu-apps` |
| `DnfProvider` | DNF dentro del contenedor `mpm-fedora-apps` |
| `AppImageProvider` | Rutas AppImage del vendor index |
| `VendorDebProvider` | Rutas DEB del vendor index |

Los resultados se puntúan y deduplicican — la misma app en varias fuentes se fusiona en una entrada con una lista de rutas ordenada por prioridad.

---

## Rutas de datos y configuración

Todos los datos respetan `XDG_DATA_HOME` (por defecto `~/.local/share`):

| Ruta | Contenido |
|---|---|
| `~/.local/share/mpm/mpm-pkg/installed.sqlite` | Registros de install / uninstall / repair |
| `~/.local/share/mpm/appimages/` | AppImages descargados |
| `~/.local/share/mpm/logs/` | Logs de operación de la GUI |

La configuración respeta `XDG_CONFIG_HOME` (por defecto `~/.config`):

| Ruta | Contenido |
|---|---|
| `~/.config/mpm/catalog.json` | Catálogo curado editable por el usuario |
| `~/.config/mpm/vendor_index.json` | Rutas vendor editables por el usuario |

---

## Variables de entorno

### GUI (`mpm`)

| Variable | Por defecto | Descripción |
|---|---|---|
| `MPM_PKG_BIN` | `~/.local/bin/mpm-pkg` | Ruta al binario `mpm-pkg` |
| `MPM_CATALOG` | ruta XDG config | Override de ubicación del catálogo |
| `MPM_VENDOR_INDEX` | ruta XDG config | Override del vendor index |
| `MPM_LLM_PROVIDER` | _(no definido)_ | Provider LLM para el advisor (`ollama`, etc.) |

### CLI (`mpm-pkg`)

| Variable | Por defecto | Descripción |
|---|---|---|
| `MPM_UBUNTU_BOX` | `mpm-ubuntu-apps` | Contenedor Distrobox para DEB/APT |
| `MPM_DEBIAN_BOX` | `mpm-debian-apps` | Contenedor Distrobox para Debian DEB |
| `MPM_FEDORA_BOX` | `mpm-fedora-apps` | Contenedor Distrobox para RPM/DNF |
| `MPM_DISTROBOX_BRIDGE` | _(auto-detectado)_ | Ruta al script bridge de Distrobox |

---

## Desarrollo

```bash
# Crear entorno de pruebas local
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install PySide6

# Ejecutar suite de tests
PATH="$PWD/.venv/bin:$PATH" make test

# Smoke-test de los binarios
PATH="$PWD/.venv/bin:$PATH" make validate

# Self-test real de GUI sin pantalla
QT_QPA_PLATFORM=offscreen \
PATH="$PWD/.venv/bin:$PATH" \
MPM_PKG_BIN="$PWD/bin/mpm-pkg" \
bin/mpm --self-test
```

Los tests usan `unittest`. La suite valida detección de host, JSON de catálogo/vendor, CLI, workflow, providers, búsqueda, advisor local y compilación de módulos.

---

## Contenedores Distrobox

Los backends DEB y RPM requieren contenedores Distrobox. Primero revisa el plan seguro del host:

```bash
# No modifica el sistema
mpm-pkg setup-host --check
mpm-pkg setup-host --plan

# Cuando podman/distrobox ya existen, crea los tres contenedores
# (descarga ~500 MB en total)
scripts/distrobox/mpm-distrobox-bridge.sh bootstrap
```

Nombres esperados (sobreescribibles vía variables de entorno):

```
mpm-ubuntu-apps   # Ubuntu LTS — para .deb y apt
mpm-debian-apps   # Debian estable
mpm-fedora-apps   # Fedora — para .rpm y dnf
```

`bootstrap` ya no instala paquetes del host. Si faltan `podman` o `distrobox`, se detiene y debes seguir el plan explícito de `setup-host`.

---

## Hacia un paquete instalable

El objetivo a medio plazo es que MPM sea distribuible como paquete AUR, pero el roadmap fue reordenado para no publicar antes de resolver los riesgos principales.

Orden nuevo:

1. `0.15`: seguridad operacional y honestidad. ✓
2. `0.16`: portabilidad de host base. ✓
3. `0.17`: `setup-host --check/--plan/--apply`.
4. `0.18`: Distrobox robusto.
5. `0.19`: PKGBUILD/AUR.
6. `0.20`: asistente gráfico de primer uso.

### Comprobaciones que debe hacer el instalador

Al ejecutar `mpm-pkg setup-host --check` (objetivo 0.17), el sistema comprueba:

| Componente | Comprobación | Acción si falta |
|---|---|---|
| Distro host | `/etc/os-release` | Clasificar Arch/no-Arch |
| Python ≥ 3.11 | `python --version` | Error — MPM no puede funcionar |
| PySide6 | `python -c "import PySide6"` | Recomendar paquete según distro |
| flatpak | `which flatpak` | Recomendar instalación + Flathub |
| Helper AUR | `which yay \|\| which paru` | Solo en Arch; revisar PKGBUILD |
| snapper | `which snapper` + config root | Avisar; snapshot opcional explícito |
| distrobox/podman | `which distrobox`, `which podman` | Recomendar instalación según distro |
| Contenedores | `distrobox list` | Plan de creación, no silencioso |
| Terminal | detección agnóstica | Elegir terminal disponible |

### Rutas de instalación del paquete AUR

```
/usr/bin/mpm
/usr/bin/mpm-pkg
/usr/bin/mpm-open
/usr/bin/mpm-host-open-url
/usr/lib/mpm/src/mpm/            ← módulos Python
/usr/lib/mpm/mpm-distrobox-bridge.sh
/usr/share/mpm/catalog.json
/usr/share/mpm/vendor_index.json
/usr/share/applications/mpm.desktop
/usr/share/applications/mpm-package-installer.desktop
```

### PKGBUILD (borrador para 0.19)

```bash
pkgname=mpm
pkgver=0.19
pkgrel=1
pkgdesc="Gestor de apps unificado para Arch Linux"
arch=('any')
depends=('python>=3.11' 'python-pyside6')
optdepends=(
  'flatpak: backend Flatpak (Flathub)'
  'yay: backend AUR'
  'snapper: snapshots BTRFS antes de installs con pacman'
  'distrobox: backends DEB/RPM en contenedores'
)
```

Ver la hoja de ruta completa en [docs/roadmap.md](docs/roadmap.md).

---

## Hoja de ruta

| Versión | Meta principal |
|---|---|
| **0.14-mvp + hardening** ✓ | Base funcional, tests, GUI offscreen, vendor index válido |
| **0.15** ✓ | Seguridad operacional: AUR review, preflight host, Snapper opcional, sudo/terminal, AppImage seguro, manifiestos |
| **0.16** ✓ | Portabilidad base: distro detection, terminal/escritorio agnóstico, degradación no-Arch |
| **0.17** | `setup-host --check/--plan/--apply` seguro |
| **0.18** | Distrobox robusto: bootstrap multi-distro, manifiestos, uninstall fiable |
| **0.19** | PKGBUILD + publicación AUR |
| **0.20** | Asistente gráfico de primer uso |
| **1.0** | Release estable — honesta, probada, instalable y documentada |

---

## Licencia

Proyecto personal. Sin licencia para redistribución.
