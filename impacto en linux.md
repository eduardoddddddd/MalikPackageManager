# Impacto En Linux

Analisis read-only realizado sobre `/home/edu/Developer/MalikPackageManager`.

No se editaron archivos durante el analisis original ni se ejecutaron tests para respetar el modo solo lectura solicitado.

## Diagnostico

La arquitectura base es buena para 0.14: GUI PySide6 delega en `mpm-pkg`, el CLI centraliza instalacion/desinstalacion/historial, y el modelo `CatalogRoute` ya expresa senales utiles como `requires_host_mutation`, `requires_container`, `requires_snapshot`, comunidad y warnings en `src/mpm/search.py`.

Eso es exactamente la base correcta para un gestor unificado.

El riesgo principal no es "instalar paquetes"; es vender una ilusion de estado unico cuando el estado real vive repartido entre:

- `pacman`
- AUR helper (`yay`/`paru`)
- `flatpak`
- SQLite local de MPM
- AppImages copiadas
- launchers XDG
- paquetes `apt`/`dnf` dentro de contenedores Distrobox

MPM hoy registra acciones en SQLite en `bin/mpm-pkg`, pero no reconcilia de forma completa contra el estado externo. En un Arch real eso puede generar registros duplicados, stale records, uninstall incompleto o confianza excesiva en lo que MPM cree que instalo.

## Riesgos Por Backend

### pacman

Hoy crea snapshot Snapper y luego ejecuta:

```bash
sudo pacman -S --needed --noconfirm TARGET
```

Esto es correcto como MVP, pero peligroso como producto final.

Falta preflight con:

- lista de paquetes
- tamano de descarga/instalacion
- reemplazos
- conflictos
- hooks
- paquetes ya instalados
- impacto en dependencias

`--noconfirm` no deberia ser default para host real sin una pantalla de confirmacion rica.

### yay/paru

Es mas delicado que pacman.

El codigo usa `--skipreview` en `paru` y respuestas automaticas en `yay`. Para AUR esto es el mayor riesgo de seguridad: se esta saltando justo la revision del `PKGBUILD`.

Recomendacion fuerte: en 0.15, AUR debe ser `review required` por defecto, con alerta roja si se instala sin revisar.

### flatpak

Es el backend mas seguro para apps graficas.

Usa scope de usuario y Flathub. Bien.

La desinstalacion preserva datos al no usar `--delete-data`. Debe mostrarse claramente:

> Se elimina la app, no sus datos.

### AppImage

Util, pero hoy es debil en seguridad.

Se copia a:

```text
~/.local/share/mpm/appimages
```

y crea `.desktop` en:

```text
~/.local/share/applications
```

Falta verificacion obligatoria de checksum/firma para URLs vendor.

Ademas, el `Exec=` puede romperse con rutas con espacios o caracteres especiales. Debe pasar a generacion XDG robusta y mostrar:

- actualizaciones manuales
- origen no verificado
- datos de usuario no gestionados por MPM

### distrobox-deb / distrobox-rpm

Buen enfoque para mantener DEB/RPM fuera del host, pero Distrobox no es sandbox fuerte; comparte integracion de usuario, display, home y D-Bus segun configuracion.

El bridge instala con `apt-get install` o `dnf install` dentro de cajas.

El producto debe decir:

> Aisla del gestor Arch.

No debe decir:

> Aisla de seguridad.

### distrobox-apt / distrobox-dnf

Ahora aparecen como rutas de descubrimiento, pero el CLI aun no las instala. `install_target` solo implementa:

- `pacman`
- `aur`
- `flatpak`
- `distrobox-deb`
- `distrobox-rpm`
- `appimage`

En la UI deben aparecer como:

> Discover only / no instalable aun.

Esto evita falsa promesa al usuario.

## Riesgos Transversales

### Snapshots

Ahora Snapper es obligatorio para host y falla duro si no existe.

Para 0.15 esta bien hacerlo opcional, pero no debe convertirse en un simple warning.

Debe haber:

- politica persistente
- confirmacion explicita
- etiqueta visible "sin punto de recuperacion"
- explicacion de rollback manual
- asociacion clara entre operacion MPM y snapshot creado

Tambien falta snapshot post-operacion o al menos asociacion clara del snapshot con la transaccion MPM.

### Sudo y prompts

La GUI lanza `mpm-pkg` con `QProcess`. Eso no garantiza un prompt sudo usable.

En escritorio real, pacman/snapper/AUR pueden fallar o quedarse sin autenticacion visible.

0.15 necesita una estrategia clara:

- terminal explicito para operaciones con sudo
- `pkexec`/polkit
- o deteccion previa `sudo -v` con error claro

No conviene confiar en `QProcess` para sudo.

### Desinstalacion

El diseno es prudente, especialmente Distrobox se niega si no puede mapear launcher/paquete.

Pero hay un bug de producto: si el bridge autodetecta el `app_id`, ese dato no vuelve al registro SQLite. `record_install` guarda solo `args.app_id`.

Resultado: muchas instalaciones DEB/RPM exitosas podrian ser dificiles de desinstalar desde MPM.

Prioridad alta:

El bridge debe devolver un manifiesto JSON con:

- `box`
- `package`
- `app_id`
- `desktop_id`
- `backend`
- `manager`
- `version`

### XDG y escritorio

El `.desktop` de paquetes externos depende de Konsole:

```desktop
Exec=konsole --hold -e mpm-open %f
```

Esto encaja con la deuda 0.15.

Tambien conviene alertar si:

- un paquete exporta multiples `.desktop`
- no exporta ninguno
- el launcher apunta a un ejecutable inexistente
- el icono no queda disponible
- el cache de escritorio no se actualiza

## Alertas Que Deberian Aparecer

- Esta ruta modifica el host Arch: pacman/AUR, requiere snapshot o aceptacion explicita sin snapshot.
- AUR es comunitario: revisar PKGBUILD antes de instalar.
- Esta operacion requiere sudo; se abrira terminal/autenticacion.
- Distrobox separa el gestor de paquetes, pero no es un sandbox de seguridad.
- DEB/RPM se instalara dentro de la caja indicada, no en Arch.
- APT/DNF route is discovery-only hasta implementar instalacion.
- Flatpak uninstall conserva datos de usuario.
- AppImage/vendor sin checksum firmado: origen no verificado.
- Desinstalacion eliminara paquete/launcher, no datos en `$HOME`.
- Estado MPM no coincide con el gestor real: registro stale.

## Roadmap Practico 0.14-0.15

### 0.14.1: hardening antes de portabilidad

Recomendacion: hacer una release de hardening antes de avanzar con portabilidad.

Prioridades:

1. Anadir manifiesto post-install para todos los backends:
   - `backend`
   - `real_package`
   - `app_id`
   - `desktop_id`
   - `box`
   - `manager`
   - `version`
2. Bloquear o marcar como no instalables las rutas `distrobox-apt` y `distrobox-dnf` en UI hasta que el CLI las soporte.
3. Cambiar AUR default: no `--skipreview` salvo flag avanzado tipo `--aur-skip-review`.
4. Anadir verificacion opcional/obligatoria de SHA256 para vendor/AppImage URL.
5. Mejorar AppImage `.desktop` con quoting/escaping correcto.
6. Anadir `mpm-pkg doctor-state`: compara SQLite contra pacman/flatpak/distrobox/AppImage/XDG.

### 0.15: portabilidad de host

Mantener la meta "portabilidad de host", pero con estos criterios de aceptacion:

1. Snapper opcional, con `--no-snapshot`, preferencia persistente y aviso fuerte.
2. Preflight host real:
   - paquetes a instalar/remover
   - conflictos
   - tamano
   - gestor afectado
   - snapshot previsto
3. Estrategia sudo de escritorio:
   - terminal agnostico
   - o polkit
   - o deteccion previa `sudo -v`
4. `.desktop` terminal agnostico: eliminar dependencia de Konsole.
5. Rutas estandar:
   - `/usr/bin`
   - `/usr/lib/mpm`
   - `/usr/share/mpm`
6. Alertas de seguridad integradas en `CatalogRoute`, no solo texto suelto.
7. Tests de reconciliacion de estado y uninstall, especialmente Distrobox con `app_id` autodetectado.

## Recomendacion De Producto

En 0.15 no conviene intentar hacerlo todo automatico.

MPM debe ser muy honesto sobre:

- que gestor toca
- donde toca
- que datos conserva
- que datos no gestiona
- que puede revertir
- que no puede revertir
- que estado ha verificado
- que estado solo ha registrado

Esa honestidad es lo que hara que sea usable sobre un Arch real sin romper la confianza del usuario.
