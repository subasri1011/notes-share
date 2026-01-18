import sqlite3

DB_NAME = "users.db"

def add_category_column():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE files ADD COLUMN category TEXT DEFAULT 'Study Material'")
        print("Successfully added 'category' column.")
    except sqlite3.OperationalError as e:
        print(f"Column might already exist: {e}")
        
    conn.commit()
    conn.close()

if __name__ == "__main__":
    add_category_column()
