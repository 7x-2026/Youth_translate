"""Separate bundled resources from writable per-user configuration."""
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def user_data_directory():
    if sys.platform == 'win32':
        base = Path(os.environ['LOCALAPPDATA']) if os.environ.get('LOCALAPPDATA') else Path.home() / 'AppData/Local'
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    return base / 'ClassroomInterpreter'


def configuration_path():
    # A one-file executable extracts resources into a temporary directory.
    # Configuration must survive both process exit and executable replacement.
    return user_data_directory() / 'config.env' if getattr(sys, 'frozen', False) else ROOT / '.env'


def records_path():
    directory = user_data_directory() if getattr(sys, 'frozen', False) else ROOT / '.local'
    return directory / 'records.sqlite3'
