import os
import sys
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor

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

def run_migration():
    """Adds the last_known_system_id column to the users table if it doesn't exist."""
    print("Running migration to add 'last_known_system_id' column...")
    conn, cursor = get_db_connection()
    
    try:
        # Add the new column, defaulting it to NULL
        cursor.execute("ALTER TABLE users ADD COLUMN last_known_system_id INTEGER")
        conn.commit()
        print("✅ Column 'last_known_system_id' added successfully.")
    except (sqlite3.OperationalError, psycopg2.errors.DuplicateColumn) as e:
        conn.rollback()
        print("ℹ️ Column 'last_known_system_id' already exists. No changes made.")
    except Exception as e:
        conn.rollback()
        print(f"❌ An unexpected error occurred: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()