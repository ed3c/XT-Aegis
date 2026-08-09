# Engineering References

XT-Aegis uses primary and standards-oriented references for protocol, security, and open-source project
structure. These references support design decisions; they do not prove this repository's implementation.

## Agent and prompt-injection security

- OWASP GenAI Security Project: Agentic AI threats and mitigations
- OpenAI: practical guide to building agents and safety guidance for tool use
- Model Context Protocol: security best practices and authorization guidance

## MCP

- Model Context Protocol specification, revision 2026-07-28
- Official MCP Python SDK
- Streamable HTTP transport specification
- MCP authorization specification

The optional adapter relies on the official SDK abstraction rather than implementing protocol headers
manually. Compatibility must be tested against pinned releases before a production profile is declared.

## Observability

- OpenTelemetry specifications and semantic conventions
- W3C Trace Context

## Open source

- GitHub documentation for repository health files and security features
- SPDX license identifiers
- Contributor Covenant
- Keep a Changelog
- Semantic Versioning

## Review rule

External references describe expected practices. A reviewer should still inspect the local code, tests,
CI, and limitations before granting implementation credit.
