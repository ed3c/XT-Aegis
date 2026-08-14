# Human-in-the-Loop Notification and Decision Binding

## Two rules

**A notification carries no payload.** It names what is waiting — approval id, subject, tool, action
digest, a bounded summary, and a deadline — and nothing else. A channel that carries the content is a
channel that leaks it, and a pending approval is exactly the moment when the content is most sensitive. A
test asserts the exact field set rather than checking for a few forbidden words.

**A channel never decides.** A transport returning `approved` is reporting data. Only a decision bound to
an authenticated subject, the exact action digest, the policy version, an expiry, and a single-use nonce
changes anything. Compromising the channel is therefore not equivalent to compromising approval.

## Bounded re-notification

A resume calls `notify` again. Each approval has a declared ceiling on attempts, so a restart loop cannot
flood the channel — and a channel that floods is a channel people mute, which is a security property, not
an ergonomics one.

```python
notifier = ApprovalNotifier(channel, max_attempts_per_approval=3)
notifier.notify(pending)  # attempt 1
notifier.notify(pending)  # attempt 2 after a restart
notifier.notify(pending)  # attempt 3
notifier.notify(pending)  # None: the ceiling is reached
notifier.undelivered(approval_id)  # True only when every permitted attempt failed
```

`None` means the ceiling was reached, not that delivery succeeded. A transport that raises is a delivery
failure, recorded as such, and never a decision.

## Decision verification

| Rejection | When |
|---|---|
| `unknown_approval` | no pending approval matches |
| `already_decided` | this approval already has an accepted decision |
| `nonce_replayed` | the nonce was used before, including for another approval |
| `decision_expired` | the decision or the approval window closed |
| `subject_mismatch` | the approval is addressed to someone else |
| `digest_mismatch` | the decision covers a different action |
| `policy_version_mismatch` | policy changed after the approval was published |

Order matters here too: replay and expiry are checked before the binding fields, so a stale credential
learns nothing about which subject or digest would have been accepted.

Every attempt and every decision, accepted or rejected, is recorded as audit evidence.

## Not provided

- No real email, chat, or paging transport. The channel is a protocol; tests use a synthetic one.
- No human authentication. The verified identity arrives from the transport, exactly as in
  [`MCP_MUTATION.md`](MCP_MUTATION.md).
- No integration with the local approval store yet. This component decides whether a returned decision is
  trustworthy; wiring it to `CheckpointStore.decide_approval` is a later change.
- State is in memory for the life of the notifier. A durable store is required before a restart may rely on
  the attempt ceiling across processes.
