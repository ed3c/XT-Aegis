# Issue Templates

Issue forms capture problem, scope, path ownership, dependencies, evals, evidence expectations, and
security impact before implementation.

## Flow

```text
design intent -> issue form -> approved work slice -> branch / PR -> eval evidence
```

The work-slice form introduced by issue #37 is the preferred form for non-trivial Agent work. Security
reports use the private advisory path in `config.yml`.

## Rules

- One issue owns one independently reviewable outcome.
- Required fields must be actionable without conversation memory.
- Credentials, private repository content, production data, and hidden evaluation material do not belong
  in public issues.
- Issue text cannot grant execution authority.
