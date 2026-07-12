#!/usr/bin/env python
"""Django command-line entry point for Big Apple Live OS."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "live_os.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django is not installed. Install project dependencies with "
            "`python -m pip install -e \".[dev]\"`."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

