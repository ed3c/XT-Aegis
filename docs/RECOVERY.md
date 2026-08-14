# Crash Recovery, Cancellation, and Deadlines

## Named transitions

`xt_aegis.lifecycle.Transition` is the single list of boundaries where the runtime can be interrupted.
Fault injection, cancellation, and deadline enforcement all address the same names through one exit
(`HarnessRunner._transition`), so a new boundary cannot honor one mechanism and silently skip another.

```text
request_received -> policy_evaluated -> step_prepared -> approval_resolved -> snapshot_created
  -> precondition_checked -> action_started -> action_completed -> postcondition_checked
  -> [rollback_started -> rollback_completed] -> result_saved
```

Interruption happens **at** a boundary, never inside a snapshot copy or a database write.

## Recovery transition table

`resume position` is `MAX(step_number) + 1` over terminal step rows. "Clean" means the owned workspace
still matches its pre-run content.

| Killed at | Persisted state after the kill | Workspace | Restart behavior |
|---|---|---|---|
| `request_received` | no step row | clean | the same request runs from the beginning |
| `policy_evaluated` | no step row | clean | the same request runs from the beginning |
| `step_prepared` | step row, non-terminal | clean | the step is re-prepared under the same identity; no duplicate step is created |
| `approval_resolved` | step row, approval claimed | clean | a claimed single-use approval is already consumed; the request must present a valid approval again |
| `snapshot_created` | step row, snapshot directory orphaned | clean | the orphaned snapshot lives under the abandoned run root and is not adopted; a new transaction takes a fresh snapshot |
| `precondition_checked` | step row, non-terminal | clean | the same request runs again from the beginning |
| `action_started` | step row, non-terminal | clean or mid-write | the atomic write either happened or did not; the next run re-applies the declared content |
| `action_completed` | step row, non-terminal | mutated, uncommitted | the mutation is not a terminal result; the next run re-applies and re-asserts it |
| `postcondition_checked` | step row, non-terminal | mutated, uncommitted | as above |
| `rollback_started` | step row, non-terminal | partially restored | the next run re-applies the declared content and re-asserts; rollback integrity of the abandoned attempt is not claimed |
| `rollback_completed` | step row, non-terminal | restored | the next run proceeds normally |
| `result_saved` | terminal step row | matches the terminal result | the same identity replays the persisted terminal result; no work is repeated |

The invariant a restart must satisfy is one of: **resume from a documented safe transition**, or **fail
closed**. A partial mutation is never promoted to a terminal result, because the terminal row is written
last.

## Idempotency after a crash

A successful protected action is not repeated. The terminal result is bound to the canonical request
digest, so a restart with the same identity returns the cached terminal result and the resume position does
not move. A changed payload produces a different digest and is refused as an identity conflict rather than
silently re-executed.

## Cancellation and deadlines

```python
from xt_aegis.lifecycle import CancellationToken

token = CancellationToken.with_timeout(30.0)
result = runner.execute(request, cancellation=token)
```

- Cancellation is cooperative and is observed at the next transition.
- A deadline is a wall-clock instant, checked at the same transitions. `execute(timeout_seconds=...)`
  creates one implicitly when no token is passed.
- Cancellation wins over an expired deadline, so an operator-initiated stop is never reported as a timeout.
- If a snapshot is open when the boundary fails, the workspace is rolled back and the result is
  `rolled_back` with reason `cancelled` or `deadline_exceeded`. Before a snapshot exists, the result is
  `blocked` with the same reason.
- Either way the result is persisted, so a restart replays the terminal record instead of executing the
  request again.

Command timeouts remain separate and unchanged: a command that exceeds its declared `timeout_seconds` has
its process group terminated and cannot be an accepted exit.

## Evidence

`tests/test_crash_recovery.py` spawns a real child process for each transition in the table above, kills it
with `os._exit` at that exact boundary through the fault-injection seam, and then restarts against the same
database and run directory to assert the documented state. `tests/crash_child.py` is that child.

The fault hook is a constructor argument that defaults to `None`; production runs pass nothing and pay one
`if` per transition.

## Non-goals

- Distributed failover and multi-worker coordination belong to #14.
- Exactly-once external side effects belong to #15; an idempotent workspace mutation is not an idempotent
  external API call.
- A killed process cannot be resumed mid-command; the contract is a documented safe state, not
  continuation.
