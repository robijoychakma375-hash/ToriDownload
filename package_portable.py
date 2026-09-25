"""Package the Windows one-file executable with its unpacked browser extension."""
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

VERSION = '0.22'


def package(executable, extension, destination):
    executable, extension, destination = map(Path, (executable, extension, destination))
    if not executable.is_file() or executable.suffix.lower() != '.exe':
        raise FileNotFoundError(f'Build the Windows EXE first: {executable}')
    if not (extension / 'manifest.json').is_file():
        raise FileNotFoundError(f'Missing browser extension: {extension}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    root = f'ToriDownload-Portable-v{VERSION}'
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        archive.write(executable, f'{root}/ToriDownload.exe')
        archive.writestr(f'{root}/portable.flag', '')
        archive.writestr(f'{root}/README-PORTABLE.txt',
                         'Extract the full folder to a writable location, then open ToriDownload.exe.\n'
                         'Keep the extension folder beside the EXE; load it once in Edge/Chrome.\n'
                         'Your queue, settings, and default downloads stay in this folder.\n'
                         'Windows startup is OFF initially for this portable copy; enable it in Settings if wanted.\n'
                         'Use Quit in the tray before moving the folder or updating the EXE.\n')
        for file in sorted(extension.rglob('*')):
            if file.is_file():
                archive.write(file, f'{root}/extension/{file.relative_to(extension).as_posix()}')
    return destination


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('Usage: python package_portable.py EXE EXTENSION OUTPUT_ZIP')
    print(package(*sys.argv[1:]))
