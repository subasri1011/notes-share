import sqlite3

def check_db():
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        print("--- Table: files ---")
        cursor.execute("PRAGMA table_info(files)")
        columns = cursor.fetchall()
        for col in columns:
            print(col)
            
        print("\n--- Table: users ---")
        cursor.execute("PRAGMA table_info(users)")
        columns = cursor.fetchall()
        for col in columns:
            print(col)
            
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_db()
