import sqlite3
import getpass # To hide password input

# --- CONFIGURATION ---
DATABASE_FILE = 'starmap.db'

def add_user():
    """
    A command-line utility to add a new user to the database.
    Prompts for username, password, and an API key.
    """
    print("--- Add New User ---")
    
    try:
        # Get user input
        username = input("Enter a username: ").strip()
        # Use getpass to hide password entry
        password = getpass.getpass("Enter a password: ").strip()
        api_key = input(f"Enter the API key for {username}: ").strip()

        if not username or not password or not api_key:
            print("\nError: Username, password, and API key cannot be empty.")
            return

        # Connect to the database
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        # Insert the new user into the 'users' table
        # In a real-world app, the password should be hashed before storing.
        # For this tool, we'll store it as plain text for simplicity.
        cursor.execute(
            "INSERT INTO users (username, password, api_key) VALUES (?, ?, ?)",
            (username, password, api_key)
        )
        
        conn.commit()
        conn.close()

        print(f"\n✅ Success! User '{username}' has been added to the database.")

    except sqlite3.IntegrityError:
        print(f"\n❌ Error: The username '{username}' already exists. Please choose a different one.")
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")

if __name__ == "__main__":
    add_user()

