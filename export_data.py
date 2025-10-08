import sqlite3
import json
import os

# --- CONFIGURATION ---
DATABASE_FILE = 'starmap.db'
EXPORT_DIR = 'seed_data'

def export_data():
    """
    Reads data from the local SQLite database and exports each table
    into a separate JSON file in the 'seed_data' directory.
    """
    if not os.path.exists(DATABASE_FILE):
        print(f"Error: The database '{DATABASE_FILE}' was not found. Nothing to export.")
        return

    if not os.path.exists(EXPORT_DIR):
        os.makedirs(EXPORT_DIR)
        print(f"Created export directory: '{EXPORT_DIR}'")

    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    tables = ['factions', 'users', 'systems', 'faction_discovered_systems', 'wormholes']
    
    print("\nStarting data export...")
    for table in tables:
        print(f"  - Exporting table: {table}")
        cursor.execute(f"SELECT * FROM {table}")
        rows = [dict(row) for row in cursor.fetchall()]
        
        file_path = os.path.join(EXPORT_DIR, f"{table}.json")
        with open(file_path, 'w') as f:
            json.dump(rows, f, indent=4)
        print(f"    > Saved {len(rows)} rows to '{file_path}'")

    conn.close()
    print("\n✅ Data export complete!")

if __name__ == "__main__":
    export_data()

