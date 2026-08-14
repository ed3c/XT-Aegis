# Egress Policy and Credential Injection

## What this is, and what it is not

`xt_aegis.egress` decides whether a destination may be contacted and which resolved address the caller is
allowed to connect to. It opens no socket and runs no proxy. That separation is deliberate: it makes the
rebinding and canonicalization defenses testable without a network, and it keeps the decision in trusted
code even when the connection is made elsewhere.

Network isolation of the sandbox itself is a runtime property, not a property of this module. The supported
container profile still denies network by default and that remains issue #12's live gate. Command
allowlisting has never been network isolation, and this module does not change that.

## Default deny

An `EgressPolicy` starts with no rules. Every destination is denied until an explicit `EgressRule` approves
the exact scheme, host, port, method, and path prefix. Each deny names exactly one machine-readable reason,
so a reviewer can reproduce the verdict from the audit record.

| Reason | Meaning |
|---|---|
| `malformed_url` | the destination could not be parsed |
| `scheme_not_allowed` | not `http` or `https` |
| `user_info_present` | the URL carried `user:password@`, which is never approved |
| `host_not_allowed` | no rule approves the canonical host |
| `port_not_allowed` | the host is approved, the port is not |
| `method_not_allowed` | the destination is approved, the method is not |
| `path_not_allowed` | no approved path prefix matches |
| `no_address_resolved` | the host resolved to nothing |
| `private_address` | resolved to loopback, private, link-local, reserved, multicast, or the cloud metadata address |
| `mixed_address_answer` | resolved to both private and public addresses, the rebinding signature |
| `address_changed` | the connected address is not the address the decision was made against |
| `redirect_not_allowed` | redirects are denied unless explicitly enabled |

## Host canonicalization

`API.Example.COM.`, `api.example.com`, and the IDNA form of a Unicode spelling all reduce to one key before
any rule comparison, so an equivalent spelling cannot slip past a rule. A hostname that cannot be IDNA
encoded is lowercased and then fails the comparison rather than raising during policy construction.

## Rebinding and time-of-check/time-of-use

An allow record carries `pinned_address`, the address the decision was made against. The caller connects to
that address and then calls `confirm_pinned_address(record, connected_address)`. A different address
produces an `address_changed` deny, so a resolver answer that changes between the check and the connection
cannot inherit the earlier approval.

A mixed public/private answer is denied before the all-private case, because reporting it as a plain
private address would hide why the host is suspicious.

## Credential injection

`CredentialBroker` holds credential values in memory only. A credential is never written to the workspace,
the child-process environment, command-line arguments, a prompt, telemetry, or persisted events.

An authorization binds one injection to the subject, tool, method, scheme, host, port, path, a canonical
digest of the request arguments, a reason, and an expiry. `inject` returns the header exactly once and only
when all of those still match; a reuse, an expiry, a changed argument, or a different destination fails
closed. The audit record names the credential and the destination — never the value.

```python
record = policy.require("https://api.example.com/v1/chat", method="POST")
authorization = broker.authorize(
    credential_name="provider",
    subject="user:alice",
    tool="proposal-adapter",
    record=record,
    arguments={"model": "m"},
    reason="one bounded proposal call",
)
headers = broker.inject(authorization, record=record, arguments={"model": "m"})
```

## Where it is used today

The optional Ollama provider is the only component in the product that makes an outbound request. Its
endpoint validator already restricted it to a loopback HTTP origin; the request now also passes through the
shared policy, so there is one destination decision for every outbound request rather than one rule per
call site. A denied destination becomes a typed `provider_error` outcome and the transport is never reached.

## Residual risks and assumptions

- This module decides; it does not enforce at the socket. A caller that ignores the decision is not
  constrained by it. Enforcement for sandboxed processes needs the runtime profile in #12 and the strong
  mutation backend in #27.
- The resolver is injected. Without one, address-based checks cannot run and only scheme, host, port,
  method, and path are enforced — the policy reports no `pinned_address` in that case.
- DNS integrity, TLS verification, and certificate pinning belong to the transport the caller uses.
- A credential is only as bounded as the arguments it is bound to; an argument digest computed over an
  incomplete argument set narrows nothing.
