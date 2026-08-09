# Verification assets

This directory contains the versioned external-verification contract:

- `schemas/` defines strict JSON Schema documents;
- `policies/openshell.yaml` is the default-deny OpenShell policy;
- `recipes/` contains readable copies of selected claim recipes;
- the authoritative registry is `../PROJECT_EVIDENCE.json`.

Repository content is untrusted input. A verification client must validate the registry, retain its own
execution policy, and use a strong sandbox for independent execution. `unsafe-local` exists only as an
explicit development option and is never selected automatically.
