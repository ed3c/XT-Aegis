# Claim Recipes

Each JSON file is a reviewable, bounded executable plan for one claim. The corresponding entry in
`PROJECT_EVIDENCE.json` is the registry source and must remain consistent.

A recipe declares argv, relative cwd, timeout, expected exit codes, denied network, output bound,
artifacts, expected status, and limitations. It cannot provide shell strings, credentials, arbitrary
environment, mounts, or backend policy.
