# MPM — Malik Package Manager

Versión **0.14-mvp** · Arch Linux · Python 3 + PySide6

Gestor de aplicaciones unificado para Arch Linux. Instala y gestiona apps a través de múltiples backends — Flatpak, pacman, AUR, AppImage y paquetes DEB/RPM en contenedores Distrobox — bajo una política consistente y con registro completo de historial.

**Objetivo de desarrollo:** paquete AUR instalable con una sola línea que detecta el host, descarga e instala todas sus dependencias de forma transparente. Ver [docs/roadmap.md](docs/roadmap.md).

---

## Arquitectura

MPM tiene dos componentes que trabajan juntos:

| Componente | Binario | Rol |
|---|---|---|
| Frontend GUI | `mpm` | Ventana PySide6 — búsqueda, instalación, desinstalación, reparación |
| Backend CLI | `mpm-pkg` | Instalador headless + estado SQLite; usable de forma independiente |

La GUI delega todas las operaciones de paquetes a `mpm-pkg`. Ambos son utilizables por separado.

---

## Backends

| Backend | Qué instala | Requiere |
|---|---|---|
| `flatpak` | Flatpak de usuario (Flathub) | `flatpak` |
| `pacman` | Paquetes del host Arch | `pacman` + `snapper`* |
| `aur` | Paquetes AUR vía `yay`/`paru` | helper AUR |
| `appimage` | Bundles AppImage de vendor | — |
| `distrobox-deb` | Archivos `.deb` en contenedor Ubuntu | `distrobox` + caja `mpm-ubuntu-apps` |
| `distrobox-rpm` | Archivos `.rpm` en contenedor Fedora | `distrobox` + caja `mpm-fedora-apps` |
| `distrobox-apt` | Nombres de paquetes APT en contenedor Ubuntu | `distrobox` + caja `mpm-ubuntu-apps` |
| `distrobox-dnf` | Nombres de paquetes DNF en contenedor Fedora | `distrobox` + caja `mpm-fedora-apps` |

> \* El backend `pacman` crea un snapshot BTRFS automático antes de cada operación. Requiere Snapper con config root (`/etc/snapper/configs/root`). En la versión 0.15 esto será opcional.

---

## Estado actual de portabilidad

| Componente | Estado en Arch genérico |
|---|---|
| `flatpak` backend | ✅ Operativo con `flatpak` instalado |
| `aur` backend | ✅ Operativo con `yay` o `paru` |
| GUI búsqueda y exploración | ✅ Operativo con `python-pyside6` |
| `pacman` backend | ⚠️ Bloqueado sin Snapper configurado (se resuelve en 0.15) |
| `distrobox-*` backends | ⚠️ Requiere contenedores creados; se automatizan en 0.17 |
| Integración `.desktop` | ⚠️ Asume `konsole`; se hace agnóstico en 0.15 |

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
- `snapper` con config root — backend pacman (snapshots BTRFS automáticos)
- `distrobox` — backends DEB/RPM/APT/DNF

**Contenedores Distrobox** (opcionales, bootstrap automático en 0.17):
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

Instala en `~/.local/`:

```
~/.local/bin/mpm
~/.local/bin/mpm-pkg
~/.local/bin/mpm-open
~/.local/bin/mpm-host-open-url
~/.local/lib/mpm/src/mpm/
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

### Desde AUR (objetivo 0.18)

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
mpm-pkg install btop --backend pacman
mpm-pkg install /ruta/vendor.deb --backend distrobox-deb

# Dry run (muestra comandos, no ejecuta)
mpm-pkg install btop --backend pacman --dry-run

# Listar apps instaladas
mpm-pkg list-installed

# Desinstalar por record ID
mpm-pkg uninstall 3
mpm-pkg uninstall 3 --dry-run

# Historial completo (JSON lines)
mpm-pkg history

# Diagnosticar un launcher roto
mpm-pkg doctor org.mozilla.firefox
mpm-pkg doctor /ruta/app.AppImage

# Reparar un launcher
mpm-pkg repair-app org.mozilla.firefox

# Refrescar integración KDE desktop/menú
mpm-pkg repair-kde
```

### Abrir paquete desde el gestor de archivos

```bash
mpm-open /ruta/paquete.deb
```

El archivo `mpm-package-installer.desktop` registra MPM como handler de `.deb` y `.rpm` — hacer doble clic en Dolphin (o cualquier gestor de archivos con soporte XDG) abre un terminal que explica e instala a través de la política MPM.

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

`configs/mpm/vendor_index.json` define rutas para apps que distribuyen su propio instalador (Cursor, OpenCode, etc.). Cada ruta mapea la app a una URL de AppImage, un DEB en el contenedor Ubuntu, o un RPM en el contenedor Fedora.

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
# Ejecutar suite de tests
make test

# Smoke-test de los binarios (sin entorno completo)
make validate
```

Los tests usan `unittest` sin mocking del estado SQLite — los tests de CLI crean bases de datos reales en directorios temporales vía overrides de `XDG_DATA_HOME`.

---

## Contenedores Distrobox

Los backends DEB y RPM requieren contenedores Distrobox. El script `scripts/distrobox/mpm-distrobox-bridge.sh` los crea y gestiona:

```bash
# Bootstrap de los tres contenedores (descarga ~500 MB en total)
scripts/distrobox/mpm-distrobox-bridge.sh bootstrap
```

Nombres esperados (sobreescribibles vía variables de entorno):

```
mpm-ubuntu-apps   # Ubuntu LTS — para .deb y apt
mpm-debian-apps   # Debian estable
mpm-fedora-apps   # Fedora — para .rpm y dnf
```

En la versión 0.17 esto se automatizará vía `mpm-pkg setup-host --bootstrap-containers`.

---

## Hacia un paquete instalable

El objetivo a medio plazo es que MPM sea distribuible como paquete AUR. El trabajo necesario:

### Comprobaciones que debe hacer el instalador

Al ejecutar `mpm-pkg setup-host` (disponible en 0.16), el sistema comprueba:

| Componente | Comprobación | Acción si falta |
|---|---|---|
| Python ≥ 3.11 | `python --version` | Error — MPM no puede funcionar |
| PySide6 | `python -c "import PySide6"` | Instalar via `pacman -S python-pyside6` |
| flatpak | `which flatpak` | Instalar + añadir Flathub |
| Helper AUR | `which yay \|\| which paru` | Ofrecer instalar `yay` |
| snapper | `which snapper` + config root | Instalar + configurar |
| distrobox | `which distrobox` | Instalar via `pacman -S distrobox` |
| Contenedores | `distrobox list` | Bootstrap automático |
| Terminal | `which konsole` | Detectar alternativa disponible |

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

### PKGBUILD (borrador para 0.18)

```bash
pkgname=mpm
pkgver=0.18
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
| **0.14-mvp** ✓ | Fork autónomo funcional, flatpak + AUR operativos |
| **0.15** | Portabilidad: snapper opcional, terminal agnóstico, rutas estándar |
| **0.16** | `mpm-pkg setup-host` — detección e instalación automática de dependencias |
| **0.17** | Bootstrap automático de contenedores Distrobox |
| **0.18** | PKGBUILD + publicación en AUR |
| **0.19** | Asistente gráfico de primer uso |
| **1.0** | Release estable — instalable, probado, documentado |

---

## Licencia

Proyecto personal. Sin licencia para redistribución.
