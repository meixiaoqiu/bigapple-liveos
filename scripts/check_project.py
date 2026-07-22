from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACTS_ROOT = (ROOT / "../bigapple-docs/static/technical-contracts").resolve()
CONTRACTS_ROOT = Path(os.environ.get("BIG_APPLE_CONTRACTS_ROOT", str(DEFAULT_CONTRACTS_ROOT))).resolve()

REQUIRED_CONTRACT_FILES = [
    "schemas/member.schema.json",
    "schemas/task.schema.json",
    "schemas/ledger-entry.schema.json",
    "schemas/resource.schema.json",
    "schemas/event.schema.json",
    "schemas/dispute.schema.json",
    "schemas/ruleset.schema.json",
    "schemas/capacity-assessment.schema.json",
    "openapi/live-os.v0.1.openapi.json",
]

def check_python_syntax() -> list[str]:
    errors: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        if {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "node_modules",
            "staticfiles",
        }.intersection(path.parts):
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"Python syntax error in {path}: {exc}")
    return errors


def check_contract_files() -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_CONTRACT_FILES:
        path = CONTRACTS_ROOT / relative
        if not path.exists():
            errors.append(f"Missing contract file: {path}")
            continue
        if path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(f"Invalid contract JSON {path}: {exc}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run lightweight Big Apple Live OS repository checks.")
    parser.add_argument(
        "--check-contracts",
        action="store_true",
        help="also verify technical contracts; set BIG_APPLE_CONTRACTS_ROOT to override the path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = []
    errors.extend(check_python_syntax())
    if args.check_contracts:
        errors.extend(check_contract_files())

    if errors:
        print("Project check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Project check passed.")
    print(f"Repository: {ROOT}")
    if args.check_contracts:
        print(f"Contracts:  {CONTRACTS_ROOT}")
    else:
        print("Contracts:  skipped (use --check-contracts for API/schema compatibility checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
