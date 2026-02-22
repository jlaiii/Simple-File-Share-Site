from flask import Flask, request, render_template, jsonify, send_from_directory, url_for, abort
import os
import time
import socket
import werkzeug.utils
import sqlite3
import uuid
import zipfile
import shutil
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
import os as _os
import sys as _sys
_project_dir = _os.path.dirname(_os.path.abspath(__file__))
if _project_dir not in _sys.path:
    _sys.path.insert(0, _project_dir)
try:
    import uptime_tracker
except Exception:
    uptime_tracker = None

# Load .env if present
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DB_PATH = os.path.join(BASE_DIR, 'files.db')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Config
MAX_FILE_BYTES = int(os.environ.get('MAX_FILE_BYTES', 1 * 1024 ** 3))  # 1 GB
# Respect an explicit TOTAL_SPACE_BYTES env var, otherwise leave None so
# the physical disk total is used as the site quota.
_env_total = os.environ.get('TOTAL_SPACE_BYTES')
try:
    TOTAL_SPACE_BYTES = int(_env_total) if _env_total is not None else None
except Exception:
    TOTAL_SPACE_BYTES = None
DELETE_AFTER_DAYS = int(os.environ.get('DELETE_AFTER_DAYS', 7))

app = Flask(__name__, template_folder='templates')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_BYTES + 1024  # small buffer


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# Logging setup
def setup_logging():
    log_path = os.path.join(BASE_DIR, 'server.log')
    handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3)
    handler.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    handler.setFormatter(fmt)
    app.logger.addHandler(handler)


@app.after_request
def set_security_headers(resp):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
    resp.headers['X-XSS-Protection'] = '1; mode=block'
    return resp


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            original_name TEXT,
            stored_name TEXT,
            size INTEGER,
            uploaded_at INTEGER,
            last_downloaded INTEGER,
            download_count INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()


def human(n):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if n < 1024.0:
            return f"{n:3.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def get_used_space():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT SUM(size) as s FROM files')
    row = c.fetchone()
    conn.close()
    return row['s'] or 0


def get_disk_totals():
    usage = shutil.disk_usage(UPLOAD_FOLDER)
    return usage.total, usage.free


def get_site_totals(used_bytes=0):
    """Return (site_total, site_free, disk_total, disk_free).

    site_total is the effective total the site will show/enforce. If
    `TOTAL_SPACE_BYTES` is set and is smaller than the physical disk total,
    the site will use that limit. Otherwise the physical disk total is used.
    site_free is computed from `site_total - used_bytes` (never negative).
    Also return the physical disk totals for checks that must use real free
    space when writing files.
    """
    disk_total, disk_free = get_disk_totals()
    env_total = globals().get('TOTAL_SPACE_BYTES')
    try:
        env_total = int(env_total) if env_total is not None else None
    except Exception:
        env_total = None
    if env_total and env_total > 0:
        site_total = min(disk_total, env_total)
    else:
        site_total = disk_total
    site_free = max(0, site_total - (used_bytes or 0))
    return site_total, site_free, disk_total, disk_free


def cleanup_job():
    now = int(time.time())
    cutoff = now - DELETE_AFTER_DAYS * 86400
    conn = get_db()
    c = conn.cursor()
    # delete files where last_downloaded older than cutoff or never downloaded and uploaded before cutoff
    c.execute('SELECT id, stored_name FROM files WHERE (last_downloaded IS NULL AND uploaded_at < ?) OR (last_downloaded IS NOT NULL AND last_downloaded < ?)', (cutoff, cutoff))
    rows = c.fetchall()
    for r in rows:
        path = os.path.join(UPLOAD_FOLDER, r['stored_name'])
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            app.logger.exception('failed to remove %s', path)
        c.execute('DELETE FROM files WHERE id = ?', (r['id'],))
    conn.commit()
    conn.close()


@app.route('/')
def index():
    used = get_used_space()
    total, free, disk_total, disk_free = get_site_totals(used)
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as cnt FROM files')
    cnt = c.fetchone()['cnt']
    conn.close()
    try:
        uptime_30d = uptime_tracker.get_30day_pct() if uptime_tracker else None
    except Exception:
        uptime_30d = None
    return render_template('index.html', used=used, total=total, free=free, files_count=cnt, human=human, uptime_30d=uptime_30d)


@app.route('/stats')
def stats():
    used = get_used_space()
    total, free, disk_total, disk_free = get_site_totals(used)
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as cnt FROM files')
    cnt = c.fetchone()['cnt']
    conn.close()
    return jsonify({
        'used': used,
        'total': total,
        'free': free,
        'disk_total': disk_total,
        'disk_free': disk_free,
        'files': cnt
    })


@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'no file part'}), 400

    # attempt cleanup to free old files before accepting upload
    try:
        cleanup_job()
    except Exception:
        app.logger.exception('cleanup during upload failed')

    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': 'no selected file'}), 400
    original_name = werkzeug.utils.secure_filename(f.filename)

    # pre-check content-length if available
    content_len = request.content_length
    if content_len and content_len > MAX_FILE_BYTES:
        return jsonify({'error': 'file too large (limit %d bytes)' % MAX_FILE_BYTES}), 413

    # ensure there is enough free disk space and site quota
    used_now = get_used_space()
    site_total, site_free, disk_total, disk_free = get_site_totals(used_now)
    needed = (content_len or 0) + 1024
    if content_len and (disk_free < needed or site_free < needed):
        try:
            cleanup_job()
            used_now = get_used_space()
            site_total, site_free, disk_total, disk_free = get_site_totals(used_now)
        except Exception:
            pass
        if disk_free < needed or site_free < needed:
            return jsonify({'error': 'not enough disk space'}), 507

    # save to temporary file
    tmp_name = str(uuid.uuid4()) + '.tmp'
    tmp_path = os.path.join(UPLOAD_FOLDER, tmp_name)
    f.save(tmp_path)

    # verify size after save
    orig_size = os.path.getsize(tmp_path)
    if orig_size > MAX_FILE_BYTES:
        os.remove(tmp_path)
        return jsonify({'error': 'file too large (limit %d bytes)' % MAX_FILE_BYTES}), 413

    # re-check both physical free space and site quota after save
    used_now = get_used_space()
    site_total, site_free, disk_total, disk_free = get_site_totals(used_now)
    if disk_free < orig_size + 1024 or site_free < orig_size + 1024:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return jsonify({'error': 'not enough disk space after upload'}), 507

    # zip and store
    file_id = str(uuid.uuid4())
    stored_name = f'{file_id}.zip'
    stored_path = os.path.join(UPLOAD_FOLDER, stored_name)
    try:
        with zipfile.ZipFile(stored_path, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(tmp_path, arcname=original_name)
        zip_size = os.path.getsize(stored_path)
        if zip_size > MAX_FILE_BYTES:
            os.remove(tmp_path)
            os.remove(stored_path)
            return jsonify({'error': 'zipped file too large after compression'}), 413

        # final quota check: ensure storing the zipped file doesn't exceed site quota
        used_now = get_used_space()
        site_total, site_free, disk_total, disk_free = get_site_totals(used_now)
        if disk_free < zip_size + 1024 or site_free < zip_size + 1024:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            try:
                os.remove(stored_path)
            except Exception:
                pass
            return jsonify({'error': 'not enough disk space to store file'}), 507

        conn = get_db()
        c = conn.cursor()
        now = int(time.time())
        c.execute('INSERT INTO files (id, original_name, stored_name, size, uploaded_at) VALUES (?, ?, ?, ?, ?)', (file_id, original_name, stored_name, zip_size, now))
        conn.commit()
        conn.close()
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

    return jsonify({
        'id': file_id,
        'page_url': url_for('download_page', file_id=file_id, _external=True),
        'download_url': url_for('download', file_id=file_id, _external=True)
    })


@app.route('/file/<file_id>')
def download_page(file_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, original_name, stored_name, size, uploaded_at, download_count FROM files WHERE id = ?', (file_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        abort(404)
    file = dict(row)
    file['uploaded_at'] = datetime.utcfromtimestamp(file['uploaded_at']).isoformat() + 'Z'
    file['size_human'] = human(file['size'])
    return render_template('download.html', file=file)


@app.route('/f/<file_id>')
def view_file(file_id):
    # alternate view route to avoid proxy/path rewrite conflicts
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, original_name, stored_name, size, uploaded_at, download_count FROM files WHERE id = ?', (file_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        abort(404)
    file = dict(row)
    file['uploaded_at'] = datetime.utcfromtimestamp(file['uploaded_at']).isoformat() + 'Z'
    file['size_human'] = human(file['size'])
    return render_template('download.html', file=file)


@app.route('/download/<file_id>')
def download(file_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, original_name, stored_name FROM files WHERE id = ?', (file_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        abort(404)
    stored_name = row['stored_name']
    original = row['original_name']
    path = os.path.join(UPLOAD_FOLDER, stored_name)
    if not os.path.exists(path):
        c.execute('DELETE FROM files WHERE id = ?', (file_id,))
        conn.commit()
        conn.close()
        abort(404)
    # update stats
    now = int(time.time())
    c.execute('UPDATE files SET last_downloaded = ?, download_count = download_count + 1 WHERE id = ?', (now, file_id))
    conn.commit()
    conn.close()
    # send the zip as attachment but with original filename (zip contains original)
    return send_from_directory(UPLOAD_FOLDER, stored_name, as_attachment=True, download_name=original + '.zip')


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    # legacy support if needed
    return send_from_directory(UPLOAD_FOLDER, filename)


def start_scheduler():
    sched = BackgroundScheduler()
    sched.add_job(cleanup_job, 'interval', hours=24, next_run_time=datetime.now())
    sched.start()


def app_startup():
    init_db()
    setup_logging()
    start_scheduler()
    if uptime_tracker:
        try:
            uptime_tracker.start()
        except Exception:
            app.logger.exception('failed to start uptime tracker')


_startup_done = False

@app.before_request
def _ensure_startup():
    global _startup_done
    if _startup_done:
        return
    try:
        app_startup()
    except Exception:
        app.logger.exception('app_startup failed in before_request')
    _startup_done = True


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=3109)
    parser.add_argument('--total-space-gb', type=int, default=None, help='override total space in GB')
    args = parser.parse_args()
    if args.total_space_gb is not None:
        TOTAL = args.total_space_gb * 1024 ** 3
        globals()['TOTAL_SPACE_BYTES'] = TOTAL
    app_startup()
    app.run(host=args.host, port=args.port)
