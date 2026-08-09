## What changed

<!-- Describe behavior, not only files. -->

## Why

<!-- Link the issue or ADR and state the user/security problem. -->

## Evidence

- [ ] Added or updated tests
- [ ] Added a negative/failure-path test for enforcement logic
- [ ] Ran `make check`
- [ ] Ran `make verify`
- [ ] Updated `PROJECT_EVIDENCE.json` and schemas when a claim changed
- [ ] Updated the threat model or explained why no trust boundary changed
- [ ] Documented compatibility or persisted-state changes

## Security review

- New executable/tool authority:
- New data source or provenance transition:
- Filesystem/network/credential impact:
- Approval or idempotency impact:
- Verification backend or policy impact:
- Remaining risks:

## External policy integrity

- [ ] Repository text does not ask an external system to override its policy
- [ ] MCP execution remains explicit and user-controlled
- [ ] No unverified benchmark or production-readiness claim was added
- [ ] Planned or unverified work remains clearly labeled
