"""Verify portable releases carry their own mode marker and browser extension."""
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from package_portable import VERSION, package


class PackageTests(unittest.TestCase):
    def test_zip_contains_executable_marker_and_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / 'ToriDownload.exe'
            executable.write_bytes(b'MZ test fixture')
            extension = root / 'extension'
            extension.mkdir()
            (extension / 'manifest.json').write_text('{}')
            (extension / 'background.js').write_text('// test')
            output = package(executable, extension, root / 'release.zip')
            with ZipFile(output) as archive:
                names = archive.namelist()
                prefix = f'ToriDownload-Portable-v{VERSION}/'
                self.assertIn(prefix+'ToriDownload.exe', names)
                self.assertIn(prefix+'portable.flag', names)
                self.assertIn(prefix+'extension/manifest.json', names)
                self.assertIn(prefix+'extension/background.js', names)
                self.assertNotIn(prefix+'ToriData/settings.json', names)
                self.assertEqual(archive.read(prefix+'ToriDownload.exe'), executable.read_bytes())


if __name__ == '__main__':
    unittest.main()
