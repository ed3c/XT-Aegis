# Engineering References

XT-Aegis uses primary and standards-oriented references. External documentation describes expected
behavior; it does not prove this repository's implementation.

## Model Context Protocol

- Model Context Protocol specification, current published revision `2025-11-25`;
- official MCP Python SDK;
- stdio and Streamable HTTP transport specification;
- MCP Registry schema and package-type documentation;
- MCP authorization and security guidance.

The repository uses the official SDK rather than manually implementing protocol headers. `server.json`
uses the MCP Registry schema dated `2025-12-11` and declares PyPI plus OCI stdio packages.

## OpenShell

- NVIDIA OpenShell sandbox policy documentation;
- OpenShell policy schema reference;
- documented `sandbox create --policy ... --no-keep -- <command>` flow.

The adapter records the reviewed policy digest. Runtime behavior must be reproduced on a host with a
supported OpenShell installation.

## Software supply chain

- GitHub Actions artifact attestations;
- PyPI trusted publishing;
- OCI image annotations and immutable digests;
- SPDX identifiers and SBOM formats.

## Open source project structure

- GitHub repository health files and security features;
- Contributor Covenant;
- Keep a Changelog;
- Semantic Versioning.

## Evidence rule

A user should still inspect local code, negative tests, CI, runtime identity, raw artifacts, and
limitations before accepting a claim.
