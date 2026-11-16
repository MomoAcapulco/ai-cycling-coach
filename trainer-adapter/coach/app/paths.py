"""Where the user's data lives: outside the version folders, so every new version finds it.

Default: ``ai-cycling-coach-data`` NEXT TO the version folders (on the Mac ``~/dev/ai-cycling-coach-data``),
so it survives new versions AND can be shared for analysis. Override with AI_COACH_HOME.
Until v4.3.0 (12-11) the default was ``~/.ai-cycling-coach``; ``migrate_legacy_home`` copies anything from
there that is missing here (never overwrites, never deletes).
"""
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LEGACY_HOME = Path('~/.ai-cycling-coach')


def data_home() -> Path:
    return Path(os.environ.get('AI_COACH_HOME') or PROJECT_ROOT.parent / 'ai-cycling-coach-data').expanduser()


def data_file(name: str, env_var: str) -> Path:
    """A file in the data home, unless its own environment variable points elsewhere."""
    return Path(os.environ.get(env_var) or data_home() / name).expanduser()


def recordings_dir() -> Path:
    return Path(os.environ.get('RECORD_DIR') or data_home() / 'recordings').expanduser()


def routes_dir() -> Path:
    """Uploaded GPX routes (coach/session/route.py). In the data home: a GPX may be a ride of the rider's own."""
    return Path(os.environ.get('ROUTES_DIR') or data_home() / 'routes').expanduser()


def diagnostics_dir() -> Path:
    """Output of the read-only diagnostic tools (scans, trainer inventory): inside the project folder,
    so it can be shared for analysis. Ride recordings stay in recordings_dir()."""
    return Path(os.environ.get('DIAGNOSTICS_DIR') or PROJECT_ROOT / 'diagnostics').expanduser()


def migrate_legacy_home(legacy: Path = LEGACY_HOME, target: Path = None) -> list:
    """Copy files from the old ~/.ai-cycling-coach that do not exist yet in the data home. Returns them.

    Only for a data home that has never been used by the database version (no ``coach.db``): once it exists, the
    profile and settings live in the database and their JSON files are moved away on purpose (coach/app/legacy_json.py);
    copying the old ones back would bring files of 12-11 next to the database."""
    legacy = Path(legacy).expanduser()
    target = Path(target) if target is not None else data_home()
    copied = []
    if not legacy.is_dir() or legacy.resolve() == target.resolve() or (target / 'coach.db').exists():
        return copied
    for source in legacy.rglob('*'):
        if source.is_file() and not source.name.endswith('.tmp'):
            destination = target / source.relative_to(legacy)
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                copied.append(destination)
    return copied
