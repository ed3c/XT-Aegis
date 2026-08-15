.PHONY: install test lint format-check typecheck check demo verify build clean

install:
	python3 -m pip install -e ".[dev]"

test:
	pytest --cov=xt_aegis --cov-report=term-missing --cov-fail-under=80

lint:
	ruff check .
	@if command -v shellcheck >/dev/null 2>&1; then \
	  scripts/git-town/lint.sh; \
	else \
	  echo 'shellcheck not installed; scripts/git-town not linted'; \
	fi

format-check:
	ruff format --check .

typecheck:
	mypy src

check: format-check lint typecheck test
	python3 -m compileall -q src tests


demo:
	xt-aegis demo

verify:
	xt-aegis verify --all --backend unsafe-local --output-dir .xt-aegis/verification/local

build:
	python3 -m build

clean:
	rm -rf .coverage .mypy_cache .pytest_cache .ruff_cache build dist *.egg-info src/*.egg-info .xt-aegis
