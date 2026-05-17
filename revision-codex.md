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
