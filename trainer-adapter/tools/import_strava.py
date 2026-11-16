"""Import a Strava account export (ZIP) into the activity history.

    trainer-adapter/.venv/bin/python trainer-adapter/tools/import_strava.py ~/Downloads/export_12345678.zip

Read straight from the ZIP; the history and copies of the activity files go to the data home
(ai-cycling-coach-data/coach.db and history/files), never to the project. Running it again only adds what is
new. Afterwards the ZIP can be deleted.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script from anywhere

from coach.history.store import HistoryStore  # noqa: E402
from coach.history.strava_import import import_strava_zip  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='Import a Strava export ZIP into the activity history.')
    parser.add_argument('zip', type=Path)
    parser.add_argument('--history', type=Path, help='history database (default: the data home)')
    args = parser.parse_args()
    store = HistoryStore(args.history) if args.history else HistoryStore.default()
    print(f'Importing {args.zip} into {store.path} …', flush=True)
    report = import_strava_zip(args.zip, store)
    print(f"Added {report['added']} activities ({report['from_file']} read from their FIT file, "
          f"{report['csv_only']} with Strava's figures only); {report['already']} were already there.")
    for problem in report['problems']:
        print('problem:', problem)
    print(f'History: {store.path} · {store.count_by()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
