"""SKILL.md compiler that executes only validated YAML, never Markdown prose."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from pydantic import ValidationError

from xt_aegis.errors import SkillCompileError
from xt_aegis.models import CompiledSkill, SkillContract


_FRONTMATTER_DELIMITER = "---"


class SkillCompiler:
    """Compile the explicit YAML contract at the beginning of a SKILL.md file."""

    @staticmethod
    def compile(path: str | Path) -> CompiledSkill:
        skill_path = Path(path)
        try:
            text = skill_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillCompileError(f"cannot read skill: {skill_path}") from exc
        return SkillCompiler.compile_text(text, source_path=str(skill_path))

    @staticmethod
    def compile_text(text: str, *, source_path: str = "<memory>") -> CompiledSkill:
        normalized = text.replace("\r\n", "\n")
        lines = normalized.splitlines()
        if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
            raise SkillCompileError("SKILL.md must start with YAML front matter")

        closing_index: int | None = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == _FRONTMATTER_DELIMITER:
                closing_index = index
                break
        if closing_index is None:
            raise SkillCompileError("SKILL.md front matter is not closed")

        yaml_text = "\n".join(lines[1:closing_index])
        markdown_body = "\n".join(lines[closing_index + 1 :]).strip()
        try:
            loaded = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            raise SkillCompileError(f"invalid YAML front matter: {exc}") from exc
        if not isinstance(loaded, dict):
            raise SkillCompileError("front matter must be a YAML mapping")

        try:
            contract = SkillContract.model_validate(loaded)
        except ValidationError as exc:
            raise SkillCompileError(f"invalid skill contract: {exc}") from exc

        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return CompiledSkill(
            contract=contract,
            markdown_body=markdown_body,
            source_path=source_path,
            source_sha256=digest,
        )
