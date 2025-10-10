import os
import sys
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from cryptography.fernet import Fernet

# --- CONFIGURATION ---
DATABASE_URL = os.environ.get('DATABASE_URL')
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')

def get_db_connection():
    """Connects to the appropriate database."""
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
        return conn, conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn = sqlite3.connect('starmap.db')
        conn.row_factory = sqlite3.Row
        return conn, conn.cursor()

def migrate_keys():
    """Encrypts all plain-text API keys in the users table."""
    if not ENCRYPTION_KEY:
        print("❌ ERROR: ENCRYPTION_KEY environment variable not set. Cannot perform migration.")
        return

    print("Starting API key migration...")
    fernet = Fernet(ENCRYPTION_KEY.encode())
    conn, cursor = get_db_connection()
    pg_compat = bool(DATABASE_URL)
    param = '%s' if pg_compat else '?'

    try:
        cursor.execute("SELECT id, api_key FROM users WHERE api_key IS NOT NULL AND api_key != ''")
        users = cursor.fetchall()
        
        if not users:
            print("No users with API keys found. Nothing to migrate.")
            return

        print(f"Found {len(users)} user(s) with API keys to check.")
        migrated_count = 0
        
        for user in users:
            user_id = user['id']
            api_key = user['api_key']
            
            try:
                # Try to decrypt the key. If it succeeds, it's already encrypted.
                fernet.decrypt(api_key.encode())
                print(f"  - User {user_id}: Key is already encrypted. Skipping.")
            except Exception:
                # If decryption fails, it's plain-text. Let's encrypt it.
                print(f"  - User {user_id}: Found plain-text key. Encrypting now...")
                encrypted_key = fernet.encrypt(api_key.encode()).decode()
                cursor.execute(f"UPDATE users SET api_key = {param} WHERE id = {param}", (encrypted_key, user_id))
                migrated_count += 1
        
        conn.commit()
        print(f"\n✅ Migration complete. {migrated_count} key(s) were newly encrypted.")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ An error occurred during migration: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    migrate_keys()