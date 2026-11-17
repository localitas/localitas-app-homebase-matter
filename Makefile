VENV := venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PORT ?= 9222
STORAGE ?= $(HOME)/.localitas/homebase/matter

GH_REPO := localitas/localitas-app-homebase-matter
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
TARBALL := localitas-matter.tar.gz
HOMEBREW_FORMULA ?= ../localitas-homebrew-tap/Formula/localitas-matter.rb
ASSET ?= dist/$(TARBALL)

.PHONY: help venv install dev stop test lint clean build-release release release-update-formula update-formula

help:
	@echo "homebase-matter — Matter sidecar for Localitas Homebase"
	@echo ""
	@echo "  make install                 install dependencies into venv"
	@echo "  make dev                     run sidecar natively on port $(PORT)"
	@echo "  make stop                    kill running sidecar"
	@echo "  make test                    run tests"
	@echo "  make lint                    run gofmt equivalent (ruff + pyright stub)"
	@echo "  make build-release           build dist/$(TARBALL), the asset the Homebrew formula installs"
	@echo "  make release VERSION=vX.Y.Z  build it and publish it as a GitHub release"
	@echo "  make release-update-formula  point the tap's localitas-matter formula at the latest release (TAG=vX.Y.Z for another)"

venv:
	@python3 -m venv $(VENV)

install: venv
	@$(PIP) install -q --upgrade pip
	@$(PIP) install -q -r requirements.txt
	@echo "✅ dependencies installed"

dev: install
	@mkdir -p $(STORAGE) $(HOME)/.localitas/logs/homebase-matter
	@$(PYTHON) main.py --listen 127.0.0.1:$(PORT) --storage $(STORAGE)

stop:
	@-pkill -f "homebase-matter.*main.py" 2>/dev/null || true
	@-lsof -ti:$(PORT) | xargs -r kill -9 2>/dev/null || true
	@echo "✅ stopped"

test: install
	@$(VENV)/bin/pytest test_app.py -v

lint: install
	@$(VENV)/bin/python -m py_compile main.py app.py matter.py routes.py
	@echo "✅ syntax ok"

clean:
	@rm -rf $(VENV) __pycache__ .pytest_cache *.pyc dist

# ── Release ───────────────────────────────────────────────────
# The release asset is the committed tree under localitas-matter/; the
# localitas-matter Homebrew formula installs it into libexec and pip-installs
# requirements.txt next to it.

build-release:
	@mkdir -p dist
	git archive --format=tar.gz --prefix=localitas-matter/ -o dist/$(TARBALL) HEAD
	@echo "Built dist/$(TARBALL) from $$(git rev-parse --short HEAD)"

release: build-release
	@if [ -z "$(VERSION)" ] || [ "$(VERSION)" = "dev" ]; then echo "Set VERSION=vX.Y.Z"; exit 1; fi
	gh release create $(VERSION) dist/$(TARBALL) --repo $(GH_REPO) --title "$(VERSION)" --generate-notes
	@echo "Released $(VERSION); run make release-update-formula to point the tap at it"

# Download the published asset (the latest release, or TAG) and set the tap
# formula's version and sha256 from it, as core's release-update-formula does
# for localitas-core. Commit and push the tap repo afterwards.
release-update-formula:
	@test -f $(HOMEBREW_FORMULA) || { echo "Missing tap formula at $(HOMEBREW_FORMULA)"; exit 1; }
	@tag="$(TAG)"; \
	if [ -z "$$tag" ]; then tag=$$(gh release view --repo $(GH_REPO) --json tagName --jq .tagName) || exit 1; fi; \
	rm -rf dist/published && mkdir -p dist/published && \
	gh release download "$$tag" --repo $(GH_REPO) --pattern $(TARBALL) --dir dist/published && \
	$(MAKE) --no-print-directory update-formula ASSET=dist/published/$(TARBALL) VERSION="$$tag"

update-formula:
	@test -f "$(ASSET)" || { echo "Missing release asset $(ASSET)"; exit 1; }
	@test -f $(HOMEBREW_FORMULA) || { echo "Missing tap formula at $(HOMEBREW_FORMULA)"; exit 1; }
	@case "$(VERSION)" in v[0-9]*) ;; *) echo "VERSION must be a release tag like v0.1.2, got '$(VERSION)'"; exit 1;; esac
	@SHA=$$(shasum -a 256 "$(ASSET)" | cut -d' ' -f1) V=$$(echo "$(VERSION)" | cut -c2-) && export SHA V && \
		grep -Eq '^ *sha256 "[^"]*"' $(HOMEBREW_FORMULA) && grep -Eq '^ *version "[^"]*"' $(HOMEBREW_FORMULA) || \
			{ echo "$(HOMEBREW_FORMULA) has no version or sha256 line"; exit 1; }; \
		perl -pi -e 's/^( *)version "[^"]*"/$$1version "$$ENV{V}"/; s/^( *)sha256 "[^"]*"/$$1sha256 "$$ENV{SHA}"/' $(HOMEBREW_FORMULA) && \
		echo "version $$V, sha256 $$SHA" && \
		echo "Updated $(HOMEBREW_FORMULA) — commit & push the tap repo."
