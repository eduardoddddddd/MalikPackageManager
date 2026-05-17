# Revision Codex

Fecha: 2026-05-17

## Estado observado

MPM esta documentado como version `0.14-mvp`, con objetivo final de convertirse en un paquete AUR instalable con una sola linea y con configuracion automatica del host.

El proyecto contiene:

- CLI backend `mpm-pkg`.
- GUI `mpm` basada en PySide6.
- Catalogo curado en `configs/mpm/catalog.json`.
- Vendor index en `configs/mpm/vendor_index.json`.
- Bridge Distrobox en `scripts/distrobox/mpm-distrobox-bridge.sh`.
- Roadmap en `docs/roadmap.md`.
- Suite de tests en `tests/`.

No se detecto repositorio Git inicializado en `/home/edu/Developer/MalikPackageManager`, por lo que no hay rama ni estado de cambios disponible mediante `git status`.

## Validaciones ejecutadas

`make test`:

- Resultado: OK.
- Tests ejecutados: 100.

`make validate`:

- Resultado: OK.
- `bin/mpm --version`: `mpm 0.14-mvp`.
- `bin/mpm-pkg --version`: `mpm-pkg 0.14-mvp`.
- Self-tests de catalogo, preflight de uninstall e historial pasaron.

`bin/mpm-pkg`:

- El CLI responde correctamente.
- Comandos disponibles: `detect`, `explain`, `install`, `list-installed`, `list-uninstalls`, `history`, `uninstall`, `doctor`, `repair-app`, `repair-kde`.
- Un dry-run de pacman genera el plan esperado con snapshot Snapper y comando pacman.

## Problema critico encontrado

La GUI no arranca actualmente.

Comando probado:

```bash
bin/mpm
```

Error:

```text
SyntaxError: expected '('
```

Origen:

- `src/mpm/main.py`

Hay identificadores Python con guion, que son invalidos sintacticamente:

- `find_mpm-pkg`
- `self.mpm-pkg_path`
- `self.run_mpm-pkg`

Esto contradice el roadmap, que marca la GUI PySide6 como funcional en `0.14-mvp`.

## Limitaciones confirmadas

El roadmap describe correctamente varias limitaciones actuales:

- Backend `pacman` bloqueado si Snapper no esta instalado o no existe `/etc/snapper/configs/root`.
- Backend `aur` tambien crea snapshot host antes de instalar.
- Backends Distrobox requieren contenedores creados manualmente por ahora.
- `configs/desktop/mpm-package-installer.desktop` depende explicitamente de `konsole`.
- No existe todavia `mpm-pkg setup-host`.
- No hay todavia PKGBUILD ni paquete AUR distribuible.

## Lectura del roadmap

El orden previsto es coherente:

1. `0.15`: portabilidad de host.
   - Snapper opcional.
   - Terminal agnostico.
   - Rutas estandar.
   - `install.sh` standalone.

2. `0.16`: deteccion inteligente del host.
   - Nuevo comando `mpm-pkg setup-host`.
   - Modo `setup-host --check`.
   - Instalacion o guia de dependencias.

3. `0.17`: bootstrap automatico de contenedores Distrobox.

4. `0.18`: PKGBUILD y publicacion AUR.

5. `0.19`: instalador grafico de primer uso.

6. `1.0`: release estable con CI, documentacion, catalogo ampliado y vendor index mas completo.

## Recomendacion inmediata

Antes de avanzar con `0.15`, conviene crear una mini-version `0.14.1` o tarea previa:

- Reparar `src/mpm/main.py` sustituyendo identificadores con guion por nombres validos, por ejemplo:
  - `find_mpm_pkg`
  - `self.mpm_pkg_path`
  - `self.run_mpm_pkg`
- Verificar que `bin/mpm` arranca o, al menos, que importa correctamente.
- Añadir una prueba de compilacion/import para la GUI, de forma que `make test` falle si vuelve a aparecer un SyntaxError en `src/mpm/main.py`.

Despues de eso, el siguiente bloque natural es implementar `0.15.1` Snapper opcional.

## Avance aplicado para cerrar 0.14

Se corrigio el bloqueo de sintaxis detectado en `src/mpm/main.py`:

- `find_mpm-pkg` paso a `find_mpm_pkg`.
- `self.mpm-pkg_path` paso a `self.mpm_pkg_path`.
- `self.run_mpm-pkg` paso a `self.run_mpm_pkg`.

Tambien se ajusto la busqueda del binario backend para aceptar la variable documentada `MPM_PKG_BIN`, conservando compatibilidad con `MPM_MPM_PKG`.

Se anadio `tests/test_syntax.py` para compilar:

- `bin/mpm`
- `bin/mpm-pkg`
- todos los modulos `src/mpm/*.py`

Esto evita que `make test` vuelva a pasar con errores de sintaxis en la GUI.

Validaciones tras el primer cambio:

- `python -m unittest tests.test_syntax`: OK.
- `make test`: OK, 112 tests.
- `make validate`: OK.

Nota: el entorno actual no tiene `PySide6`, por lo que no se pudo ejecutar `bin/mpm --self-test` con ventana Qt. La compilacion de `src/mpm/main.py` si pasa correctamente. En Arch, la dependencia esperada es `python-pyside6`.

## Cierre adicional de 0.14 tras revision de subagentes

Se incorporaron hallazgos criticos detectados por revision read-only:

### Config instalada localmente

Problema: `make install-config` copia catalogo y vendor index a `~/.config/mpm`, pero el codigo no miraba `XDG_CONFIG_HOME`.

Cambios:

- `src/mpm/catalog.py` busca tambien `XDG_CONFIG_HOME/mpm/catalog.json`.
- `src/mpm/catalog_providers.py` busca tambien `XDG_CONFIG_HOME/mpm/vendor_index.json`.
- Tests nuevos cubren ambos casos.

### Bridge Distrobox en instalacion local

Problema: `make install` copiaba modulos Python pero no instalaba `mpm-distrobox-bridge.sh`, aunque `mpm-pkg` instalado lo espera en `~/.local/lib/mpm/mpm-distrobox-bridge.sh`.

Cambio:

- `Makefile` instala `scripts/distrobox/mpm-distrobox-bridge.sh` en `$(LIBDIR)/mpm-distrobox-bridge.sh`.

### `mpm-open` y rutas de binario

Problema: `mpm-open` buscaba por defecto solo `~/.local/bin/mpm-pkg`, fragil para paquete del sistema.

Cambio:

- `bin/mpm-open` usa `MPM_PKG_BIN` si existe, despues `command -v mpm-pkg`, despues `~/.local/bin/mpm-pkg`, y finalmente `/usr/bin/mpm-pkg`.

### Dry-run de URLs vendor

Problema: `mpm-pkg install URL.deb --dry-run` imprimia `curl`, pero despues fallaba porque el archivo no existia realmente.

Cambio:

- `bin/mpm-pkg` ya no exige existencia del archivo descargado cuando `--dry-run` esta activo.
- Test nuevo cubre URL `.deb` con `distrobox-deb --dry-run`.

### Rutas APT/DNF discovery-only

Problema: la GUI podia ofrecer instalar rutas `distrobox-apt`/`distrobox-dnf`, pero el CLI aun no implementa esos backends.

Cambio:

- `src/mpm/main.py` bloquea instalacion directa desde seleccion de catalogo para `distrobox-apt` y `distrobox-dnf`, mostrando que son rutas solo de descubrimiento en 0.14.

### Cierre de conexiones SQLite

Problema: `make test` emitia `ResourceWarning` por conexiones SQLite sin cerrar.

Cambios:

- `bin/mpm-pkg` cierra conexiones en registros, listados, historial y resolucion de registros.
- Helpers de `tests/test_mpm_pkg_cli.py` cierran conexiones explicitas.

## Validacion final de 0.14

- `make test`: OK, 115 tests.
- `make validate`: OK.
- `bash -n bin/mpm-open scripts/distrobox/mpm-distrobox-bridge.sh`: OK.
- `python -m py_compile` sobre binarios/modulos tocados: OK.
- `bin/mpm-pkg install https://vendor.example/cool.deb --backend distrobox-deb --dry-run`: OK, imprime plan sin exigir archivo real.

Limitacion restante: el entorno actual no tiene `PySide6`, por lo que no se puede ejecutar `bin/mpm --self-test` con ventana Qt aqui. La compilacion de `src/mpm/main.py` si pasa. En Arch, la dependencia esperada sigue siendo `python-pyside6`.

## Alertas arquitectonicas para 0.15

Del analisis de arquitectura:

- MPM no debe vender una ilusion de estado unico: el estado real vive en pacman, AUR helper, Flatpak, SQLite local, AppImages, XDG y contenedores Distrobox.
- AUR con `--skipreview`/respuestas automaticas es un riesgo de seguridad. En 0.15 deberia requerir revision por defecto o un flag avanzado explicito.
- `sudo` desde GUI via `QProcess` puede no mostrar autenticacion usable. 0.15 necesita estrategia terminal/polkit/sudo-preflight.
- Distrobox aisla del gestor Arch, pero no debe describirse como sandbox de seguridad.
- AppImage/vendor necesita checksum/firma o una advertencia clara de origen no verificado.
- Las instalaciones Distrobox deberian devolver un manifiesto post-install con `box`, `package`, `app_id` y `desktop_id` para mejorar desinstalacion y reconciliacion.
- Snapper opcional debe ser una decision explicita y persistente, no solo una advertencia silenciosa.
