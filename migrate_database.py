import sqlite3
import psycopg2
import os

# --- CONFIGURATION ---
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    """Connects to the appropriate database."""
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)
    else:
        # This script is primarily for the live server, but can work locally too.
        return sqlite3.connect('starmap.db')

def migrate_database():
    """
    Adds the 'is_developer' column to the 'users' table if it doesn't already exist.
    This script is safe to run multiple times.
    """
    print("Starting database migration check...")
    conn = get_db_connection()
    cursor = conn.cursor()
    pg_compat = bool(DATABASE_URL)

    try:
        if pg_compat:
            # Check if column exists in PostgreSQL
            cursor.execute("""
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='users' AND column_name='is_developer'
            """)
        else:
            # Check if column exists in SQLite
            cursor.execute("PRAGMA table_info(users)")
        
        columns = [row[1] for row in cursor.fetchall()] if not pg_compat else [row[0] for row in cursor.fetchall()]

        if 'is_developer' in columns:
            print("Migration already applied. The 'is_developer' column already exists.")
        else:
            print("Applying migration: Adding 'is_developer' column to 'users' table...")
            cursor.execute("ALTER TABLE users ADD COLUMN is_developer BOOLEAN DEFAULT FALSE")
            conn.commit()
            print("✅ Success! Database migration complete.")

    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()

