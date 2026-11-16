"""Unit tests. Run from trainer-adapter/:  python -m unittest discover -s tests -t ."""
# The tests never touch the rider's data home (coach.db, profile, devices…): everything that has no explicit path
# goes to a temporary folder.
import os as _os
import tempfile as _tempfile

_os.environ['AI_COACH_HOME'] = _tempfile.mkdtemp(prefix='coach-tests-')
