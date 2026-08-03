"""Simulation-world runtime object cleanup, separate from historical archives."""

from __future__ import annotations

from django.core.files.storage import storages
from django.core.management.base import CommandError

from core.file_storage.keys import world_runtime_prefix
from worlds.models import WorldRegistry


def _list_keys(storage, prefix: str) -> list[str]:
    root = prefix.rstrip("/")
    try:
        directories, files = storage.listdir(root)
    except FileNotFoundError:
        return []
    result = [f"{root}/{name}" for name in files]
    for directory in directories:
        result.extend(_list_keys(storage, f"{root}/{directory}"))
    return result


def clean_simulation_world_runtime(world: WorldRegistry) -> int:
    """Delete only one simulation world's runtime objects, never archive data."""

    if world.world_type != WorldRegistry.WorldType.SIMULATION:
        raise CommandError("拒绝清理非仿真 world 的 runtime 文件。")
    prefix = world_runtime_prefix(world.world_id)
    deleted: set[str] = set()
    try:
        # Test/local aliases may be separate storage instances; OCI aliases share
        # one bucket. Repeating the safe prefix scan is harmless and keeps both
        # configurations correct.
        for alias in ("avatars", "avatar_temporary"):
            storage = storages[alias]
            for key in _list_keys(storage, prefix):
                if not key.startswith(prefix) or ".." in key or "\\" in key:
                    raise CommandError("存储后端返回了 world runtime 前缀之外的对象。")
                storage.delete(key)
                deleted.add(key)
    except CommandError:
        raise
    except Exception as exc:
        raise CommandError(f"清理仿真 world runtime 文件失败：{type(exc).__name__}") from exc
    return len(deleted)
