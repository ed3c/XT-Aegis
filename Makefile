.PHONY: install test lint typecheck check demo build clean

install:
	python3 -m pip install -e ".[dev]"

test:
	pytest --cov=xt_aegis --cov-report=term-missing --cov-fail-under=80

lint:
	ruff check .

typecheck:
	mypy src

check: lint typecheck test
	python3 -m compileall -q src tests


demo:
	xt-aegis demo

build:
	python3 -m build

clean:
	rm -rf .coverage .mypy_cache .pytest_cache .ruff_cache build dist *.egg-info src/*.egg-info .xt-aegis
