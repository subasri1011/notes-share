import sqlite3

DB_NAME = "users.db"

def patch_comments_table():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Check if we need to remove NOT NULL constraints from user_id or username
    # SQLite ALTER TABLE is limited, so we might need to recreate the table or just allow NULLs if possible?
    # Actually, simpler approach for now:
    # 1. Rename old table
    # 2. Create new table with nullable user_id (or guest columns)
    # 3. Copy data
    
    print("Patching comments table for guest support...")
    
    # Rename existing
    try:
        cursor.execute("ALTER TABLE comments RENAME TO comments_old")
    except sqlite3.OperationalError:
        # Maybe already renamed or doesn't exist?
        pass

    # Create new table with guest support
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            user_id INTEGER, -- Nullable for guests
            username TEXT,   -- Nullable, we'll store guest_name here or display name
            guest_dept TEXT, -- New column for guests
            comment TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (file_id) REFERENCES files (id)
        )
    ''')
    
    # Copy data back if old table exists
    try:
        cursor.execute("INSERT INTO comments (id, file_id, user_id, username, comment, timestamp) SELECT id, file_id, user_id, username, comment, timestamp FROM comments_old")
        cursor.execute("DROP TABLE comments_old")
        print("Migrated existing comments.")
    except Exception as e:
        print(f"Migration note: {e}")
        
    conn.commit()
    conn.close()
    print("Comments table patched.")

if __name__ == "__main__":
    patch_comments_table()
