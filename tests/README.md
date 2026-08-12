# Test Suite

Tests provide positive, negative, failure-path, compatibility, and integrity evidence. Passing tests are
necessary but not sufficient for production or universal security claims.

## Flow

```text
contract / implementation / fixture
  -> deterministic test
  -> bounded result
  -> CI evidence
  -> claim status review
```

Tests should expose trust-boundary failures, rollback behavior, unavailable protection, timeout, redaction,
schema rejection, and replay/approval confusion. See [`AGENTS.md`](AGENTS.md).
