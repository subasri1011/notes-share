import os
import psycopg2
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

def init_pg():
    if not DATABASE_URL:
        print("Error: DATABASE_URL not found in .env")
        return

    # Fix legacy postgres:// URL
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    conn = psycopg2.connect(url)
    cursor = conn.cursor()

    print("Checking/Creating tables in PostgreSQL...")

    # 1. Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'student'))
        )
    ''')

    # 2. Files Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
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
            file_size BIGINT NOT NULL
        )
    ''')

    # 3. Comments Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            username TEXT,
            guest_dept TEXT,
            comment TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 4. Notifications Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            message TEXT NOT NULL,
            link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Add Default Admin User
    admin_pwd = generate_password_hash("admin1234")
    try:
        cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING", 
                       ("admin", admin_pwd, "admin"))
        print("Ensured admin user exists.")
    except Exception as e:
        print(f"Error creating admin: {e}")

    conn.commit()
    cursor.close()
    conn.close()
    print("PostgreSQL Database initialized successfully.")

if __name__ == "__main__":
    init_pg()
