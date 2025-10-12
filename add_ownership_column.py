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
    """Adds the owner_faction_id column to the systems table if it doesn't exist."""
    print("Running migration to add 'owner_faction_id' column...")
    conn, cursor = get_db_connection()
    
    try:
        # The ALTER TABLE command will fail if the column already exists.
        cursor.execute("ALTER TABLE systems ADD COLUMN owner_faction_id INTEGER")
        conn.commit()
        print("✅ Column 'owner_faction_id' added successfully.")
    except (sqlite3.OperationalError, psycopg2.errors.DuplicateColumn) as e:
        # Catch the specific error for an existing column and treat it as success.
        conn.rollback()
        print("ℹ️ Column 'owner_faction_id' already exists. No changes made.")
    except Exception as e:
        conn.rollback()
        print(f"❌ An unexpected error occurred: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()