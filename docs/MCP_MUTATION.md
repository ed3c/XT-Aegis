# Admission for Mutating MCP Calls

## Status

**No mutating MCP tool exists.** The MCP surface remains read-only by default, and this document describes
the decision component that any future mutating tool must pass through — not a capability that is enabled.

## The one question

`MutatingToolAdmission.admit` answers: may this exact call proceed? It returns a decision that is either
admitted or carries exactly one machine-readable reason.

## Check order is a security property

```text
1. protection profile        isolation, egress, credential brokerage, approval, audit — all required
2. assertion validity        expiry, issuer, audience
3. replay                    the nonce must not have been presented before
4. tool declaration          an undeclared tool is denied, never defaulted to allowed
5. scopes                    every required scope must be present
6. approval                  present, unconsumed, unexpired, and bound to this exact call
```

The profile is evaluated **first, deliberately**. A call that cannot be executed safely must be refused
regardless of how well the caller authenticates; authenticating a request that cannot be safely executed
only tells the caller which credentials work.

Every field of `ProtectionProfile` defaults to `False`. A protection nobody declared is treated as absent,
so forgetting to configure one fails closed rather than open.

## Approval binding

An approval covers one call: subject, tool, canonical action digest, and policy version must all match, it
must be unexpired, and it is single use. Changing the payload changes the action digest, so argument
substitution after approval is a different call and is denied — with `action_digest` named in the detail.

## Request identity

A repeated request id never executes twice:

- a request that already reached a terminal decision replays that decision with `replayed=true`;
- a request that was admitted and has not reported a terminal result is denied with `request_in_progress`.

`record_terminal` is how the caller reports the terminal result, and it is what turns an in-progress
request into a replayable one.

## What this component is not

- It does not verify a bearer credential. It consumes an already-verified `SubjectAssertion`; signature,
  transport security, and host/origin validation belong to the transport layer and remain part of #16.
- It does not register, expose, or enable any tool. `declared_tools` is the exhaustive set that could ever
  be admitted, and it is supplied by trusted configuration.
- It performs no I/O. A test asserts that by replacing `socket.socket`, `subprocess.run`, and
  `subprocess.Popen` with failures while the decision runs.
- It makes no claim about the rest of #16: the SDK adapter, protocol-version compatibility matrix,
  structured result shaping, and the security-review checklist are all still open.
