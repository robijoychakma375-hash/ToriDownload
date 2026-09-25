"""Tori Download: personal Windows desktop download manager."""
import json
import email.message
import math
import os
import queue
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import messagebox
import startup

if os.name == 'nt':
    # Importing app also opens the queue DB; prevent a second launch from
    # resetting active jobs before the first instance can finish them.
    import ctypes
    _instance_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\ToriDownloadManager')
    if not _instance_mutex:
        raise OSError('Could not create the Tori single-instance mutex')
    if ctypes.windll.kernel32.GetLastError() == 183:
        if '--background' not in sys.argv:
            messagebox.showinfo('Tori Download', 'Tori is already running. Open it from the system tray.')
        raise SystemExit(0)

# Installed builds keep existing queue data; the ZIP build keeps its own data.
PORTABLE_DIR = (Path(sys.executable).resolve().parent
                if getattr(sys, 'frozen', False) and
                (Path(sys.executable).resolve().parent / 'portable.flag').is_file() else None)
STARTUP_DEFAULT = PORTABLE_DIR is None
STARTUP_NAME = 'ToriDownloadPortable' if PORTABLE_DIR else 'ToriDownload'
BASE = (PORTABLE_DIR / 'ToriData' if PORTABLE_DIR else
        Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'FrejaDownloadManager')
LEGACY_DEST = PORTABLE_DIR / 'Downloads' if PORTABLE_DIR else Path.home() / 'Downloads' / 'Freja Downloads'
SETTINGS = BASE / 'settings.json'
try:
    configured = Path(json.loads(SETTINGS.read_text(encoding='utf-8'))['download_folder']) if SETTINGS.exists() else LEGACY_DEST
    DEST = PORTABLE_DIR / configured if PORTABLE_DIR and not configured.is_absolute() else configured
except (OSError, ValueError, KeyError, TypeError):
    DEST = LEGACY_DEST
BASE.mkdir(parents=True, exist_ok=True)
DEST.mkdir(parents=True, exist_ok=True)
DB = BASE / 'queue.sqlite3'
TRUSTED_ORIGIN = 'chrome-extension://fabmofikglnnbbobdhfcnlcneebfffhn'
CONNECTOR_ID = 'fabmofikglnnbbobdhfcnlcneebfffhn'
lock = threading.RLock()
controls = {}
slots = threading.BoundedSemaphore(3)
speeds = {}
speed_times = {}
server_ready = False
offers = {}
offer_queue = queue.Queue()
OFFER_TIMEOUT = 120


def smooth_speed(previous, sample, elapsed):
    """Show a short rolling trend without changing the actual transfer rate."""
    if previous is None:
        return sample
    weight = 1 - math.exp(-max(elapsed, 0) / 2.0)
    return previous + weight * (sample - previous)


def current_speed(job_id):
    measured = speeds.get(job_id, 0)
    age = time.monotonic() - speed_times.get(job_id, 0)
    # If socket reads stall, let the last measurement fade instead of
    # displaying a frozen high number until the request times out.
    return measured * math.exp(-max(0, age - 1) / 2.0) if measured else 0


def connection():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    return db


with connection() as db:
    db.execute('CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, url TEXT NOT NULL, filename TEXT NOT NULL, status TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0, etag TEXT, modified TEXT, error TEXT DEFAULT "", folder TEXT, storage_name TEXT, last_try REAL NOT NULL DEFAULT 0)')
    if 'folder' not in {row[1] for row in db.execute('PRAGMA table_info(jobs)')}:
        db.execute('ALTER TABLE jobs ADD COLUMN folder TEXT')
    if 'storage_name' not in {row[1] for row in db.execute('PRAGMA table_info(jobs)')}:
        db.execute('ALTER TABLE jobs ADD COLUMN storage_name TEXT')
    if 'last_try' not in {row[1] for row in db.execute('PRAGMA table_info(jobs)')}:
        db.execute('ALTER TABLE jobs ADD COLUMN last_try REAL NOT NULL DEFAULT 0')
    if 'kind' not in {row[1] for row in db.execute('PRAGMA table_info(jobs)')}:
        db.execute("ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'file'")
    if 'quality' not in {row[1] for row in db.execute('PRAGMA table_info(jobs)')}:
        db.execute("ALTER TABLE jobs ADD COLUMN quality TEXT NOT NULL DEFAULT 'Auto'")
    db.execute('UPDATE jobs SET folder=? WHERE folder IS NULL', (str(LEGACY_DEST),))
    # Existing files used numeric prefixes. Keep their exact locations across upgrades.
    db.execute("UPDATE jobs SET storage_name=CAST(id AS TEXT)||'-'||filename WHERE storage_name IS NULL")
    db.execute("UPDATE jobs SET status='paused' WHERE status IN ('downloading','queued')")


def valid_url(value):
    try:
        parsed = urllib.parse.urlsplit(value)
        return parsed.scheme.lower() in ('http', 'https') and bool(parsed.hostname) and not parsed.username and not parsed.password and len(value) < 4096
    except ValueError:
        return False


def safe_name(url):
    raw = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit('/', 1)[-1])
    raw = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', raw).strip(' .')[:140]
    if not raw or raw.upper().split('.')[0] in {'CON','PRN','AUX','NUL','COM1','LPT1'}:
        raw = 'download.bin'
    return raw


def clean_filename(value):
    if not isinstance(value, str) or not value:
        return None
    return safe_name('https://download.invalid/' + urllib.parse.quote(value.replace('\\', '/').rsplit('/',1)[-1]))


def disposition_filename(header):
    if not header:
        return None
    message = email.message.Message()
    message['Content-Disposition'] = header
    name = message.get_filename()
    return clean_filename(name) if name else None


def update(job_id, **fields):
    if not fields:
        return
    with lock, connection() as db:
        db.execute('UPDATE jobs SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?', (*fields.values(), job_id))


def get_job(job_id):
    with lock, connection() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        return dict(row) if row else None


def enqueue(url, filename=None, folder=None, kind='file', quality='Auto'):
    if not valid_url(url):
        raise ValueError('A direct HTTP or HTTPS URL is required')
    if kind not in ('file', 'video'):
        raise ValueError('Unsupported download type')
    if quality not in ('Auto', 'MP3') and not (isinstance(quality, str) and re.fullmatch(r'\d{3,4}p', quality)
                                                   and 144 <= int(quality[:-1]) <= 4320):
        raise ValueError('Unsupported video quality')
    chosen = Path(folder).expanduser().resolve() if folder else DEST
    if not chosen.is_dir():
        raise ValueError('Choose an existing download folder')
    with lock, connection() as db:
        display = clean_filename(filename) or safe_name(url)
        storage = available_name(db, chosen, display)
        cur = db.execute('INSERT INTO jobs(url,filename,status,folder,storage_name,kind,quality) VALUES(?,?,?,?,?,?,?)',
                         (url, storage, 'queued', str(chosen), storage, kind, quality))
        job_id = cur.lastrowid
    start(job_id)
    return job_id


def probe_file(url):
    """Check that the desktop process can fetch file bytes before browser handoff."""
    if not valid_url(url):
        raise ValueError('A direct HTTP or HTTPS URL is required')
    request = urllib.request.Request(url, headers={
        'Range': 'bytes=0-0', 'User-Agent': 'ToriDownload/0.6',
        'Accept': '*/*', 'Accept-Encoding': 'identity'})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if not valid_url(response.geturl()) or response.status not in (200, 206):
                raise ValueError('The file URL cannot be fetched safely')
            if 'text/html' in response.headers.get('Content-Type', '').lower():
                raise ValueError('The link returned a webpage instead of a file')
            if response.status == 206 and not re.match(r'^bytes 0-0/\d+$', response.headers.get('Content-Range', '')):
                raise ValueError('The server sent an invalid byte range')
            if not response.read(1):
                raise ValueError('The link returned an empty response')
    except urllib.error.HTTPError as exc:
        raise ValueError(f'Server rejected the download (HTTP {exc.code})') from exc
    except urllib.error.URLError as exc:
        raise ValueError(f'Could not reach the file server: {exc.reason}') from exc


def paths(job):
    target = Path(job.get('folder') or DEST) / (job.get('storage_name') or f"{job['id']}-{job['filename']}")
    return target, Path(str(target) + '.part')


def available_name(db, folder, name, exclude_id=None):
    """Reserve a readable filename without overwriting jobs or existing files."""
    stem, suffix = os.path.splitext(name)
    for number in range(1, 10001):
        candidate = name if number == 1 else f'{stem} ({number}){suffix}'
        target = folder / candidate
        claimed = db.execute('SELECT 1 FROM jobs WHERE folder=? AND storage_name=? AND id IS NOT ? LIMIT 1',
                             (str(folder), candidate, exclude_id)).fetchone()
        if not claimed and not target.exists() and not Path(str(target) + '.part').exists():
            return candidate
    raise FileExistsError('Too many files with this name in the selected folder')


def set_download_folder(path):
    global DEST
    folder = Path(path).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError('Choose an existing folder')
    marker = folder / f'.tori-write-check-{os.getpid()}'
    try:
        with marker.open('xb') as check:
            check.write(b'ok')
    except OSError as exc:
        raise ValueError(f'Cannot write to this folder: {exc}') from exc
    finally:
        marker.unlink(missing_ok=True)
    with lock:
        if PORTABLE_DIR and folder.is_relative_to(PORTABLE_DIR):
            configured = str(folder.relative_to(PORTABLE_DIR))
        else:
            configured = str(folder)
        startup.save_config(SETTINGS, {'download_folder':configured})
        DEST = folder


def rename_job(job_id, name):
    clean = clean_filename(name)
    if not clean:
        raise ValueError('Enter a valid filename')
    with lock:
        if job_id in controls:
            raise RuntimeError('Pause this download before renaming it')
        job = get_job(job_id)
        if not job:
            return
        if clean == job['filename'] and clean == job['storage_name']:
            return
        old_target, old_part = paths(job)
        with connection() as db:
            candidate = available_name(db, Path(job['folder']), clean, job_id)
        if candidate != clean:
            raise FileExistsError('A file with this name already exists')
        job['filename'] = clean
        job['storage_name'] = clean
        new_target, new_part = paths(job)
        if (new_target.exists() and new_target != old_target) or (new_part.exists() and new_part != old_part):
            raise FileExistsError('A file with this name already exists')
        if old_target.exists():
            old_target.rename(new_target)
        if old_part.exists():
            old_part.rename(new_part)
        update(job_id, filename=clean, storage_name=clean)


def worker(job_id, stop):
    slots.acquire()
    job = get_job(job_id)
    if not job:
        slots.release()
        return
    target, part = paths(job)
    offset = part.stat().st_size if part.exists() else 0
    headers = {'User-Agent': 'ToriDownload/0.6', 'Accept-Encoding': 'identity'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
        validator = job['etag'] or job['modified']
        if validator:
            headers['If-Range'] = validator
    try:
        if stop.is_set():
            return
        update(job_id, status='downloading', error='', last_try=time.time())
        request = urllib.request.Request(job['url'], headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=25)
        except urllib.error.HTTPError:
            raise
        with response:
            if not valid_url(response.geturl()):
                raise ValueError('Unsafe redirect URL')
            code = response.status
            content_type = response.headers.get('Content-Type', '').lower()
            if 'text/html' in content_type:
                raise ValueError('Server returned an HTML page instead of a file')
            if not offset:
                suggested = disposition_filename(response.headers.get('Content-Disposition'))
                if suggested and job['filename'] == safe_name(job['url']):
                    with lock, connection() as db:
                        suggested = available_name(db, Path(job['folder']), suggested, job_id)
                        update(job_id, filename=suggested, storage_name=suggested)
                        job['filename'] = suggested
                        job['storage_name'] = suggested
                        target, part = paths(job)
            if code == 206:
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+|\*)', response.headers.get('Content-Range', ''))
                if not match or int(match.group(1)) != offset:
                    raise ValueError('Invalid resume response; partial file preserved')
                if offset and ((job['etag'] and response.headers.get('ETag') != job['etag']) or
                               (job['modified'] and response.headers.get('Last-Modified') != job['modified'])):
                    raise ValueError('File changed on server; partial file preserved')
                total = int(match.group(3)) if match.group(3) != '*' else 0
            elif code == 200:
                offset = 0
                total = int(response.headers.get('Content-Length') or 0)
            else:
                raise ValueError(f'Unexpected HTTP status {code}')
            update(job_id, total=total, done=offset, etag=response.headers.get('ETag'), modified=response.headers.get('Last-Modified'))
            last = time.monotonic()
            last_bytes = offset
            with part.open('ab' if offset else 'wb') as output:
                done = offset
                while not stop.is_set():
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last > .4:
                        sample = (done - last_bytes) / max(now - last, .001)
                        speeds[job_id] = smooth_speed(speeds.get(job_id), sample, now-last)
                        speed_times[job_id] = now
                        last_bytes = done
                        update(job_id, done=done)
                        last = now
            update(job_id, done=done)
            if stop.is_set():
                return
            if total and done != total:
                raise IOError(f'Incomplete download: {done} of {total} bytes')
            if target.exists():
                raise FileExistsError(f'Output exists: {target.name}')
            os.replace(part, target)
            update(job_id, status='completed')
    except Exception as exc:
        if not stop.is_set():
            update(job_id, status='failed', error=str(exc)[:240])
    finally:
        speeds.pop(job_id, None)
        speed_times.pop(job_id, None)
        with lock:
            controls.pop(job_id, None)
        slots.release()


def video_worker(job_id, stop):
    """Fetch a public supported video page via yt-dlp; never import browser cookies."""
    slots.acquire()
    try:
        job = get_job(job_id)
        if not job or stop.is_set():
            return
        import yt_dlp
        import imageio_ffmpeg
        folder = Path(job['folder'])
        prefix = f'.tori-video-{job_id}.'
        update(job_id, status='downloading', error='', last_try=time.time())
        def progress(data):
            if stop.is_set():
                raise RuntimeError('Download paused')
            if data.get('status') == 'downloading':
                received = int(data.get('downloaded_bytes') or 0)
                total = int(data.get('total_bytes') or data.get('total_bytes_estimate') or 0)
                update(job_id, done=received, total=total)
                speeds[job_id] = float(data.get('speed') or 0)
                speed_times[job_id] = time.monotonic()
        options = {
            'format':'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b',
            'merge_output_format':'mp4', 'ffmpeg_location':imageio_ffmpeg.get_ffmpeg_exe(),
            'outtmpl':str(folder / (prefix+'%(ext)s')),
            'noplaylist':True, 'quiet':True, 'no_warnings':True,
            'continuedl':True, 'socket_timeout':25, 'retries':3,
            'fragment_retries':3, 'progress_hooks':[progress],
        }
        quality = job.get('quality') or 'Auto'
        if quality == 'MP3':
            options['format'] = 'bestaudio/best'
            options['postprocessors'] = [{'key':'FFmpegExtractAudio',
                                          'preferredcodec':'mp3', 'preferredquality':'192'}]
        elif quality != 'Auto':
            height = int(quality[:-1])
            options['format'] = f'bv*[height<={height}]+ba/b[height<={height}]'
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.download([job['url']])
        if stop.is_set():
            return
        finished = [path for path in folder.glob(prefix+'*')
                    if path.is_file() and path.suffix.lower() in ('.mp3', '.mp4', '.webm', '.mkv', '.mov')]
        if len(finished) != 1:
            raise IOError('Video was not saved in a supported format')
        source = finished[0]
        name = Path(job['filename']).stem + source.suffix.lower()
        with lock, connection() as db:
            target_name = available_name(db, folder, name, job_id)
            target = folder / target_name
            source.rename(target)
            update(job_id, filename=target_name, storage_name=target_name,
                   done=target.stat().st_size, total=target.stat().st_size, status='completed')
    except Exception as exc:
        if not stop.is_set():
            update(job_id, status='failed', error=str(exc)[:240])
    finally:
        speeds.pop(job_id, None)
        speed_times.pop(job_id, None)
        with lock:
            controls.pop(job_id, None)
        slots.release()


def start(job_id):
    with lock:
        job = get_job(job_id)
        if not job or job['status'] in ('completed', 'cancelled', 'downloading') or job_id in controls:
            return
        stop = threading.Event()
        controls[job_id] = stop
        update(job_id, status='queued')
        task = video_worker if job.get('kind') == 'video' else worker
        threading.Thread(target=task, args=(job_id, stop), daemon=True).start()


def stop_job(job_id, status):
    with lock:
        job = get_job(job_id)
        if not job or job['status'] in ('completed', 'cancelled'):
            return
        update(job_id, status=status)
        if job_id in controls:
            controls[job_id].set()


def retry(job_id):
    job = get_job(job_id)
    if job and job['status'] in ('failed', 'cancelled'):
        update(job_id, status='paused', error='')
        start(job_id)


def remove_job(job_id):
    with lock:
        if job_id in controls:
            raise RuntimeError('Pause the download and wait for it to stop before removing it.')
        job = get_job(job_id)
        if not job:
            return
        _, part = paths(job)
        with connection() as db:
            db.execute('DELETE FROM jobs WHERE id=?', (job_id,))
        part.unlink(missing_ok=True)
        if job.get('kind') == 'video':
            for fragment in Path(job['folder']).glob(f'.tori-video-{job_id}.*'):
                if fragment.is_file(): fragment.unlink(missing_ok=True)


def video_qualities(info):
    """Report resolutions actually advertised by this source, plus audio."""
    formats = info.get('formats') or [info]
    heights = set()
    audio = False
    for item in formats:
        if not isinstance(item, dict):
            continue
        if item.get('acodec') not in (None, 'none'):
            audio = True
        if item.get('vcodec') not in (None, 'none'):
            height = item.get('height')
            if isinstance(height, int) and 144 <= height <= 4320:
                heights.add(height)
    return ['Auto'] + [f'{height}p' for height in sorted(heights)] + (['MP3'] if audio else [])


def make_offer(url, filename=None, verify=True, kind='file'):
    if not valid_url(url):
        raise ValueError('A direct HTTP or HTTPS URL is required')
    if kind not in ('file', 'video'):
        raise ValueError('Unsupported download type')
    with lock:
        now = time.monotonic()
        for key, offer in list(offers.items()):
            if now - offer['created'] > 600:
                del offers[key]
        if sum(item['state'] == 'pending' for item in offers.values()) >= 8:
            raise ValueError('Too many download confirmations are open')
        key = secrets.token_urlsafe(18)
        offers[key] = {'url':url, 'filename':clean_filename(filename) or safe_name(url),
                       'verify':bool(verify) and kind == 'file', 'kind':kind,
                       'state':'pending', 'created':now,
                       'qualities':['Auto'], 'quality_state':'checking' if kind == 'video' else 'ready'}
        offer_queue.put(key)
    if kind == 'video':
        def inspect_formats():
            try:
                import yt_dlp
                with yt_dlp.YoutubeDL({'quiet':True,'no_warnings':True,'noplaylist':True,
                                       'skip_download':True,'socket_timeout':10}) as downloader:
                    info = downloader.extract_info(url, download=False)
                found = video_qualities(info) if isinstance(info, dict) else ['Auto']
                state = 'ready'
            except Exception:
                found, state = ['Auto'], 'unavailable'
            with lock:
                if key in offers:
                    offers[key]['qualities'] = found
                    offers[key]['quality_state'] = state
        threading.Thread(target=inspect_formats, daemon=True).start()
    return key


def offer_status(key):
    with lock:
        offer = offers.get(key)
        if not offer:
            return 'fallback'
        if offer['state'] == 'pending' and time.monotonic() - offer['created'] > OFFER_TIMEOUT:
            offer['state'] = 'fallback'
        return offer['state']


def resolve_offer(key, accepted, filename=None, folder=None, quality='Auto'):
    with lock:
        if offer_status(key) != 'pending':
            return False
        offer = offers[key]
        if accepted and quality not in offer['qualities']:
            raise ValueError('Choose an available quality')
        if not accepted:
            offer['state'] = 'declined'
            return True
        offer['state'] = 'checking'

    def finish():
        try:
            if offer['verify']:
                probe_file(offer['url'])
            enqueue(offer['url'], filename or offer['filename'], folder,
                    offer.get('kind', 'file'), quality)
            state = 'accepted'
        except (ValueError, OSError, KeyError) as exc:
            state = 'fallback'
            offer['error'] = str(exc)[:240]
        with lock:
            offer['state'] = state
    threading.Thread(target=finish, daemon=True).start()
    return True


def abort_offers():
    with lock:
        for offer in offers.values():
            if offer['state'] == 'pending':
                offer['state'] = 'fallback'


class Handler(BaseHTTPRequestHandler):
    def trusted(self):
        if self.headers.get('Host', '') != '127.0.0.1:8765':
            return False
        origin = self.headers.get('Origin')
        return origin == TRUSTED_ORIGIN or (not origin and self.headers.get('X-Tori-Connector') == CONNECTOR_ID)

    def do_GET(self):
        if self.path.startswith('/offer/'):
            if not self.trusted():
                return self.reply(403, 'Forbidden')
            return self.reply(200, json.dumps({'result':offer_status(self.path[7:])}))
        if (self.path != '/health' or self.headers.get('Host', '') != '127.0.0.1:8765'
                or self.headers.get('Origin') not in (None, TRUSTED_ORIGIN)):
            return self.reply(403, 'Forbidden')
        self.reply(200, 'Tori desktop app connected')

    def do_POST(self):
        if self.path not in ('/enqueue', '/offer') or not self.trusted():
            return self.reply(403, 'Forbidden')
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8192:
                return self.reply(413, 'Invalid request size')
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError('Invalid request body')
            if self.path == '/offer':
                key = make_offer(payload['url'], payload.get('filename'),
                                 payload.get('verify', True), payload.get('kind', 'file'))
                return self.reply(200, json.dumps({'id':key}))
            if payload.get('verify'):
                probe_file(payload['url'])
            job_id = enqueue(payload['url'], payload.get('filename'))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return self.reply(400, str(exc))
        self.reply(200, str(job_id))

    def do_OPTIONS(self):
        if not self.trusted():
            return self.reply(403, 'Forbidden')
        self.reply(204, '')

    def reply(self, code, message):
        origin = self.headers.get('Origin', '')
        self.send_response(code)
        if origin == TRUSTED_ORIGIN:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Tori-Connector')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(message.encode())

    def log_message(self, *_):
        pass


def main():
    import ui
    global server_ready
    try:
        startup.sync_startup(SETTINGS, default=STARTUP_DEFAULT, run_name=STARTUP_NAME)
    except OSError as exc:
        if '--background' not in sys.argv:
            messagebox.showwarning('Windows startup', f'Tori could not enable sign-in startup: {exc}')
    try:
        server = ThreadingHTTPServer(('127.0.0.1', 8765), Handler)
    except OSError as exc:
        messagebox.showerror('Browser connection unavailable', f'Could not start local connector: {exc}')
        server = None
    if server:
        server_ready = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        ui.run(sys.modules[__name__])
    finally:
        abort_offers()
        if server:
            server.shutdown()
            server_ready = False


if __name__ == '__main__':
    main()
