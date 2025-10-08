import sqlite3
import os

OLD_DB = 'starmap.db'
NEW_DB = 'starmap_migrated.db'

def migrate():
    """
    Reads data from the old database and inserts it into a new
    database with the updated schema, including the 'is_developer' column.
    """
    if not os.path.exists(OLD_DB):
        print(f"Error: The database '{OLD_DB}' was not found. Nothing to migrate.")
        return

    if os.path.exists(NEW_DB):
        os.remove(NEW_DB)
        print(f"Removed existing '{NEW_DB}' to start fresh.")

    print(f"Connecting to old database '{OLD_DB}' and new database '{NEW_DB}'...")
    old_conn = sqlite3.connect(OLD_DB)
    old_conn.row_factory = sqlite3.Row
    old_cursor = old_conn.cursor()

    new_conn = sqlite3.connect(NEW_DB)
    new_cursor = new_conn.cursor()

    print("Creating new database schema...")
    new_cursor.execute('CREATE TABLE factions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)')
    new_cursor.execute('''
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, api_key TEXT,
        faction_id INTEGER NOT NULL REFERENCES factions(id),
        is_admin BOOLEAN DEFAULT 0 NOT NULL,
        is_developer BOOLEAN DEFAULT 0 NOT NULL
    )''')
    new_cursor.execute('CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, position REAL NOT NULL UNIQUE, catapult_radius REAL DEFAULT 0)')
    new_cursor.execute('CREATE TABLE faction_discovered_systems (faction_id INTEGER NOT NULL REFERENCES factions(id), system_id INTEGER NOT NULL REFERENCES systems(id), PRIMARY KEY (faction_id, system_id))')
    new_cursor.execute('CREATE TABLE wormholes (system_a_id INTEGER NOT NULL REFERENCES systems(id), system_b_id INTEGER NOT NULL REFERENCES systems(id), PRIMARY KEY (system_a_id, system_b_id))')
    new_conn.commit()
    print("New schema created successfully.")

    # --- Data Migration ---
    tables = ['factions', 'systems', 'faction_discovered_systems', 'wormholes']
    for table in tables:
        print(f"Migrating data for table: {table}...")
        old_cursor.execute(f"SELECT * FROM {table}")
        rows = old_cursor.fetchall()
        if rows:
            # Assumes columns are in the same order
            placeholders = ', '.join(['?'] * len(rows[0]))
            new_cursor.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
            print(f"  > Migrated {len(rows)} rows.")
    
    # Special handling for the 'users' table
    print("Migrating data for table: users...")
    old_cursor.execute("SELECT id, username, password, api_key, faction_id, is_admin FROM users")
    user_rows = old_cursor.fetchall()
    if user_rows:
        users_to_insert = []
        for row in user_rows:
            # Add the new 'is_developer' column with a default value of 0 (False)
            users_to_insert.append(tuple(row) + (0,))
        
        new_cursor.executemany("INSERT INTO users (id, username, password, api_key, faction_id, is_admin, is_developer) VALUES (?, ?, ?, ?, ?, ?, ?)", users_to_insert)
        print(f"  > Migrated {len(user_rows)} users.")

    new_conn.commit()
    old_conn.close()
    new_conn.close()

    print("\n--- MIGRATION COMPLETE ---")
    print(f"All data has been copied from '{OLD_DB}' to '{NEW_DB}'.")
    print("\nNext steps:")
    print(f"1. Rename your old database: '{OLD_DB}' -> '{OLD_DB}.old'")
    print(f"2. Rename the new migrated database: '{NEW_DB}' -> '{OLD_DB}'")

if __name__ == "__main__":
    migrate()
