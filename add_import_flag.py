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
    """Adds the initial_import_done column to the factions table if it doesn't exist."""
    print("Running migration to add 'initial_import_done' column...")
    conn, cursor = get_db_connection()
    
    try:
        # Add the new column, defaulting it to FALSE for all existing factions
        cursor.execute("ALTER TABLE factions ADD COLUMN initial_import_done BOOLEAN DEFAULT FALSE NOT NULL")
        conn.commit()
        print("✅ Column 'initial_import_done' added successfully.")
    except (sqlite3.OperationalError, psycopg2.errors.DuplicateColumn) as e:
        conn.rollback()
        print("ℹ️ Column 'initial_import_done' already exists. No changes made.")
    except Exception as e:
        conn.rollback()
        print(f"❌ An unexpected error occurred: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()