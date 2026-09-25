"""Local HTTP checks for file integrity, resume, and browser handoff."""
import http.server
import pathlib
import queue
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import json
import sys
import types
from unittest.mock import patch

import app

DATA = bytes(range(256)) * 1000


class Files(http.server.BaseHTTPRequestHandler):
    etag = '"v1"'

    def do_GET(self):
        if self.path == '/login':
            body, mime = b'<html>Sign in</html>', 'text/html'
        else:
            body, mime = DATA, 'application/octet-stream'
        offset = 0
        header = self.headers.get('Range', '')
        if header.startswith('bytes='):
            offset = int(header[6:].split('-')[0])
        if offset >= len(body):
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{len(body)}')
            self.end_headers()
            return
        ranged = bool(header) and self.path != '/ignore-range'
        if not ranged:
            offset = 0
        self.send_response(206 if ranged else 200)
        self.send_header('Content-Type', mime)
        if self.path == '/named':
            self.send_header('Content-Disposition', 'attachment; filename="actual-name.bin"')
        self.send_header('ETag', self.etag)
        self.send_header('Content-Length', str(len(body)-offset))
        if ranged:
            end = offset if header.endswith(f'-{offset}') else len(body)-1
            body = body[offset:end+1]
            self.send_header('Content-Range', f'bytes {offset}-{end}/{len(DATA)}')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db, self.old_dest, self.old_settings = app.DB, app.DEST, app.SETTINGS
        self.old_offers, self.old_offer_queue = app.offers, app.offer_queue
        app.offers, app.offer_queue = {}, queue.Queue()
        app.DB = pathlib.Path(self.tmp.name) / 'queue.db'
        app.DEST = pathlib.Path(self.tmp.name)
        app.SETTINGS = pathlib.Path(self.tmp.name) / 'settings.json'
        with app.connection() as db:
            db.execute('CREATE TABLE jobs (id INTEGER PRIMARY KEY, url TEXT NOT NULL, filename TEXT NOT NULL, status TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0, etag TEXT, modified TEXT, error TEXT DEFAULT "", folder TEXT, storage_name TEXT, last_try REAL NOT NULL DEFAULT 0, kind TEXT NOT NULL DEFAULT "file", quality TEXT NOT NULL DEFAULT "Auto")')
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1',0),Files)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        app.DB, app.DEST, app.SETTINGS = self.old_db, self.old_dest, self.old_settings
        app.offers, app.offer_queue = self.old_offers, self.old_offer_queue
        self.tmp.cleanup()

    def url(self, suffix='/file'):
        return f'http://127.0.0.1:{self.server.server_port}{suffix}'

    def finish(self, job_id):
        for _ in range(100):
            job = app.get_job(job_id)
            if job['status'] in ('completed','failed'):
                return job
            time.sleep(.03)
        self.fail('Download did not finish')

    def test_full_download_byte_exact(self):
        job = self.finish(app.enqueue(self.url()))
        self.assertEqual(job['status'], 'completed')
        self.assertGreater(job['last_try'], 0)
        self.assertEqual(app.paths(job)[0].read_bytes(), DATA)

    def test_video_confirmation_and_local_worker_finish(self):
        selected_options = []
        class Downloader:
            def __init__(self, options):
                self.options = options
                selected_options.append(options)
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def extract_info(self, _url, download=False):
                self.assert_download_false = not download
                return {'formats':[{'height':480,'vcodec':'avc1','acodec':'none'},
                                   {'height':1080,'vcodec':'avc1','acodec':'none'},
                                   {'height':1440,'vcodec':'vp9','acodec':'none'},
                                   {'vcodec':'none','acodec':'mp4a'}]}
            def download(self, urls):
                self.options['progress_hooks'][0]({'status':'downloading', 'downloaded_bytes':4,
                                                   'total_bytes':4, 'speed':1000})
                suffix = 'mp3' if self.options.get('postprocessors') else 'mp4'
                pathlib.Path(self.options['outtmpl'].replace('%(ext)s', suffix)).write_bytes(b'VID!')
        fake_dl = types.SimpleNamespace(YoutubeDL=Downloader)
        fake_ffmpeg = types.SimpleNamespace(get_ffmpeg_exe=lambda:'/tmp/fake-ffmpeg')
        with patch.dict(sys.modules, {'yt_dlp':fake_dl,'imageio_ffmpeg':fake_ffmpeg}), \
             patch.object(app, 'start'):
            offer = app.make_offer(self.url('/page'), 'Clip.mp4', verify=False, kind='video')
            for _ in range(100):
                if app.offers[offer]['quality_state'] != 'checking': break
                time.sleep(.01)
            self.assertEqual(app.offers[offer]['qualities'], ['Auto','480p','1080p','1440p','MP3'])
            self.assertTrue(app.resolve_offer(offer, True, 'Clip.mp4', str(app.DEST), quality='1080p'))
            for _ in range(100):
                if app.offer_status(offer) == 'accepted': break
                time.sleep(.01)
            self.assertEqual(app.offer_status(offer), 'accepted')
            with app.connection() as db:
                job_id = db.execute('SELECT id FROM jobs WHERE kind="video"').fetchone()[0]
            app.video_worker(job_id, threading.Event())
            job = app.get_job(job_id)
            self.assertEqual(job['status'], 'completed')
            self.assertEqual(job['quality'], '1080p')
            self.assertIn('height<=1080', selected_options[-1]['format'])
            self.assertEqual(app.paths(job)[0].read_bytes(), b'VID!')
            mp3_offer = app.make_offer(self.url('/audio'), 'Audio.mp3', verify=False, kind='video')
            for _ in range(100):
                if app.offers[mp3_offer]['quality_state'] != 'checking': break
                time.sleep(.01)
            self.assertTrue(app.resolve_offer(mp3_offer, True, 'Audio.mp3', str(app.DEST), quality='MP3'))
            for _ in range(100):
                if app.offer_status(mp3_offer) == 'accepted': break
                time.sleep(.01)
            with app.connection() as db:
                audio_id = db.execute('SELECT id FROM jobs WHERE quality="MP3"').fetchone()[0]
            app.video_worker(audio_id, threading.Event())
            audio = app.get_job(audio_id)
            self.assertEqual(audio['status'], 'completed')
            self.assertEqual(app.paths(audio)[0].suffix, '.mp3')
            self.assertEqual(selected_options[-1]['postprocessors'][0]['preferredcodec'], 'mp3')

    def test_speed_display_smooths_bursts_and_fades_stalls(self):
        self.assertEqual(app.smooth_speed(None, 10_000_000, .4), 10_000_000)
        self.assertGreater(app.smooth_speed(10_000_000, 0, .4), 8_000_000)
        app.speeds[-101] = 10_000_000
        app.speed_times[-101] = 100
        try:
            with patch.object(app.time, 'monotonic', return_value=104):
                self.assertLess(app.current_speed(-101), 3_000_000)
        finally:
            app.speeds.pop(-101, None)
            app.speed_times.pop(-101, None)

    def test_filename_from_response_and_browser_is_sanitized(self):
        server_name = self.finish(app.enqueue(self.url('/named')))
        self.assertEqual(server_name['filename'], 'actual-name.bin')
        self.assertEqual(app.paths(server_name)[0].name, 'actual-name.bin')
        browser_name = self.finish(app.enqueue(self.url('/file'), 'C:\\Downloads\\sample.zip'))
        self.assertEqual(browser_name['filename'], 'sample.zip')
        self.assertEqual(app.paths(browser_name)[0].name, 'sample.zip')
        self.assertEqual(app.paths(browser_name)[0].read_bytes(), DATA)

    def test_matching_names_get_numbered_without_overwriting(self):
        first = self.finish(app.enqueue(self.url(), 'example.zip'))
        second = self.finish(app.enqueue(self.url(), 'example.zip'))
        self.assertEqual(app.paths(first)[0].name, 'example.zip')
        self.assertEqual(app.paths(second)[0].name, 'example (2).zip')
        self.assertEqual(app.paths(first)[0].read_bytes(), DATA)

    def test_selected_folder_and_rename_keep_old_downloads_in_place(self):
        first = self.finish(app.enqueue(self.url()))
        new_folder = pathlib.Path(self.tmp.name) / 'chosen'
        new_folder.mkdir()
        app.set_download_folder(new_folder)
        second = self.finish(app.enqueue(self.url()))
        self.assertEqual(app.paths(first)[0].parent, pathlib.Path(self.tmp.name))
        self.assertEqual(app.paths(second)[0].parent, new_folder)
        app.rename_job(second['id'], 'report-final.zip')
        renamed = app.get_job(second['id'])
        self.assertEqual(renamed['filename'], 'report-final.zip')
        self.assertEqual(app.paths(renamed)[0].read_bytes(), DATA)

    def test_resume_byte_exact(self):
        job_id = app.enqueue(self.url())
        self.finish(job_id)
        job = app.get_job(job_id)
        target, part = app.paths(job)
        target.unlink()
        part.write_bytes(DATA[:111111])
        app.update(job_id, status='paused', done=111111, total=len(DATA), etag='"v1"')
        self.finish_after_start(job_id)
        self.assertEqual(target.read_bytes(), DATA)

    def finish_after_start(self, job_id):
        app.start(job_id)
        job = self.finish(job_id)
        self.assertEqual(job['status'], 'completed', job['error'])

    def test_changed_etag_preserves_partial_file(self):
        job_id = self.finish(app.enqueue(self.url()))['id']
        job = app.get_job(job_id)
        target, part = app.paths(job)
        target.unlink()
        original = DATA[:120000]
        part.write_bytes(original)
        app.update(job_id, status='paused', done=len(original), total=len(DATA), etag='"old"')
        app.start(job_id)
        result = self.finish(job_id)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(part.read_bytes(), original)

    def test_probe_rejects_html_and_accepts_file(self):
        app.probe_file(self.url())
        with self.assertRaisesRegex(ValueError, 'webpage'):
            app.probe_file(self.url('/login'))

    def test_browser_offer_waits_for_confirmation_and_decline_starts_nothing(self):
        declined = app.make_offer(self.url(), 'ignore.zip')
        self.assertEqual(app.offer_status(declined), 'pending')
        with app.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 0)
        self.assertTrue(app.resolve_offer(declined, False))
        self.assertEqual(app.offer_status(declined), 'declined')
        self.assertFalse(app.resolve_offer(declined, True))
        chosen = pathlib.Path(self.tmp.name) / 'confirmed'
        chosen.mkdir()
        accepted = app.make_offer(self.url(), 'default.zip')
        self.assertTrue(app.resolve_offer(accepted, True, 'confirmed.zip', chosen))
        for _ in range(100):
            if app.offer_status(accepted) != 'checking': break
            time.sleep(.03)
        self.assertEqual(app.offer_status(accepted), 'accepted')
        with app.connection() as db:
            row = db.execute('SELECT * FROM jobs').fetchone()
        self.assertEqual(pathlib.Path(row['folder']), chosen)
        self.assertEqual(row['filename'], 'confirmed.zip')
        self.finish(row['id'])

    def test_unsupported_confirmed_link_returns_browser_fallback(self):
        offer_id = app.make_offer(self.url('/login'), 'requires-login.html')
        app.resolve_offer(offer_id, True)
        for _ in range(100):
            if app.offer_status(offer_id) != 'checking': break
            time.sleep(.03)
        self.assertEqual(app.offer_status(offer_id), 'fallback')
        with app.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 0)

    def test_browser_connector_without_origin_header(self):
        connector = http.server.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        threading.Thread(target=connector.serve_forever,daemon=True).start()
        try:
            endpoint = f'http://127.0.0.1:{connector.server_port}'
            headers = {'Host':'127.0.0.1:8765'}
            with urllib.request.urlopen(urllib.request.Request(endpoint+'/health',headers=headers)) as reply:
                self.assertEqual(reply.status,200)
            payload = json.dumps({'url':self.url()}).encode()
            request = urllib.request.Request(endpoint+'/enqueue',data=payload,
                headers={**headers,'X-Tori-Connector':app.CONNECTOR_ID,'Content-Type':'application/json'})
            with urllib.request.urlopen(request) as reply:
                self.assertEqual(reply.status,200)
            offer_request = urllib.request.Request(endpoint+'/offer',data=payload,
                headers={**headers,'X-Tori-Connector':app.CONNECTOR_ID,'Content-Type':'application/json'})
            with urllib.request.urlopen(offer_request) as reply:
                offer_id = json.loads(reply.read())['id']
            poll_request = urllib.request.Request(endpoint+'/offer/'+offer_id,
                headers={**headers,'X-Tori-Connector':app.CONNECTOR_ID})
            with urllib.request.urlopen(poll_request) as reply:
                self.assertEqual(json.loads(reply.read())['result'],'pending')
            app.resolve_offer(offer_id, False)
            with urllib.request.urlopen(poll_request) as reply:
                self.assertEqual(json.loads(reply.read())['result'],'declined')
            rejected = urllib.request.Request(endpoint+'/enqueue',data=payload,
                headers={**headers,'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(rejected)
            self.assertEqual(error.exception.code,403)
        finally:
            connector.shutdown()
            connector.server_close()


if __name__ == '__main__':
    unittest.main()
