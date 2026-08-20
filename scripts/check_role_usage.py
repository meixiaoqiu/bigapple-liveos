"""盘点并校验生产代码中的直接角色判断。

本检查刻意不评价判断本身是否正确。它要求每一处直接读取或比较角色名的
生产代码，都在 ``ROLE_USAGE_CATALOG`` 中说明其用途：权威事实、授权、显示
或兼容。这样新增旁路时，项目检查会先要求开发者做出明确分类。
"""

from __future__ import annotations

import argparse
import ast
import os
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]

ROLE_USAGE_CATEGORIES = {
    "权威事实查询",
    "授权查询",
    "显示查询",
    "兼容用途",
}

# 每项均以 ``相对路径:行号`` 为键。分类说明是本次角色迁移的静态盘点基线，
# 新增直接角色判断必须同时更新此目录并接受代码审查。
ROLE_USAGE_CATALOG: dict[str, dict[str, str]] = {
    "core/admin_identity.py:239": {
        "category": "显示查询",
        "reason": "Django Admin 的任命历史搜索字段。",
    },
    "core/admin_identity.py:294": {
        "category": "显示查询",
        "reason": "Django Admin 的角色权限搜索字段。",
    },
    "core/admin_identity.py:297": {
        "category": "显示查询",
        "reason": "Django Admin 的角色权限排序字段。",
    },
    "core/application_services.py:298": {
        "category": "权威事实查询",
        "reason": "阻止已具守约者资格的账号重复提交成员报名。",
    },
    "core/authorization_services.py:261": {
        "category": "授权查询",
        "reason": "兼容授权后端下的完整工作台访问判定。",
    },
    "core/authorization_services.py:271": {
        "category": "授权查询",
        "reason": "OpenFGA 工作台授权前以 Django 当前守约者任命否决陈旧 tuple。",
    },
    "core/authorization_services.py:219": {
        "category": "授权查询",
        "reason": "OpenFGA 角色关系检查前以 Django 当前任命事实收窄，防止陈旧 tuple 恢复权限。",
    },
    "core/deliberator_exam_services.py:115": {
        "category": "权威事实查询",
        "reason": "开始或提交执衡者考试时确认当前守约者资格。",
    },
    "core/deliberator_exam_services.py:117": {
        "category": "权威事实查询",
        "reason": "阻止已有有效任期的成员重复参加执衡者考试。",
    },
    "core/identity_display.py:24": {
        "category": "显示查询",
        "reason": "身份展示投影确认某项规范角色当前有效。",
    },
    "core/identity_display.py:27": {
        "category": "显示查询",
        "reason": "身份展示投影读取规范角色对应的当前任命。",
    },
    "core/management/commands/openfga_rebuild_tuples.py:101": {
        "category": "权威事实查询",
        "reason": "从当前守约者资格、议事职责和维护职责重建 OpenFGA 关系。",
    },
    "core/management/commands/openfga_rebuild_tuples.py:121": {
        "category": "授权查询",
        "reason": "投影当前有效管理员任命，不读取任意角色任命。",
    },
    "core/management/commands/openfga_rebuild_tuples.py:120": {
        "category": "授权查询",
        "reason": "管理员 tuple 仅接受同时满足前置资格的当前职责事实。",
    },
    "core/management/commands/openfga_rebuild_tuples.py:157": {
        "category": "授权查询",
        "reason": "只投影管理员的显式权限绑定。",
    },
    "core/management/commands/repair_covenanter_credentials.py:34": {
        "category": "权威事实查询",
        "reason": "识别应持有守约者编号凭证的成员。",
    },
    "core/member_roles.py:81": {
        "category": "权威事实查询",
        "reason": "读取成员当前有效规范角色时复用统一前置条件过滤器。",
    },
    "core/member_roles.py:91": {
        "category": "权威事实查询",
        "reason": "由当前角色事实判断是否存在指定职责。",
    },
    "core/member_roles.py:112": {
        "category": "显示查询",
        "reason": "由守约者资格派生贡献者展示状态。",
    },
    "core/models/identity.py:78": {
        "category": "显示查询",
        "reason": "成员模型读取当前规范角色名称以供展示。",
    },
    "core/models/identity.py:82": {
        "category": "显示查询",
        "reason": "成员模型拼接当前角色名称的显示文本。",
    },
    "core/permission_services.py:49": {
        "category": "授权查询",
        "reason": "权限检查确认受保护权限的守约者资格前置条件。",
    },
    "core/permission_services.py:94": {
        "category": "授权查询",
        "reason": "权限查询筛选具备受保护权限的守约者。",
    },
    "core/professional_qualification_services.py:55": {
        "category": "权威事实查询",
        "reason": "录入专业资格前确认成员当前具备守约者资格。",
    },
    "core/professional_qualification_services.py:143": {
        "category": "授权查询",
        "reason": "专业资格授权查询确认成员当前具备守约者资格。",
    },
    "core/professional_qualification_services.py:171": {
        "category": "授权查询",
        "reason": "筛选可用于专业提案授权的当前守约者。",
    },
    "core/management/commands/openfga_rebuild_tuples.py:141": {
        "category": "授权查询",
        "reason": "只投影规范财务组织中的基线财务角色任命。",
    },
    "core/management/commands/openfga_rebuild_tuples.py:142": {
        "category": "授权查询",
        "reason": "财务职责 tuple 持有人必须持续具备守约者资格。",
    },
    "core/management/commands/openfga_rebuild_tuples.py:176": {
        "category": "授权查询",
        "reason": "只投影规范财务角色的 finance 权限绑定。",
    },
    "core/role_assignment_services.py:45": {
        "category": "权威事实查询",
        "reason": "校验目录角色是否需要当前守约者资格。",
    },
    "core/role_assignment_services.py:52": {
        "category": "权威事实查询",
        "reason": "校验动态角色的守约者资格前置条件。",
    },
    "core/role_audit.py:289": {
        "category": "权威事实查询",
        "reason": "盘点角色是否满足守约者资格前置条件。",
    },
    "workspace/deliberator_exam_views.py:46": {
        "category": "显示查询",
        "reason": "执衡者考试首页显示当前成员是否已有有效任期。",
    },
    "core/openfga_projection_services.py:119": {
        "category": "授权查询",
        "reason": "增量投影仅为持续满足守约者前置条件的当前任命写入 tuple。",
    },
}

ROLE_HELPER_CALLS = {
    "active_member_role_names",
    "active_role_names",
    "member_has_role",
    "member_role_filter",
}

SKIPPED_PATH_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "migrations",
    "node_modules",
    "staticfiles",
    "tests",
}


@dataclass(frozen=True)
class RoleUsage:
    """一处生产代码中的直接角色判断。"""

    location: str
    detectors: tuple[str, ...]


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_role_name_reference(node: ast.AST) -> bool:
    """判断表达式是否读取 ``role.name`` 或 ``assignment.role.name``。"""

    if not isinstance(node, ast.Attribute) or node.attr != "name":
        return False
    value = node.value
    return isinstance(value, ast.Name) and value.id == "role" or (
        isinstance(value, ast.Attribute) and value.attr == "role"
    )


class _RoleUsageVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.found: dict[int, set[str]] = defaultdict(set)

    def _add(self, node: ast.AST, detector: str) -> None:
        self.found[node.lineno].add(detector)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = _call_name(node.func)
        if call_name in ROLE_HELPER_CALLS:
            self._add(node, f"调用 {call_name}")
        for keyword in node.keywords:
            if keyword.arg in {"role__name", "role__name__in"}:
                self._add(node, f"查询条件 {keyword.arg}")
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        if any(_is_role_name_reference(item) for item in [node.left, *node.comparators]):
            self._add(node, "比较 role.name")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and node.value == "role__name":
            self._add(node, "读取字段 role__name")
        self.generic_visit(node)


def discover_role_usages(root: Path = ROOT) -> list[RoleUsage]:
    """返回所有应在角色用途目录中分类的生产代码位置。"""

    usages: list[RoleUsage] = []
    paths: list[Path] = []
    for directory, child_directories, file_names in os.walk(root):
        child_directories[:] = [name for name in child_directories if name not in SKIPPED_PATH_PARTS]
        paths.extend(Path(directory) / name for name in file_names if name.endswith(".py"))
    for path in sorted(paths):
        relative_path = path.relative_to(root).as_posix()
        if relative_path == "scripts/check_role_usage.py":
            continue
        if path.name == "tests.py" or SKIPPED_PATH_PARTS.intersection(path.relative_to(root).parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _RoleUsageVisitor(relative_path)
        visitor.visit(tree)
        for line_no, detectors in sorted(visitor.found.items()):
            usages.append(
                RoleUsage(
                    location=f"{relative_path}:{line_no}",
                    detectors=tuple(sorted(detectors)),
                )
            )
    return usages


def check_role_usage_catalog(
    root: Path = ROOT,
    catalog: Mapping[str, Mapping[str, str]] = ROLE_USAGE_CATALOG,
) -> list[str]:
    """返回未分类或已失效的直接角色判断错误。"""

    errors: list[str] = []
    usages = {usage.location: usage for usage in discover_role_usages(root)}
    for location, usage in sorted(usages.items()):
        catalog_entry = catalog.get(location)
        if catalog_entry is None:
            errors.append(
                f"未分类的直接角色判断：{location}（{', '.join(usage.detectors)}）"
            )
            continue
        category = catalog_entry.get("category", "")
        if category not in ROLE_USAGE_CATEGORIES:
            errors.append(f"角色用途分类无效：{location}（{category or '缺失'}）")
        if not catalog_entry.get("reason", "").strip():
            errors.append(f"角色用途缺少中文说明：{location}")

    for location in sorted(catalog):
        if location not in usages:
            errors.append(f"角色用途目录包含已失效位置：{location}")
    return errors


def _report_payload(root: Path) -> dict[str, object]:
    usages = discover_role_usages(root)
    return {
        "检查目录": str(root),
        "直接角色判断数量": len(usages),
        "角色用途目录": [
            {
                "位置": usage.location,
                "检测方式": list(usage.detectors),
                "分类": ROLE_USAGE_CATALOG.get(usage.location, {}).get("category", "未分类"),
                "说明": ROLE_USAGE_CATALOG.get(usage.location, {}).get("reason", ""),
            }
            for usage in usages
        ],
        "错误": check_role_usage_catalog(root),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查生产代码中的直接角色判断是否已分类。")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = _report_payload(ROOT)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"直接角色判断：{report['直接角色判断数量']} 处")
        for item in report["角色用途目录"]:
            print(f"- {item['位置']}：{item['分类']}；{item['说明']}")
        for error in report["错误"]:
            print(f"错误：{error}")
    return 1 if report["错误"] else 0


if __name__ == "__main__":
    sys.exit(main())
