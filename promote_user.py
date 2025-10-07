import sqlite3
import sys

# --- CONFIGURATION ---
DATABASE_FILE = 'starmap.db'

def promote_user(username):
    """
    A command-line utility to grant admin privileges to a user.
    """
    print(f"Attempting to promote user '{username}' to admin...")
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        # Check if the user exists
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()

        if not user:
            print(f"\n❌ Error: User '{username}' not found in the database.")
            return

        # Update the user's is_admin flag
        cursor.execute("UPDATE users SET is_admin = 1 WHERE username = ?", (username,))
        
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
