#!/usr/bin/env bash
set -euo pipefail

UBUNTU_BOX="${MPM_UBUNTU_BOX:-mpm-ubuntu-apps}"
DEBIAN_BOX="${MPM_DEBIAN_BOX:-mpm-debian-apps}"
FEDORA_BOX="${MPM_FEDORA_BOX:-mpm-fedora-apps}"

UBUNTU_IMAGE="${MPM_UBUNTU_IMAGE:-docker.io/library/ubuntu:24.04}"
DEBIAN_IMAGE="${MPM_DEBIAN_IMAGE:-docker.io/library/debian:trixie}"
FEDORA_IMAGE="${MPM_FEDORA_IMAGE:-registry.fedoraproject.org/fedora:44}"

DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

usage() {
  cat <<EOF
Usage:
  $(basename "$0") bootstrap
  $(basename "$0") create-boxes
  $(basename "$0") install-deb FILE [APP_ID]
  $(basename "$0") install-rpm FILE [APP_ID]
  $(basename "$0") export-app BOX APP_ID
  $(basename "$0") repair-desktop
  $(basename "$0") repair-kde
  $(basename "$0") status

Environment overrides:
  MPM_UBUNTU_BOX=$UBUNTU_BOX
  MPM_DEBIAN_BOX=$DEBIAN_BOX
  MPM_FEDORA_BOX=$FEDORA_BOX
  MPM_UBUNTU_IMAGE=$UBUNTU_IMAGE
  MPM_DEBIAN_IMAGE=$DEBIAN_IMAGE
  MPM_FEDORA_IMAGE=$FEDORA_IMAGE
EOF
}

log() {
  printf '==> %s\n' "$*"
}

warn() {
  printf 'warn: %s\n' "$*" >&2
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

create_pre_host_snapshot() {
  local description="$1"

  require_cmd sudo
  require_cmd snapper
  [[ -f /etc/snapper/configs/root ]] || die "Snapper root config is required before host package install"
  sudo snapper -c root create --cleanup-algorithm number --description "$description"
}

install_host_packages() {
  require_cmd sudo
  require_cmd pacman

  log "Installing MalikOS Distrobox bridge host packages"
  create_pre_host_snapshot "pre-mpm-distrobox-bridge host packages"
  sudo pacman -S --needed --noconfirm \
    podman \
    distrobox \
    fuse-overlayfs \
    slirp4netns \
    xdg-utils \
    desktop-file-utils

  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user enable --now podman.socket >/dev/null 2>&1 || \
      warn "podman.socket user service was not enabled; rootless podman still works without the API socket"
  fi
}

container_exists() {
  local name="$1"
  podman container exists "$name" >/dev/null 2>&1
}

create_box() {
  local name="$1"
  local image="$2"

  require_cmd distrobox
  require_cmd podman

  if container_exists "$name"; then
    log "Distrobox already exists: $name"
    return
  fi

  log "Creating Distrobox $name from $image"
  distrobox create --yes --name "$name" --image "$image"
}

enter_box() {
  local name="$1"
  shift
  distrobox enter --name "$name" -- "$@"
}

init_deb_box() {
  local name="$1"

  log "Preparing DEB tooling in $name"
  enter_box "$name" bash -lc '
    set -euo pipefail
    sudo apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
      ca-certificates \
      dbus-x11 \
      desktop-file-utils \
      xdg-utils
  '
}

init_rpm_box() {
  local name="$1"

  log "Preparing RPM tooling in $name"
  enter_box "$name" bash -lc '
    set -euo pipefail
    sudo dnf install -y \
      ca-certificates \
      dbus-x11 \
      desktop-file-utils \
      xdg-utils
  '
}

create_boxes() {
  create_box "$UBUNTU_BOX" "$UBUNTU_IMAGE"
  create_box "$DEBIAN_BOX" "$DEBIAN_IMAGE"
  create_box "$FEDORA_BOX" "$FEDORA_IMAGE"

  init_deb_box "$UBUNTU_BOX"
  init_deb_box "$DEBIAN_BOX"
  init_rpm_box "$FEDORA_BOX"
}

copy_package_to_box() {
  local box="$1"
  local package="$2"
  local suffix="$3"
  local real_package
  local target

  [[ -f "$package" ]] || die "package file not found: $package"
  real_package="$(realpath "$package")"
  target="/tmp/mpm-bridge-$(date +%s)-$(basename "$real_package")"

  enter_box "$box" true >/dev/null
  podman cp "$real_package" "$box:$target"
  printf '%s\n' "$target"

  [[ "$target" == *".$suffix" ]] || warn "package does not end in .$suffix: $package"
}

export_app() {
  local box="$1"
  local app_id="$2"

  [[ -n "$box" ]] || die "box name is required"
  [[ -n "$app_id" ]] || die "app id is required"

  log "Exporting $app_id from $box"
  enter_box "$box" distrobox-export --app "$app_id"
  repair_desktop
}

export_single_desktop_from_deb_package() {
  local box="$1"
  local package_name="$2"
  local desktop_ids
  local app_id

  [[ -n "$package_name" ]] || return 1

  desktop_ids="$(
    enter_box "$box" bash -lc '
      set -euo pipefail
      mapfile -t files < <(dpkg -L "$1" 2>/dev/null | awk "/\\/applications\\/.*\\.desktop$/ { print }" | sort -u)
      visible=()
      for file in "${files[@]}"; do
        if ! grep -Eq "^[[:space:]]*NoDisplay[[:space:]]*=[[:space:]]*true[[:space:]]*$" "$file"; then
          visible+=("$(basename "$file")")
        fi
      done
      if [[ "${#visible[@]}" -gt 0 ]]; then
        printf "%s\n" "${visible[@]}" | sort -u
      else
        printf "%s\n" "${files[@]}" | awk -F/ "{ print \$NF }" | sort -u
      fi
    ' _ "$package_name"
  )"

  if [[ -z "$desktop_ids" ]]; then
    return 1
  fi

  if [[ "$(wc -l <<<"$desktop_ids")" -ne 1 ]]; then
    warn "package $package_name installed multiple desktop files; pass APP_ID explicitly"
    sed 's/^/  /' <<<"$desktop_ids" >&2
    return 1
  fi

  app_id="${desktop_ids%.desktop}"
  export_app "$box" "$app_id"
}

export_single_desktop_from_rpm_package() {
  local box="$1"
  local package_name="$2"
  local desktop_ids
  local app_id

  [[ -n "$package_name" ]] || return 1

  desktop_ids="$(
    enter_box "$box" bash -lc '
      set -euo pipefail
      mapfile -t files < <(rpm -ql "$1" 2>/dev/null | awk "/\\/applications\\/.*\\.desktop$/ { print }" | sort -u)
      visible=()
      for file in "${files[@]}"; do
        if ! grep -Eq "^[[:space:]]*NoDisplay[[:space:]]*=[[:space:]]*true[[:space:]]*$" "$file"; then
          visible+=("$(basename "$file")")
        fi
      done
      if [[ "${#visible[@]}" -gt 0 ]]; then
        printf "%s\n" "${visible[@]}" | sort -u
      else
        printf "%s\n" "${files[@]}" | awk -F/ "{ print \$NF }" | sort -u
      fi
    ' _ "$package_name"
  )"

  if [[ -z "$desktop_ids" ]]; then
    return 1
  fi

  if [[ "$(wc -l <<<"$desktop_ids")" -ne 1 ]]; then
    warn "package $package_name installed multiple desktop files; pass APP_ID explicitly"
    sed 's/^/  /' <<<"$desktop_ids" >&2
    return 1
  fi

  app_id="${desktop_ids%.desktop}"
  export_app "$box" "$app_id"
}

install_deb() {
  local package="${1:-}"
  local app_id="${2:-}"
  local target
  local detected_package

  [[ -n "$package" ]] || die "missing .deb file"
  require_cmd podman
  require_cmd distrobox
  container_exists "$UBUNTU_BOX" || die "missing box $UBUNTU_BOX; run bootstrap first"

  target="$(copy_package_to_box "$UBUNTU_BOX" "$package" deb)"
  detected_package="$(
    enter_box "$UBUNTU_BOX" bash -lc 'dpkg-deb -f "$1" Package 2>/dev/null || true' _ "$target"
  )"

  log "Installing DEB in $UBUNTU_BOX: $(basename "$package")"
  enter_box "$UBUNTU_BOX" bash -lc '
    set -euo pipefail
    sudo apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$1"
  ' _ "$target"

  if [[ -n "$app_id" ]]; then
    export_app "$UBUNTU_BOX" "$app_id"
  elif [[ -n "$detected_package" ]] && export_single_desktop_from_deb_package "$UBUNTU_BOX" "$detected_package"; then
    true
  elif [[ -n "$detected_package" ]]; then
    warn "installed package $detected_package; pass APP_ID to export a desktop launcher"
  else
    warn "package installed; pass APP_ID to export a desktop launcher"
  fi
}

install_rpm() {
  local package="${1:-}"
  local app_id="${2:-}"
  local target
  local detected_package

  [[ -n "$package" ]] || die "missing .rpm file"
  require_cmd podman
  require_cmd distrobox
  container_exists "$FEDORA_BOX" || die "missing box $FEDORA_BOX; run bootstrap first"

  target="$(copy_package_to_box "$FEDORA_BOX" "$package" rpm)"
  detected_package="$(
    enter_box "$FEDORA_BOX" bash -lc 'rpm -qp --queryformat "%{NAME}" "$1" 2>/dev/null || true' _ "$target"
  )"

  log "Installing RPM in $FEDORA_BOX: $(basename "$package")"
  enter_box "$FEDORA_BOX" bash -lc '
    set -euo pipefail
    sudo dnf install -y "$1"
  ' _ "$target"

  if [[ -n "$app_id" ]]; then
    export_app "$FEDORA_BOX" "$app_id"
  elif [[ -n "$detected_package" ]] && export_single_desktop_from_rpm_package "$FEDORA_BOX" "$detected_package"; then
    true
  elif [[ -n "$detected_package" ]]; then
    warn "installed package $detected_package; pass APP_ID to export a desktop launcher"
  else
    warn "package installed; pass APP_ID to export a desktop launcher"
  fi
}

repair_desktop() {
  local refreshed=0

  log "Repairing desktop/icon integration"
  mkdir -p "$DESKTOP_DIR"

  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
    refreshed=1
  else
    warn "update-desktop-database was not found; desktop MIME cache may refresh later"
  fi

  if command -v xdg-desktop-menu >/dev/null 2>&1; then
    xdg-desktop-menu forceupdate >/dev/null 2>&1 || true
    refreshed=1
  fi

  if command -v gtk-update-icon-cache >/dev/null 2>&1 && [[ -d "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" ]]; then
    gtk-update-icon-cache -q -t -f "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" >/dev/null 2>&1 || true
    refreshed=1
  fi

  if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
    refreshed=1
  elif command -v kbuildsycoca5 >/dev/null 2>&1; then
    kbuildsycoca5 --noincremental >/dev/null 2>&1 || true
    refreshed=1
  else
    warn "kbuildsycoca was not found; KDE menu may refresh on next login"
  fi

  if [[ "$refreshed" -eq 0 ]]; then
    warn "no desktop refresh tool was found; menu may update on next login"
  fi
}

repair_kde() {
  repair_desktop
}

status() {
  local box

  printf 'MalikOS Distrobox bridge status\n\n'

  for cmd in podman distrobox; do
    if command -v "$cmd" >/dev/null 2>&1; then
      printf 'ok      %s: %s\n' "$cmd" "$(command -v "$cmd")"
    else
      printf 'missing %s\n' "$cmd"
    fi
  done

  echo
  for box in "$UBUNTU_BOX" "$DEBIAN_BOX" "$FEDORA_BOX"; do
    if command -v podman >/dev/null 2>&1 && container_exists "$box"; then
      printf 'ok      box exists: %s\n' "$box"
    else
      printf 'missing box: %s\n' "$box"
    fi
  done

  echo
  printf 'desktop entries: %s\n' "$DESKTOP_DIR"
  find "$DESKTOP_DIR" -maxdepth 1 -type f -name '*.desktop' 2>/dev/null |
    sed 's/^/  /' |
    sort || true
}

bootstrap() {
  install_host_packages
  create_boxes
  repair_desktop
  status
}

cmd="${1:-}"
case "$cmd" in
  bootstrap)
    bootstrap
    ;;
  create-boxes)
    create_boxes
    ;;
  install-deb)
    shift
    install_deb "$@"
    ;;
  install-rpm)
    shift
    install_rpm "$@"
    ;;
  export-app)
    shift
    export_app "$@"
    ;;
  repair-desktop)
    repair_desktop
    ;;
  repair-kde)
    repair_desktop
    ;;
  status)
    status
    ;;
  -h|--help|help|'')
    usage
    ;;
  *)
    usage >&2
    die "unknown command: $cmd"
    ;;
esac
