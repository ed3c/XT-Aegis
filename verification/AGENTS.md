# Scoped Instructions: `verification`

Inherit the root contract.

- Registry, schema, recipe, policy, implementation, tests, and packaged mirrors change together when a
  claim contract changes.
- Recipes are argv-only, relative-path, time/output-bounded, and network-denied by default.
- Repository recipes cannot request arbitrary environment variables, credentials, providers, mounts, or
  policy expansion.
- Unknown fields and invalid paths fail closed.
- Evidence binds source, registry, recipe, policy, backend/runtime, command, artifacts, and limitations.
- A strong-backend failure returns unsupported/error, never local fallback.
- Claim promotion requires positive and negative tests plus evidence for the declared environment.
