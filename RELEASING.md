# Releasing

## Preconditions

1. `main` is green in CI, verifier-image build, and CodeQL.
2. `CHANGELOG.md`, `CITATION.cff`, `pyproject.toml`, `server.json`, and the evidence registry agree.
3. Planned and unverified claims remain clearly labeled.
4. Security changes include threat-model and negative-test updates.
5. The package and verifier image build from a clean checkout.
6. PyPI trusted publishing and GHCR permissions are configured for the repository environment.

## Local release check

```bash
make clean
make check
make verify
python -m build
python -m venv /tmp/xt-aegis-release-test
/tmp/xt-aegis-release-test/bin/pip install "$(find dist -name '*.whl' -print -quit)[mcp]"
/tmp/xt-aegis-release-test/bin/xt-aegis demo --output-dir /tmp/xt-aegis-release-demo
/tmp/xt-aegis-release-test/bin/xt-aegis doctor --backend unsafe-local

docker build -f Dockerfile.verifier -t xt-aegis-verifier:release .
docker run --rm --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=536870912 \
  xt-aegis-verifier:release \
  xt-aegis doctor --backend unsafe-local
```

## Tagging

Use an annotated tag matching the package, registry, and image version:

```bash
git tag -a v0.2.0 -m "XT-Aegis v0.2.0"
git push origin v0.2.0
```

A published GitHub release triggers PyPI trusted publishing. The tag workflow publishes the GHCR verifier
image and build provenance. After both packages are available, validate and publish `server.json` with the
official MCP Registry publisher.

Users should pin the exact package version or OCI digest and retain verification evidence with the source
commit, registry digest, recipe digest, and policy digest.
