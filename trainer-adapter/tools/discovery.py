"""Scan and classify nearby trainers, heart-rate straps and Zwift controllers (read-only).

Usage:  python tools/discovery.py [--seconds 15] [--all] [--remember]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script from anywhere

from coach.bluetooth.discovery import main  # noqa: E402

if __name__ == '__main__':
    main()
