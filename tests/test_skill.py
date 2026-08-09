from __future__ import annotations

import pytest

from xt_aegis.errors import SkillCompileError
from xt_aegis.skill import SkillCompiler


VALID_SKILL = """---
schema_version: "1.0"
name: safe_demo
description: A sufficiently detailed safe demonstration contract.
allowed_executables: [python3]
allowed_write_paths: [sample/app.py]
network_policy: deny
preconditions: []
postconditions: []
---
# Documentation

```bash
rm -rf /
```
"""


def test_compiler_uses_only_frontmatter() -> None:
    compiled = SkillCompiler.compile_text(VALID_SKILL)
    assert compiled.contract.name == "safe_demo"
    assert "rm -rf /" in compiled.markdown_body
    assert compiled.contract.allowed_executables == {"python3"}


def test_compiler_requires_frontmatter() -> None:
    with pytest.raises(SkillCompileError, match="must start"):
        SkillCompiler.compile_text("# missing")


def test_compiler_rejects_unknown_fields() -> None:
    with pytest.raises(SkillCompileError, match="invalid skill contract"):
        SkillCompiler.compile_text(VALID_SKILL.replace("preconditions: []", "unknown: true\npreconditions: []"))


def test_compiler_rejects_unclosed_frontmatter() -> None:
    with pytest.raises(SkillCompileError, match="not closed"):
        SkillCompiler.compile_text("---\nname: x")
