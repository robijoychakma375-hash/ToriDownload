"""Startup preferences survive download-folder changes and quote paths safely."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import startup


class StartupTests(unittest.TestCase):
    def test_folder_and_autostart_preferences_survive_each_other(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'settings.json'
            self.assertTrue(startup.startup_enabled(config))
            self.assertFalse(startup.startup_enabled(config, default=False))
            startup.save_config(config, {'launch_on_login':False})
            startup.save_config(config, {'download_folder':r'C:\Tori Files'})
            self.assertFalse(startup.startup_enabled(config))
            self.assertEqual(startup.read_config(config)['download_folder'], r'C:\Tori Files')

    def test_frozen_startup_command_quotes_exe_path(self):
        with patch.object(startup.sys, 'frozen', True, create=True), \
             patch.object(startup.sys, 'executable', r'C:\Program Files\Tori Download\ToriDownload.exe'), \
             patch.object(startup.Path, 'resolve', lambda self: self):
            command = startup.startup_command()
        self.assertEqual(command, subprocess.list2cmdline([
            r'C:\Program Files\Tori Download\ToriDownload.exe', '--background']))


if __name__ == '__main__':
    unittest.main()
