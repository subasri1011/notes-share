import sqlite3

DB_NAME = "users.db"

def add_dept_column():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE files ADD COLUMN dept TEXT DEFAULT 'General'")
        print("Successfully added 'dept' column.")
    except sqlite3.OperationalError as e:
        print(f"Column might already exist: {e}")
        
    conn.commit()
    conn.close()

if __name__ == "__main__":
    add_dept_column()
