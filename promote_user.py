import sqlite3
import psycopg2
import sys
import os
from urllib.parse import urlparse

# --- CONFIGURATION ---
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect('starmap.db')
    return conn

def promote_user(username):
    """Grants admin privileges to a user."""
    print(f"Attempting to promote user '{username}' to admin...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        param_style = '%s' if bool(DATABASE_URL) else '?'

        cursor.execute(f"SELECT id FROM users WHERE username = {param_style}", (username,))
        if not cursor.fetchone():
            print(f"\n❌ Error: User '{username}' not found.")
            return

        cursor.execute(f"UPDATE users SET is_admin = TRUE WHERE username = {param_style}", (username,))
        
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

