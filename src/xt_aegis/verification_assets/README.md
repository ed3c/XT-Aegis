# Packaged Verification Assets

These assets allow an installed wheel to expose the same claim registry contract as the source tree.

The root `PROJECT_EVIDENCE.json` and `verification/` schemas/recipes remain the reviewed sources of truth.
Packaging tests must detect drift. Never update a mirrored asset without updating and validating its root
counterpart in the same owning implementation PR.
