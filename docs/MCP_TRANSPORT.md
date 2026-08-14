# MCP Transport Security

## The defect this closes

The SDK ships DNS-rebinding protection and turns it off when nothing is passed:

```python
# If not specified, disable DNS rebinding protection by default for backwards compatibility
self.settings = settings or TransportSecuritySettings(enable_dns_rebinding_protection=False)
```

`xt-aegis-mcp --transport streamable-http` passed nothing, so the shipped HTTP server validated neither
`Host` nor `Origin`. `tests/test_mcp_transport.py::test_protection_is_off_when_no_settings_are_supplied`
records that behaviour against the installed SDK rather than describing it.

**Loopback is not the protection it looks like.** A page in the user's own browser can resolve an
attacker-controlled name to `127.0.0.1` and reach a loopback server; the connection is local, the intent is
not. What stops it is the server checking the `Host` header it was handed.

## What is enforced now

| Request | Outcome |
|---|---|
| `Host: 127.0.0.1:8765` (the declared bind address) | admitted |
| `Host: localhost:8765`, `Host: [::1]:8765` | admitted — a loopback bind answers to all of loopback's names |
| `Host: 127.0.0.1:9999` | rejected — another port is another origin |
| `Host: evil.example.com` | rejected, 421 |
| `Host: rebind.attacker.example:8765` with the matching `Origin` | rejected, 421 — the rebinding case |
| `Origin: https://evil.example.com` on an allowed `Host` | rejected, 403 |
| no `Host` header | rejected |
| HTTP transport on an SDK that cannot take the settings | **refuses to start** |

The last row is the point. Starting unprotected because a parameter went missing is the failure mode; the
check is made against the callable that will actually run, not against a version string.

## What Origin does not do

The SDK treats an **absent** `Origin` as same-origin and admits it. That is correct for non-browser clients,
which never send one, and it means `Origin` is a browser-facing defence only. `Host` is the enforced gate.
Do not read the Origin allowlist as authentication.

## Reverse proxy requirements

A proxy in front of the server must:

- set `Host` to a value on the allowlist — pass `--extra-host` for the public name, or have the proxy
  rewrite `Host` to the bind address;
- terminate TLS itself; the server speaks plain HTTP on loopback;
- not forward `X-Forwarded-*` from clients unmodified. Nothing here reads those headers, but anything else
  in the chain that does will trust whatever the client sent;
- perform authentication. There is none in this server, which is why the execution tools stay behind
  `--allow-execution` and a loopback bind.

## Compatibility matrix

| Dimension | Tested | How |
|---|---|---|
| MCP SDK | `mcp` 2.0.0 | every test in `tests/test_mcp_transport.py` runs against the installed SDK's own middleware |
| Protocol version | latest `2026-07-28`, default negotiated `2025-03-26` | the SDK's constants; no cross-version negotiation was exercised |
| Transport: stdio | yes | unchanged, and covered by the existing read-only tests |
| Transport: streamable-http | header validation only | the guard is asserted at the call boundary; no live HTTP server was started |
| Transport: SSE | **not tested** | the SDK offers it; `xt-aegis-mcp` does not |
| SDK 1.x (`mcp.server.fastmcp`) | **not tested** | the loader still tries it and the fail-closed check still applies, but no 1.x environment was exercised |
| Authentication, per-tool scopes | **not implemented** | #16, decided in #78 |

The matrix lists what ran, not what is expected to work. An untested row is not a supported row.

## Running it

```bash
xt-aegis-mcp --transport streamable-http --host 127.0.0.1 --port 8765
xt-aegis-mcp --transport streamable-http --max-request-bytes 262144   # bound the body below the SDK default
```

Execution tools require `--allow-execution` and refuse any non-loopback bind. That check predates this
document and is unchanged.
