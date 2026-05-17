.PHONY: test validate install install-bin install-config install-desktop install-system-data uninstall

# ── Test ──────────────────────────────────────────────────────────────────────

test:
	python -m unittest discover -s tests

# ── Self-tests (smoke-check installed bins without a full env) ─────────────────

validate:
	@echo "==> mpm --version"
	bin/mpm --version
	@echo "==> mpm --self-test-catalog"
	MPM_CATALOG=configs/mpm/catalog.json bin/mpm --self-test-catalog
	@echo "==> mpm --self-test-uninstall-preflight"
	bin/mpm --self-test-uninstall-preflight
	@echo "==> mpm --self-test-history-format"
	bin/mpm --self-test-history-format
	@echo "==> mpm-pkg --version"
	bin/mpm-pkg --version
	@echo "All self-tests passed."

# ── Install ───────────────────────────────────────────────────────────────────

PREFIX  ?= $(HOME)/.local
XDG_CONFIG_HOME ?= $(HOME)/.config
BINDIR   := $(DESTDIR)$(PREFIX)/bin
LIBDIR   := $(DESTDIR)$(PREFIX)/lib/mpm
SHAREDIR := $(DESTDIR)$(PREFIX)/share/mpm
CFGDIR   ?= $(XDG_CONFIG_HOME)/mpm
APPDIR   := $(DESTDIR)$(PREFIX)/share/applications
RUNTIME_BINDIR := $(PREFIX)/bin

install: install-bin install-system-data install-config install-desktop
	@echo "MPM installed. Add $(BINDIR) to PATH if not already there."

install-bin:
	mkdir -p $(BINDIR)
	install -m 755 bin/mpm        $(BINDIR)/mpm
	install -m 755 bin/mpm-pkg    $(BINDIR)/mpm-pkg
	install -m 755 bin/mpm-open   $(BINDIR)/mpm-open
	install -m 755 bin/mpm-host-open-url $(BINDIR)/mpm-host-open-url
	mkdir -p $(LIBDIR)/src
	rm -rf $(LIBDIR)/src/mpm
	cp -R src/mpm $(LIBDIR)/src/mpm
	install -m 755 scripts/distrobox/mpm-distrobox-bridge.sh $(LIBDIR)/mpm-distrobox-bridge.sh

install-system-data:
	mkdir -p $(SHAREDIR)
	install -m 644 configs/mpm/catalog.json      $(SHAREDIR)/catalog.json
	install -m 644 configs/mpm/vendor_index.json $(SHAREDIR)/vendor_index.json

install-config:
	mkdir -p $(CFGDIR)
	cp -n configs/mpm/catalog.json     $(CFGDIR)/catalog.json     2>/dev/null || true
	cp -n configs/mpm/vendor_index.json $(CFGDIR)/vendor_index.json 2>/dev/null || true

install-desktop:
	mkdir -p $(APPDIR)
	sed 's|^Exec=mpm$$|Exec=$(RUNTIME_BINDIR)/mpm|' configs/desktop/mpm.desktop > $(APPDIR)/mpm.desktop
	sed 's|^Exec=mpm-open %f$$|Exec=$(RUNTIME_BINDIR)/mpm-open %f|' configs/desktop/mpm-package-installer.desktop > $(APPDIR)/mpm-package-installer.desktop
	chmod 644 $(APPDIR)/mpm.desktop $(APPDIR)/mpm-package-installer.desktop
	update-desktop-database $(APPDIR) 2>/dev/null || true

uninstall:
	rm -f $(BINDIR)/mpm $(BINDIR)/mpm-pkg $(BINDIR)/mpm-open $(BINDIR)/mpm-host-open-url
	rm -rf $(LIBDIR)
	rm -f $(SHAREDIR)/catalog.json $(SHAREDIR)/vendor_index.json
	rmdir $(SHAREDIR) 2>/dev/null || true
	rm -f $(APPDIR)/mpm.desktop $(APPDIR)/mpm-package-installer.desktop
	update-desktop-database $(APPDIR) 2>/dev/null || true
	@echo "MPM uninstalled. Config and data dirs left intact:"
	@echo "  $(CFGDIR)"
	@echo "  $(HOME)/.local/share/mpm"
