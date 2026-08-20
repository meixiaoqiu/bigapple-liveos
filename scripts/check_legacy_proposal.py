from __future__ import annotations

import re
import os
from pathlib import Path


FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("旧模型 ProposalVote", re.compile(r"\bProposalVote\b")),
    ("旧模型 ProposalExecution", re.compile(r"\bProposalExecution\b")),
    ("旧提案类型选民规则模型", re.compile(r"\bProposalTypeElectorateRule\b")),
    ("旧提案执行来源字段", re.compile(r"\bsource_proposal_execution\b")),
    ("旧提案来源字段", re.compile(r"\bsource_proposal\b")),
    ("旧领域模块", re.compile(r"\bcore\.(?:proposals|electorate_rules)\b")),
    ("旧数据库表", re.compile(r"\bcore_(?:proposal|proposalvote|proposalexecution|proposaltypeelectoraterule)\b")),
)

SCAN_SUFFIXES = {".py", ".html", ".json", ".fga", ".md", ".yaml", ".yml"}
IGNORED_PARTS = {
    ".git",
    ".venv",
    ".codex",
    ".agents",
    "__pycache__",
    "build",
    "logs",
    "media",
    "node_modules",
    "output",
    "staticfiles",
    "temp",
    "uploads",
    "var",
}
ALLOWED_LIVEOS_PREFIXES = (
    Path("openspec/changes"),
    Path("core/legacy_proposal_schema.py"),
    Path("core/tests/test_legacy_proposal_schema.py"),
    Path("scripts/check_legacy_proposal.py"),
)


def _is_beneath(path: Path, prefix: Path) -> bool:
    return path == prefix or prefix in path.parents


def check_legacy_proposal_residuals(*, liveos_root: Path, docs_root: Path | None = None) -> list[str]:
    """返回产品源码与公开文档中的旧提案标识；过程文档和检查器自身除外。"""

    roots = (("Live OS", liveos_root.resolve()),)
    if docs_root is not None and docs_root.exists():
        roots += (("Docs", docs_root.resolve()),)

    errors: list[str] = []
    for root_label, root in roots:
        paths: list[Path] = []
        for directory, child_directories, file_names in os.walk(root):
            child_directories[:] = [name for name in child_directories if name not in IGNORED_PARTS]
            paths.extend(Path(directory) / name for name in file_names)
        for path in sorted(paths):
            if path.suffix.lower() not in SCAN_SUFFIXES:
                continue
            relative = path.relative_to(root)
            if root_label == "Live OS" and any(_is_beneath(relative, prefix) for prefix in ALLOWED_LIVEOS_PREFIXES):
                continue
            content = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(content.splitlines(), start=1):
                for label, pattern in FORBIDDEN_PATTERNS:
                    if pattern.search(line):
                        errors.append(f"旧提案残余：{root_label}/{relative.as_posix()}:{line_number}（{label}）")
    return errors
