install:
	uv sync

project:
	uv run project

run: project

parser:
	uv run valutatrade-parser

build:
	uv build

publish:
	uv publish --dry-run

package-install:
	uv tool install --force $(lastword $(sort $(wildcard dist/*.whl)))

lint:
	uv run ruff check .

format:
	uv run ruff format .

.PHONY: install project run parser build publish package-install lint format
