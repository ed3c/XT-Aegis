# Git Town Adoption Checklist

## 1. Suitability

- [ ] More than one dependent PR or recurring stack workflow exists.
- [ ] Each feature branch has one clear owner.
- [ ] Feature branches may be rebased and safely force-updated.
- [ ] Branch protection and required checks are compatible with the chosen workflow.
- [ ] A dedicated checkout can contain only manifest-declared branches.
- [ ] A human or named Agent owns semantic conflicts.
- [ ] The forge exposes reliable PR head/base/state metadata.
- [ ] Git Town and unattended sync have separate adoption decisions.

## 2. Repository contract

- [ ] Root and local Agent/contributor instructions are read.
- [ ] Existing Git Town files, open PRs, branch collisions, and prior issues are discovered.
- [ ] An eval-first issue exists before implementation.
- [ ] One observable outcome is assigned to each branch/PR.
- [ ] Sibling paths are disjoint or a shared integration owner is named.
- [ ] The active manifest contains only open PRs whose bases match declared parents.
- [ ] A header-only manifest blocks synchronization before mutation.

## 3. License and supply chain

- [ ] Exact Git Town version/tag and source commit are recorded.
- [ ] License ID, exact text/blob identity, notice obligations, and local digest are recorded.
- [ ] Configuration schema for the exact version is reviewed.
- [ ] Official checksums source and package checksum are verified.
- [ ] Installed-binary checksum is supplied by an immutable worker profile.
- [ ] No `latest`, unpinned package channel, or `curl | sh` install path exists.
- [ ] Documentation avoids a zero-risk legal or supply-chain claim.

## 4. Conservative configuration

- [ ] Interactive prompts are disabled for unattended work.
- [ ] Feature branches use the reviewed rebase strategy.
- [ ] The perennial/default branch uses the reviewed fast-forward strategy.
- [ ] Automatic semantic conflict resolution is disabled.
- [ ] Auto-sync, push hooks, tag sync, upstream sync, implicit publication, and PR-body mutation are disabled unless explicitly justified.
- [ ] Exact pinned CLI/schema validation passes.

## 5. Worker preflight and mutation

- [ ] Expected repository and origin identity are exact and credential-free.
- [ ] Worktree is clean and no Git operation is suspended.
- [ ] Exclusive repository lock is held.
- [ ] Local and origin-tracking refs, upstreams, parents, and PR head/base/state are verified.
- [ ] A no-push dry run passes before mutation.
- [ ] Timeout, bounded logs, private state, and atomic status are configured.
- [ ] Complete local/tracking refs and parent metadata are snapshotted before sync.
- [ ] Preflight failure never invokes `git town undo`.
- [ ] Recovery acts only on evidence from the current mutating run.
- [ ] `failed_restored` requires complete state equality.
- [ ] Semantic conflicts stop unattended execution.

## 6. Evidence and deployment

- [ ] Repository-side fixture passes.
- [ ] Exact binary and ShellCheck results are preserved.
- [ ] Real clean sync, semantic conflict, partial mutation, remote race, timeout, and secret-canary evals pass.
- [ ] Failed and timed-out trials remain in evidence.
- [ ] Live Worker authorization is scoped to one immutable profile.
- [ ] Documentation/tooling merge does not silently authorize deployment.
