# Verification Schemas

JSON Schemas define the portable contract for registries, results, and evidence bundles. Unknown fields
and incompatible versions fail closed.

Schema evolution requires compatibility/migration analysis, generated-model synchronization where
applicable, positive and negative fixtures, packaged-asset consistency, and release notes. A schema
change does not automatically promote any claim.

`benchmark-report.schema.json` describes a profile-bound measurement artifact. Every repetition, including
failures and deadline overruns, stays in `trials[]`; `summaries[]` is derived and never replaces the raw
data. A schema-valid report is not a performance claim.
