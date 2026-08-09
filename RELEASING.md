# Releasing

## Preconditions

1. `main` is green in CI and CodeQL.
2. `CHANGELOG.md`, `CITATION.cff`, package version, and evidence registry agree.
3. No `planned` claim is presented as implemented.
4. Security-sensitive changes have threat-model and negative-test updates.
5. The package builds from a clean checkout.

## Local release check

```bash
make clean
make check
python -m build
python -m venv /tmp/xt-aegis-release-test
/tmp/xt-aegis-release-test/bin/pip install dist/*.whl
/tmp/xt-aegis-release-test/bin/xt-aegis demo --output-dir /tmp/xt-aegis-release-demo
```

## Tagging

Use an annotated tag matching the package version:

```bash
git tag -a v0.1.0 -m "XT-Aegis v0.1.0"
git push origin v0.1.0
```

Releases should attach checksums and, when available, an SBOM and signed provenance. PyPI publication is
not enabled until the package name, release identity, and trusted publishing configuration are reviewed.
