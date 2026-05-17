# MPM Roadmap

Objetivo final: **MPM estable, instalable y honesto operacionalmente**. El host primario sigue siendo Arch Linux, pero los backends portables — Flatpak, AppImage y Distrobox — deben degradar correctamente en otras distros sin romper el sistema ni prometer más aislamiento del que existe.

Este roadmap incorpora las conclusiones de:

- `Claude Analisis.md`
- `impacto en linux.md`
- `revision-codex.md`

---

## Principio rector

MPM no debe vender una ilusión de estado único.

El estado real vive repartido entre:

- `pacman`
- `yay` / `paru`
- `flatpak`
- AppImages copiadas por MPM
- launchers XDG
- paquetes `apt` / `dnf` dentro de Distrobox
- SQLite local de MPM

Por tanto, cada operación debe mostrar:

- qué gestor toca
- dónde toca
- si modifica el host
- si requiere `sudo`
- si hay snapshot
- qué datos elimina y cuáles conserva
- qué estado ha verificado y qué estado solo ha registrado

---

## Estado actual — 0.16 portabilidad de host base

Fork autónomo de Malik Store con CLI, GUI, catálogo y búsqueda federada.

### Ya validado

- ✅ CLI `mpm-pkg`: `host-info`, `detect`, `explain`, `install`, `uninstall`, `history`, `doctor`, `repair-app`, `repair-desktop`, `repair-kde`
- ✅ GUI PySide6 construible con `QT_QPA_PLATFORM=offscreen`
- ✅ Tests locales: `134` tests pasando
- ✅ Catálogo curado: 9 apps
- ✅ Vendor index válido con rutas Cursor AppImage/DEB/RPM
- ✅ Búsqueda federada: curated, vendor, Flatpak, pacman, AUR, APT, DNF
- ✅ `make install` instala el bridge Distrobox en instalación local
- ✅ Config XDG: catálogo y vendor index se buscan en `XDG_CONFIG_HOME`
- ✅ `mpm-open` ya busca `mpm-pkg` por `MPM_PKG_BIN`, `PATH`, `~/.local/bin`, `/usr/bin`
- ✅ Rutas `distrobox-apt` y `distrobox-dnf` marcadas como discovery-only desde GUI
- ✅ AUR requiere revisión por defecto: `paru` no usa `--skipreview` salvo `--aur-skip-review`
- ✅ `yay` ya no auto-responde prompts de clean/diff/edit por defecto
- ✅ `pacman`/AUR tienen preflight host legible con mutación host, sudo, snapshot y advertencias
- ✅ Host install real exige `--yes` tras preflight; GUI lo añade solo tras confirmación
- ✅ Snapper es opcional de forma explícita con `--no-snapshot` o preferencia `pacman_snapshots: false`
- ✅ Operaciones host validan `sudo -n -v` para evitar prompts invisibles en GUI
- ✅ AppImage/vendor verifica `sha256` cuando existe y alerta si falta
- ✅ AppImage genera `Exec=` con quoting XDG e `Icon=` cuando hay dato disponible
- ✅ Instalaciones registran manifiesto interno en SQLite
- ✅ Detección de host basada en `/etc/os-release`, `ID`, `ID_LIKE` y comandos disponibles
- ✅ `mpm-pkg host-info` con salida humana y `--json`
- ✅ `pacman`/AUR se limitan a hosts Arch/Arch-like con comandos disponibles
- ✅ Flatpak/AppImage siguen portables y Distrobox se reporta portable con `podman` + `distrobox`
- ✅ `mpm-open` ya no depende directamente de Konsole y detecta terminal disponible
- ✅ `repair-desktop` refresca integración XDG de forma agnóstica; `repair-kde` queda como alias legacy

### Limitaciones actuales

- ⚠️ `pacman` y `aur` cancelan por defecto sin Snapper root configurado; continuar requiere `--no-snapshot` o preferencia explícita
- ⚠️ Preflight de conflictos/reemplazos/tamaño depende de lo que el gestor pueda reportar sin mutar el host
- ⚠️ `pacman`/AUR aún ejecutan el gestor final con `--noconfirm` después de la confirmación MPM
- ⚠️ AppImage/vendor solo puede verificar artefactos con `sha256` disponible en índice o CLI
- ⚠️ Distrobox no es sandbox de seguridad, solo separa gestores de paquetes
- ⚠️ Desinstalación Distrobox depende demasiado de `app_id`
- ⚠️ `.desktop` del handler de paquetes necesita que exista alguna terminal soportada si el gestor de archivos no provee TTY
- ⚠️ No existe `setup-host`
- ⚠️ Sin paquete distribuible

---

## Lectura de portabilidad

MPM tiene dos niveles:

| Capa | Estado |
|---|---|
| XDG, SQLite, GUI, búsqueda, scoring | Portable |
| Flatpak user | Portable |
| AppImage | Portable con advertencias de librerías e integridad |
| Distrobox DEB/RPM | Portable si `podman` + `distrobox` existen |
| pacman/AUR | Arch-only |
| Snapper | BTRFS/Snapper-only |
| Bootstrap actual | Arch-only si instala dependencias host con `pacman` |

Decisión de producto:

> MPM 1.0 será primero excelente en Arch. En otras distros debe funcionar como gestor complementario para Flatpak, AppImage y Distrobox, no como reemplazo del gestor nativo.

Backends nativos `apt-host`, `dnf-host` o `zypper-host` quedan fuera de 1.0 salvo que el diseño esté ya estabilizado.

---

## 0.15 — Seguridad operacional y honestidad

**Meta:** antes de automatizar más, MPM debe dejar claro qué va a tocar y reducir los riesgos de host.

Estado: ✅ completado en la rama actual.

### 0.15.1 — AUR review required ✅

- Eliminar `--skipreview` por defecto en `paru`
- Eliminar respuestas automáticas peligrosas en `yay`
- Añadir flag avanzado explícito:

```bash
mpm-pkg install paquete-aur --backend aur --aur-skip-review
```

- Mostrar alerta fuerte:
  - AUR es comunitario
  - el PKGBUILD debe revisarse
  - la operación modifica el host

### 0.15.2 — Preflight host real ✅

Antes de `pacman`/AUR:

- listar paquetes que se instalarán
- listar conflictos/reemplazos si el gestor los reporta
- mostrar tamaño/descarga cuando sea posible
- mostrar si se creará snapshot
- exigir confirmación explícita

No basta con `--dry-run` textual: la GUI debe presentar una confirmación legible.

### 0.15.3 — Snapper opcional pero explícito ✅

- Reemplazar fallo duro de `ensure_snapper_root_ready`
- Añadir `--no-snapshot`
- Añadir preferencia persistente:

```json
{
  "pacman_snapshots": true
}
```

- Si no hay Snapper:
  - cancelar por defecto
  - permitir continuar solo con confirmación explícita
  - registrar en historial que no hubo snapshot

### 0.15.4 — Estrategia sudo/terminal ✅

La GUI no debe confiar en `sudo` dentro de `QProcess` para operaciones host.

Opciones aceptables:

- abrir terminal explícito para operaciones con `sudo`
- usar `pkexec`/polkit si se implementa bien
- ejecutar preflight `sudo -v` y fallar con mensaje claro

### 0.15.5 — AppImage/vendor seguro ✅

- Usar `sha256` del vendor index cuando exista
- Si falta `sha256`, mostrar alerta clara antes de instalar
- Corregir `Exec=` en `.desktop` generado con quoting XDG robusto
- Añadir `Icon=` cuando sea posible

### 0.15.6 — Manifiesto post-install ✅

Cada instalación debe producir un manifiesto interno con:

- `backend`
- `manager`
- `target`
- `real_package`
- `app_id`
- `desktop_id`
- `box`
- `version`
- `installed_files` cuando sea razonable

Este manifiesto será la base de uninstall, doctor y reconciliación.

---

## 0.16 — Portabilidad de host base

**Meta:** MPM debe detectar el host, degradar bien y eliminar requisitos implícitos KDE/BTRFS/Arch donde no sean estrictos.

Estado: ✅ completado en la rama actual para detección, degradación de backends, terminal agnóstico e integración desktop. `setup-host` y bootstrap Distrobox multi-distro quedan fuera de esta fase.

### 0.16.1 — Detección de distro ✅

Nuevo módulo de host detection basado en:

- `/etc/os-release`
- `ID`
- `ID_LIKE`
- comandos disponibles: `pacman`, `yay`, `paru`, `flatpak`, `distrobox`, `podman`, `apt`, `dnf`, `zypper`, `snapper`

Resultado esperado:

```text
host-family: arch
native-manager: pacman
portable-backends: flatpak, appimage, distrobox
host-backends: pacman, aur
snapshot: snapper-root-ready
desktop: kde
terminal: konsole
```

### 0.16.2 — Terminal agnóstico ✅

- `mpm-open` detecta terminal disponible:
  `konsole`, `gnome-terminal`, `xfce4-terminal`, `alacritty`, `kitty`, `xterm`
- `.desktop` elimina dependencia directa de Konsole
- Añadir `X-MPM-RequiresTerminal=true`

### 0.16.3 — Integración de escritorio agnóstica ✅

- `repair-desktop` sustituye o envuelve `repair-kde`
- Usar `update-desktop-database` como base
- Ejecutar `kbuildsycoca6/5` solo si existen
- Mostrar warning si no se puede refrescar menú

### 0.16.4 — Rutas estándar

- `/usr/bin/mpm`
- `/usr/bin/mpm-pkg`
- `/usr/bin/mpm-open`
- `/usr/bin/mpm-host-open-url`
- `/usr/lib/mpm/src/mpm/`
- `/usr/lib/mpm/mpm-distrobox-bridge.sh`
- `/usr/share/mpm/catalog.json`
- `/usr/share/mpm/vendor_index.json`

### 0.16.5 — Instalador local manual

Crear `install.sh` para instalación manual sin `make`, respetando:

- `~/.local/bin`
- `~/.local/lib/mpm`
- `~/.config/mpm`
- `.desktop` de usuario

---

## 0.17 — `setup-host` seguro

**Meta:** `mpm-pkg setup-host` informa primero y solo modifica el sistema con confirmación explícita.

### 0.17.1 — `setup-host --check`

Modo read-only obligatorio:

```bash
mpm-pkg setup-host --check
```

Debe reportar:

- distro detectada
- gestor nativo
- Python / PySide6
- Flatpak / Flathub
- AUR helper si host Arch
- Snapper y estado root
- Podman / Distrobox
- contenedores MPM
- terminal disponible
- backends disponibles/no disponibles

### 0.17.2 — `setup-host --plan`

Imprime acciones recomendadas sin ejecutarlas.

Ejemplo:

```text
install flatpak: sudo pacman -S flatpak
add flathub: flatpak remote-add --if-not-exists ...
create box: mpm-ubuntu-apps
```

### 0.17.3 — `setup-host --apply`

Ejecuta solo con confirmación explícita.

Reglas:

- no instalar dependencias host de forma silenciosa
- no usar `--noconfirm` sin preflight
- no configurar Snapper automáticamente sin explicar BTRFS/rollback
- en no-Arch, no intentar instalar con `pacman`

---

## 0.18 — Distrobox robusto

**Meta:** DEB/RPM funcionan bien sin ensuciar Arch y sin fingir sandbox de seguridad.

### 0.18.1 — Bootstrap multi-distro

Separar:

- bootstrap de dependencias host (`podman`, `distrobox`)
- creación de cajas
- instalación de librerías dentro de cajas

Host package manager por distro:

| Host | Dependencias |
|---|---|
| Arch | `pacman` |
| Fedora | `dnf` |
| Ubuntu/Debian | `apt` |
| openSUSE | `zypper` |

### 0.18.2 — Manifiesto desde el bridge

El bridge debe devolver JSON con:

- `box`
- `distro`
- `manager`
- `package`
- `app_id`
- `desktop_id`
- `exported_desktop`
- `repair_actions`

`mpm-pkg` debe guardar ese manifiesto.

### 0.18.3 — Uninstall Distrobox fiable

- No depender solo de `app_id` pasado por CLI
- Usar manifiesto
- Detectar stale records
- Si no puede desinstalar con seguridad, explicar exactamente qué falta

### 0.18.4 — URL bridge reversible

- Documentar que reemplazar `xdg-open` dentro de caja es global
- Añadir reparación y reversión
- Registrar si se aplicó el override

### 0.18.5 — Contenedores lazy

Crear cajas bajo demanda solo tras confirmación:

```text
Contenedor mpm-ubuntu-apps no encontrado.
Crear ahora? Descargará imagen base y compartirá el HOME del usuario. [y/N]
```

---

## 0.19 — Paquete Arch / AUR

**Meta:** `yay -S mpm` instala MPM completo en Arch.

### 0.19.1 — PKGBUILD

- `depends`: Python, PySide6
- `optdepends`: Flatpak, AUR helper, Snapper, Distrobox, Podman
- instalar binarios en `/usr/bin`
- instalar librería en `/usr/lib/mpm`
- instalar datos en `/usr/share/mpm`
- instalar `.desktop`

### 0.19.2 — Hook post-install

Mensaje, no configuración agresiva:

```bash
post_install() {
  echo "MPM instalado."
  echo "Ejecuta 'mpm-pkg setup-host --check' para ver backends disponibles."
}
```

### 0.19.3 — CI de empaquetado

- `make test`
- `make validate`
- `bin/mpm --self-test` con Qt offscreen
- validar JSON catálogo/vendor
- `shellcheck` si está disponible
- construcción de paquete Arch en entorno limpio

---

## 0.20 — Asistente gráfico de primer uso

**Meta:** la GUI ayuda a configurar sin ocultar riesgos.

- estado visual de backends
- botones por backend
- explicación de riesgo por ruta
- terminal/polkit para acciones con privilegios
- posibilidad de omitir backends
- guardar `~/.config/mpm/preferences.json`

No debe crear Snapper, instalar AUR ni crear contenedores sin confirmación explícita.

---

## 1.0 — Release estable

**Meta:** MPM es estable, probado, instalable y honesto sobre el sistema que toca.

### Requisitos para 1.0

- [x] AUR review required por defecto
- [x] Preflight host para pacman/AUR
- [x] Snapper opcional con política persistente
- [x] Estrategia sudo/terminal resuelta
- [x] AppImage/vendor con SHA256 o warning bloqueante/confirmable
- [x] Manifiestos post-install
- [ ] Distrobox DEB/RPM con uninstall fiable
- [ ] `setup-host --check/--plan/--apply`
- [ ] Bootstrap Distrobox multi-distro
- [x] `.desktop` sin dependencia de Konsole
- [ ] PKGBUILD publicado en AUR
- [ ] CI pasando
- [ ] Catálogo ampliado a 25 apps curadas
- [ ] Vendor index con al menos 3 apps de terceros reales
- [ ] Documentación de usuario completa

---

## Backlog post-1.0

| Feature | Descripción |
|---|---|
| Backends host no-Arch | `apt-host`, `dnf-host`, `zypper-host` |
| Actualizaciones | `mpm-pkg update` por backend |
| Auto-update de catálogo | Fetch periódico de catálogo remoto firmado |
| Advisor LLM | Integración real con Ollama u otro provider |
| Plugin de backends | API pública para backends de terceros |
| GUI de preferencias | Backends, cajas, proxy, riesgo, políticas |
| Soporte pacman hooks | Detectar apps instaladas fuera de MPM |
| Firma GPG del catálogo | Integridad del catálogo curado |
