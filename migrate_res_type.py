import sqlite3
import os

DB_NAME = "users.db"

def migrate():
    if not os.path.exists(DB_NAME):
        print(f"Database {DB_NAME} not found.")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    print("Adding 'storage_resource_type' column to 'files' table...")
    
    # Check columns in 'files'
    cursor.execute("PRAGMA table_info(files)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'storage_resource_type' not in columns:
        cursor.execute("ALTER TABLE files ADD COLUMN storage_resource_type TEXT")
        print("Added 'storage_resource_type' column.")
    else:
        print("'storage_resource_type' column already exists.")

    conn.commit()
    conn.close()
    print("Migration completed.")

if __name__ == "__main__":
    migrate()
