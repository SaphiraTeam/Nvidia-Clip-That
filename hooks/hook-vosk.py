# PyInstaller hook to ensure Vosk native DLLs are bundled and discoverable at runtime.
# This places the dynamic libraries into a 'vosk' dir inside the bundle so that
# vosk.__init__.open_dll can successfully add that directory on Windows.

from PyInstaller.utils.hooks import collect_dynamic_libs

# Collect Vosk dynamic libraries and put them under a folder named 'vosk' in the bundle
binaries = collect_dynamic_libs('vosk', destdir='vosk')
