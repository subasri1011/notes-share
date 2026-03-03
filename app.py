import os
import uuid
import sqlite3
import psycopg2
import psycopg2.extras
import cloudinary
import cloudinary.uploader
import cloudinary.api
import cloudinary.utils
import boto3
from io import BytesIO
from dotenv import load_dotenv
from flask import (Flask, render_template, request, redirect,
                   url_for, flash, session, send_from_directory, abort, jsonify)
import firebase_admin
from firebase_admin import credentials, auth
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from flask_wtf.csrf import CSRFProtect
from flask_talisman import Talisman
from utils import with_retry, CircuitBreaker, get_monitoring_stats

# ─────────────────────────── Circuit Breakers ───────────────────────
db_cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30)
storage_cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

# ─────────────────────────── Environment ────────────────────────────
load_dotenv()

CLOUDINARY_CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME')
CLOUDINARY_API_KEY    = os.getenv('CLOUDINARY_API_KEY')
CLOUDINARY_API_SECRET = os.getenv('CLOUDINARY_API_SECRET')
DATABASE_URL          = os.getenv('DATABASE_URL')
AWS_ACCESS_KEY_ID     = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
S3_BUCKET_NAME        = os.getenv('S3_BUCKET_NAME')
AWS_REGION            = os.getenv('AWS_REGION', 'ap-south-1')
DB_NAME               = 'users.db'  # local SQLite fallback only

# ─────────────────────────── Firebase Auth Setup ────────────────────
def initialize_firebase():
    """Initialize Firebase Admin SDK with support for local file or env var."""
    try:
        # Check if already initialized
        if firebase_admin._apps:
            print('[OK] Firebase Admin already initialized')
            return

        # Option 1: Check for JSON credentials in environment variable
        # Support both FIREBASE_CREDENTIALS_JSON and FIREBASE_CONFIG_JSON
        firebase_creds_json = os.getenv('FIREBASE_CREDENTIALS_JSON') or os.getenv('FIREBASE_CONFIG_JSON')
        if firebase_creds_json:
            import json
            cred_dict = json.loads(firebase_creds_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            print('[OK] Firebase Admin Initialized from environment variable')
            return

        # Option 2: Check for local firebase_key.json file
        if os.path.exists('firebase_key.json'):
            cred = credentials.Certificate('firebase_key.json')
            firebase_admin.initialize_app(cred)
            print('[OK] Firebase Admin Initialized from firebase_key.json')
            return

        # Option 3: Try default credentials (GOOGLE_APPLICATION_CREDENTIALS env var)
        try:
            firebase_admin.initialize_app()
            print('[OK] Firebase Admin Initialized with default credentials')
        except Exception as e:
            print(f'[WARN] Firebase initialization deferred (No credentials found): {e}')

    except Exception as e:
        print(f'[WARN] Firebase initialization failed: {e}')

initialize_firebase()

# ─────────────────────────── Storage Setup ──────────────────────────
cloudinary_active = False
if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
    try:
        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_API_SECRET,
            secure=True
        )
        cloudinary_active = True
        print('[OK] Cloudinary Connected')
    except Exception as e:
        print(f'[ERROR] Cloudinary: {e}')

s3_client = None
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and S3_BUCKET_NAME:
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        print('[OK] AWS S3 Connected')
    except Exception as e:
        print(f'[ERROR] S3: {e}')

def get_storage_type():
    if cloudinary_active: return 'cloudinary'
    if s3_client:         return 's3'
    return 'local'

# ─────────────────────────── Storage Helpers ────────────────────────
def sanitize_public_id(filename):
    """Sanitize filename to be used as a Cloudinary public_id (readable for analytics)."""
    base_name = os.path.splitext(filename)[0][:100]  # limit length
    clean = "".join(c for c in base_name if c.isalnum() or c in ('-', '_')).strip()
    return f"{clean}_{uuid.uuid4().hex[:6]}"

class StorageService:
    @staticmethod
    @with_retry(max_attempts=3, circuit_breaker=storage_cb)
    def upload(file, stored_name):
        storage = get_storage_type()
        if storage == 'cloudinary':
            res_type = _cloudinary_res_type(stored_name)
            # Upload with explicit public_id — do NOT use use_filename/unique_filename
            # as they override or conflict with public_id on some SDK versions
            result = cloudinary.uploader.upload(
                file,
                public_id=stored_name,
                resource_type=res_type,
                overwrite=True
            )
            actual_public_id = result.get('public_id', 'UNKNOWN')
            actual_res_type  = result.get('resource_type', res_type)
            print(f'[UPLOAD] Cloudinary OK: public_id={actual_public_id} type={actual_res_type}')
            return actual_res_type

        elif storage == 's3':
            s3_client.upload_fileobj(file, S3_BUCKET_NAME, stored_name,
                                     ExtraArgs={'ContentType': file.content_type})
            return 'raw'
        else:
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], stored_name))
            return 'raw'

    @staticmethod
    @with_retry(max_attempts=2, circuit_breaker=storage_cb)
    def delete(filename, res_type=None):
        storage = get_storage_type()
        if storage == 'cloudinary':
            if not res_type:
                res_type = _cloudinary_res_type(filename)
            cloudinary.uploader.destroy(filename, resource_type=res_type)
        elif storage == 's3':
            s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=filename)
        elif storage == 'local':
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(path):
                os.remove(path)

# ─────────────────────────── Flask App ──────────────────────────────
app = Flask(__name__)
_secret_key_env = os.getenv('SECRET_KEY')
if _secret_key_env:
    app.secret_key = _secret_key_env
else:
    # Persist a generated key so sessions survive restarts
    _key_file = os.path.join(os.path.dirname(__file__), '.secret_key')
    if os.path.exists(_key_file):
        with open(_key_file, 'rb') as _f:
            app.secret_key = _f.read()
    else:
        _new_key = os.urandom(32)
        with open(_key_file, 'wb') as _f:
            _f.write(_new_key)
        app.secret_key = _new_key
app.config['UPLOAD_FOLDER']          = 'uploads'
app.config['MAX_CONTENT_LENGTH']     = 30 * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

csrf = CSRFProtect(app)

csp = {
    'default-src': ["'self'"],
    'script-src':  ["'self'", "'unsafe-inline'", "'unsafe-eval'", 
                    'cdnjs.cloudflare.com', 'cdn.tailwindcss.com', 
                    '*.gstatic.com', 'cdn.jsdelivr.net', 'unpkg.com', 
                    'apis.google.com', '*.googleapis.com'],
    'style-src':   ["'self'", "'unsafe-inline'", 'cdnjs.cloudflare.com', 
                    '*.googleapis.com', '*.fontshare.com'],
    'font-src':    ["'self'", '*.gstatic.com', 'cdnjs.cloudflare.com', 
                    '*.fontshare.com'],
    'img-src':     ["'self'", 'data:', '*', 'grainy-gradients.vercel.app'],
    'frame-src':   ["'self'", '*.cloudinary.com', '*.amazonaws.com', 
                    '*.firebaseapp.com', 'apis.google.com', '*.google.com'],
    'connect-src': ["'self'", '*.googleapis.com', '*.firebaseapp.com', 
                    '*.firebaseio.com', 'firebaseinstallations.googleapis.com', 
                    'api.emailjs.com', 'cdn.jsdelivr.net'],
}

# Apply Talisman with the relaxed CSP
# We disable force_https here because Render handles it, and it can 
# sometimes interfere with session cookies in certain dev setups.
# session_cookie_secure is set to False for local development.
# We consider it prod ONLY if DATABASE_URL is set AND we're NOT in debug mode.
is_prod = (DATABASE_URL is not None) and (not app.debug)
talisman = Talisman(
    app, 
    content_security_policy=csp, 
    force_https=False,
    session_cookie_secure=is_prod, 
    session_cookie_http_only=True,
    session_cookie_samesite='Lax'
)

ALLOWED_EXTENSIONS = {
    'pdf', 'ppt', 'pptx', 'doc', 'docx',
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg',
    'txt', 'xlsx', 'xls', 'csv', 'py', 'java', 'cpp', 'c', 'js', 'html', 'css'
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ─────────────────────────── DB Helpers ─────────────────────────────
class CursorWrapper:
    def __init__(self, cursor, is_pg):
        self.cursor = cursor
        self.is_pg  = is_pg

    def execute(self, query, params=()):
        if self.is_pg:
            query = query.replace('?', '%s')
        self.cursor.execute(query, params)
        return self

    @property
    def lastrowid(self):
        if self.is_pg:
            try:
                row = self.cursor.fetchone()
                return row['id'] if row else None
            except Exception:
                return None
        return self.cursor.lastrowid

    def fetchone(self):  return self.cursor.fetchone()
    def fetchall(self):  return self.cursor.fetchall()
    def close(self):
        try: self.cursor.close()
        except: pass


class DBWrapper:
    def __init__(self, conn, is_pg):
        self.conn  = conn
        self.is_pg = is_pg

    def execute(self, query, params=()):
        if self.is_pg:
            query = query.replace('?', '%s')
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(query, params)
            return CursorWrapper(cur, True)
        else:
            cur = self.conn.execute(query, params)
            return CursorWrapper(cur, False)

    def cursor(self):
        if self.is_pg:
            return CursorWrapper(self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor), True)
        return CursorWrapper(self.conn.cursor(), False)

    def commit(self): self.conn.commit()
    def rollback(self): self.conn.rollback()
    def close(self):  self.conn.close()


@with_retry(max_attempts=3, base_delay=0.5, circuit_breaker=db_cb)
def get_db_connection():
    if DATABASE_URL:
        url = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        conn = psycopg2.connect(url)
        return DBWrapper(conn, True)
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return DBWrapper(conn, False)

# ─────────────────────────── Schema Init ────────────────────────────
@with_retry(max_attempts=5, base_delay=2, circuit_breaker=db_cb)
def init_db():
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','student'))
        )''' if DATABASE_URL else '''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','student'))
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS files (
            id SERIAL PRIMARY KEY,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            uploader_username TEXT NOT NULL,
            subject TEXT NOT NULL,
            semester TEXT NOT NULL,
            category TEXT DEFAULT 'Study Material',
            dept TEXT DEFAULT 'General',
            description TEXT,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            file_type TEXT NOT NULL,
            file_size BIGINT NOT NULL,
            storage_resource_type TEXT,
            circular_type TEXT DEFAULT 'standalone', -- 'standalone', 'inter', 'intra'
            related_circular_ids TEXT -- comma-separated IDs
        )''' if DATABASE_URL else '''CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            uploader_username TEXT NOT NULL,
            subject TEXT NOT NULL,
            semester TEXT NOT NULL,
            category TEXT DEFAULT 'Study Material',
            dept TEXT DEFAULT 'General',
            description TEXT,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            file_type TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            storage_resource_type TEXT,
            circular_type TEXT DEFAULT 'standalone', -- 'standalone', 'inter', 'intra'
            related_circular_ids TEXT -- comma-separated IDs
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY,
            file_id INTEGER NOT NULL,
            user_id INTEGER,
            username TEXT,
            guest_dept TEXT,
            comment TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''' if DATABASE_URL else '''CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            user_id INTEGER,
            username TEXT,
            guest_dept TEXT,
            comment TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            message TEXT NOT NULL,
            link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''' if DATABASE_URL else '''CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            event_date DATE,
            event_type TEXT NOT NULL CHECK(event_type IN ('inter', 'intra')),
            venue TEXT,
            organizer TEXT,
            register_link TEXT,
            image_filename TEXT,
            storage_resource_type TEXT,
            uploader_username TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''' if DATABASE_URL else '''CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            event_date DATE,
            event_type TEXT NOT NULL CHECK(event_type IN ('inter', 'intra')),
            venue TEXT,
            organizer TEXT,
            register_link TEXT,
            image_filename TEXT,
            storage_resource_type TEXT,
            uploader_username TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS circulars (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            dept TEXT,
            stored_filename TEXT,
            original_filename TEXT,
            file_type TEXT,
            storage_resource_type TEXT,
            uploader_username TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''' if DATABASE_URL else '''CREATE TABLE IF NOT EXISTS circulars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            dept TEXT,
            stored_filename TEXT,
            original_filename TEXT,
            file_type TEXT,
            storage_resource_type TEXT,
            uploader_username TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS event_rsvps (
            id SERIAL PRIMARY KEY,
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(event_id, user_id)
        )''' if DATABASE_URL else '''CREATE TABLE IF NOT EXISTS event_rsvps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(event_id, user_id)
        )''')

        # Patch missing columns on existing tables (safe, idempotent)
        patches = [
            ('files', 'category', "TEXT DEFAULT 'Study Material'"),
            ('files', 'dept',     "TEXT DEFAULT 'General'"),
            ('files', 'description', 'TEXT'),
            ('files', 'storage_resource_type', 'TEXT'),
            ('events', 'is_archived', 'BOOLEAN DEFAULT FALSE' if DATABASE_URL else 'INTEGER DEFAULT 0'),
            ('circulars', 'is_archived', 'BOOLEAN DEFAULT FALSE' if DATABASE_URL else 'INTEGER DEFAULT 0'),
        ]
        
        if DATABASE_URL:
            for table, col, definition in patches:
                c.execute(f"SELECT 1 FROM information_schema.columns WHERE table_name='{table}' AND column_name='{col}'")
                if not c.fetchone():
                    c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {definition}')
        else:
            for table, col, definition in patches:
                try:
                    c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {definition}')
                except Exception as e:
                    pass

        # Default Administrative Account
        active_admins = [
            ('DSCEAdmin', 'DSCE@Admin2552')
        ]
        for username, password in active_admins:
            c.execute("SELECT id FROM users WHERE username = ?", (username, ))
            if not c.fetchone():
                c.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    (username, generate_password_hash(password), 'admin')
                )

        conn.commit()
        print('[OK] Database schema ready')
    except Exception as e:
        print(f'[ERROR] DB init: {e}')
    finally:
        if conn:
            try: conn.close()
            except: pass

# Run at startup
init_db()

# Ensure local upload folder exists (dev fallback)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ─────────────────────────── Template Filters ───────────────────────
@app.template_filter('file_icon')
def file_icon_filter(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    return {
        'pdf': 'fa-file-pdf', 'doc': 'fa-file-word', 'docx': 'fa-file-word',
        'ppt': 'fa-file-powerpoint', 'pptx': 'fa-file-powerpoint',
        'jpg': 'fa-file-image', 'jpeg': 'fa-file-image', 'png': 'fa-file-image',
        'gif': 'fa-file-image', 'bmp': 'fa-file-image', 'webp': 'fa-file-image',
        'svg': 'fa-file-image', 'txt': 'fa-file-alt',
        'xlsx': 'fa-file-excel', 'xls': 'fa-file-excel', 'csv': 'fa-file-csv',
        'py': 'fa-file-code', 'java': 'fa-file-code', 'cpp': 'fa-file-code',
        'c': 'fa-file-code', 'js': 'fa-file-code', 'html': 'fa-file-code',
        'css': 'fa-file-code',
    }.get(ext, 'fa-file')

@app.context_processor
def inject_system_vars():
    return {
        'college_name': os.environ.get('COLLEGE_NAME', 'College Notes Platform'),
        'college_short': os.environ.get('COLLEGE_SHORT', 'College')
    }

# ─────────────────────────── Context Processors ─────────────────────
@app.context_processor
def inject_notifications():
    try:
        conn = get_db_connection()
        notifs = conn.execute(
            'SELECT * FROM notifications ORDER BY created_at DESC LIMIT 5'
        ).fetchall()
        conn.close()
        processed = []
        for n in notifs:
            n = dict(n)
            if hasattr(n.get('created_at'), 'strftime'):
                n['created_at'] = n['created_at'].strftime('%Y-%m-%d %H:%M')
            processed.append(n)
        return dict(notifications=processed)
    except Exception:
        return dict(notifications=[])

# ─────────────────────────── Error Pages ────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500

@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403

# ─────────────────────────── Auth Guard ─────────────────────────────
@app.before_request
def require_login():
    # These endpoints do NOT require login (Public access)
    public_endpoints = {
        'login', 'logout', 'static', 'health', 'home', 'firebase_login_token'
    }
    if not request.endpoint or request.endpoint in public_endpoints:
        return
    if 'user_id' not in session:
        return redirect(url_for('login'))

# ─────────────────────────── Cloudinary Helper ──────────────────────
def _cloudinary_res_type(stored_filename, stored_res_type=None):
    """Return the correct Cloudinary resource_type for a stored file."""
    if stored_res_type:
        return stored_res_type
    ext = stored_filename.rsplit('.', 1)[1].lower() if '.' in stored_filename else ''
    return 'image' if ext in {'jpg','png','jpeg','gif','webp'} else 'raw'

# ─────────────────────────── Routes ─────────────────────────────────
@app.route('/monitoring')
def monitoring():
    if session.get('role') != 'admin':
        abort(403)
    return jsonify(get_monitoring_stats())

@app.route('/health')
def health():
    try:
        conn = get_db_connection()
        conn.execute('SELECT 1').fetchone()
        conn.close()
        return jsonify(status='ok', database='connected', storage=get_storage_type())
    except Exception as e:
        return jsonify(status='error', message=str(e)), 500


@app.route('/')
def home():
    conn = get_db_connection()
    
    # Handle AJAX for pagination if needed
    page = int(request.args.get('page', 1))
    items_per_page = 6
    
    sql = 'SELECT * FROM files ORDER BY upload_date DESC LIMIT ? OFFSET ?'
    files = conn.execute(sql, [items_per_page, (page - 1) * items_per_page]).fetchall()
    has_more = len(files) == items_per_page
    
    conn.close()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('_latest_uploads.html', latest_files=files, page=page, has_more=has_more)
        
    return render_template('home.html', latest_files=files, page=page, has_more=has_more)

@app.route('/notes')
def notes():
    conn = get_db_connection()
    q        = request.args.get('q', '')
    subject  = request.args.get('subject', '')
    semester = request.args.get('semester', '')
    category = request.args.get('category', '')
    dept     = request.args.get('dept', '')
    page     = int(request.args.get('page', 1))
    items_per_page = 9

    sql, params = 'SELECT * FROM files WHERE 1=1', []
    if q:
        sql += ' AND (original_filename LIKE ? OR subject LIKE ?)'
        params += [f'%{q}%', f'%{q}%']
    if subject:
        sql += ' AND subject LIKE ?';  params.append(f'%{subject}%')
    if semester:
        sql += ' AND semester LIKE ?'; params.append(f'%{semester}%')
    if category:
        sql += ' AND category LIKE ?'; params.append(f'%{category}%')
    if dept:
        sql += ' AND dept LIKE ?';     params.append(f'%{dept}%')

    sql += ' ORDER BY upload_date DESC LIMIT ? OFFSET ?'
    params += [items_per_page, (page - 1) * items_per_page]
    files = conn.execute(sql, params).fetchall()

    subjects_query = conn.execute("SELECT DISTINCT subject FROM files WHERE subject IS NOT NULL AND subject != '' ORDER BY subject ASC").fetchall()
    all_subjects = [r['subject'] for r in subjects_query]

    has_more = len(files) == items_per_page
    conn.close()
    return render_template('notes.html', files=files, page=page, has_more=has_more, all_subjects=all_subjects)

@app.route('/inter')
def inter_events_route():
    conn = get_db_connection()
    q = request.args.get('q', '')
    page = int(request.args.get('page', 1))
    items_per_page = 6

    evt_q = ''
    evt_params = []
    if q:
        evt_q += ' AND (title LIKE ? OR description LIKE ? OR organizer LIKE ?)'
        evt_params += [f'%{q}%', f'%{q}%', f'%{q}%']

    inter_sql = f"SELECT * FROM events WHERE event_type='inter'{evt_q} ORDER BY event_date ASC LIMIT ? OFFSET ?"
    inter_params = evt_params + [items_per_page, (page - 1) * items_per_page]
    events = conn.execute(inter_sql, inter_params).fetchall()

    has_more = len(events) == items_per_page
    conn.close()
    return render_template('inter.html', events=events, page=page, has_more=has_more)

@app.route('/intra')
def intra_events_route():
    conn = get_db_connection()
    q = request.args.get('q', '')
    page = int(request.args.get('page', 1))
    items_per_page = 6

    evt_q = ''
    evt_params = []
    if q:
        evt_q += ' AND (title LIKE ? OR description LIKE ? OR organizer LIKE ?)'
        evt_params += [f'%{q}%', f'%{q}%', f'%{q}%']

    intra_sql = f"SELECT * FROM events WHERE event_type='intra'{evt_q} ORDER BY event_date ASC LIMIT ? OFFSET ?"
    intra_params = evt_params + [items_per_page, (page - 1) * items_per_page]
    events = conn.execute(intra_sql, intra_params).fetchall()

    has_more = len(events) == items_per_page
    conn.close()
    return render_template('intra.html', events=events, page=page, has_more=has_more)

@app.route('/circulars')
def circulars_route():
    conn = get_db_connection()
    q = request.args.get('q', '')
    dept = request.args.get('dept', '')
    page = int(request.args.get('page', 1))
    items_per_page = 8

    circ_q = ''
    circ_params = []
    if q:
        circ_q += ' AND (title LIKE ? OR description LIKE ?)'
        circ_params += [f'%{q}%', f'%{q}%']
    if dept:
        circ_q += ' AND (dept = ? OR dept = ?)'
        circ_params += [dept, 'All']

    circ_sql = f"SELECT * FROM circulars WHERE 1=1{circ_q} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    circ_params += [items_per_page, (page - 1) * items_per_page]
    circulars = conn.execute(circ_sql, circ_params).fetchall()

    has_more = len(circulars) == items_per_page
    conn.close()
    return render_template('circulars.html', circulars=circulars, page=page, has_more=has_more)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id']  = user['id']
            session['username'] = user['username']
            session['role']     = user['role']
            flash('Logged in successfully!', 'success')
            return redirect(url_for('home'))
        flash('Invalid credentials', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'info')
    return redirect(url_for('login'))

@app.route('/relogin')
def relogin():
    """Quickly clear session and redirect with a flag to trigger seamless re-auth."""
    session.clear()
    return redirect(url_for('login', auto='true'))

@app.route('/auth/firebase', methods=['POST'])
def firebase_login_token():
    # ... (existing initialization checks)
    if not firebase_admin._apps:
        return jsonify({'error': 'Authentication service unavailable.'}), 500
    
    token = request.json.get('token')
    if not token:
        return jsonify({'error': 'Missing token.'}), 400
    
    try:
        try:
            decoded_token = auth.verify_id_token(token)
        except Exception as e:
            # Handle clock skew: if token is "too early", wait and retry
            if 'Token used too early' in str(e):
                import time
                time.sleep(2)
                decoded_token = auth.verify_id_token(token)
            else:
                raise e

        email = decoded_token.get('email', '').lower()
        if not email.endswith('@dsce.ac.in'):
            return jsonify({'error': 'Access Denied: @dsce.ac.in only.'}), 403
            
        username = email.split('@')[0]
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if not user:
            # Creation of user logic...
            if DATABASE_URL:
                cursor = conn.cursor()
                cursor.cursor.execute('INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id', (username, 'FIREBASE_AUTH', 'student'))
                res = cursor.cursor.fetchone()
                user_id = res['id'] if res else None
            else:
                cur = conn.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)', (username, 'FIREBASE_AUTH', 'student'))
                user_id = cur.lastrowid
            conn.commit()
            role = 'student'
        else:
            user_id, role = user['id'], user['role']
        conn.close()
        
        session['user_id'], session['username'], session['role'] = user_id, username, role
        flash('Successfully logged in!', 'success')
        return jsonify({'success': True, 'redirect': url_for('home')})
    except Exception as e:
        print(f'[AUTH ERROR] {e}')
        return jsonify({'error': str(e)}), 401

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if session.get('role') != 'admin':
        flash('Only admins can upload files.', 'error')
        return redirect(url_for('home'))

    if request.method == 'POST':
        file       = request.files.get('file')
        drive_link = request.form.get('drive_link', '').strip()
        subject    = request.form.get('subject', '').strip()
        semester   = request.form.get('semester', '1')
        category   = request.form.get('category', 'Study Material')
        dept       = request.form.get('dept', 'General')
        description = request.form.get('description', '').strip()
        circular_type = request.form.get('circular_type', 'standalone')
        related_ids   = request.form.get('related_circular_ids', '').strip()

        # Automated Classification / Tagging
        if 'cross-ref' in description.lower() or 'refer to circular' in description.lower():
            circular_type = 'inter'
        elif 'internal' in description.lower() or 'part of' in description.lower():
            circular_type = 'intra'

        # ── Drive link shortcut ──
        if drive_link:
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                if DATABASE_URL:
                    sql = ('INSERT INTO files (original_filename, stored_filename, uploader_username, '
                           'subject, semester, category, dept, file_type, file_size, description, circular_type, related_circular_ids) '
                           'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id')
                    cursor.cursor.execute(sql, ('Google Drive Link', drive_link, session['username'],
                                               subject, semester, category, dept, 'link', 0, description, circular_type, related_ids))
                    row = cursor.cursor.fetchone()
                    file_id = row['id'] if row else None
                else:
                    sql = ('INSERT INTO files (original_filename, stored_filename, uploader_username, '
                           'subject, semester, category, dept, file_type, file_size, description, circular_type, related_circular_ids) '
                           'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
                    cursor.execute(sql, ('Google Drive Link', drive_link, session['username'],
                                        subject, semester, category, dept, 'link', 0, description, circular_type, related_ids))
                    file_id = cursor.lastrowid
                if session.get('role') == 'admin' and file_id:
                    conn.execute('INSERT INTO notifications (message, link) VALUES (?, ?)',
                                 (f'New {subject} link by Admin', url_for('view_file_page', file_id=file_id)))
                conn.commit()
                flash('Link shared successfully!', 'success')
                return redirect(url_for('notes'))
            except Exception as e:
                print(f'[DRIVE LINK DB ERROR] {e}')
                flash(f'Error sharing link: {e}', 'error')
                return redirect(request.url)
            finally:
                conn.close()

        # ── File upload ──
        if not file or file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)

        if not allowed_file(file.filename):
            flash('File type not allowed', 'error')
            return redirect(request.url)

        file.seek(0, os.SEEK_END)
        file_length = file.tell()
        file.seek(0)

        if file_length > 30 * 1024 * 1024:
            flash('File too large (Max 30MB). Use the Drive Link option.', 'error')
            return redirect(request.url)

        original_filename = secure_filename(file.filename)
        file_ext          = original_filename.rsplit('.', 1)[1].lower()
        stored_name       = sanitize_public_id(original_filename) + '.' + file_ext
        res_type          = 'auto'

        try:
            res_type = StorageService.upload(file, stored_name)
        except Exception as e:
            flash(f'Upload failed after retries: {e}', 'error')
            return redirect(request.url)

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            if DATABASE_URL:
                sql = ('INSERT INTO files (original_filename, stored_filename, uploader_username, '
                       'subject, semester, category, dept, file_type, file_size, description, storage_resource_type, circular_type, related_circular_ids) '
                       'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id')
                cursor.cursor.execute(sql, (original_filename, stored_name, session['username'],
                                     subject, semester, category, dept, file_ext,
                                     file_length, description, res_type, circular_type, related_ids))
                row = cursor.cursor.fetchone()
                file_id = row['id'] if row else None
            else:
                sql = ('INSERT INTO files (original_filename, stored_filename, uploader_username, '
                       'subject, semester, category, dept, file_type, file_size, description, storage_resource_type, circular_type, related_circular_ids) '
                       'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
                cursor.execute(sql, (original_filename, stored_name, session['username'],
                                     subject, semester, category, dept, file_ext,
                                     file_length, description, res_type, circular_type, related_ids))
                file_id = cursor.lastrowid
            if session.get('role') == 'admin' and file_id:
                conn.execute('INSERT INTO notifications (message, link) VALUES (?, ?)',
                             (f'New {subject} note by Admin: {original_filename}',
                              url_for('view_file_page', file_id=file_id)))
            conn.commit()
        except Exception as e:
            print(f'[UPLOAD DB ERROR] {e}')
            flash(f'Database error: {e}', 'error')
            return redirect(request.url)
        finally:
            conn.close()

        flash('File uploaded successfully!', 'success')
        return redirect(url_for('notes'))

    return render_template('upload.html')

@app.route('/upload_event', methods=['GET', 'POST'])
def upload_event():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if session.get('role') != 'admin':
        flash('Only admins can host events.', 'error')
        return redirect(url_for('home'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        event_date = request.form.get('event_date', '')
        event_type = request.form.get('event_type', 'intra')
        venue = request.form.get('venue', '').strip()
        organizer = request.form.get('organizer', '').strip()
        register_link = request.form.get('register_link', '').strip()
        file = request.files.get('file')

        if not title or not event_date:
            flash('Title and date are required.', 'error')
            return redirect(request.url)

        res_type = None
        stored_name = None
        if file and file.filename != '':
            if not allowed_file(file.filename):
                flash('File type not allowed', 'error')
                return redirect(request.url)
            original_filename = secure_filename(file.filename)
            file_ext = original_filename.rsplit('.', 1)[1].lower()
            stored_name = 'event_' + sanitize_public_id(file.filename) + '.' + file_ext
            try:
                res_type = StorageService.upload(file, stored_name)
            except Exception as e:
                flash(f'Upload failed: {e}', 'error')
                return redirect(request.url)

        conn = get_db_connection()
        try:
            if DATABASE_URL:
                sql = ('INSERT INTO events (title, description, event_date, event_type, venue, organizer, register_link, image_filename, storage_resource_type, uploader_username) '
                       'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id')
                pg_cur = conn.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                pg_cur.execute(sql, (title, description, event_date, event_type, venue, organizer, register_link, stored_name, res_type, session['username']))
                row = pg_cur.fetchone()
                event_id = row['id'] if row else None
            else:
                sql = ('INSERT INTO events (title, description, event_date, event_type, venue, organizer, register_link, image_filename, storage_resource_type, uploader_username) '
                       'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
                cursor = conn.execute(sql, (title, description, event_date, event_type, venue, organizer, register_link, stored_name, res_type, session['username']))
                event_id = cursor.lastrowid
            if session.get('role') == 'admin' and event_id:
                conn.execute('INSERT INTO notifications (message, link) VALUES (?, ?)',
                             (f'New {event_type} event: {title}', url_for('inter_events_route' if event_type == 'inter' else 'intra_events_route')))
            conn.commit()
            flash('Event created successfully!', 'success')
            return redirect(url_for('inter_events_route' if event_type == 'inter' else 'intra_events_route'))
        except Exception as e:
            print(f'[EVENT DB ERROR] {e}')
            flash(f'Database error: {e}', 'error')
            return redirect(request.url)
        finally:
            conn.close()

    return render_template('upload_event.html')

@app.route('/upload_circular', methods=['GET', 'POST'])
def upload_circular():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'admin':
        flash('Only admins can upload circulars.', 'error')
        return redirect(url_for('home'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        dept = request.form.get('dept', 'General').strip()
        file = request.files.get('file')

        if not title:
            flash('Title is required.', 'error')
            return redirect(request.url)

        res_type = None
        stored_name = None
        original_filename = None
        file_ext = None
        if file and file.filename != '':
            if not allowed_file(file.filename):
                flash('File type not allowed', 'error')
                return redirect(request.url)
            original_filename = secure_filename(file.filename)
            file_ext = original_filename.rsplit('.', 1)[1].lower()
            stored_name = 'circular_' + sanitize_public_id(file.filename) + '.' + file_ext
            try:
                res_type = StorageService.upload(file, stored_name)
            except Exception as e:
                flash(f'Upload failed: {e}', 'error')
                return redirect(request.url)

        conn = get_db_connection()
        try:
            if DATABASE_URL:
                sql = ('INSERT INTO circulars (title, description, dept, stored_filename, original_filename, file_type, storage_resource_type, uploader_username) '
                       'VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id')
                pg_cur = conn.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                pg_cur.execute(sql, (title, description, dept, stored_name, original_filename, file_ext, res_type, session['username']))
                row = pg_cur.fetchone()
                circular_id = row['id'] if row else None
            else:
                sql = ('INSERT INTO circulars (title, description, dept, stored_filename, original_filename, file_type, storage_resource_type, uploader_username) '
                       'VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
                cursor = conn.execute(sql, (title, description, dept, stored_name, original_filename, file_ext, res_type, session['username']))
                circular_id = cursor.lastrowid
            conn.execute('INSERT INTO notifications (message, link) VALUES (?, ?)',
                         (f'New Circular: {title}', url_for('circulars_route')))
            conn.commit()
            flash('Circular published successfully!', 'success')
            return redirect(url_for('circulars_route'))
        except Exception as e:
            print(f'[CIRCULAR DB ERROR] {e}')
            flash(f'Database error: {e}', 'error')
            return redirect(request.url)
        finally:
            conn.close()

    return render_template('upload_circular.html')

@app.route('/view/<int:file_id>')
def view_file_page(file_id):
    conn = get_db_connection()
    file_data = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    comments  = conn.execute(
        'SELECT * FROM comments WHERE file_id = ? ORDER BY timestamp DESC', (file_id,)
    ).fetchall()
    conn.close()
    if not file_data:
        abort(404)
    return render_template('view.html', file=file_data, comments=comments)

@app.route('/file_content/<int:file_id>')
def file_content(file_id):
    conn = get_db_connection()
    file_data = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    conn.close()
    if not file_data:
        abort(404)

    if file_data['file_type'] == 'link':
        return redirect(file_data['stored_filename'])

    storage = get_storage_type()

    if storage == 'local':
        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            file_data['stored_filename'],
            as_attachment=False
        )

    # For cloud storage (Cloudinary/S3), we need to fetch the file and stream it back inline
    # to avoid the forced "Content-Disposition: attachment" headers from the CDN.
    import requests
    from flask import Response

    if storage == 'cloudinary':
        stored_name = file_data['stored_filename']
        res_type = _cloudinary_res_type(stored_name, file_data.get('storage_resource_type'))
        
        if res_type == 'image' and '.' in stored_name:
            public_id = stored_name.rsplit('.', 1)[0]
            fmt       = stored_name.rsplit('.', 1)[1].lower()
        else:
            public_id = stored_name
            fmt       = ''

        url = cloudinary.utils.private_download_url(
            public_id, fmt, resource_type=res_type,
            type='upload', attachment=False, 
            expires_at=int(__import__('time').time()) + 3600
        )
        
    elif storage == 's3':
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': file_data['stored_filename']},
            ExpiresIn=3600
        )

    try:
        req = requests.get(url, stream=True)
        return Response(req.iter_content(chunk_size=1024 * 1024),
                        content_type=req.headers.get('content-type'),
                        direct_passthrough=True)
    except Exception as e:
        print(f'[ERROR] Inline proxy failed: {e}')
        abort(500)

@app.route('/circular_content/<int:circular_id>')
def circular_content(circular_id):
    conn = get_db_connection()
    circular = conn.execute('SELECT * FROM circulars WHERE id = ?', (circular_id,)).fetchone()
    conn.close()
    if not circular or not circular['stored_filename']:
        abort(404)

    storage = get_storage_type()

    if storage == 'local':
        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            circular['stored_filename'],
            as_attachment=False
        )

    import requests
    from flask import Response

    if storage == 'cloudinary':
        stored_name = circular['stored_filename']
        res_type = _cloudinary_res_type(stored_name, circular.get('storage_resource_type'))
        
        if res_type == 'image' and '.' in stored_name:
            public_id = stored_name.rsplit('.', 1)[0]
            fmt       = stored_name.rsplit('.', 1)[1].lower()
        else:
            public_id = stored_name
            fmt       = ''

        url = cloudinary.utils.private_download_url(
            public_id, fmt, resource_type=res_type,
            type='upload', attachment=False, 
            expires_at=int(__import__('time').time()) + 3600
        )
        
    elif storage == 's3':
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': circular['stored_filename']},
            ExpiresIn=3600
        )

    try:
        req = requests.get(url, stream=True)
        return Response(req.iter_content(chunk_size=1024 * 1024),
                        content_type=req.headers.get('content-type'),
                        direct_passthrough=True)
    except Exception as e:
        print(f'[ERROR] Inline proxy failed: {e}')
        abort(500)

@app.route('/event_image/<int:event_id>')
def event_image(event_id):
    conn = get_db_connection()
    event = conn.execute('SELECT * FROM events WHERE id = ?', (event_id,)).fetchone()
    conn.close()
    if not event or not event['image_filename']:
        abort(404)

    storage = get_storage_type()

    if storage == 'local':
        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            event['image_filename'],
            as_attachment=False
        )

    if storage == 'cloudinary':
        stored_name = event['image_filename']
        res_type = _cloudinary_res_type(stored_name, event.get('storage_resource_type'))
        try:
            # Fetch the real URL directly from Cloudinary to avoid public_id extension issues
            result = cloudinary.api.resource(stored_name, resource_type=res_type)
            return redirect(result['secure_url'])
        except Exception:
            # Fallback: strip extension and let Cloudinary reconstruct URL
            public_id = stored_name.rsplit('.', 1)[0] if '.' in stored_name else stored_name
            url, _ = cloudinary.utils.cloudinary_url(public_id, resource_type=res_type)
            return redirect(url)
        
    elif storage == 's3':
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': event['image_filename']},
            ExpiresIn=3600
        )
        return redirect(url)

@app.route('/download/<int:file_id>')
def download_file(file_id):
    conn = get_db_connection()
    file_data = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    conn.close()
    if not file_data:
        abort(404)

    # External link type – just redirect
    if file_data['file_type'] == 'link':
        return redirect(file_data['stored_filename'])

    storage = get_storage_type()

    if storage == 'cloudinary':
        try:
            stored_name   = file_data['stored_filename']
            res_type      = _cloudinary_res_type(stored_name, file_data.get('storage_resource_type'))

            # Debug confirmed files are stored as raw type with public_id = uuid.pdf
            # For image type: public_id has no extension, format passed separately
            # For raw type:  public_id INCLUDES extension, format must be ''
            if res_type == 'image' and '.' in stored_name:
                public_id = stored_name.rsplit('.', 1)[0]
                fmt       = stored_name.rsplit('.', 1)[1].lower()
            else:
                public_id = stored_name   # e.g. "3ecfbddc-ad51-4aaf-b635-650cde3288e6.pdf"
                fmt       = ''            # MUST be empty for raw — extension is in public_id

            # private_download_url generates a signed API URL (identical to Cloudinary console)
            # This works for ALL resource types and forces browser download.
            import time as _time
            url = cloudinary.utils.private_download_url(
                public_id,
                fmt,
                resource_type=res_type,
                type='upload',
                attachment=True,
                expires_at=int(_time.time()) + 3600
            )
            return redirect(url)
        except Exception as e:
            print(f'[ERROR] Cloudinary download: {e}')
            abort(500)




    if storage == 's3':
        try:
            url = s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': S3_BUCKET_NAME,
                    'Key':    file_data['stored_filename'],
                    'ResponseContentDisposition': f'attachment; filename="{file_data["original_filename"]}"'
                },
                ExpiresIn=3600
            )
            return redirect(url)
        except Exception as e:
            print(f'[ERROR] S3 download: {e}')
            abort(500)

    # Local fallback
    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        file_data['stored_filename'],
        as_attachment=True,
        download_name=file_data['original_filename']
    )

@app.route('/delete/<int:file_id>', methods=['POST'])
def delete_file(file_id):
    if 'user_id' not in session:
        abort(403)
    conn = get_db_connection()
    file_data = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    if not file_data:
        conn.close(); abort(404)

    if session['role'] != 'admin' and session['username'] != file_data['uploader_username']:
        conn.close(); abort(403)

    filename = file_data['stored_filename']
    try:
        if file_data['file_type'] != 'link':
            res_type = _cloudinary_res_type(filename, file_data.get('storage_resource_type'))
            StorageService.delete(filename, res_type=res_type)
    except Exception as e:
        print(f'[WARN] Storage delete error: {e}')

    if conn.is_pg:
        cur = conn.conn.cursor()
        cur.execute("DELETE FROM files WHERE id = %s", (file_id,))
        count = cur.rowcount
        cur.close()
    else:
        cur = conn.conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
        count = cur.rowcount

    conn.commit()
    conn.close()
    print(f'[DELETE] File {file_id} deleted (rowcount={count})')
    
    if count > 0:
        flash('File deleted successfully.', 'success')
    else:
        flash('File could not be deleted or already gone.', 'error')
    
    return redirect(url_for('notes'))

@app.route('/delete_event/<int:event_id>', methods=['POST'])
def delete_event(event_id):
    if 'user_id' not in session:
        abort(403)
    conn = get_db_connection()
    event_data = conn.execute('SELECT * FROM events WHERE id = ?', (event_id,)).fetchone()
    if not event_data:
        conn.close(); abort(404)

    if session['role'] != 'admin' and session['username'] != event_data['uploader_username']:
        conn.close(); abort(403)

    if event_data['image_filename']:
        try:
            res_type = _cloudinary_res_type(event_data['image_filename'], event_data.get('storage_resource_type'))
            StorageService.delete(event_data['image_filename'], res_type=res_type)
        except Exception as e:
            print(f'[WARN] Storage delete error: {e}')

    if conn.is_pg:
        cur = conn.conn.cursor()
        cur.execute("DELETE FROM events WHERE id = %s", (event_id,))
        count = cur.rowcount
        cur.close()
    else:
        cur = conn.conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        count = cur.rowcount

    conn.commit()
    conn.close()
    print(f'[DELETE] Event {event_id} deleted (rowcount={count})')
    
    if count > 0:
        flash('Event deleted successfully.', 'success')
    else:
        flash('Event could not be deleted or already gone.', 'error')
    
    return redirect(url_for('inter_events_route' if event_data['event_type'] == 'inter' else 'intra_events_route'))

@app.route('/delete_circular/<int:circular_id>', methods=['POST'])
def delete_circular(circular_id):
    if session.get('role') != 'admin':
        abort(403)
    conn = get_db_connection()
    circular_data = conn.execute('SELECT * FROM circulars WHERE id = ?', (circular_id,)).fetchone()
    if not circular_data:
        conn.close(); abort(404)

    if circular_data['stored_filename']:
        try:
            res_type = _cloudinary_res_type(circular_data['stored_filename'], circular_data.get('storage_resource_type'))
            StorageService.delete(circular_data['stored_filename'], res_type=res_type)
        except Exception as e:
            print(f'[WARN] Storage delete error: {e}')

    if conn.is_pg:
        cur = conn.conn.cursor()
        cur.execute("DELETE FROM circulars WHERE id = %s", (circular_id,))
        count = cur.rowcount
        cur.close()
    else:
        cur = conn.conn.execute("DELETE FROM circulars WHERE id = ?", (circular_id,))
        count = cur.rowcount

    conn.commit()
    conn.close()
    print(f'[DELETE] Circular {circular_id} deleted (rowcount={count})')
    
    if count > 0:
        flash('Circular deleted successfully.', 'success')
    else:
        flash('Circular could not be deleted.', 'error')
    
    return redirect(url_for('circulars_route'))

@app.route('/toggle_rsvp/<int:event_id>', methods=['POST'])
def toggle_rsvp(event_id):
    if 'user_id' not in session:
        return jsonify({'status': 'redirect', 'url': url_for('login')})
    
    conn = get_db_connection()
    try:
        user_id = session['user_id']
        username = session['username']
        # check if exists
        exists = conn.execute('SELECT id FROM event_rsvps WHERE event_id = ? AND user_id = ?', (event_id, user_id)).fetchone()
        if exists:
            conn.execute('DELETE FROM event_rsvps WHERE id = ?', (exists['id'],))
            status = 'removed'
        else:
            conn.execute('INSERT INTO event_rsvps (event_id, user_id, username) VALUES (?, ?, ?)', (event_id, user_id, username))
            status = 'added'
        conn.commit()
        
        # update active count
        count = conn.execute('SELECT COUNT(*) as c FROM event_rsvps WHERE event_id = ?', (event_id,)).fetchone()['c']
        return jsonify({'status': status, 'count': count})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        conn.close()

# ─────────────────────────── Comments ───────────────────────────────
TOXIC_WORDS = {'abuse','kill','hate','stupid','idiot','scam','fake','trash','garbage'}

def is_toxic(text):
    return any(w in text.lower() for w in TOXIC_WORDS)

@app.route('/add_comment/<int:file_id>', methods=['POST'])
def add_comment(file_id):
    comment    = request.form.get('comment', '').strip()
    guest_name = request.form.get('guest_name', '').strip()
    guest_dept = request.form.get('guest_dept', '').strip()

    if not comment:
        return redirect(url_for('view_file_page', file_id=file_id))

    if is_toxic(comment):
        flash('Comment removed by moderation.', 'error')
        return redirect(url_for('view_file_page', file_id=file_id))

    username = session['username'] if 'user_id' in session else (
        f'{guest_name} ({guest_dept})' if guest_dept else guest_name or 'Anonymous'
    )
    user_id = session.get('user_id')

    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO comments (file_id, user_id, username, guest_dept, comment) VALUES (?, ?, ?, ?, ?)',
            (file_id, user_id, username, guest_dept, comment)
        )
        conn.commit()
        flash('Comment posted!', 'success')
    except Exception as e:
        flash('Error posting comment', 'error')
    finally:
        conn.close()
    return redirect(url_for('view_file_page', file_id=file_id))

@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
def delete_comment(comment_id):
    if session.get('role') != 'admin':
        abort(403)
    conn = get_db_connection()
    row  = conn.execute('SELECT file_id FROM comments WHERE id = ?', (comment_id,)).fetchone()
    if row:
        conn.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
        conn.commit()
        flash('Comment deleted', 'info')
    conn.close()
    return redirect(url_for('view_file_page', file_id=row['file_id'])) if row else redirect(url_for('home'))

# ─────────────────────────── Admin ──────────────────────────────────
@app.route('/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if session.get('role') != 'admin':
        abort(403)
        
    # Prevent admin from deleting themselves
    if user_id == session.get('user_id'):
        flash('You cannot delete your own admin account.', 'error')
        return redirect(url_for('admin_dashboard'))
        
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    
    if user:
        if user['username'] == 'DSCEAdmin':
            flash('Access Denied: Cannot delete the Master Administrator account.', 'error')
        elif user['id'] == session.get('user_id'):
            flash('Security Violation: You cannot delete your own active session.', 'error')
        else:
            conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
            conn.commit()
            flash(f'User {user["username"]} has been purged from the system.', 'success')
    else:
        flash('Target user does not exist.', 'error')
        
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add_user', methods=['POST'])
def add_user():
    if 'user_id' not in session or session.get('role') != 'admin':
        abort(403)
        
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role', 'student')

    if not username or not password or len(password) < 6:
        flash('Username and a password (min 6 chars) are required.', 'error')
        return redirect(url_for('admin_dashboard'))

    if role not in ('admin', 'student'):
        role = 'student'

    try:
        conn = get_db_connection()
        pw_hash = generate_password_hash(password)
        conn.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
                     (username, pw_hash, role))
        conn.commit()
        flash(f'User {username} created successfully with role {role}.', 'success')
    except Exception as e:
        if 'UNIQUE' in str(e).upper() or 'duplicate key' in str(e).lower():
            flash('Username already exists.', 'error')
        else:
            print(f'[ERROR] Add user failed: {e}')
            flash('Database error while creating user.', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))

@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'admin':
        abort(403)
    conn  = get_db_connection()
    users = conn.execute('SELECT * FROM users ORDER BY id DESC').fetchall()
    files = conn.execute('SELECT * FROM files ORDER BY upload_date DESC LIMIT 50').fetchall()
    conn.close()
    return render_template('admin.html', users=users, files=files)

@app.route('/admin/cleanup')
def admin_cleanup():
    if 'user_id' not in session or session.get('role') != 'admin':
        abort(403)
    conn = get_db_connection()
    files     = conn.execute('SELECT id, original_filename, uploader_username, upload_date FROM files ORDER BY id DESC').fetchall()
    events    = conn.execute('SELECT id, title, event_type, uploader_username FROM events ORDER BY id DESC').fetchall()
    circulars = conn.execute('SELECT id, title, uploader_username FROM circulars ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('cleanup.html', files=files, events=events, circulars=circulars)

# ─────────────────────────── Entry Point ────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)
