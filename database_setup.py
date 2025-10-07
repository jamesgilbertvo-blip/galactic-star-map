import sqlite3

# Database file name
DATABASE_FILE = 'starmap.db'

def setup_database():
    """
    Sets up the database, now including an 'is_admin' flag in the users table.
    """
    print(f"Setting up database at '{DATABASE_FILE}'...")
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    # --- Factions Table ---
    cursor.execute('CREATE TABLE IF NOT EXISTS factions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)')
    print("Checked 'factions' table.")

    # --- UPDATED: Users Table with is_admin flag ---
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        api_key TEXT,
        faction_id INTEGER NOT NULL,
        is_admin BOOLEAN DEFAULT 0 NOT NULL,
        FOREIGN KEY (faction_id) REFERENCES factions (id)
    )
    ''')
    print("Updated 'users' table with is_admin flag.")

    # --- Other tables (unchanged) ---
    cursor.execute('CREATE TABLE IF NOT EXISTS systems (id INTEGER PRIMARY KEY, name TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, position REAL NOT NULL UNIQUE, catapult_radius REAL DEFAULT 0)')
    print("Checked 'systems' table.")
    cursor.execute('CREATE TABLE IF NOT EXISTS connections ( from_system_id INTEGER NOT NULL, to_system_id INTEGER NOT NULL, FOREIGN KEY (from_system_id) REFERENCES systems (id), FOREIGN KEY (to_system_id) REFERENCES systems (id), PRIMARY KEY (from_system_id, to_system_id))')
    print("Checked 'connections' table.")
    cursor.execute('CREATE TABLE IF NOT EXISTS wormholes ( system_a_id INTEGER NOT NULL, system_b_id INTEGER NOT NULL, FOREIGN KEY (system_a_id) REFERENCES systems (id), FOREIGN KEY (system_b_id) REFERENCES systems (id), PRIMARY KEY (system_a_id, system_b_id))')
    print("Checked 'wormholes' table.")
    cursor.execute('CREATE TABLE IF NOT EXISTS faction_discovered_systems ( faction_id INTEGER NOT NULL, system_id INTEGER NOT NULL, FOREIGN KEY (faction_id) REFERENCES factions (id), FOREIGN KEY (system_id) REFERENCES systems (id), PRIMARY KEY (faction_id, system_id))')
    print("Checked 'faction_discovered_systems' table.")

    conn.commit()
    conn.close()
    print("Database setup complete.")

if __name__ == "__main__":
    setup_database()

