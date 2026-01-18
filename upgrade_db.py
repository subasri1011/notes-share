import sqlite3

DB_NAME = "users.db"

def upgrade_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. Add description column to files table if it doesn't exist
    try:
        cursor.execute("ALTER TABLE files ADD COLUMN description TEXT")
        print("Added 'description' column to 'files' table.")
    except sqlite3.OperationalError:
        print("'description' column already exists in 'files' table.")

    # 2. Create Comments Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            comment TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (file_id) REFERENCES files (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    print("Ensured 'comments' table exists.")

    # 3. Create Notifications Table
    # A simple broadcast system: Admin actions create a notification record.
    # Users will see the latest notifications.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("Ensured 'notifications' table exists.")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    upgrade_db()
