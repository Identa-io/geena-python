# Development is driven by uv (https://docs.astral.sh/uv/); `make check` is what CI runs.

IDENTA ?= ../identa
IDENTA_TAG ?=

.PHONY: sync lint format typecheck test check openapi-sync

sync:
	uv sync --all-groups

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

test:
	uv run pytest -q

check: lint typecheck test

## openapi-sync: copy identa's two OpenAPI documents at IDENTA_TAG into openapi/ and record the pin.
## Run the tests afterwards: the conformance test tells you which models the new contract changed.
openapi-sync:
	@test -n "$(IDENTA_TAG)" || { echo "usage: make openapi-sync IDENTA_TAG=vX.Y.Z [IDENTA=../identa]"; exit 1; }
	@git -C $(IDENTA) rev-parse -q --verify "refs/tags/$(IDENTA_TAG)" >/dev/null || { echo "$(IDENTA): no tag $(IDENTA_TAG) (git fetch --tags?)"; exit 1; }
	@git -C $(IDENTA) show $(IDENTA_TAG):pkg/partnerapi/openapi.yaml > openapi/partner-v1.yaml
	@git -C $(IDENTA) show $(IDENTA_TAG):pkg/orgapi/openapi.yaml > openapi/org-v1.yaml
	@printf 'identa_tag: %s\nidenta_commit: %s\npartner: pkg/partnerapi/openapi.yaml\norg: pkg/orgapi/openapi.yaml\n' \
	  "$(IDENTA_TAG)" "$$(git -C $(IDENTA) rev-parse --short $(IDENTA_TAG))" > openapi/PIN.yaml
	@cat openapi/PIN.yaml
