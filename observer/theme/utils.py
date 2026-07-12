"""Theme utility helpers."""

from __future__ import annotations


def _clean_path(value: object, fallback: str = "") -> str:
    return str(value or fallback).replace("\\", "/").strip("/")


def _bool(value: object, fallback: bool) -> bool:
    if value is None:
        return fallback
    return bool(value)
