from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from simulation.runtime_storage import clean_simulation_world_runtime
from worlds.models import WorldRegistry


class SimulationRuntimeStorageTests(SimpleTestCase):
    def setUp(self):
        for alias in ("avatars", "avatar_temporary"):
            storages._storages.pop(alias, None)
        self.world = WorldRegistry(
            world_id="simulation0001",
            world_type=WorldRegistry.WorldType.SIMULATION,
            status=WorldRegistry.Status.ACTIVE,
        )

    def test_cleanup_deletes_only_target_world_runtime(self):
        target = "simulation0001/runtime/current-assets/avatars/a.webp"
        temporary = "simulation0001/runtime/temporary/avatar-uploads/b"
        other_world = "simulation0002/runtime/current-assets/avatars/c.webp"
        archive_like = "simulation0001/archives/snapshot-1/manifest.json"
        storages["avatars"].save(target, ContentFile(b"a"))
        storages["avatars"].save(other_world, ContentFile(b"c"))
        storages["avatars"].save(archive_like, ContentFile(b"archive"))
        storages["avatar_temporary"].save(temporary, ContentFile(b"b"))

        clean_simulation_world_runtime(self.world)

        self.assertFalse(storages["avatars"].exists(target))
        self.assertFalse(storages["avatar_temporary"].exists(temporary))
        self.assertTrue(storages["avatars"].exists(other_world))
        self.assertTrue(storages["avatars"].exists(archive_like))

    def test_cleanup_rejects_real_world(self):
        real = WorldRegistry(world_id="realworld", world_type=WorldRegistry.WorldType.REAL)
        with self.assertRaises(CommandError):
            clean_simulation_world_runtime(real)

    @patch("simulation.runtime_storage._list_keys", side_effect=OSError("storage down"))
    def test_cleanup_fails_closed_on_storage_error(self, _list_keys):
        with self.assertRaises(CommandError):
            clean_simulation_world_runtime(self.world)
