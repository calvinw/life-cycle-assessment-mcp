import pathlib
import types
import unittest
from unittest.mock import Mock, patch

import lca_engine


class ProductionStartupTests(unittest.TestCase):
    def setUp(self):
        self.original_ready = lca_engine._startup_databases_ready

    def tearDown(self):
        lca_engine._startup_databases_ready = self.original_ready

    def test_fresh_projection_is_reused(self):
        fresh = {
            "exists": True,
            "fresh": True,
            "path": "/tmp/search.sqlite3",
            "source_databases": ["bafu", "biosphere3", "mock_background"],
        }
        with (
            patch("lca_search.get_projection_status", return_value=fresh) as get_status,
            patch("lca_search.build_search_database") as build,
        ):
            result = lca_engine._ensure_search_projection()

        self.assertEqual(result, fresh)
        get_status.assert_called_once_with(project=lca_engine.BRIGHTWAY_PROJECT)
        build.assert_not_called()

    def test_missing_or_stale_projection_is_built_and_rechecked(self):
        stale = {"exists": False, "fresh": False, "reason": "not built"}
        fresh = {
            "exists": True,
            "fresh": True,
            "path": "/tmp/search.sqlite3",
            "source_databases": ["bafu", "biosphere3", "mock_background"],
        }
        with (
            patch("lca_search.get_projection_status", side_effect=[stale, fresh]),
            patch("lca_search.build_search_database") as build,
        ):
            result = lca_engine._ensure_search_projection()

        self.assertEqual(result, fresh)
        build.assert_called_once_with(
            databases=["bafu", "mock_background"],
            project=lca_engine.BRIGHTWAY_PROJECT,
        )

    def test_failed_freshness_validation_stops_startup(self):
        stale = {"exists": True, "fresh": False, "reason": "source changed"}
        with (
            patch("lca_search.get_projection_status", side_effect=[stale, stale]),
            patch("lca_search.build_search_database"),
            self.assertRaisesRegex(RuntimeError, "freshness validation failed"),
        ):
            lca_engine._ensure_search_projection()

    def test_startup_check_runs_once_for_existing_bafu_volume(self):
        projects = Mock()
        fake_bd = types.SimpleNamespace(projects=projects, databases={"bafu": {}})
        lca_engine._startup_databases_ready = False

        with (
            patch.object(lca_engine, "bd", fake_bd),
            patch.object(
                lca_engine,
                "ensure_mock_background_database",
                return_value={"changed": False, "activities": 3},
            ),
            patch.object(lca_engine, "_ensure_search_projection") as ensure_projection,
        ):
            lca_engine._ensure_databases()
            lca_engine._ensure_databases()

        projects.set_current.assert_called_once_with(lca_engine.BRIGHTWAY_PROJECT)
        ensure_projection.assert_called_once_with()

    def test_startup_removes_legacy_shared_foreground_database(self):
        projects = Mock()
        databases = {"bafu": {}, "foreground": {}}
        fake_bd = types.SimpleNamespace(projects=projects, databases=databases)
        lca_engine._startup_databases_ready = False

        with (
            patch.object(lca_engine, "bd", fake_bd),
            patch.object(
                lca_engine,
                "ensure_mock_background_database",
                return_value={"changed": False, "activities": 3},
            ),
            patch.object(lca_engine, "_ensure_search_projection"),
        ):
            lca_engine._ensure_databases()

        self.assertNotIn("foreground", databases)

    def test_startup_installs_bundled_mock_background(self):
        projects = Mock()
        fake_bd = types.SimpleNamespace(projects=projects, databases={"bafu": {}})
        lca_engine._startup_databases_ready = False

        with (
            patch.object(lca_engine, "bd", fake_bd),
            patch.object(
                lca_engine,
                "ensure_mock_background_database",
                return_value={"changed": False, "activities": 3},
            ) as install_mock,
            patch.object(lca_engine, "_ensure_search_projection"),
        ):
            lca_engine._ensure_databases()

        install_mock.assert_called_once_with(
            fake_bd, biosphere_database=lca_engine.BIOSPHERE_DB
        )

    def test_first_boot_reloads_metadata_after_extracting_release(self):
        projects = Mock()
        databases = {}
        fake_bd = types.SimpleNamespace(
            projects=projects,
            databases=databases,
            Database=Mock(return_value=[]),
        )
        lca_engine._startup_databases_ready = False

        project_selections = 0

        def reload_project(_project):
            nonlocal project_selections
            project_selections += 1
            if project_selections == 2:
                databases["bafu"] = {}
                databases["biosphere3"] = {}
                databases["foreground"] = {}

        projects.set_current.side_effect = reload_project

        with (
            patch.object(lca_engine, "bd", fake_bd),
            patch("urllib.request.urlretrieve"),
            patch("tarfile.open") as open_tar,
            patch.object(pathlib.Path, "stat") as path_stat,
            patch.object(pathlib.Path, "unlink"),
            patch.object(
                lca_engine,
                "ensure_mock_background_database",
                return_value={"changed": False, "activities": 3},
            ),
            patch.object(lca_engine, "_ensure_search_projection"),
        ):
            path_stat.return_value.st_size = 1
            open_tar.return_value.__enter__.return_value.extractall.return_value = None
            lca_engine._ensure_databases()

        self.assertEqual(projects.set_current.call_count, 2)
        self.assertIn("biosphere3", databases)
        self.assertNotIn("foreground", databases)

    def test_docker_image_copies_projection_module(self):
        dockerfile = pathlib.Path(__file__).parents[1] / "Dockerfile"
        self.assertIn("lca_search.py", dockerfile.read_text())
        self.assertIn("COPY mock_background/ ./mock_background/", dockerfile.read_text())


if __name__ == "__main__":
    unittest.main()
