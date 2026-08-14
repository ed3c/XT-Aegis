# Protected External Side Effects

## Where the guarantee actually stops

XT-Aegis can guarantee that **it** does not dispatch the same protected operation twice. It cannot
guarantee that an external service received it exactly once, and no amount of local bookkeeping changes
that: when an acknowledgement is lost, "it did not happen" and "it happened and I did not hear" look
identical from here.

So ambiguity is a state, not an error to swallow. What this module provides:

| Situation | Behavior |
|---|---|
| the operation already committed | the stored receipt is returned; the adapter is not called |
| the provider reported a definite failure | retry is allowed, because retry is safe only here |
| the acknowledgement was lost | the record becomes `unknown` and is **not** retried |
| the adapter can look the operation up | reconciliation resolves `unknown` to `committed` or `failed` |
| the adapter cannot | the record stays `unknown` and the caller is told why |

## Identity

The idempotency key is a digest of subject, tool, target resource, policy version, logical operation id,
and a canonical digest of the arguments. Changing any one of them makes it a different operation by
construction, so a substituted argument cannot ride on an earlier operation's key.

```python
identity = EffectIdentity(
    subject="user:alice",
    tool="deployer",
    resource="service:checkout",
    policy_version="1.0",
    logical_operation_id="deploy-2026-08-14-a",
    argument_digest=argument_digest({"revision": "abc123"}),
)
record = ProtectedEffectRunner(EffectStore(path)).execute(identity, adapter)
```

## Intent before dispatch

The `pending` record is written **before** the adapter is called. A crash between the two therefore leaves
a record the next run treats as ambiguous, rather than leaving no trace of an operation that may have
reached the provider. A test asserts this by reading the store from inside the adapter's `dispatch`.

## Adapters declare their own guarantees

```python
class MyAdapter:
    supports_idempotency_key = True  # the provider accepts and honors a client key
    supports_reconciliation = True  # the provider can be asked whether an operation happened
```

Both are declared, not probed. An adapter that guesses about its provider's guarantees is worse than one
that admits it has none: when `supports_reconciliation` is false, an ambiguous operation stays ambiguous
and a human decides, which is the honest outcome.

When `supports_idempotency_key` is false, the adapter receives `None` instead of a key, and the protection
degrades to "XT-Aegis will not dispatch twice" without any provider-side deduplication.

## Receipts

A receipt is bounded at the type boundary (4096 characters) rather than truncated at runtime, so an adapter
cannot construct an oversized one at all. Stored receipts pass the shared redaction pass. Credentials and
raw payloads are never stored.

## Not provided

- Exactly-once external delivery. It does not exist without provider cooperation, and this document says so
  rather than implying otherwise.
- Compensation. Undoing a committed external effect is domain-specific; this module records that the effect
  happened and leaves the compensation to the caller.
- Runner integration. Nothing in `HarnessRunner` routes through this yet.
- The resumable human-in-the-loop notification channel and authenticated decision callback, which are the
  rest of issue #15.
