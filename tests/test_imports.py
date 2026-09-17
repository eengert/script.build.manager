import sys
import os
import unittest

# Make the repo root importable so resources.lib can be found when running
# tests from any directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestBuildManagerImports(unittest.TestCase):
    """Verify that core modules are importable outside the Kodi runtime."""

    def test_build_manager_class_importable(self):
        from resources.lib.build_manager import BuildManager
        self.assertIsNotNone(BuildManager)

    def test_build_manager_instantiates(self):
        from resources.lib.build_manager import BuildManager
        bm = BuildManager()
        self.assertIsInstance(bm, BuildManager)

    def test_resources_lib_is_package(self):
        import resources.lib
        self.assertIsNotNone(resources.lib)


if __name__ == '__main__':
    unittest.main()
