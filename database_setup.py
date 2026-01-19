import sqlite3
from werkzeug.security import generate_password_hash
import os

DB_NAME = "users.db"

def init_db():
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Create Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'student'))
        )
    ''')

    # Create Files Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
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
            file_size INTEGER NOT NULL
        )
    ''')

    # Create Notifications Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Add Default Users
    users = [
        ("admin", "admin1234", "admin"),
        ("student", "student123", "student"),
        ("student2", "student123", "student")
    ]

    for username, pwd, role in users:
        pwd_hash = generate_password_hash(pwd)
        try:
            cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", (username, pwd_hash, role))
            print(f"Added user: {username} | Role: {role}")
        except sqlite3.IntegrityError:
            print(f"User {username} already exists")

    conn.commit()
    conn.close()
    print("Database initialized successfully.")

if __name__ == "__main__":
    init_db()
