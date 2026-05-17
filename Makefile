.PHONY: test validate install install-bin install-config install-desktop uninstall

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

BINDIR   := $(HOME)/.local/bin
LIBDIR   := $(HOME)/.local/lib/mpm
SHAREDIR := $(HOME)/.local/share/mpm
CFGDIR   := $(HOME)/.config/mpm
APPDIR   := $(HOME)/.local/share/applications

install: install-bin install-config install-desktop
	@echo "MPM installed. Add $(BINDIR) to PATH if not already there."

install-bin:
	mkdir -p $(BINDIR)
	install -m 755 bin/mpm        $(BINDIR)/mpm
	install -m 755 bin/mpm-pkg    $(BINDIR)/mpm-pkg
	install -m 755 bin/mpm-open   $(BINDIR)/mpm-open
	install -m 755 bin/mpm-host-open-url $(BINDIR)/mpm-host-open-url
	mkdir -p $(LIBDIR)
	cp -r src/mpm $(LIBDIR)/src/mpm

install-config:
	mkdir -p $(CFGDIR)
	cp -n configs/mpm/catalog.json     $(CFGDIR)/catalog.json     2>/dev/null || true
	cp -n configs/mpm/vendor_index.json $(CFGDIR)/vendor_index.json 2>/dev/null || true

install-desktop:
	mkdir -p $(APPDIR)
	install -m 644 configs/desktop/mpm.desktop                  $(APPDIR)/mpm.desktop
	install -m 644 configs/desktop/mpm-package-installer.desktop $(APPDIR)/mpm-package-installer.desktop
	update-desktop-database $(APPDIR) 2>/dev/null || true

uninstall:
	rm -f $(BINDIR)/mpm $(BINDIR)/mpm-pkg $(BINDIR)/mpm-open $(BINDIR)/mpm-host-open-url
	rm -rf $(LIBDIR)
	rm -f $(APPDIR)/mpm.desktop $(APPDIR)/mpm-package-installer.desktop
	update-desktop-database $(APPDIR) 2>/dev/null || true
	@echo "MPM uninstalled. Config and data dirs left intact:"
	@echo "  $(CFGDIR)"
	@echo "  $(HOME)/.local/share/mpm"
