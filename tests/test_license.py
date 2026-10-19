from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class LicenseFiles(unittest.TestCase):
    def test_python_distribution_preserves_project_license(self):
        license_text=(ROOT/'LICENSE').read_text()
        self.assertTrue(license_text.startswith('MIT License\n'))
        self.assertEqual((ROOT/'python/LICENSE').read_text(),license_text)
        self.assertIn('license = { file = "LICENSE" }',(ROOT/'python/pyproject.toml').read_text())
        self.assertIn('license = "MIT"',(ROOT/'wasm/Cargo.toml').read_text())


if __name__=='__main__':unittest.main()
