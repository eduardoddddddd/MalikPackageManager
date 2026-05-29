# MPM User Guide

Guia practica para instalar, preparar y reparar Malik Package Manager 1.0.

## Instalacion local

MPM se puede usar desde el repo sin paquete del sistema:

```bash
git clone https://github.com/usuario/MalikPackageManager
cd MalikPackageManager
make install
```

Alternativa equivalente:

```bash
./install.sh
```

La instalacion local copia binarios, modulo Python, datos XDG y lanzadores de escritorio en `~/.local` y `~/.config/mpm`. Asegurate de tener `~/.local/bin` en `PATH`:

```bash
command -v mpm
command -v mpm-pkg
```

Si PySide6 no esta instalado, la GUI no arrancara. El CLI sigue siendo util para diagnostico:

```bash
mpm-pkg host-info
mpm-pkg setup-host --check
```

En hosts donde no quieras usar `sudo` para instalar PySide6, puedes crear una instalacion local con venv:

```bash
MPM_WITH_VENV=1 ./install.sh
```

## Primer setup del host

Empieza siempre con modos read-only:

```bash
mpm-pkg setup-host --check
mpm-pkg setup-host --plan
```

Para scripts o GUI:

```bash
mpm-pkg setup-host --check --json
mpm-pkg setup-host --plan --json
```

`setup-host --apply --yes` solo ejecuta acciones conservadoras que no instalan dependencias del host con `sudo`: Flathub user remote y contenedores Distrobox que falten cuando `podman` y `distrobox` ya existen. Si faltan paquetes host como `flatpak`, `podman`, `distrobox`, `python-pyside6` o `snapper`, MPM muestra el comando recomendado y lo deja como accion manual.

## Backends

| Backend | Uso recomendado | Riesgo principal |
|---|---|---|
| `flatpak` | Apps graficas portables desde Flathub | Permisos Flatpak y portales XDG |
| `appimage` | Artefactos directos del vendor | Sin `sha256`, no hay verificacion fuerte |
| `distrobox-deb` | `.deb` de vendor dentro de Ubuntu Distrobox | Distrobox separa gestores, no aisla la app |
| `distrobox-rpm` | `.rpm` de vendor dentro de Fedora Distrobox | Export desktop y uninstall dependen del manifiesto |
| `pacman` | Paquetes host Arch | Modifica el host; requiere preflight, `--yes` y politica Snapper |
| `aur` | Paquetes comunitarios Arch | Requiere revisar PKGBUILD; modifica host |
| `distrobox-apt` | Descubrimiento APT en caja Ubuntu | Busqueda solamente |
| `distrobox-dnf` | Descubrimiento DNF en caja Fedora | Busqueda solamente |

MPM bloquea `pacman` y AUR en hosts no Arch/Arch-like. Flatpak, AppImage y Distrobox son las rutas portables.

## Instalar con CLI

Explica primero:

```bash
mpm-pkg explain org.mozilla.firefox --backend flatpak
mpm-pkg explain btop --backend pacman
mpm-pkg explain https://example.com/app.AppImage --backend appimage
```

Instala despues:

```bash
mpm-pkg install org.mozilla.firefox --backend flatpak
mpm-pkg install btop --backend pacman --yes
mpm-pkg install paquete-aur --backend aur
mpm-pkg install /ruta/app.AppImage --backend appimage --sha256 HASH
mpm-pkg install /ruta/vendor.deb --backend distrobox-deb
mpm-pkg install /ruta/vendor.rpm --backend distrobox-rpm
```

Usa `--dry-run` cuando quieras ver comandos sin ejecutar:

```bash
mpm-pkg install btop --backend pacman --dry-run
```

## Riesgos y politica de seguridad

MPM intenta ser explicito, no magico:

- `pacman` y AUR modifican el host. Sin Snapper root configurado, cancelan por defecto salvo `--no-snapshot` o preferencia explicita.
- AUR es comunitario. Revisa el PKGBUILD; `--aur-skip-review` es un override avanzado.
- AppImage/vendor debe tener `sha256` para verificacion fuerte. Si no existe, MPM debe avisar y registrar el riesgo.
- Distrobox mantiene DEB/RPM fuera de pacman, pero no es sandbox fuerte. Las apps pueden compartir HOME, sesion grafica, D-Bus, audio y secretos del usuario segun configuracion.
- El vendor index empaquetado contiene rutas oficiales razonables, pero no sustituye la verificacion criptografica cuando el proveedor no publica hashes.

## Catalogo y vendor index

El catalogo curado esta en:

```text
configs/mpm/catalog.json
~/.config/mpm/catalog.json
~/.local/share/mpm/catalog.json
/usr/share/mpm/catalog.json
```

El vendor index esta en:

```text
configs/mpm/vendor_index.json
~/.config/mpm/vendor_index.json
~/.local/share/mpm/vendor_index.json
/usr/share/mpm/vendor_index.json
```

Puedes forzar rutas con:

```bash
MPM_CATALOG=/ruta/catalog.json mpm
MPM_VENDOR_INDEX=/ruta/vendor_index.json mpm
```

No inventes `sha256`. Si no tienes hash oficial, deja el campo vacio y acepta el warning esperado.

## Uninstall

Lista registros:

```bash
mpm-pkg list-installed
```

Desinstala por record ID:

```bash
mpm-pkg uninstall 3
mpm-pkg uninstall 3 --dry-run
```

MPM conserva config y datos locales por defecto. Para quitar la instalacion local:

```bash
make uninstall
```

Despues puedes borrar manualmente, si de verdad quieres limpiar todo:

```bash
rm -rf ~/.config/mpm
rm -rf ~/.local/share/mpm
```

## Doctor y repair

Diagnostica una app o launcher:

```bash
mpm-pkg doctor org.mozilla.firefox
mpm-pkg doctor /ruta/app.AppImage
```

Repara un launcher registrado:

```bash
mpm-pkg repair-app org.mozilla.firefox
```

Repara integracion desktop:

```bash
mpm-pkg repair-desktop
```

`repair-kde` existe como alias legacy. En escritorios no KDE, `repair-desktop` intenta refrescar XDG y solo ejecuta herramientas KDE si estan disponibles.

## Troubleshooting

### `mpm` no abre

Comprueba PySide6 y el binario:

```bash
python -c "import PySide6"
MPM_PKG_BIN="$PWD/bin/mpm-pkg" QT_QPA_PLATFORM=offscreen bin/mpm --self-test
```

### Flatpak no encuentra apps

Comprueba Flathub:

```bash
flatpak remotes
flatpak remote-add --if-not-exists --user flathub https://flathub.org/repo/flathub.flatpakrepo
```

### Pacman/AUR se cancela por Snapper

Es esperado si no hay Snapper root listo. Decide explicitamente:

```bash
mpm-pkg install btop --backend pacman --yes --no-snapshot
```

### Distrobox no instala DEB/RPM

Revisa plan y cajas:

```bash
mpm-pkg setup-host --check
distrobox list
```

Cajas esperadas:

```text
mpm-ubuntu-apps
mpm-debian-apps
mpm-fedora-apps
```

### AppImage no arranca

Verifica permisos y FUSE:

```bash
chmod +x ~/.local/share/mpm/appimages/*.AppImage
mpm-pkg doctor /ruta/app.AppImage
```

En algunas distros hace falta `libfuse2` o compatibilidad equivalente.

### Handler de `.deb` o `.rpm` no abre terminal

Ejecuta:

```bash
mpm-pkg repair-desktop
```

Y comprueba que tienes una terminal soportada o define:

```bash
export MPM_TERMINAL=konsole
```
