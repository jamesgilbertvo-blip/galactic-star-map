import requests
import sqlite3
import math
import sys
import argparse # Import argparse to handle command-line arguments

# --- CONFIGURATION ---
# The API endpoint for nearby systems
API_URL = "https://play.textspaced.com/api/lookup/nearby/stream/"
# Database file name
DATABASE_FILE = 'starmap.db'

# Constants for converting linear position to a 2D spiral
SPIRAL_TIGHTNESS = 0.1
SPIRAL_SCALE = 50

def get_spiral_coords(position):
    """Converts a linear system position to a 2D spiral coordinate."""
    if position is None:
        return 0, 0
    angle = position * SPIRAL_TIGHTNESS
    radius = position * SPIRAL_SCALE / 1000
    x = radius * math.cos(angle)
    y = radius * math.sin(angle)
    return x, y

def fetch_api_data(api_key):
    """Fetches system data from the game's API using the provided key."""
    if not api_key:
        print("API Key is missing. Cannot fetch data.", file=sys.stderr)
        return None
        
    print("Fetching data from API...")
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Accept': 'application/json'
    }
    try:
        response = requests.get(API_URL, headers=headers)
        response.raise_for_status()
        print("Data fetched successfully.")
        return response.json()
    except requests.exceptions.RequestException as req_err:
        print(f"Network or Connection Error: {req_err}", file=sys.stderr)
    except Exception as e:
        print(f"An unexpected error occurred during API fetch: {e}", file=sys.stderr)
    return None

def get_user_details(username):
    """Retrieves user ID and API key from the database for a given username."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, api_key FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    if user:
        return {'id': user[0], 'api_key': user[1]}
    return None

def update_database(api_data, user_id):
    """
    Connects to the database and adds new systems to the master list,
    then links those systems to the specific user who discovered them.
    """
    if not api_data:
        print("No API data to process.")
        return

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    # 1. Add new systems to the master 'systems' table
    systems_to_insert = []
    for system_data in api_data:
        position = system_data.get('system_position')
        x, y = get_spiral_coords(position)
        systems_to_insert.append((
            system_data.get('system_id'),
            system_data.get('system_name'),
            x,
            y,
            position
        ))
    cursor.executemany(
        'INSERT OR IGNORE INTO systems (id, name, x, y, position) VALUES (?, ?, ?, ?, ?)',
        systems_to_insert
    )

    # 2. Link the discovered systems to the current user
    user_systems_to_link = [(user_id, s.get('system_id')) for s in api_data]
    cursor.executemany(
        'INSERT OR IGNORE INTO user_discovered_systems (user_id, system_id) VALUES (?, ?)',
        user_systems_to_link
    )
    
    # 3. Add connections to the master 'connections' table
    sorted_systems = sorted(api_data, key=lambda s: s.get('system_position', 0))
    connections_to_insert = []
    if len(sorted_systems) > 1:
        for i in range(len(sorted_systems) - 1):
            from_sys_id = sorted_systems[i].get('system_id')
            to_sys_id = sorted_systems[i+1].get('system_id')
            connections_to_insert.append((from_sys_id, to_sys_id))
            connections_to_insert.append((to_sys_id, from_sys_id)) # Add reverse connection
            
    if connections_to_insert:
        cursor.executemany(
            'INSERT OR IGNORE INTO connections (from_system_id, to_system_id) VALUES (?, ?)',
            connections_to_insert
        )

    conn.commit()
    print(f"Database updated successfully for user ID {user_id}.")
    conn.close()

def main():
    """Main function to run the data sync process for a specific user."""
    parser = argparse.ArgumentParser(description="Sync game data for a specific user.")
    parser.add_argument("username", type=str, help="The username of the user to sync data for.")
    args = parser.parse_args()
    
    print(f"Starting data sync for user: {args.username}...")
    
    user = get_user_details(args.username)
    if not user:
        print(f"Error: User '{args.username}' not found in the database.", file=sys.stderr)
        return
        
    if not user['api_key']:
        print(f"Error: User '{args.username}' does not have an API key set.", file=sys.stderr)
        return

    api_data = fetch_api_data(user['api_key'])
    if api_data:
        update_database(api_data, user['id'])
    
    print("Data sync complete.")

if __name__ == "__main__":
    main()

