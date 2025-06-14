import os
import sys
import subprocess
import sqlite3
import uuid
import time
import threading
from datetime import datetime, timedelta

# --- Dependency Installation ---
try:
    from flask import Flask, request, send_from_directory, jsonify, render_template_string, abort
    from werkzeug.utils import secure_filename
    import waitress
except ImportError:
    print("[-] Required libraries not found. Attempting to install...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "Flask", "werkzeug", "waitress"])
        print("[+] Libraries installed successfully.")
        from flask import Flask, request, send_from_directory, jsonify, render_template_string, abort
        from werkzeug.utils import secure_filename
        import waitress
    except Exception as e:
        print(f"[!] Critical Error: Failed to install required libraries: {e}")
        print("[!] Please install them manually using: pip install Flask werkzeug waitress")
        sys.exit(1)

# --- Configuration ---
UPLOAD_FOLDER = 'uploads'
DATABASE_FILE = 'file_registry.db'
ALLOWED_EXTENSIONS = {'zip', 'rar', '7z'}
MAX_CONTENT_LENGTH = 1 * 1024 * 1024 * 1024  # 1 GB
EXPIRATION_DAYS = 3
TOKEN_EXPIRATION_MINUTES = 60 # A download token is valid for 1 hour
HOST = '0.0.0.0'
PORT = 8080

# --- Flask App Initialization ---
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# --- Helper Functions ---
def get_db_connection():
    """Establishes a connection to the SQLite database."""
    print("[DB] Connecting to database...")
    conn = sqlite3.connect(DATABASE_FILE, check_same_thread=False) # Allow multi-thread access
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database schema if it doesn't exist."""
    print("[Setup] Initializing database...")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Main table for active files
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                saved_filename TEXT NOT NULL,
                upload_timestamp REAL NOT NULL,
                last_download_timestamp REAL NOT NULL,
                file_size INTEGER NOT NULL,
                download_count INTEGER NOT NULL DEFAULT 0
            )
        ''')
        # Table for download tokens
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS download_tokens (
                token TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                expiration_timestamp REAL NOT NULL,
                FOREIGN KEY (file_id) REFERENCES files (id)
            )
        ''')
        # Separate table for persistent stats
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            )
        ''')
        # Check if total_uploads stat exists, if not, create it
        cursor.execute("SELECT value FROM stats WHERE key = 'total_uploads'")
        if cursor.fetchone() is None:
            print("[Setup] Initializing 'total_uploads' stat.")
            cursor.execute("INSERT INTO stats (key, value) VALUES ('total_uploads', 0)")
        
        conn.commit()
        print("[Setup] Database initialized successfully.")

def allowed_file(filename):
    """Checks if the file extension is in the allowed list."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Background Cleanup Thread ---
def cleanup_expired_items():
    """Periodically checks for and deletes expired files and tokens."""
    print(f"[Cleanup] Cleanup thread started. Will run every hour.")
    while True:
        try:
            print("[Cleanup] Running scheduled cleanup...")
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # --- Clean up expired files ---
                file_expiration_limit = time.time() - timedelta(days=EXPIRATION_DAYS).total_seconds()
                cursor.execute("SELECT id, saved_filename FROM files WHERE last_download_timestamp < ?", (file_expiration_limit,))
                expired_files = cursor.fetchall()
                
                if not expired_files:
                    print("[Cleanup] No expired files found.")
                else:
                    for file_record in expired_files:
                        file_id = file_record['id']
                        saved_filename = file_record['saved_filename']
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)
                        print(f"[Cleanup] Deleting expired file: {saved_filename} (ID: {file_id})")
                        if os.path.exists(file_path): os.remove(file_path)
                        cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))
                        cursor.execute("DELETE FROM download_tokens WHERE file_id = ?", (file_id,)) # Clean associated tokens
                
                # --- Clean up expired tokens ---
                token_expiration_limit = time.time()
                cursor.execute("DELETE FROM download_tokens WHERE expiration_timestamp < ?", (token_expiration_limit,))
                deleted_tokens_count = cursor.rowcount
                if deleted_tokens_count > 0:
                    print(f"[Cleanup] Cleared {deleted_tokens_count} expired download tokens.")

                conn.commit()
                print("[Cleanup] Cleanup process finished.")

        except Exception as e:
            print(f"[!] Error in cleanup thread: {e}")

        time.sleep(3600) # Wait for an hour

# --- Flask Routes ---
@app.route('/')
def index():
    """Serves the main HTML page."""
    print(f"[*] Request for index page from {request.remote_addr}")
    try:
        with open('index.html', 'r') as f:
            return render_template_string(f.read())
    except FileNotFoundError:
        return "<h1>Error: Frontend file 'index.html' not found.</h1>", 404

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handles file uploads."""
    # (Same upload logic as before, but returns a page link instead)
    print(f"[*] Received upload request from {request.remote_addr}")
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request."}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file."}), 400

    if file and allowed_file(file.filename):
        original_filename = secure_filename(file.filename)
        file_extension = original_filename.rsplit('.', 1)[1]
        unique_id = str(uuid.uuid4())
        saved_filename = f"{unique_id}.{file_extension}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)
        
        try:
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            file.save(file_path)
            
            current_time = time.time()
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO files (id, original_filename, saved_filename, upload_timestamp, last_download_timestamp, file_size) VALUES (?, ?, ?, ?, ?, ?)",
                    (unique_id, original_filename, saved_filename, current_time, current_time, file_size)
                )
                cursor.execute("UPDATE stats SET value = value + 1 WHERE key = 'total_uploads'")
                conn.commit()
            
            page_link = f"{request.host_url}page/{unique_id}"
            return jsonify({
                "success": True, 
                "message": "File uploaded successfully!",
                "page_link": page_link
            }), 201
        except Exception as e:
            print(f"[!] Error during file save or DB operation: {e}")
            return jsonify({"error": "An internal error occurred."}), 500
    else:
        return jsonify({"error": f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"}), 400

@app.route('/page/<file_id>')
def file_page(file_id):
    """Serves the dedicated download page for a file."""
    print(f"[*] Serving file page for ID: {file_id}")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT original_filename, file_size FROM files WHERE id = ?", (file_id,))
        file_record = cursor.fetchone()

    if file_record:
        try:
            with open('download_page.html', 'r') as f:
                # Pass file data to the template
                return render_template_string(
                    f.read(), 
                    file_id=file_id,
                    file_name=file_record['original_filename'],
                    file_size=round(file_record['file_size'] / (1024*1024), 2) # MB
                )
        except FileNotFoundError:
            return "<h1>Error: 'download_page.html' not found on server.</h1>", 500
    else:
        return "<h1>File not found</h1><p>The link may have expired or is incorrect.</p>", 404

@app.route('/generate_download_link/<file_id>', methods=['POST'])
def generate_download_link(file_id):
    """Generates a temporary download token and link."""
    print(f"[*] Generating download token for file ID: {file_id}")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM files WHERE id = ?", (file_id,))
        if not cursor.fetchone():
            return jsonify({"error": "File not found"}), 404
        
        token = str(uuid.uuid4())
        expiration = time.time() + timedelta(minutes=TOKEN_EXPIRATION_MINUTES).total_seconds()
        
        cursor.execute("INSERT INTO download_tokens (token, file_id, expiration_timestamp) VALUES (?, ?, ?)",
                       (token, file_id, expiration))
        conn.commit()
        
        download_link = f"{request.host_url}download/{token}"
        print(f"  -> Generated link: {download_link}")
        return jsonify({"success": True, "download_link": download_link})

@app.route('/download/<token>')
def download_file_with_token(token):
    """Serves a file for download using a valid token."""
    print(f"[*] Download request with token: {token}")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Check if token is valid and not expired
        cursor.execute("SELECT file_id FROM download_tokens WHERE token = ? AND expiration_timestamp > ?", (token, time.time()))
        token_record = cursor.fetchone()
        
        if not token_record:
            print(f"[-] Invalid or expired token: {token}")
            # Invalidate the token after one use attempt
            cursor.execute("DELETE FROM download_tokens WHERE token = ?", (token,))
            conn.commit()
            return "<h1>Link Expired or Invalid</h1><p>Please return to the file page to generate a new download link.</p>", 403
            
        file_id = token_record['file_id']
        cursor.execute("SELECT saved_filename, original_filename FROM files WHERE id = ?", (file_id,))
        file_record = cursor.fetchone()
        
        if file_record:
            # Update last download time and count on the main file record
            cursor.execute(
                "UPDATE files SET last_download_timestamp = ?, download_count = download_count + 1 WHERE id = ?",
                (time.time(), file_id)
            )
            # IMPORTANT: Delete the token after use to make it a one-time link
            cursor.execute("DELETE FROM download_tokens WHERE token = ?", (token,))
            conn.commit()

            print(f"  -> Token valid. Serving file '{file_record['original_filename']}'")
            return send_from_directory(
                app.config['UPLOAD_FOLDER'],
                file_record['saved_filename'],
                as_attachment=True,
                download_name=file_record['original_filename']
            )
        else:
            # This case is unlikely if token exists, but good for safety
            return "<h1>File not found</h1><p>The file associated with this link is no longer available.</p>", 404


@app.route('/stats')
def get_stats():
    """Provides statistics about the stored files."""
    # (No changes needed here)
    print("[*] Request for stats")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), SUM(file_size) FROM files")
            active_files, total_size = cursor.fetchone()
            cursor.execute("SELECT value FROM stats WHERE key = 'total_uploads'")
            total_uploads = cursor.fetchone()[0]
            
            return jsonify({
                "active_files": active_files or 0,
                "current_storage_gb": round((total_size or 0) / (1024**3), 4),
                "total_uploads_ever": total_uploads or 0
            })
    except Exception as e:
        print(f"[!] Error fetching stats: {e}")
        return jsonify({"error": "Could not retrieve stats."}), 500


# --- Main Execution ---
if __name__ == '__main__':
    print("--- Simple File Share Server (V2) ---")
    
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    init_db()

    cleanup_thread = threading.Thread(target=cleanup_expired_items, daemon=True)
    cleanup_thread.start()
    
    print(f"\n[+] Server starting...")
    print(f"[+] Go to http://{HOST}:{PORT} (or http://127.0.0.1:{PORT} on this machine).")
    waitress.serve(app, host=HOST, port=PORT)
