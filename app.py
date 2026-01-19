from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, abort
import sqlite3
import os
import psycopg2
import psycopg2.extras
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
import uuid
import boto3
from dotenv import load_dotenv

load_dotenv()

# --- AWS Configuration ---
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
AWS_REGION = os.getenv('AWS_REGION', 'ap-south-1')

s3_client = None
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and S3_BUCKET_NAME:
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        print("[OK] AWS S3 Connected Successfully")
    except Exception as e:
        print(f"[ERROR] AWS Connection Failed: {e}")

# --- Cloudinary Configuration ---
import cloudinary
import cloudinary.uploader
import cloudinary.api
from io import BytesIO

CLOUDINARY_CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME')
CLOUDINARY_API_KEY = os.getenv('CLOUDINARY_API_KEY')
CLOUDINARY_API_SECRET = os.getenv('CLOUDINARY_API_SECRET')

cloudinary_active = False
if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY:
    try:
        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_API_SECRET
        )
        cloudinary_active = True
        print("[OK] Cloudinary Connected Successfully")
    except Exception as e:
        print(f"[ERROR] Cloudinary Connection Failed: {e}")

# Helper to check storage backend
def get_storage_type():
    if cloudinary_active: return 'cloudinary'
    if s3_client: return 's3'
    return 'local'

from flask_wtf.csrf import CSRFProtect
from flask_talisman import Talisman

# ... imports ...

app = Flask(__name__)

# SECURITY: Secret Key
app.secret_key = os.getenv('SECRET_KEY', os.urandom(32))

# SECURITY: CSRF Protection
csrf = CSRFProtect(app)

# SECURITY: Headers & HTTPS (CSP relaxed for inline scripts/CDN as used in templates)
# forces HTTPS in production
csp = {
    'default-src': '\'self\'',
    'script-src': ['\'self\'', '\'unsafe-inline\'', 'cdnjs.cloudflare.com', 'cdn.sheetjs.com'],
    'style-src': ['\'self\'', '\'unsafe-inline\'', 'cdnjs.cloudflare.com', 'fonts.googleapis.com'],
    'font-src': ['\'self\'', 'fonts.gstatic.com', 'cdnjs.cloudflare.com'],
    'img-src': ['\'self\'', 'data:', '*'], 
    'frame-src': ['\'self\'', 'docs.google.com', '*.cloudinary.com', '*.amazonaws.com']
}
talisman = Talisman(app, content_security_policy=csp, force_https=False) 
# Note: force_https=False because we are running on local IP without certs currently. 
# In a real production deployment with a domain, this should be True.

app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024  # Enforce 30MB limit at Flask level too
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'



ALLOWED_EXTENSIONS = {
    'pdf', 'ppt', 'pptx', 'doc', 'docx', 
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg',
    'txt', 'xlsx', 'xls', 'csv', 'py', 'java', 'cpp', 'c', 'js', 'html', 'css'
}
DB_NAME = "users.db"
DATABASE_URL = os.getenv('DATABASE_URL')

class DBWrapper:
    def __init__(self, conn, is_pg):
        self.conn = conn
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
        else:
            return CursorWrapper(self.conn.cursor(), False)
    def commit(self):
        self.conn.commit()
    def close(self):
        self.conn.close()

class CursorWrapper:
    def __init__(self, cursor, is_pg):
        self.cursor = cursor
        self.is_pg = is_pg
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
            except Exception as e:
                print(f"DEBUG: Error fetching lastrowid: {e}")
                return None
        return self.cursor.lastrowid
    def fetchone(self):
        return self.cursor.fetchone()
    def fetchall(self):
        return self.cursor.fetchall()
    def close(self):
        try:
            self.cursor.close()
        except:
            pass

def get_db_connection():
    if DATABASE_URL:
        # PostgreSQL (Render)
        # Fix legacy postgres:// URL if necessary
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(url)
        return DBWrapper(conn, True)
    else:
        # Local SQLite
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        return DBWrapper(conn, False)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.template_filter('file_icon')
def file_icon_filter(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    icons = {
        'pdf': 'fa-file-pdf',
        'doc': 'fa-file-word',
        'docx': 'fa-file-word',
        'ppt': 'fa-file-powerpoint',
        'pptx': 'fa-file-powerpoint',
        'zip': 'fa-file-archive',
        'exe': 'fa-file-code',
        'jpg': 'fa-file-image',
        'jpeg': 'fa-file-image',
        'png': 'fa-file-image',
        'gif': 'fa-file-image',
        'bmp': 'fa-file-image',
        'webp': 'fa-file-image',
        'svg': 'fa-file-image',
        'txt': 'fa-file-alt',
        'xlsx': 'fa-file-excel',
        'xls': 'fa-file-excel',
        'csv': 'fa-file-csv',
        'py': 'fa-file-code',
        'java': 'fa-file-code',
        'cpp': 'fa-file-code',
        'c': 'fa-file-code',
        'js': 'fa-file-code',
        'html': 'fa-file-code',
        'css': 'fa-file-code'
    }
    return icons.get(ext, 'fa-file')

@app.context_processor
def inject_notifications():
    try:
        conn = get_db_connection()
        # Fetch last 5 notifications
        notifs = conn.execute('SELECT * FROM notifications ORDER BY created_at DESC LIMIT 5').fetchall()
        conn.close()
        # Ensure created_at is a string for slicing in template fallback
        processed_notifs = []
        for n in notifs:
            n_dict = dict(n)
            if hasattr(n_dict.get('created_at'), 'strftime'):
                n_dict['created_at'] = n_dict['created_at'].strftime('%Y-%m-%d %H:%M')
            processed_notifs.append(n_dict)
        return dict(notifications=processed_notifs)
    except Exception:
        return dict(notifications=[])

def init_postgreSQL():
    if not DATABASE_URL:
        return
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Users
        cursor.execute('CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN (\'admin\', \'student\')))')
        # Files
        cursor.execute('CREATE TABLE IF NOT EXISTS files (id SERIAL PRIMARY KEY, original_filename TEXT NOT NULL, stored_filename TEXT NOT NULL, uploader_username TEXT NOT NULL, subject TEXT NOT NULL, semester TEXT NOT NULL, category TEXT DEFAULT \'Study Material\', dept TEXT DEFAULT \'General\', description TEXT, upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, file_type TEXT NOT NULL, file_size BIGINT NOT NULL, storage_resource_type TEXT)')
        # Comments
        cursor.execute('CREATE TABLE IF NOT EXISTS comments (id SERIAL PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, username TEXT, guest_dept TEXT, comment TEXT NOT NULL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        # Notifications
        cursor.execute('CREATE TABLE IF NOT EXISTS notifications (id SERIAL PRIMARY KEY, message TEXT NOT NULL, link TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        
        # Check if admin exists
        admin = conn.execute('SELECT * FROM users WHERE username = ?', ('admin',)).fetchone()
        if not admin:
            from werkzeug.security import generate_password_hash
            pwd_hash = generate_password_hash("admin1234")
            conn.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)', ('admin', pwd_hash, 'admin'))
        
        conn.commit()
    except Exception as e:
        print(f"DEBUG: init_postgreSQL Error: {e}")
    finally:
        if conn:
            try: conn.close()
            except: pass
    print("[OK] PostgreSQL Schema Verified")

@app.route('/health')
def health():
    try:
        conn = get_db_connection()
        conn.execute('SELECT 1').fetchone()
        conn.close()
        return {"status": "ok", "database": "connected", "storage": get_storage_type()}
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

# Ensure upload folder exists for local fallback
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
    print(f"[OK] Created upload folder: {app.config['UPLOAD_FOLDER']}")

# Auto-Init DB if on PostgreSQL
if DATABASE_URL:
    try:
        init_postgreSQL()
    except Exception as e:
        print(f"[ERROR] Auto-Init Failed: {e}")

# --- Routes ---

@app.route('/')
def home():
    query = request.args.get('q', '')
    subject_filter = request.args.get('subject', '')
    semester_filter = request.args.get('semester', '')
    category_filter = request.args.get('category', '')
    
    conn = get_db_connection()
    sql = "SELECT * FROM files WHERE 1=1"
    params = []
    
    if query:
        sql += " AND (original_filename LIKE ? OR subject LIKE ?)"
        params.extend([f'%{query}%', f'%{query}%'])
    if subject_filter:
        sql += " AND subject LIKE ?"
        params.append(f'%{subject_filter}%')
    if semester_filter:
        sql += " AND semester LIKE ?"
        params.append(f'%{semester_filter}%')
    if category_filter:
        sql += " AND category LIKE ?"
        params.append(f'%{category_filter}%')
        
    sql += " ORDER BY upload_date DESC"
    files = conn.execute(sql, params).fetchall()
    conn.close()
    return render_template('home.html', files=files)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            # Create uploads directory if it doesn't exist (safety check)
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
                
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash('Logged in successfully!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid credentials', 'error')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'info')
    return redirect(url_for('login'))

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        file = request.files.get('file')
        drive_link = request.form.get('drive_link')
        subject = request.form['subject']
        semester = request.form['semester']
        category = request.form.get('category', 'Study Material')
        dept = request.form.get('dept', 'General')
        description = request.form.get('description', '')
        
        print(f"DEBUG: Receiving upload request: File: {file.filename if file else 'None'}, Link: {drive_link}, {subject}")
        
        # Priority 1: Drive Link (if provided, usually because file was too big)
        if drive_link:
            # Save link as a file entry
            original_filename = "Google Drive Link"
            stored_filename = drive_link
            file_ext = "link"
            
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                sql = 'INSERT INTO files (original_filename, stored_filename, uploader_username, subject, semester, category, dept, file_type, file_size, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
                if DATABASE_URL:
                    sql += " RETURNING id"
                cursor.execute(sql, (original_filename, stored_filename, session['username'], subject, semester, category, dept, file_ext, 0, description))
                file_id = cursor.lastrowid
                
                if session.get('role') == 'admin':
                    msg = f"New {subject} link posted by Admin"
                    link = url_for('view_file_page', file_id=file_id)
                    conn.execute('INSERT INTO notifications (message, link) VALUES (?, ?)', (msg, link))
                
                conn.commit()
                flash('Link shared successfully!', 'success')
                return redirect(url_for('home'))
            except Exception as e:
                print(f"DEBUG: Error DB insert for link: {e}")
                flash('Error sharing link', 'error')
                return redirect(request.url)
            finally:
                conn.close()

        # Priority 2: File Upload
        if not file or file.filename == '':
            flash('No selected file and no link provided', 'error')
            return redirect(request.url)
            
        if file and allowed_file(file.filename):
            # Check size manually just in case, though frontend should catch it
            file.seek(0, os.SEEK_END)
            file_length = file.tell()
            file.seek(0)
            
            if file_length > 30 * 1024 * 1024: # 30MB
                flash('File too large (Max 30MB). Please use the Drive Link option.', 'error')
                return redirect(request.url)

            original_filename = secure_filename(file.filename)
            file_ext = original_filename.rsplit('.', 1)[1].lower()
            random_name = str(uuid.uuid4()) + '.' + file_ext
            
            # Save file
            try:
                storage = get_storage_type()
                
                res_type = "auto"
                if storage == 'cloudinary':
                    print(f"DEBUG: Uploading to Cloudinary: {random_name}")
                    
                    upload_result = cloudinary.uploader.upload(
                        file, 
                        public_id=random_name.rsplit('.', 1)[0],
                        resource_type="auto",
                        use_filename=True,
                        unique_filename=False
                    )
                    res_type = upload_result.get('resource_type', 'raw')
                    print(f"DEBUG: Cloudinary upload successful. Resource Type: {res_type}")
                    
                elif storage == 's3':
                    print(f"DEBUG: Uploading to S3: {random_name}")
                    s3_client.upload_fileobj(
                        file, 
                        S3_BUCKET_NAME, 
                        random_name,
                        ExtraArgs={'ContentType': file.content_type}
                    )
                else:
                    # LOCAL FALLBACK
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], random_name)
                    print(f"DEBUG: Saving to Local: {save_path}")
                    file.save(save_path)

            except Exception as e:
                print(f"DEBUG: Error saving file: {e}")
                flash(f'Error saving file: {str(e)}', 'error')
                return redirect(request.url)
            
            # Save to DB
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                sql = 'INSERT INTO files (original_filename, stored_filename, uploader_username, subject, semester, category, dept, file_type, file_size, description, storage_resource_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
                if DATABASE_URL:
                    sql += " RETURNING id"
                cursor.execute(sql, (original_filename, random_name, session['username'], subject, semester, category, dept, file_ext, file_length, description, res_type))
                file_id = cursor.lastrowid
                
                if session.get('role') == 'admin' and file_id:
                    msg = f"New {subject} note posted by Admin: {original_filename}"
                    link = url_for('view_file_page', file_id=file_id)
                    conn.execute('INSERT INTO notifications (message, link) VALUES (?, ?)', (msg, link))
                
                conn.commit()
                print(f"DEBUG: File record committed to DB. ID: {file_id}")
            except Exception as e:
                print(f"DEBUG: Error DB insert: {e}")
                raise e # Re-raise to be caught by outer try
            finally:
                conn.close()
            
            flash('File uploaded successfully!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid file type (ZIP and EXE are not allowed)', 'error')
            
    return render_template('upload.html')

@app.route('/view/<int:file_id>')
def view_file_page(file_id):
    conn = get_db_connection()
    file_data = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    comments = conn.execute('SELECT * FROM comments WHERE file_id = ? ORDER BY timestamp DESC', (file_id,)).fetchall()
    conn.close()
    
    if not file_data:
        abort(404)
        
    return render_template('view.html', file=file_data, comments=comments)

# Simple keyword-based AI moderation
def is_content_toxic(text):
    bad_words = ['bad', 'abuse', 'kill', 'hate', 'stupid', 'idiot', 'scam', 'fake', 'trash', 'garbage']
    text = text.lower()
    for word in bad_words:
        if word in text:
            return True
    return False

@app.route('/add_comment/<int:file_id>', methods=['POST'])
def add_comment(file_id):
    comment = request.form.get('comment')
    guest_name = request.form.get('guest_name')
    guest_dept = request.form.get('guest_dept')
    
    # 1. AI Moderation Check
    if comment and is_content_toxic(comment):
        flash('Your comment was removed by AI Moderation due to inappropriate content.', 'error')
        return redirect(url_for('view_file_page', file_id=file_id))

    if comment:
        conn = get_db_connection()
        try:
            # Determine user identity
            if 'user_id' in session:
                user_id = session['user_id']
                username = session['username']
                dept = 'Member' # or fetch from profile if existed
            else:
                user_id = None
                # Format: "Name (Dept)" or just Name
                username = f"{guest_name} ({guest_dept})" if guest_dept else guest_name
                if not username:
                    username = "Anonymous Student"

            conn.execute('INSERT INTO comments (file_id, user_id, username, guest_dept, comment) VALUES (?, ?, ?, ?, ?)',
                         (file_id, user_id, username, guest_dept, comment))
            conn.commit()
            flash('Comment added successfully', 'success')
        except Exception as e:
            print(f"Error adding comment: {e}")
            flash('Error adding comment', 'error')
        finally:
            conn.close()
    
    return redirect(url_for('view_file_page', file_id=file_id))

@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
def delete_comment(comment_id):
    if session.get('role') != 'admin':
        flash('Permission denied', 'error')
        return redirect(url_for('home'))

    conn = get_db_connection()
    # Get file_id to redirect back
    comment = conn.execute('SELECT file_id FROM comments WHERE id = ?', (comment_id,)).fetchone()
    if comment:
        conn.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
        conn.commit()
        flash('Comment deleted', 'info')
        file_id = comment['file_id']
    else:
        file_id = None
        
    conn.close()
    
    if file_id:
        return redirect(url_for('view_file_page', file_id=file_id))
    return redirect(url_for('home'))

# ... (rest of file) ...

if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    # SECURITY: Debug disabled, 0.0.0.0 for mobile access
    app.run(host='0.0.0.0', debug=False, port=5000)

@app.route('/file_content/<int:file_id>')
def file_content(file_id):
    conn = get_db_connection()
    file_data = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    conn.close()
    
    if file_data:
        # HYBRID VIEW LOGIC
        storage = get_storage_type()
        
        if storage == 'cloudinary':
            try:
                filename = file_data['stored_filename']
                res_type = file_data.get('storage_resource_type') or 'raw'
                
                # If res_type is not stored, fallback to guessing
                if not file_data.get('storage_resource_type'):
                    ext = filename.rsplit('.', 1)[1].lower()
                    if ext in ['jpg', 'png', 'jpeg', 'gif', 'webp', 'pdf']:
                        res_type = 'image'
                    else:
                        res_type = 'raw'
                    
                public_id = filename.rsplit('.', 1)[0]
                ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                
                # For Cloudinary, including the extension in the URL is more reliable for PDFs and non-images
                url, options = cloudinary.utils.cloudinary_url(public_id, resource_type=res_type, format=ext)
                return redirect(url)
            except Exception as e:
                print(f"Cloudinary View Error: {e}")
                abort(500)

        elif storage == 's3':
            try:
                # Generate Presigned URL for direct access/download
                url = s3_client.generate_presigned_url('get_object',
                                                    Params={'Bucket': S3_BUCKET_NAME,
                                                            'Key': file_data['stored_filename']},
                                                    ExpiresIn=3600)
                return redirect(url)
            except Exception as e:
                print(f"S3 Error: {e}")
                return abort(500)
        else:
            # LOCAL FALLBACK
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_data['stored_filename'])
            
            # Explicitly determine mimetype
            import mimetypes
            mimetype, _ = mimetypes.guess_type(file_data['original_filename'])
            if not mimetype:
                mimetype = 'application/octet-stream'
                
            return send_from_directory(app.config['UPLOAD_FOLDER'], file_data['stored_filename'], mimetype=mimetype, as_attachment=False)
    else:
        abort(404)

@app.route('/get_file_base64/<int:file_id>')
def get_file_base64(file_id):
    conn = get_db_connection()
    file_data = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    conn.close()
    
    if file_data:
        try:
            filename = file_data['stored_filename']
            import base64

            # HYBRID CONTENT FETCH (BASE64)
            storage = get_storage_type()
            
            if storage == 'cloudinary':
                # Fetch content via URL then encode
                import requests
                filename = file_data['stored_filename']
                res_type = file_data.get('storage_resource_type') or 'raw'
                
                if not file_data.get('storage_resource_type'):
                    ext = filename.rsplit('.', 1)[1].lower()
                    if ext in ['jpg', 'png', 'jpeg', 'gif', 'webp', 'pdf']:
                        res_type = 'image'
                    else:
                        res_type = 'raw'
                    
                public_id = filename.rsplit('.', 1)[0]
                ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                url, _ = cloudinary.utils.cloudinary_url(public_id, resource_type=res_type, format=ext)
                
                print(f"DEBUG: Fetching for Base64 from: {url} (Type: {res_type})")
                resp = requests.get(url)
                if resp.status_code == 200:
                    encoded_string = base64.b64encode(resp.content).decode('utf-8')
                    return {"data": encoded_string}
                else:
                    print(f"DEBUG: Cloud fetch failed for {filename}. Status: {resp.status_code}")
                    return {"error": f"Cloud fetch failed with status {resp.status_code}"}, 500

            elif storage == 's3':
                # Fetch bytes from S3
                file_obj = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=filename)
                file_content = file_obj['Body'].read()
                heading_base64 = base64.b64encode(file_content).decode('utf-8')
                return {"data": heading_base64}
            else:
                # Fetch from Local
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                with open(file_path, "rb") as f:
                    encoded_string = base64.b64encode(f.read()).decode('utf-8')
                return {"data": encoded_string}

        except Exception as e:
            print(f"Error reading file: {e}")
            return {"error": str(e)}, 500
    else:
        return {"error": "File not found"}, 404

@app.route('/download/<int:file_id>')
def download_file(file_id):
    conn = get_db_connection()
    file_data = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    conn.close()
    
    if file_data:
        # Handle Link Type
        if file_data['file_type'] == 'link':
            return redirect(file_data['stored_filename'])

        # HYBRID DOWNLOAD
        storage = get_storage_type()
        
        if storage == 'cloudinary':
             try:
                filename = file_data['stored_filename']
                res_type = file_data.get('storage_resource_type') or 'raw'
                
                if not file_data.get('storage_resource_type'):
                    ext = filename.rsplit('.', 1)[1].lower()
                    if ext in ['jpg', 'png', 'jpeg', 'gif', 'webp', 'pdf']:
                        res_type = 'image'
                    else:
                        res_type = 'raw'

                public_id = filename.rsplit('.', 1)[0]
                ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                
                # Cloudinary URL (attachment) + format to preserve extension
                url, _ = cloudinary.utils.cloudinary_url(public_id, resource_type=res_type, flags="attachment", format=ext)
                return redirect(url)
             except Exception as e:
                 abort(500)
                 
        elif storage == 's3':
            try:
                # Redirect to Presigned URL
                url = s3_client.generate_presigned_url('get_object',
                                                        Params={'Bucket': S3_BUCKET_NAME,
                                                                'Key': file_data['stored_filename'],
                                                                'ResponseContentDisposition': f"attachment; filename={file_data['original_filename']}"},
                                                        ExpiresIn=3600)
                return redirect(url)
            except Exception as e:
                print(f"S3 Download Error: {e}")
                abort(500)
        else:
            return send_from_directory(app.config['UPLOAD_FOLDER'], file_data['stored_filename'], as_attachment=True, download_name=file_data['original_filename'])
    else:
        abort(404)
        
@app.route('/delete/<int:file_id>', methods=['POST'])
def delete_file(file_id):
    if 'user_id' not in session:
        abort(403)
        
    conn = get_db_connection()
    file_data = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    
    if not file_data:
        conn.close()
        abort(404)
        
    # Check permissions: Admin or Owner
    if session['role'] == 'admin' or session['username'] == file_data['uploader_username']:
        try:
            filename = file_data['stored_filename']
            storage = get_storage_type()
            
            if storage == 'cloudinary':
                public_id = filename.rsplit('.', 1)[0]
                res_type = file_data.get('storage_resource_type') or 'raw'
                
                if not file_data.get('storage_resource_type'):
                    ext = filename.rsplit('.', 1)[1].lower()
                    if ext in ['jpg', 'png', 'jpeg', 'gif', 'webp', 'pdf']:
                        res_type = 'image'
                    else:
                        res_type = 'raw'
                    
                cloudinary.uploader.destroy(public_id, resource_type=res_type)
                print(f"Deleted from Cloudinary: {public_id}")
                
            elif storage == 's3':
                s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=filename)
                print(f"Deleted from S3: {filename}")
            else:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"Deleted from Local: {file_path}")
        except Exception as e:
            print(f"Error deleting file from storage: {e}")
            
        conn.execute('DELETE FROM files WHERE id = ?', (file_id,))
        conn.commit()
        conn.close()
        flash('File deleted.', 'success')
    else:
        conn.close()
        abort(403)
        
    return redirect(url_for('home'))

@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or session['role'] != 'admin':
        abort(403)
        
    conn = get_db_connection()
    users = conn.execute('SELECT * FROM users').fetchall()
    files = conn.execute('SELECT * FROM files').fetchall()
    conn.close()
    
    return render_template('admin.html', users=users, files=files)


