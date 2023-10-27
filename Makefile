OPEN_CMD := $(shell type xdg-open &> /dev/null && echo 'xdg-open' || echo 'open')
NAME := release-gitter
ENV := venv

.PHONY: default
default: test

# Creates de virtualenv
$(ENV):
	python3 -m venv $(ENV)

# Install package and dependencies in virtualenv
$(ENV)/bin/$(NAME): $(ENV)
	$(ENV)/bin/pip install -r requirements-dev.txt

# Install hatch into virtualenv for running tests
$(ENV)/bin/hatch: $(ENV)
	$(ENV)/bin/pip install hatch

# Installs dev requirements to virtualenv
.PHONY: devenv
devenv: $(ENV)/bin/$(NAME)

# Runs tests for current python
.PHONY: test
test: $(ENV)/bin/hatch
	$(ENV)/bin/hatch run +py=3 test:run

# Runs test matrix
.PHONY: test-matrix
test-matrix: $(ENV)/bin/hatch
	$(ENV)/bin/hatch run test:run

# Builds wheel for package to upload
.PHONY: build
build: $(ENV)/bin/hatch
	$(ENV)/bin/hatch build

# Verify that the python version matches the git tag so we don't push bad shas
.PHONY: verify-tag-version
verify-tag-version:
	$(eval TAG_NAME = $(shell [ -n "$(DRONE_TAG)" ] && echo $(DRONE_TAG) || git describe --tags --exact-match))
	test "v$(shell $(ENV)/bin/hatch version)" = "$(TAG_NAME)"

# Upload to pypi
.PHONY: upload
upload: verify-tag-version build
	$(ENV)/bin/hatch publish

# Uses twine to upload to test pypi
.PHONY: upload-test
upload-test: build
	$(ENV)/bin/hatch publish --repo test

# Cleans all build, runtime, and test artifacts
.PHONY: clean
clean:
	rm -fr ./build *.egg-info ./htmlcov ./.coverage ./.pytest_cache
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -delete

# Cleans dist and env
.PHONY: dist-clean
dist-clean: clean
	-$(ENV)/bin/hatch env prune
	rm -fr ./dist $(ENV)

# Run linters
.PHONY: lint
lint: $(ENV)/bin/hatch
	$(ENV)/bin/hatch run lint:all

# Install pre-commit hooks
.PHONY: install-hooks
install-hooks: devenv
	$(ENV)/bin/hatch run lint:install-hooks

# Generates test coverage
.coverage: test

# Builds coverage html
htmlcov/index.html: .coverage
	$(ENV)/bin/hatch run coverage html

# Opens coverage html in browser (on macOS and some Linux systems)
.PHONY: open-coverage
open-coverage: htmlcov/index.html
	$(OPEN_CMD) htmlcov/index.html

# Cleans out docs
.PHONY: docs-clean
docs-clean:
	rm -fr docs/build/* docs/source/code/*

# Builds docs
docs/build/html/index.html:
	$(ENV)/bin/hatch run docs:build

# Shorthand for building docs
.PHONY: docs
docs: docs/build/html/index.html

.PHONY: clean-all
clean-all: clean dist-clean docs-clean
