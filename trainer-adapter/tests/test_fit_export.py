"""FIT export of a session: structure, CRC, values, pauses, invalid fields, HTTP download, official validation."""
import json
import os
import struct
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from coach.session.fit_export import FIT_EPOCH, fit_crc, session_fit, session_to_fit
from coach.session.session import SESSION_FIELDS

START = datetime(2026, 11, 13, 13, 0, 0, tzinfo=timezone.utc)
FMT = {0x00: 'B', 0x02: 'B', 0x83: 'h', 0x84: 'H', 0x86: 'I', 0x8C: 'I'}


def decode(data: bytes):
    """A small independent FIT reader: (header size, [(global mesg num, {field num: raw value})])."""
    size = data[0]
    header = data[:size]
    assert header[8:12] == b'.FIT', 'no .FIT signature'
    assert struct.unpack('<H', header[12:14])[0] == fit_crc(header[:12]), 'header CRC'
    data_size = struct.unpack('<I', header[4:8])[0]
    assert len(data) == size + data_size + 2, 'size'
    assert struct.unpack('<H', data[-2:])[0] == fit_crc(data[:-2]), 'file CRC'
    i, defs, messages = size, {}, []
    while i < size + data_size:
        record = data[i]
        i += 1
        local = record & 0x0F
        if record & 0x40:                                   # definition
            mesg, count = struct.unpack('<HB', data[i + 2:i + 5])
            fields = [tuple(data[i + 5 + 3 * k:i + 8 + 3 * k]) for k in range(count)]
            defs[local] = (mesg, fields)
            i += 5 + 3 * count
        else:
            mesg, fields = defs[local]
            values = {}
            for number, width, code in fields:
                values[number] = struct.unpack('<' + FMT[code], data[i:i + width])[0]
                i += width
            messages.append((mesg, values))
    return size, messages


def row(t, **over):
    base = {k: '' for k in SESSION_FIELDS}
    base.update({'recordedAtUtc': (START + timedelta(seconds=t)).isoformat(timespec='milliseconds'),
                 'elapsedSeconds': str(t), 'connected': 'True', 'powerWatts': '200', 'cadenceRpm': '80',
                 'speedKph': '30', 'rideSpeedKph': '25.2', 'estimatedDistanceKm': f'{t * 0.007:.5f}',
                 'altitudeM': f'{100 + t * 0.1:.1f}', 'roadGradePercent': '1.5', 'heartRateBpm': '140',
                 'heartRateConnected': 'True'})
    base.update(over)
    return base


def write_session(folder: Path, rows, **summary):
    stem = 'session_20261113_130000'
    with (folder / f'{stem}.csv').open('w', newline='', encoding='utf-8') as handle:
        import csv
        writer = csv.DictWriter(handle, fieldnames=SESSION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    data = {'session': stem, 'startedAtUtc': START.isoformat(), 'csv': f'{stem}.csv',
            'finishedAtUtc': (START + timedelta(seconds=len(rows) + 30)).isoformat(),
            'elapsedSeconds': 60.0, 'distanceKm': 0.42, 'workKj': 12.0, 'avgPowerW': 200.0, 'maxPowerW': 260,
            'normalizedPowerW': 205.3, 'ftpWatts': 250, 'intensityFactor': 0.821, 'tss': 11.2,
            'elevationGainM': 6.0, 'avgHeartRateBpm': 140.0, 'maxHeartRateBpm': 150.0, 'avgCadenceRpm': 80.0}
    data.update(summary)
    (folder / f'{stem}.json').write_text(json.dumps(data), encoding='utf-8')
    return stem


class FitExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def export(self, rows, **summary):
        return session_fit(self.folder, write_session(self.folder, rows, **summary))

    def test_structure_crc_and_order(self):
        _size, messages = decode(self.export([row(t) for t in range(60)]))
        kinds = [m for m, _ in messages]
        self.assertEqual(kinds[0], 0)                                   # file_id first
        self.assertEqual(kinds[-3:], [19, 18, 34])                      # lap, session, activity last
        self.assertEqual(kinds.count(20), 60)                           # one record per sample
        file_id = messages[0][1]
        self.assertEqual((file_id[0], file_id[1]), (4, 255))            # activity, development

    def test_record_values_and_scales(self):
        _size, messages = decode(self.export([row(t) for t in range(60)]))
        records = [v for m, v in messages if m == 20]
        first, tenth = records[0], records[10]
        self.assertEqual(first[253], int((START - FIT_EPOCH).total_seconds()))
        self.assertEqual((tenth[7], tenth[4], tenth[3]), (200, 80, 140))       # power, cadence, heart rate
        self.assertEqual(tenth[6], round(25.2 / 3.6 * 1000))                    # virtual road speed, m/s ×1000
        self.assertEqual(tenth[5], round(10 * 0.007 * 1000 * 100))              # distance, m ×100
        self.assertEqual(first[2], 500 * 5)                                     # altitude relative to start: 0 m
        self.assertEqual(tenth[2], round((1.0 + 500) * 5))                      # +1 m after 10 s
        self.assertEqual(tenth[9], 150)                                         # grade 1.5 % ×100

    def test_session_totals(self):
        _size, messages = decode(self.export([row(t) for t in range(60)]))
        session = next(v for m, v in messages if m == 18)
        self.assertEqual((session[5], session[6]), (2, 58))              # cycling, virtual activity
        self.assertEqual(session[8], 60_000)                             # timer time, ms
        self.assertEqual(session[9], 42_000)                             # 0.42 km, cm
        self.assertEqual((session[20], session[21], session[34]), (200, 260, 205))
        self.assertEqual((session[35], session[36], session[45]), (112, 821, 250))   # TSS ×10, IF ×1000, FTP
        self.assertEqual((session[22], session[48]), (6, 12_000))        # ascent m, work J

    def test_dropouts_are_invalid_not_zero(self):
        rows = [row(t) for t in range(10)] + [row(10, connected='False', heartRateConnected='False')]
        _size, messages = decode(self.export(rows))
        gap = [v for m, v in messages if m == 20][-1]
        self.assertEqual((gap[7], gap[4], gap[3], gap[6]), (0xFFFF, 0xFF, 0xFF, 0xFFFF))

    def test_pauses_become_timer_events(self):
        rows = [row(t) for t in range(10)]
        rows += [row(t, recordedAtUtc=(START + timedelta(seconds=t + 120)).isoformat()) for t in range(10, 20)]
        _size, messages = decode(self.export(rows))
        events = [(v[0], v[1]) for m, v in messages if m == 21]
        self.assertEqual(events, [(0, 0), (0, 4), (0, 0), (0, 4)])      # start, stop (pause), start, stop

    def test_old_session_without_virtual_road(self):
        rows = [row(t, rideSpeedKph='', altitudeM='', roadGradePercent='') for t in range(20)]
        _size, messages = decode(self.export(rows, normalizedPowerW=None, tss=None, intensityFactor=None, ftpWatts=None))
        session = next(v for m, v in messages if m == 18)
        self.assertEqual(session[6], 6)                                  # indoor cycling
        self.assertEqual((session[34], session[35], session[36], session[45]), (0xFFFF,) * 4)   # unknown: invalid
        record = [v for m, v in messages if m == 20][5]
        self.assertEqual(record[6], round(30 / 3.6 * 1000))              # the trainer speed
        self.assertEqual((record[2], record[9]), (0xFFFF, 0x7FFF))       # no altitude, no grade

    def test_an_empty_session_is_refused(self):
        with self.assertRaises(ValueError):
            self.export([])

    @unittest.skipUnless(os.environ.get('FIT_SDK_DIR'), 'set FIT_SDK_DIR to the FIT SDK folder to run the official checks')
    def test_official_garmin_verification(self):
        tool = Path(os.environ['FIT_SDK_DIR']) / 'java' / 'FitCSVTool.jar'
        fit = self.folder / 'check.fit'
        rows = [row(t) for t in range(30)]                              # with a pause and a dropout: the hard cases
        rows += [row(t, recordedAtUtc=(START + timedelta(seconds=t + 90)).isoformat()) for t in range(30, 60)]
        rows[45] = row(45, connected='False', recordedAtUtc=(START + timedelta(seconds=135)).isoformat())
        fit.write_bytes(self.export(rows))
        out = subprocess.run(['java', '-jar', str(tool), '-i', '-t', '-b', str(fit), str(self.folder / 'check.csv')],
                             capture_output=True, text=True, timeout=120).stdout
        self.assertIn('Status: PASSED', out)
        self.assertNotIn('Status: FAILED', out)


class FitDownloadTests(unittest.TestCase):
    def test_download_through_http(self):
        from threading import Thread
        from urllib.error import HTTPError
        from urllib.request import urlopen
        from coach.app.runtime import AdapterRuntime, EnvConfig
        from coach.app.server import make_server
        from coach.app.settings import Settings
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            stem = write_session(folder, [row(t) for t in range(30)])
            runtime = AdapterRuntime(EnvConfig(record_dir=folder, routes_dir=folder / 'routes'), Settings(),
                                     start_workers=False).start()
            httpd = make_server('127.0.0.1', 0, runtime)
            Thread(target=httpd.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{httpd.server_address[1]}'
            try:
                with urlopen(f'{base}/sessions/{stem}.fit', timeout=5) as response:
                    body = response.read()
                    self.assertEqual(response.headers['Content-Type'], 'application/vnd.ant.fit')
                    self.assertIn(f'{stem}.fit', response.headers['Content-Disposition'])
                self.assertEqual(decode(body)[1][0][0], 0)
                for bad in ('session_20990101_000000.fit', 'x.fit', '..%2Fsession_20261113_130000.fit'):
                    with self.subTest(bad=bad), self.assertRaises(HTTPError) as ctx:
                        urlopen(f'{base}/sessions/{bad}', timeout=5)
                    self.assertEqual(ctx.exception.code, 404)
            finally:
                runtime.shutdown()
                httpd.shutdown()
                httpd.server_close()


if __name__ == '__main__':
    unittest.main()
