import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
import sys
import os

# --- CONFIGURATION ---
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    """Connects to the appropriate database."""
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
        return conn, conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn = sqlite3.connect('starmap.db')
        conn.row_factory = sqlite3.Row
        return conn, conn.cursor()

def promote_user(username):
    """Grants admin privileges to a user."""
    print(f"Attempting to promote user '{username}' to admin...")
    try:
        conn, cursor = get_db_connection()
        pg_compat = bool(DATABASE_URL)
        param = '%s' if pg_compat else '?'

        cursor.execute(f"SELECT id FROM users WHERE username = {param}", (username,))
        user = cursor.fetchone()

        if not user:
            print(f"\n❌ Error: User '{username}' not found in the database.")
            conn.close()
            return

        cursor.execute(f"UPDATE users SET is_admin = TRUE WHERE username = {param}", (username,))
        
        conn.commit()
        conn.close()

        print(f"\n✅ Success! User '{username}' has been granted admin privileges.")

    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python promote_user.py <username>")
    else:
        promote_user(sys.argv[1])

