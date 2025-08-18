unittest:
	poetry run pytest -v tests/

ruff-check:
	poetry run ruff check src/ tests/

ruff-format-check:
	poetry run ruff format --check .

lint: ruff-check ruff-format-check
	
test-all: lint unittest

level=patch
export level

bump-version:
	bumpversion  --config-file .bumpversion.app $(level)
	@NEW_VERSION=$$(tail -1 VERSION);\
	echo New version: $$NEW_VERSION
