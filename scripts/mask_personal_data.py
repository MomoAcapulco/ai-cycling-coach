#!/usr/bin/env python3
"""Replace identifying data in the project's text files by fixed fakes, so the repository can be shared.

What is masked (only in the project files, never in ai-cycling-coach-data/ or diagnostics/):
- Bluetooth identifiers of real devices (CoreBluetooth UUIDs of the rider's controllers, strap, trainer and of
  every device a recorded scan picked up around the house). Standard service UUIDs are NOT touched: they are the
  same everywhere (FTMS 0x1826, heart rate 0x180D, the Zwift service, Wahoo, Nordic DFU…).
  Each real identifier becomes a fixed fake derived from a hash of it: the same real ID always gives the same fake
  (tests and recordings stay consistent), no table of real IDs is kept, and it cannot be reversed. Fakes start
  with FA4E0000-0000-4000-8000- so a second run leaves them alone. The last 8 characters of a real ID, used in
  some recording file names, are replaced the same way (contents and file names).
- Serial numbers and names: an HR50 serial ("HR50-" + digits) → "HR50-0000000", the KICKR suffix ("KICKR CORE" +
  4 hex characters) → "KICKR CORE 0000", names of nearby TVs and smart plugs → "Nearby TV" / "Nearby device".
  (No real value is written in this file: it would mask itself.)
- The rider's body weight where a text states it (rider 100-119 kg, bike 10-19.9 kg, total 120-139 kg, in
  sentences and in "--rider-kg"/"--bike-kg" examples) → example weights (80 kg rider, 9 kg bike, 89 kg total).
  The ranges are wide on purpose: this public file must not reveal anybody's exact weight.

Usage:  python3 scripts/mask_personal_data.py [--root DIR] [--check]
  --check  only lists what would change; exit code 1 if anything would.
Used by scripts/mask-git-history.sh for the commits already made.
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

FAKE_PREFIX = 'FA4E0000-0000-4000-8000-'
UUID = re.compile(r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')
STANDARD = re.compile(r'(?i)^(0000[0-9a-f]{4}-0000-1000-8000-00805f9b34fb|[0-9a-f]{8}-19ca-4651-86e5-fa29dcdd09d1|'
                      r'8ec9[0-9a-f]{4}-|a026[0-9a-f]{4}-|6e40[0-9a-f]{4}-|00000000-0000-0000-)')
NAMES = [
    (re.compile(r'HR50-\d{4,}'), 'HR50-0000000'),
    (re.compile(r'(KICKR CORE) [0-9A-F]{4}\b'), r'\1 0000'),
    (re.compile(r'\[TV\] Samsung [0-9A-Za-z ]+(\([0-9]+\))?'), 'Nearby TV'),
    (re.compile(r'\d{2}\\?" QLED'), 'Nearby TV'),
    (re.compile(r'TUYA_\w*'), 'Nearby device'),
    # The rider's body weight where a text states it (guides, command examples, comments) → example weights.
    # Bare numbers in tests are left alone: nothing ties them to a person once the texts are masked.
    (re.compile(r'--rider-kg 1[01]\d\b'), '--rider-kg 80'),
    (re.compile(r'--bike-kg 1\d(?:[.,]\d)?\b'), '--bike-kg 9'),
    (re.compile(r'\b1[01]\d ?\+ ?1\d(?:[.,]\d)?( ?kg)'), r'80 + 9\1'),
    (re.compile(r'\b1[01]\d kg'), '80 kg'),
    (re.compile(r'\b1\d[.,]\d ?kg'), '9 kg'),
    (re.compile(r'\b1[23]\d(?:[.,]\d)? ?kg'), '89 kg'),
]
TEXT_SUFFIXES = {'.py', '.json', '.jsonl', '.md', '.ts', '.tsx', '.java', '.sh', '.txt', '.csv', '.example', '.yml',
                 '.yaml', '.properties', '.html', '.css'}
SKIP_DIRS = {'.git', 'node_modules', '.venv', 'target', 'dist', 'diagnostics', 'recordings', '__pycache__'}


def fake_for(real: str) -> str:
    digest = hashlib.sha256(real.upper().encode()).hexdigest()[:12].upper()
    fake = FAKE_PREFIX + digest
    return fake if real.isupper() or not real.islower() else fake.lower()


def is_real(uuid: str) -> bool:
    return not STANDARD.search(uuid) and not uuid.upper().startswith(FAKE_PREFIX)


def files(root: Path):
    for path in sorted(root.rglob('*')):
        if path.is_file() and not (set(path.relative_to(root).parts) & SKIP_DIRS) \
                and (path.suffix in TEXT_SUFFIXES or path.name.startswith('.env')):
            if path.name in ('.env', 'mask_personal_data.py', Path(__file__).name):
                continue  # the rider's local config is never in the repository; this file holds the patterns
            yield path


def build_map(root: Path) -> dict:
    reals = set()
    for path in files(root):
        try:
            reals.update(u for u in UUID.findall(path.read_text(encoding='utf-8')) if is_real(u))
        except (UnicodeDecodeError, OSError):
            continue
    mapping = {}
    for real in reals:
        fake = fake_for(real)
        mapping[real] = fake
        mapping[real.upper()[-8:]] = fake[-8:]          # the short suffix used in recording file names
        mapping[real.lower()[-8:]] = fake[-8:].lower()
    return mapping


def mask_text(text: str, mapping: dict) -> str:
    text = UUID.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)
    for short, fake in mapping.items():
        if len(short) == 8:
            text = re.sub(rf'(?<![0-9A-Fa-f]){re.escape(short)}(?![0-9A-Fa-f])', fake, text)
    for pattern, replacement in NAMES:
        text = pattern.sub(replacement, text)
    return text


def run(root: Path, check: bool) -> list:
    mapping = build_map(root)
    changed = []
    for path in list(files(root)):
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        masked = mask_text(text, mapping)
        new_name = mask_text(path.name, {k: v for k, v in mapping.items() if len(k) == 8})
        if masked != text or new_name != path.name:
            changed.append(str(path.relative_to(root)) + (f' → {new_name}' if new_name != path.name else ''))
            if not check:
                path.write_text(masked, encoding='utf-8')
                if new_name != path.name:
                    path.rename(path.with_name(new_name))
    return changed


def main():
    parser = argparse.ArgumentParser(description='Mask identifying data in the project text files.')
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    changed = run(Path(args.root), args.check)
    for line in changed:
        print(('would mask: ' if args.check else 'masked: ') + line)
    if args.check:
        return 1 if changed else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
