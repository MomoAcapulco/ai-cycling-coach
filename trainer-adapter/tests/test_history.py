"""Activity history: FIT reader (format variants), summaries, Strava export import, app sessions, HTTP API."""
import csv
import gzip
import io
import json
import struct
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from coach.history.fit_reader import FIT_EPOCH, FitError, read_fit
from coach.history.store import HistoryStore, import_app_sessions, summarize_records
from coach.history.strava_import import import_strava_zip, parse_date
from coach.session.fit_export import fit_crc, session_fit
from tests.test_fit_export import START, row, write_session


def fit_bytes(body: bytes) -> bytes:
    header = struct.pack('<BBHI4s', 14, 0x20, 21171, len(body), b'.FIT')
    header += struct.pack('<H', fit_crc(header))
    data = header + body
    return data + struct.pack('<H', fit_crc(data))


def ts(seconds):
    return int((START - FIT_EPOCH).total_seconds()) + seconds


class FitReaderTests(unittest.TestCase):
    def test_reads_our_own_export(self):
        with tempfile.TemporaryDirectory() as folder:
            stem = write_session(Path(folder), [row(t) for t in range(60)])
            fit = read_fit(session_fit(Path(folder), stem, Path(folder) / 'coach.db'))
        self.assertTrue(fit.crc_ok)
        self.assertEqual(len(fit.records), 60)
        self.assertEqual(fit.records[10]['power'], 200)
        self.assertEqual(fit.records[10]['heart_rate'], 140)
        self.assertAlmostEqual(fit.records[10]['speed'], 25.2 / 3.6, places=3)
        self.assertEqual(fit.records[0]['timestamp'], START)
        self.assertAlmostEqual(fit.sessions[0]['total_timer_time'], 60.0)
        self.assertEqual(fit.sessions[0]['normalized_power'], 205)
        self.assertEqual(fit.file_id['manufacturer'], 255)

    def test_developer_fields_are_skipped(self):
        body = bytes([0x60, 0, 0]) + struct.pack('<HB', 20, 2) + bytes([253, 4, 0x86, 7, 2, 0x84])
        body += bytes([1, 0, 2, 0])                               # one developer field of 2 bytes
        body += bytes([0x00]) + struct.pack('<IH', ts(0), 250) + b'\xAA\xBB'
        body += bytes([0x00]) + struct.pack('<IH', ts(1), 251) + b'\xCC\xDD'
        fit = read_fit(fit_bytes(body))
        self.assertEqual([r['power'] for r in fit.records], [250, 251])
        self.assertEqual(fit.developer_fields_skipped, 1)

    def test_big_endian_and_compressed_timestamps(self):
        body = bytes([0x40, 0, 1]) + struct.pack('>HB', 20, 2) + bytes([253, 4, 0x86, 7, 2, 0x84])
        body += bytes([0x00]) + struct.pack('>IH', ts(0), 300)
        body += bytes([0x41, 0, 1]) + struct.pack('>HB', 20, 1) + bytes([7, 2, 0x84])    # local 1: power only
        offset = (ts(0) + 3) & 0x1F
        body += bytes([0x80 | (1 << 5) | offset]) + struct.pack('>H', 310)               # compressed: +3 s
        fit = read_fit(fit_bytes(body))
        self.assertEqual([r['power'] for r in fit.records], [300, 310])
        self.assertEqual(fit.records[1]['timestamp'], START + timedelta(seconds=3))

    def test_invalid_values_chained_files_and_errors(self):
        one = bytes([0x40, 0, 0]) + struct.pack('<HB', 20, 2) + bytes([253, 4, 0x86, 3, 1, 0x02])
        one += bytes([0x00]) + struct.pack('<IB', ts(0), 0xFF)           # heart rate "invalid"
        two = bytes([0x40, 0, 0]) + struct.pack('<HB', 20, 2) + bytes([253, 4, 0x86, 3, 1, 0x02])
        two += bytes([0x00]) + struct.pack('<IB', ts(5), 130)
        fit = read_fit(fit_bytes(one) + fit_bytes(two))
        self.assertEqual([r.get('heart_rate') for r in fit.records], [None, 130])
        broken = bytearray(fit_bytes(one))
        broken[-3] ^= 0xFF
        self.assertFalse(read_fit(bytes(broken)).crc_ok)
        for bad in (b'', b'not a fit file at all', fit_bytes(one)[:-6]):
            with self.subTest(bad=bad[:10]), self.assertRaises(FitError):
                read_fit(bad)


class SummaryTests(unittest.TestCase):
    def test_one_hz_grid_gaps_and_np(self):
        records = [{'timestamp': START + timedelta(seconds=t), 'power': 200, 'heart_rate': 140, 'cadence': 80,
                    'distance': t * 8.0} for t in range(0, 600)]
        records += [{'timestamp': START + timedelta(seconds=t), 'power': 200, 'heart_rate': 140, 'cadence': 80,
                     'distance': t * 8.0} for t in range(900, 1200, 2)]          # 5 min of pause, then every 2 s
        s = summarize_records(records)
        self.assertEqual((s['avg_power'], s['np'], s['avg_hr']), (200.0, 200.0, 140.0))
        self.assertAlmostEqual(s['moving_s'], 900, delta=3)                     # the pause is not moving
        self.assertAlmostEqual(s['distance_m'], 1198 * 8.0)
        self.assertEqual((s['has_power'], s['has_hr']), (1, 1))

    def test_without_power(self):
        records = [{'timestamp': START + timedelta(seconds=t), 'heart_rate': 130, 'speed': 7.0} for t in range(120)]
        s = summarize_records(records)
        self.assertEqual((s['avg_power'], s['np'], s['has_power'], s['avg_hr']), (None, None, 0, 130.0))


HEADER = ['ID de actividad', 'Fecha de la actividad', 'Nombre de la actividad', 'Tipo de actividad',
          'Descripción de la actividad', 'Tiempo transcurrido', 'Distancia', 'Frecuencia cardiaca máxima',
          'Esfuerzo Relativo', 'Viaje diario', 'Equipo de la actividad', 'Nombre del archivo', 'Peso del atleta',
          'Peso de la bicicleta', 'Tiempo transcurrido', 'Tiempo en movimiento', 'Distancia', 'Velocidad máxima',
          'Desnivel positivo', 'Frecuencia cardiaca promedio', 'Vatios promedio', 'Potencia promedio ponderada']


def strava_zip(path: Path, fit: bytes):
    lines = io.StringIO()
    w = csv.writer(lines)
    w.writerow(HEADER)
    w.writerow(['111', '13 nov 2026, 13:00:00', 'Rodillo', 'Bicicleta virtual', '', '60', '0,42', '150', '20', 'false',
                '', 'activities/111.fit.gz', '', '', '60.0', '60.0', '420.0', '9', '6.0', '140.0', '200.0', '205'])
    w.writerow(['222', '14 nov 2026, 9:30:00', 'Por el monte', 'Bicicleta', '', '7200', '40,1', '170', '120', 'false',
                '', 'activities/222.gpx', '', '', '7200.0', '6900.0', '40100.5', '15', '812.0', '135.0', '', ''])
    w.writerow(['333', '15 nov 2026, 18:00:00', 'Pesas', 'Entrenamiento con pesas', '', '2700', '0', '', '',
                'false', '', '', '', '', '2700.0', '2700.0', '0.0', '', '0.0', '', '', ''])
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('activities.csv', lines.getvalue())
        z.writestr('activities/111.fit.gz', gzip.compress(fit))
        z.writestr('activities/222.gpx', '<gpx/>')
        z.writestr('profile.csv', 'private,data\n')


class StravaImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        stem = write_session(self.folder, [row(t) for t in range(60)])
        self.zip = self.folder / 'export.zip'
        strava_zip(self.zip, session_fit(self.folder, stem, self.folder / 'coach.db'))
        self.store = HistoryStore(self.folder / 'data' / 'history.db')

    def tearDown(self):
        self.temp.cleanup()

    def test_import_is_complete_and_idempotent(self):
        report = import_strava_zip(self.zip, self.store)
        self.assertEqual((report['added'], report['from_file'], report['csv_only'], report['problems']), (3, 1, 2, []))
        again = import_strava_zip(self.zip, self.store)
        self.assertEqual((again['added'], again['already']), (0, 3))
        rows = {r['id']: r for r in self.store.list()}
        ride = rows['strava:111']
        self.assertEqual((ride['type'], ride['source'], ride['device']), ('virtual_ride', 'strava', 'development'))
        self.assertEqual((ride['avg_power'], ride['np'], ride['has_hr']), (200.0, 200.0, 1))   # from the records
        self.assertEqual(ride['ascent_m'], 6.0)                                                # Strava's figure
        self.assertTrue((self.folder / 'data' / ride['file']).is_file())                       # original kept
        mtb = rows['strava:222']
        self.assertEqual((mtb['type'], mtb['distance_m'], mtb['moving_s'], mtb['ascent_m']), ('ride', 40100.5, 6900.0, 812.0))
        self.assertEqual(mtb['start_utc'], '2026-11-14T09:30:00+00:00')
        self.assertEqual(rows['strava:333']['type'], 'strength')

    def test_not_a_strava_export(self):
        bad = self.folder / 'bad.zip'
        with zipfile.ZipFile(bad, 'w') as z:
            z.writestr('readme.txt', 'x')
        with self.assertRaises(ValueError):
            import_strava_zip(bad, self.store)

    def test_dates(self):
        self.assertEqual(parse_date('12 sept 2026, 8:05:52'), datetime(2026, 9, 12, 8, 5, 52, tzinfo=timezone.utc))
        self.assertEqual(parse_date('Sep 12, 2026, 8:05:52 AM'), datetime(2026, 9, 12, 8, 5, 52, tzinfo=timezone.utc))
        self.assertIsNone(parse_date('yesterday'))


class AppSessionsAndApiTests(unittest.TestCase):
    def test_app_sessions_join_the_history_and_the_api(self):
        from threading import Thread
        from urllib.request import urlopen
        from coach.app.runtime import AdapterRuntime, EnvConfig
        from coach.app.server import make_server
        from coach.app.settings import Settings
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            write_session(folder, [row(t) for t in range(60)])
            store = HistoryStore(folder / 'history.db')
            self.assertEqual(import_app_sessions(store, folder), 1)
            self.assertEqual(import_app_sessions(store, folder), 0)
            runtime = AdapterRuntime(EnvConfig(record_dir=folder, routes_dir=folder / 'r', history_db=folder / 'h.db'),
                                     Settings(), start_workers=False).start()
            httpd = make_server('127.0.0.1', 0, runtime)
            Thread(target=httpd.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{httpd.server_address[1]}'
            try:
                listing = json.loads(urlopen(base + '/history', timeout=5).read())
                self.assertEqual([a['id'] for a in listing['activities']], ['app:session_20261113_130000'])
                weeks = json.loads(urlopen(base + '/history/weeks', timeout=5).read())['weeks']
                self.assertEqual(weeks[0]['week'], '2026-11-09')                    # the Monday of that week
                self.assertEqual(weeks[0]['hours'], {'virtual_ride': round(60 / 3600, 2)})
                self.assertEqual(weeks[0]['distanceKm'], 0.4)
            finally:
                runtime.shutdown()
                httpd.shutdown()
                httpd.server_close()


if __name__ == '__main__':
    unittest.main()
