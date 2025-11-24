from flask import Flask, jsonify, request, session, send_from_directory
from flask_cors import CORS
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
import math
import os
import requests
import sys
import heapq
from functools import wraps
from cryptography.fernet import Fernet
import decimal # Use decimal for precise position comparisons

# --- CONFIGURATION ---
DATABASE_URL = os.environ.get('DATABASE_URL')
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))

# --- ENCRYPTION SETUP ---
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    raise ValueError("ENCRYPTION_KEY environment variable not set!")
fernet = Fernet(ENCRYPTION_KEY.encode())

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-key-for-dev')
CORS(app, supports_credentials=True)

# API endpoints
SYSTEMS_API_URL = "https://play.textspaced.com/api/lookup/nearby/stream/"
WORMHOLE_API_URL = "https://play.textspaced.com/api/lookup/nearby/wormholes/"
STRUCTURES_API_URL = "https://play.textspaced.com/api/system/structures/"
CURRENT_SYSTEM_API_URL = "https://play.textspaced.com/api/system/"
FACTION_API_URL = "https://play.textspaced.com/api/faction/info/"
RELATIONSHIPS_API_URL = "https://play.textspaced.com/api/faction/karma/all/"
FACTION_SYSTEMS_API_URL = "https://play.textspaced.com/api/faction/systems/"
POI_API_URL = "https://play.textspaced.com/api/lookup/points_of_interest/"


# --- DATABASE CONNECTION & SETUP ---
def get_db_connection():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=10) # Added timeout
        # Use Decimal type for position to avoid floating point issues
        psycopg2.extensions.register_adapter(decimal.Decimal, psycopg2.extensions.AsIs)
        return conn, conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn = sqlite3.connect('starmap.db')
        conn.row_factory = sqlite3.Row
        return conn, conn.cursor()

# --- MODIFIED: Enhanced setup_database_if_needed for migrations ---
def setup_database_if_needed():
    conn, cursor = get_db_connection()
    pg_compat = bool(DATABASE_URL)
    param = '%s' if pg_compat else '?'

    print("Checking database schema...")

    # Create core tables IF THEY DON'T EXIST
    try:
        user_id_type = 'SERIAL PRIMARY KEY' if pg_compat else 'INTEGER PRIMARY KEY AUTOINCREMENT'
        faction_id_type = 'SERIAL PRIMARY KEY' if pg_compat else 'INTEGER PRIMARY KEY AUTOINCREMENT'
        intel_id_type = 'SERIAL PRIMARY KEY' if pg_compat else 'INTEGER PRIMARY KEY AUTOINCREMENT'

        cursor.execute(f'CREATE TABLE IF NOT EXISTS factions (id {faction_id_type}, name TEXT UNIQUE NOT NULL, initial_import_done BOOLEAN DEFAULT FALSE NOT NULL)')
        cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS users (
            id {user_id_type},
            username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, api_key TEXT,
            faction_id INTEGER NOT NULL REFERENCES factions(id),
            is_admin BOOLEAN DEFAULT FALSE NOT NULL,
            is_developer BOOLEAN DEFAULT FALSE NOT NULL,
            last_known_system_id INTEGER
        )''')
        # Use NUMERIC for position in Postgres for precision
        position_type = 'NUMERIC(10, 2)' if pg_compat else 'REAL'
        cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS systems (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL,
            x REAL NOT NULL, y REAL NOT NULL, position {position_type} NOT NULL UNIQUE,
            catapult_radius REAL DEFAULT 0, owner_faction_id INTEGER REFERENCES factions(id),
            region_name TEXT DEFAULT NULL -- Initially default to NULL
        )''')
        cursor.execute('CREATE TABLE IF NOT EXISTS faction_discovered_systems (faction_id INTEGER NOT NULL REFERENCES factions(id), system_id INTEGER NOT NULL REFERENCES systems(id), PRIMARY KEY (faction_id, system_id))')
        cursor.execute('CREATE TABLE IF NOT EXISTS wormholes (system_a_id INTEGER NOT NULL REFERENCES systems(id), system_b_id INTEGER NOT NULL REFERENCES systems(id), PRIMARY KEY (system_a_id, system_b_id))')
        cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS faction_relationships (
            faction_a_id INTEGER NOT NULL REFERENCES factions(id),
            faction_b_id INTEGER NOT NULL REFERENCES factions(id),
            status TEXT NOT NULL CHECK (status IN ('allied', 'war')),
            PRIMARY KEY (faction_a_id, faction_b_id),
            CHECK (faction_a_id < faction_b_id)
        )''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS region_effects (
            region_name TEXT PRIMARY KEY,
            effect_name TEXT NOT NULL
        )''')
        
        # --- NEW: Intel Markers Table ---
        cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS faction_intel (
            id {intel_id_type},
            faction_id INTEGER NOT NULL REFERENCES factions(id),
            system_id INTEGER REFERENCES systems(id),
            x REAL NOT NULL,
            y REAL NOT NULL,
            type TEXT NOT NULL,
            note TEXT,
            created_by_user_id INTEGER REFERENCES users(id)
        )''')
        # --- END NEW ---

        conn.commit()
        print("Core table existence check complete.")

    except (sqlite3.OperationalError, psycopg2.Error) as e:
        print(f"Error during initial table creation checks: {e}")
        conn.rollback()
        conn.close()
        raise # Re-raise error if basic tables fail

    # --- Schema Migration: Add region_name to systems if missing ---
    try:
        column_exists = False
        if pg_compat:
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'public' AND table_name = 'systems' AND column_name = 'region_name';
            """)
            if cursor.fetchone():
                column_exists = True
        else: # SQLite
            cursor.execute("PRAGMA table_info(systems);")
            columns = cursor.fetchall()
            if any(col['name'] == 'region_name' for col in columns):
                 column_exists = True

        if not column_exists:
            print("Migrating schema: Adding 'region_name' column to 'systems' table...")
            cursor.execute("ALTER TABLE systems ADD COLUMN region_name TEXT DEFAULT NULL;")
            conn.commit()
            print("'region_name' column added successfully.")
        else:
             print("'region_name' column already exists in 'systems'.")

    except (sqlite3.OperationalError, psycopg2.Error) as e:
        print(f"Error during schema migration (adding region_name): {e}")
        conn.rollback()
        # Don't raise here, maybe the app can still run without the column temporarily

    # --- Schema Migration: Ensure position column type is correct for PG ---
    if pg_compat:
        try:
             cursor.execute("""
                 SELECT data_type 
                 FROM information_schema.columns 
                 WHERE table_schema = 'public' AND table_name = 'systems' AND column_name = 'position';
             """)
             col_info = cursor.fetchone()
             if col_info and col_info['data_type'] != 'numeric':
                 print("Migrating schema: Changing 'position' column type to NUMERIC(10, 2)...")
                 # This might lock the table for a while on large datasets
                 cursor.execute("ALTER TABLE systems ALTER COLUMN position TYPE NUMERIC(10, 2);")
                 conn.commit()
                 print("'position' column type updated.")
             elif col_info:
                 print("'position' column type is already correct (NUMERIC).")
             else:
                 print("Warning: Could not verify 'position' column type.")
        except (psycopg2.Error) as e:
             print(f"Error during schema migration (position type): {e}")
             conn.rollback()


    conn.close()
    print("Database setup and migration check complete.")
# --- END MODIFIED ---


# --- Admin Decorator & Utilities ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'is_admin' not in session or not session['is_admin']: return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

def get_spiral_coords(position):
    if position is None: return 0, 0
    # Ensure position is treated as float for calculations
    pos_float = float(position)
    angle = pos_float * 0.1; radius = pos_float * 50 / 1000
    return radius * math.cos(angle), radius * math.sin(angle)

def fetch_api_data(url, api_key):
    if not api_key: return None
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15) # Added timeout
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"API request failed for {url}: {e}", file=sys.stderr)
        return None

def bulk_add_systems(systems_list, faction_id, cursor, pg_compat, param):
    if not systems_list:
        return 0
    
    systems_to_insert = []
    links_to_insert = []
    
    for system_data in systems_list:
        sys_id = system_data.get('system_id')
        sys_pos_str = system_data.get('system_position') # Get as string initially
        
        if not sys_id or sys_pos_str is None: # Check for None explicitly
            continue
        
        try:
            sys_id_int = int(sys_id)
            # Use Decimal for position
            sys_pos_decimal = decimal.Decimal(sys_pos_str)
            
            # --- PRIORITY 1: Block negative positions ---
            if sys_pos_decimal < 0:
                print(f"Skipping system {sys_id_int} (bulk/nearby) due to negative position {sys_pos_decimal}.", file=sys.stderr)
                continue 
            # --- END PRIORITY 1 ---

            sys_name = system_data.get('system_name') or f"System {sys_id_int}"
            x, y = get_spiral_coords(sys_pos_decimal) # Pass Decimal here
            
            # Append Decimal for position
            systems_to_insert.append((sys_id_int, sys_name, x, y, sys_pos_decimal))
            links_to_insert.append((faction_id, sys_id_int))
        except (ValueError, decimal.InvalidOperation) as e:
            print(f"Skipping system due to invalid data: id={sys_id}, pos='{sys_pos_str}'. Error: {e}", file=sys.stderr)
            continue
    
    if systems_to_insert:
        # Adjust INSERT statement for position type
        if pg_compat:
            cursor.executemany(f'INSERT INTO systems (id, name, x, y, position) VALUES ({param}, {param}, {param}, {param}, {param}) ON CONFLICT(id) DO NOTHING', systems_to_insert)
        else:
            # SQLite still uses REAL, convert Decimal back to float just for insert
            systems_to_insert_sqlite = [(d[0], d[1], d[2], d[3], float(d[4])) for d in systems_to_insert]
            cursor.executemany('INSERT OR IGNORE INTO systems (id, name, x, y, position) VALUES (?, ?, ?, ?, ?)', systems_to_insert_sqlite)
    
    if links_to_insert:
        if pg_compat:
            cursor.executemany(f'INSERT INTO faction_discovered_systems (faction_id, system_id) VALUES ({param}, {param}) ON CONFLICT (faction_id, system_id) DO NOTHING', links_to_insert)
        else:
            cursor.executemany('INSERT OR IGNORE INTO faction_discovered_systems (faction_id, system_id) VALUES (?, ?)', links_to_insert)
    
    return len(links_to_insert)

# --- ROUTES ---
@app.route('/api/sync', methods=['POST'])
def sync_data():
    if 'user_id' not in session or session.get('is_developer'): return jsonify({'error': 'Not authenticated or developer accounts cannot sync'}), 401
    
    conn, cursor = get_db_connection()
    pg_compat = bool(DATABASE_URL)
    param = '%s' if pg_compat else '?'
    
    try:
        user_id = session['user_id']
        cursor.execute(f"SELECT api_key, faction_id FROM users WHERE id = {param}", (user_id,))
        user = cursor.fetchone()
        
        encrypted_api_key = user['api_key'] if user else None
        if not encrypted_api_key: return jsonify({'message': 'API key not found.'}), 400
        api_key = fernet.decrypt(encrypted_api_key.encode()).decode()

        # Fetch faction info first to get faction_id
        faction_info = fetch_api_data(FACTION_API_URL, api_key)
        if not faction_info or 'info' not in faction_info or 'name' not in faction_info['info']:
             return jsonify({'message': 'Could not verify faction with game API.'}), 500
        faction_name = faction_info['info']['name']

        cursor.execute(f"SELECT id FROM factions WHERE name = {param}", (faction_name,))
        faction_row = cursor.fetchone()
        if faction_row: faction_id = faction_row['id']
        else:
            if pg_compat:
                cursor.execute(f"INSERT INTO factions (name) VALUES ({param}) RETURNING id", (faction_name,)); faction_id = cursor.fetchone()['id']
            else:
                cursor.execute("INSERT INTO factions (name) VALUES (?)", (faction_name,)); faction_id = cursor.lastrowid
        
        if user['faction_id'] != faction_id:
            cursor.execute(f"UPDATE users SET faction_id = {param} WHERE id = {param}", (faction_id, user_id)); session['faction_id'] = faction_id
        
        # Sync relationships
        relationship_data = fetch_api_data(RELATIONSHIPS_API_URL, api_key)
        if relationship_data:
            cursor.execute(f"DELETE FROM faction_relationships WHERE faction_a_id = {param} OR faction_b_id = {param}", (faction_id, faction_id))
            all_relationships_from_api = []
            
            alliance_data = relationship_data.get('alliance', {})
            if isinstance(alliance_data, dict):
                for item in alliance_data.values():
                    if item.get('faction_name'):
                        all_relationships_from_api.append({'name': item['faction_name'], 'status': 'allied'})

            war_data = relationship_data.get('war', [])
            if isinstance(war_data, list):
                for item in war_data:
                    if item.get('faction_name'):
                        all_relationships_from_api.append({'name': item['faction_name'], 'status': 'war'})
            
            for rel in all_relationships_from_api:
                if rel['name'] == faction_name: continue # Skip self-relation
                cursor.execute(f"SELECT id FROM factions WHERE name = {param}", (rel['name'],))
                other_fac_row = cursor.fetchone()
                other_fac_id = None
                if other_fac_row:
                    other_fac_id = other_fac_row['id']
                else:
                    try:
                        if pg_compat:
                            cursor.execute(f"INSERT INTO factions (name) VALUES ({param}) RETURNING id", (rel['name'],)); other_fac_id = cursor.fetchone()['id']
                        else:
                            cursor.execute("INSERT INTO factions (name) VALUES (?)", (rel['name'],)); other_fac_id = cursor.lastrowid
                    except (sqlite3.IntegrityError, psycopg2.IntegrityError): # Handle race condition if another sync inserted it
                         conn.rollback()
                         cursor.execute(f"SELECT id FROM factions WHERE name = {param}", (rel['name'],))
                         other_fac_row = cursor.fetchone()
                         if other_fac_row: other_fac_id = other_fac_row['id']
                         else: raise # Re-raise if still not found
                
                if other_fac_id: # Ensure we found/created the other faction
                    fac_a = min(faction_id, other_fac_id)
                    fac_b = max(faction_id, other_fac_id)
                    if pg_compat:
                        cursor.execute(f"INSERT INTO faction_relationships (faction_a_id, faction_b_id, status) VALUES ({param}, {param}, {param}) ON CONFLICT DO NOTHING", (fac_a, fac_b, rel['status']))
                    else:
                        cursor.execute("INSERT OR IGNORE INTO faction_relationships (faction_a_id, faction_b_id, status) VALUES (?, ?, ?)", (fac_a, fac_b, rel['status']))

        # Fetch system data
        current_system_data = fetch_api_data(CURRENT_SYSTEM_API_URL, api_key)
        systems_data = fetch_api_data(SYSTEMS_API_URL, api_key)
        wormholes_data = fetch_api_data(WORMHOLE_API_URL, api_key)
        structures_data = fetch_api_data(STRUCTURES_API_URL, api_key)

        if not current_system_data or 'system' not in current_system_data:
             return jsonify({'message': 'Failed to fetch current system data from game API.'}), 500

        # Process current system first (crucial for region info)
        current_system_id = None
        current_sys_details = None
        current_sys_pos_str = None
        current_sys_pos_decimal = None # Store decimal version
        region_name = None
        region_effect_name = None
        
        for sys_id_str, sys_info in current_system_data['system'].items(): 
            try:
                current_system_id_temp = int(sys_id_str) 
                current_sys_details_temp = sys_info
                current_sys_pos_str_temp = sys_info.get('system_position')
                
                if current_sys_pos_str_temp is None:
                     print(f"Warning: Current system {current_system_id_temp} missing position data.", file=sys.stderr)
                     continue # Skip if position is missing

                # Use Decimal for position
                current_sys_pos_decimal_temp = decimal.Decimal(current_sys_pos_str_temp)

                # --- PRIORITY 1: Block sync if current system is negative ---
                if current_sys_pos_decimal_temp < 0:
                     print(f"Blocking sync: User is in negative-position system {current_system_id_temp} ({current_sys_pos_decimal_temp}).", file=sys.stderr)
                     conn.rollback() # Rollback faction updates
                     conn.close()
                     return jsonify({'message': f'Sync blocked: You are in a restricted sector (position {current_sys_pos_decimal_temp} < 0). Please move to normal space and try again.'}), 400
                # --- END PRIORITY 1 ---

                # If we get here, position is valid
                current_system_id = current_system_id_temp
                current_sys_details = current_sys_details_temp
                current_sys_pos_str = current_sys_pos_str_temp
                current_sys_pos_decimal = current_sys_pos_decimal_temp
                
                region_name = sys_info.get('region_name')
                region_effect_name = sys_info.get('region_effect_name')
                
                x, y = get_spiral_coords(current_sys_pos_decimal)
                
                # Insert/Update current system in systems table
                sys_name = sys_info.get('system_name') or f"System {current_system_id}"
                if pg_compat:
                     cursor.execute(f'''
                         INSERT INTO systems (id, name, x, y, position, region_name) 
                         VALUES ({param}, {param}, {param}, {param}, {param}, {param}) 
                         ON CONFLICT(id) DO UPDATE SET 
                             name = EXCLUDED.name, x = EXCLUDED.x, y = EXCLUDED.y, position = EXCLUDED.position, region_name = EXCLUDED.region_name
                     ''', (current_system_id, sys_name, x, y, current_sys_pos_decimal, region_name))
                else:
                     cursor.execute('''
                         INSERT OR REPLACE INTO systems (id, name, x, y, position, region_name) 
                         VALUES (?, ?, ?, ?, ?, ?)
                     ''', (current_system_id, sys_name, x, y, float(current_sys_pos_decimal), region_name))

                # Link current system to faction
                if pg_compat:
                    cursor.execute(f'INSERT INTO faction_discovered_systems (faction_id, system_id) VALUES ({param}, {param}) ON CONFLICT DO NOTHING', (faction_id, current_system_id))
                else:
                    cursor.execute('INSERT OR IGNORE INTO faction_discovered_systems (faction_id, system_id) VALUES (?, ?)', (faction_id, current_system_id))

            except (ValueError, decimal.InvalidOperation) as e:
                 print(f"Error processing current system data for ID {sys_id_str}: {e}", file=sys.stderr)
                 current_system_id = None # Invalidate if processing failed
                 continue

        if not current_system_id or current_sys_details is None or current_sys_pos_decimal is None:
              return jsonify({'message': 'Could not process current system data from API response.'}), 500

        # Now handle other discovered systems
        all_nearby_systems = {} # system_id -> {system_id, system_name, system_position}
        if systems_data:
            for s in systems_data: 
                if s.get('system_id') and s.get('system_position') is not None:
                    all_nearby_systems[s['system_id']] = s
        if wormholes_data and 'stable' in wormholes_data:
            stable_wormholes = wormholes_data['stable'].values() if isinstance(wormholes_data['stable'], dict) else wormholes_data['stable']
            for wh in stable_wormholes:
                for prefix in ['from', 'to']:
                    sys_id = wh.get(f'{prefix}_system_id')
                    sys_pos = wh.get(f'{prefix}_system_position')
                    if sys_id and sys_pos is not None and sys_id not in all_nearby_systems:
                         all_nearby_systems[sys_id] = {
                             'system_id': sys_id, 
                             'system_name': wh.get(f'{prefix}_system_name'), 
                             'system_position': sys_pos
                         }
        
        # Bulk insert/ignore nearby systems (excluding current system, already handled)
        bulk_add_systems([s for s in all_nearby_systems.values() if s['system_id'] != current_system_id], faction_id, cursor, pg_compat, param)
        
        # --- Region Extrapolation Logic ---
        if region_name and current_sys_pos_decimal is not None:
             # Update region_effects table first
             if region_effect_name:
                 print(f"Updating region_effects: Region='{region_name}', Effect='{region_effect_name}'")
                 if pg_compat:
                     cursor.execute(f"INSERT INTO region_effects (region_name, effect_name) VALUES ({param}, {param}) ON CONFLICT (region_name) DO UPDATE SET effect_name = EXCLUDED.effect_name", (region_name, region_effect_name))
                 else:
                     cursor.execute("INSERT OR REPLACE INTO region_effects (region_name, effect_name) VALUES (?, ?)", (region_name, region_effect_name))
             
             # Calculate region range based on current system's position
             region_size = decimal.Decimal('50.0')
             region_start = (current_sys_pos_decimal // region_size) * region_size
             region_end = region_start + region_size # Exclusive end (e.g., 8750.0 to 8800.0)
             print(f"Extrapolating region '{region_name}' to systems with position >= {region_start} and < {region_end}")

             # Update all systems within this coordinate range
             try:
                 if pg_compat:
                     cursor.execute(f"UPDATE systems SET region_name = {param} WHERE position >= {param} AND position < {param}", (region_name, region_start, region_end))
                 else:
                     # SQLite needs float for comparison
                     cursor.execute("UPDATE systems SET region_name = ? WHERE position >= ? AND position < ?", (region_name, float(region_start), float(region_end)))
                 print(f"Updated {cursor.rowcount} systems with region_name '{region_name}'.")
             except Exception as update_err:
                 print(f"Error during region extrapolation update: {update_err}", file=sys.stderr)
                 conn.rollback() # Rollback just this update if it fails
        
        # Update catapult radius for current system
        if structures_data:
            max_catapult_radius = 0
            if isinstance(structures_data, dict):
                for structure in structures_data.values():
                    if structure and isinstance(structure, dict) and structure.get("type_name") == "Null Space Catapult":
                        current_radius = structure.get("quantity", 0)
                        if current_radius > max_catapult_radius: max_catapult_radius = current_radius
            cursor.execute(f"UPDATE systems SET catapult_radius = {param} WHERE id = {param}", (max_catapult_radius, current_system_id))

        # Update owner faction for current system
        owner_faction_name = current_sys_details.get('system_faction_name')
        owner_db_id = None
        if owner_faction_name:
            cursor.execute(f"SELECT id FROM factions WHERE name = {param}", (owner_faction_name,))
            owner_row = cursor.fetchone()
            if owner_row:
                owner_db_id = owner_row['id']
            else: 
                try:
                    if pg_compat:
                        cursor.execute(f"INSERT INTO factions (name) VALUES ({param}) RETURNING id", (owner_faction_name,))
                        owner_db_id = cursor.fetchone()['id']
                    else:
                        cursor.execute("INSERT INTO factions (name) VALUES (?)", (owner_faction_name,)); owner_db_id = cursor.lastrowid
                except (sqlite3.IntegrityError, psycopg2.IntegrityError): # Handle race condition
                     conn.rollback()
                     cursor.execute(f"SELECT id FROM factions WHERE name = {param}", (owner_faction_name,))
                     owner_row = cursor.fetchone()
                     if owner_row: owner_db_id = owner_row['id']
                     else: raise # Re-raise if still not found

        cursor.execute(f"UPDATE systems SET owner_faction_id = {param} WHERE id = {param}", (owner_db_id, current_system_id))

        # Update user's last known location
        cursor.execute(f"UPDATE users SET last_known_system_id = {param} WHERE id = {param}", (current_system_id, user_id))
        session['last_known_system_id'] = current_system_id 
        
        # Sync wormholes connected to current system
        cursor.execute(f"DELETE FROM wormholes WHERE system_a_id = {param} OR system_b_id = {param}", (current_system_id, current_system_id))
        if wormholes_data and 'stable' in wormholes_data:
            stable_wormholes = wormholes_data['stable'].values() if isinstance(wormholes_data['stable'], dict) else wormholes_data['stable']
            wormholes_to_insert = []
            known_system_ids = set(all_nearby_systems.keys()) | {current_system_id} # All systems we know about in this sync
            
            for wh in stable_wormholes:
                from_id = wh.get('from_system_id')
                to_id = wh.get('to_system_id')
                # Only add if BOTH ends are known systems from this sync
                if from_id and to_id and from_id in known_system_ids and to_id in known_system_ids:
                    wormholes_to_insert.append((min(from_id, to_id), max(from_id, to_id)))
            
            if wormholes_to_insert:
                if pg_compat: 
                    cursor.executemany(f'INSERT INTO wormholes (system_a_id, system_b_id) VALUES ({param}, {param}) ON CONFLICT DO NOTHING', wormholes_to_insert)
                else: 
                    cursor.executemany('INSERT OR IGNORE INTO wormholes (system_a_id, system_b_id) VALUES (?, ?)', wormholes_to_insert)
        
        conn.commit()
        return jsonify({'message': 'Sync successful!'})

    except Exception as e:
        conn.rollback(); 
        print(f"ERROR in /api/sync: {e}", file=sys.stderr); 
        import traceback
        traceback.print_exc() # Print full traceback for debugging
        return jsonify({'error': f'An internal error occurred during sync: {e}'}), 500
    finally:
        if conn: conn.close()
        
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json(); username, password, api_key = data.get('username'), data.get('password'), data.get('api_key')
    conn, cursor = get_db_connection(); pg_compat = bool(DATABASE_URL); param = '%s' if pg_compat else '?'
    is_developer_account = not api_key
    if not username or not password or (not is_developer_account and not api_key): return jsonify({'message': 'Username, password, and API key are required for normal users.'}), 400
    
    faction_name = "Developer"
    if not is_developer_account:
        faction_info = fetch_api_data(FACTION_API_URL, api_key)
        faction_name = faction_info.get('info', {}).get('name')
        if not faction_name: return jsonify({'message': 'Could not verify your faction with the provided API key.'}), 400
    
    is_first_user_of_faction = False
    try:
        cursor.execute("SELECT id FROM users LIMIT 1"); is_first_user = cursor.fetchone() is None
        is_admin_flag = True if is_first_user else False
        
        cursor.execute(f"SELECT id, initial_import_done FROM factions WHERE name = {param}", (faction_name,)); faction = cursor.fetchone()
        if faction: 
            faction_id = faction['id']
            cursor.execute(f"SELECT id FROM users WHERE faction_id = {param} LIMIT 1", (faction_id,))
            if cursor.fetchone() is None:
                is_first_user_of_faction = True
        else:
            if pg_compat: cursor.execute(f"INSERT INTO factions (name) VALUES ({param}) RETURNING id", (faction_name,)); faction_id = cursor.fetchone()['id']
            else: cursor.execute("INSERT INTO factions (name) VALUES (?)", (faction_name,)); faction_id = cursor.lastrowid
            is_first_user_of_faction = True
        
        encrypted_api_key = fernet.encrypt(api_key.encode()).decode() if api_key else None
        if pg_compat:
            cursor.execute(f"INSERT INTO users (username, password, api_key, faction_id, is_admin, is_developer) VALUES ({param}, {param}, {param}, {param}, {param}, {param}) RETURNING id", (username, password, encrypted_api_key, faction_id, is_admin_flag, is_developer_account))
            user_id = cursor.fetchone()['id']
        else:
            cursor.execute("INSERT INTO users (username, password, api_key, faction_id, is_admin, is_developer) VALUES (?, ?, ?, ?, ?, ?)", (username, password, encrypted_api_key, faction_id, is_admin_flag, is_developer_account)); user_id = cursor.lastrowid
        
        conn.commit(); 
        session['user_id'] = user_id; session['username'] = username; session['faction_id'] = faction_id; session['is_admin'] = is_admin_flag; session['is_developer'] = is_developer_account
        
        if is_first_user_of_faction and not is_developer_account:
            print(f"First user for faction {faction_name}. Triggering bulk system import.")
            try:
                conn_bulk, cursor_bulk = get_db_connection()
                pg_compat_bulk = bool(DATABASE_URL)
                param_bulk = '%s' if pg_compat_bulk else '?'

                all_systems_to_add = {}
                faction_systems = fetch_api_data(FACTION_SYSTEMS_API_URL, api_key)
                poi_systems = fetch_api_data(POI_API_URL, api_key)
                
                if faction_systems and isinstance(faction_systems, dict):
                    for system_data in faction_systems.values():
                        if system_data.get('system_id'):
                            all_systems_to_add[system_data['system_id']] = {
                                'system_id': system_data['system_id'],
                                'system_name': system_data.get('system_name'),
                                'system_position': system_data.get('system_position')
                            }

                if poi_systems and isinstance(poi_systems, dict):
                    for system_data in poi_systems.values():
                        if system_data.get('system_id'):
                            all_systems_to_add[system_data['system_id']] = {
                                'system_id': system_data['system_id'],
                                'system_name': system_data.get('system_name'),
                                'system_position': system_data.get('system_position')
                            }

                count = bulk_add_systems(all_systems_to_add.values(), faction_id, cursor_bulk, pg_compat_bulk, param_bulk)
                
                cursor_bulk.execute(f"UPDATE factions SET initial_import_done = TRUE WHERE id = {param_bulk}", (faction_id,))
                conn_bulk.commit()
                conn_bulk.close()
                print(f"Bulk import complete. Added {count} systems for faction {faction_id}.")
            except Exception as e:
                print(f"ERROR during automatic bulk import: {e}", file=sys.stderr)
        
        return jsonify({
            'message': 'Registration successful',
            'username': username,
            'is_admin': is_admin_flag,
            'is_developer': is_developer_account
        }), 201
    except (sqlite3.IntegrityError, psycopg2.IntegrityError): return jsonify({'message': 'Username already exists.'}), 409
    finally: 
        if conn: conn.close()

@app.route('/api/bulk_sync_faction_systems', methods=['POST'])
def bulk_sync_faction_systems():
    if 'user_id' not in session or session.get('is_developer'):
        return jsonify({'error': 'Not authenticated'}), 401

    conn, cursor = get_db_connection()
    pg_compat = bool(DATABASE_URL)
    param = '%s' if pg_compat else '?'
    
    try:
        user_id = session['user_id']
        faction_id = session['faction_id']
        
        cursor.execute(f"SELECT api_key FROM users WHERE id = {param}", (user_id,))
        user = cursor.fetchone()
        encrypted_api_key = user['api_key'] if user else None
        
        if not encrypted_api_key:
            return jsonify({'error': 'API key not found.'}), 400
        
        api_key = fernet.decrypt(encrypted_api_key.encode()).decode()

        all_systems_to_add = {}
        faction_systems = fetch_api_data(FACTION_SYSTEMS_API_URL, api_key)
        poi_systems = fetch_api_data(POI_API_URL, api_key)
        
        if faction_systems and isinstance(faction_systems, dict):
            for system_data in faction_systems.values():
                if system_data.get('system_id'):
                    all_systems_to_add[system_data['system_id']] = {
                        'system_id': system_data['system_id'],
                        'system_name': system_data.get('system_name'),
                        'system_position': system_data.get('system_position')
                    }

        if poi_systems and isinstance(poi_systems, dict):
            for system_data in poi_systems.values():
                if system_data.get('system_id'):
                    all_systems_to_add[system_data['system_id']] = {
                        'system_id': system_data['system_id'],
                        'system_name': system_data.get('system_name'),
                        'system_position': system_data.get('system_position')
                    }
        
        if not all_systems_to_add:
            return jsonify({'error': 'Failed to fetch any systems from the API.'}), 500

        count = bulk_add_systems(all_systems_to_add.values(), faction_id, cursor, pg_compat, param)
        
        cursor.execute(f"UPDATE factions SET initial_import_done = TRUE WHERE id = {param}", (faction_id,))
        
        conn.commit()
        
        return jsonify({'message': f'Successfully imported {count} systems for your faction!'})
    
    except Exception as e:
        conn.rollback()
        print(f"ERROR in /api/bulk_sync_faction_systems: {e}", file=sys.stderr)
        return jsonify({'error': 'An internal error occurred during the import.'}), 500
    finally:
        if conn: conn.close()


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(); username, password = data.get('username'), data.get('password')
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?'
    
    cursor.execute(f"SELECT u.*, f.initial_import_done FROM users u JOIN factions f ON u.faction_id = f.id WHERE u.username = {param}", (username,)); 
    user = cursor.fetchone()
    
    if user and user['password'] == password:
        session['user_id'], session['username'], session['faction_id'], session['is_admin'], session['is_developer'] = user['id'], user['username'], user['faction_id'], user['is_admin'], user.get('is_developer', False)
        
        show_bulk_sync = (not user['initial_import_done']) and not user.get('is_developer', False)
        
        conn.close()
        return jsonify({
            'message': 'Login successful', 
            'username': user['username'], 
            'is_admin': user['is_admin'], 
            'is_developer': user.get('is_developer', False),
            'show_bulk_sync': show_bulk_sync,
            'last_known_system_id': user.get('last_known_system_id') 
        })
    
    if conn: conn.close()
    return jsonify({'message': 'Invalid username or password'}), 401

@app.route('/')
def serve_index(): return send_from_directory(STATIC_DIR, 'index.html')

@app.route('/<path:filename>')
def serve_static_files(filename):
    return send_from_directory(STATIC_DIR, filename)

@app.route('/admin')
@admin_required
def serve_admin_panel(): return send_from_directory(STATIC_DIR, 'admin.html')

@app.route('/logout', methods=['POST'])
def logout(): session.clear(); return jsonify({'message': 'Logout successful'})

@app.route('/status')
def status():
    if 'user_id' in session:
        conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?'
        user_id = session['user_id']
        faction_id = session['faction_id']
        is_developer = session.get('is_developer', False)
        
        cursor.execute(f"SELECT u.last_known_system_id, f.initial_import_done FROM users u JOIN factions f ON u.faction_id = f.id WHERE u.id = {param}", (user_id,))
        user_data = cursor.fetchone()
        
        show_bulk_sync = (user_data and not user_data['initial_import_done']) and not is_developer
        
        conn.close()
        return jsonify({
            'logged_in': True, 
            'username': session['username'], 
            'is_admin': session.get('is_admin', False), 
            'is_developer': is_developer,
            'show_bulk_sync': show_bulk_sync,
            'last_known_system_id': user_data.get('last_known_system_id') if user_data else None 
        })
    return jsonify({'logged_in': False})

@app.route('/api/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session: return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']; conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?';
    if request.method == 'GET':
        cursor.execute(f"SELECT api_key FROM users WHERE id = {param}", (user_id,)); user = cursor.fetchone(); conn.close()
        return jsonify({'api_key_set': bool(user and user['api_key'])})
    elif request.method == 'POST':
        data = request.get_json(); updates, params = [], []
        if data.get('api_key'):
            encrypted_api_key = fernet.encrypt(data.get('api_key').encode()).decode()
            updates.append("api_key = %s"); params.append(encrypted_api_key)
        if data.get('password'): 
            updates.append("password = %s"); params.append(data.get('password'))
        if not updates: return jsonify({'message': 'No changes provided.'}), 400
        params.append(user_id); query = f"UPDATE users SET {', '.join(updates)} WHERE id = {param}"
        cursor.execute(query, tuple(params)); conn.commit(); conn.close()
        return jsonify({'message': 'Profile updated successfully.'})

@app.route('/api/admin/factions')
@admin_required
def get_all_factions():
    conn, cursor = get_db_connection(); cursor.execute('SELECT id, name FROM factions ORDER BY name'); factions = cursor.fetchall(); conn.close()
    return jsonify(factions)
@app.route('/api/admin/relationships')
@admin_required
def get_relationships():
    conn, cursor = get_db_connection()
    query = """
        SELECT fr.faction_a_id, f1.name as name_a, fr.faction_b_id, f2.name as name_b, fr.status
        FROM faction_relationships fr JOIN factions f1 ON fr.faction_a_id = f1.id JOIN factions f2 ON fr.faction_b_id = f2.id
        ORDER BY f1.name, f2.name
    """
    cursor.execute(query); relationships = cursor.fetchall(); conn.close()
    return jsonify(relationships)
@app.route('/api/admin/add_relationship', methods=['POST'])
@admin_required
def add_relationship():
    data = request.get_json(); id_a, id_b, status = data.get('faction_a_id'), data.get('faction_b_id'), data.get('status')
    if not all([id_a, id_b, status]) or id_a == id_b or status not in ['allied', 'war']: return jsonify({'error': 'Invalid input'}), 400
    faction_a_id, faction_b_id = min(int(id_a), int(id_b)), max(int(id_a), int(id_b)) # Ensure integer comparison
    conn, cursor = get_db_connection(); pg_compat = bool(DATABASE_URL); param = '%s' if pg_compat else '?'
    try:
        if pg_compat:
            cursor.execute(f"INSERT INTO faction_relationships (faction_a_id, faction_b_id, status) VALUES ({param}, {param}, {param}) ON CONFLICT (faction_a_id, faction_b_id) DO UPDATE SET status = EXCLUDED.status", (faction_a_id, faction_b_id, status))
        else:
            cursor.execute("INSERT OR REPLACE INTO faction_relationships (faction_a_id, faction_b_id, status) VALUES (?, ?, ?)", (faction_a_id, faction_b_id, status))
        conn.commit(); return jsonify({'message': 'Relationship set successfully'})
    except Exception as e:
        conn.rollback(); return jsonify({'error': f'Database error: {e}'}), 500
    finally: conn.close()
@app.route('/api/admin/delete_relationship', methods=['POST'])
@admin_required
def delete_relationship():
    data = request.get_json(); id_a, id_b = data.get('faction_a_id'), data.get('faction_b_id')
    if not all([id_a, id_b]): return jsonify({'error': 'Invalid input'}), 400
    faction_a_id, faction_b_id = min(int(id_a), int(id_b)), max(int(id_a), int(id_b)) # Ensure integer comparison
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?';
    cursor.execute(f"DELETE FROM faction_relationships WHERE faction_a_id = {param} AND faction_b_id = {param}", (faction_a_id, faction_b_id))
    conn.commit(); conn.close(); return jsonify({'message': 'Relationship deleted'})
@app.route('/api/admin/update_system_owner', methods=['POST'])
@admin_required
def update_system_owner():
    data = request.get_json(); system_id, owner_id = data.get('system_id'), data.get('owner_faction_id')
    if system_id is None: return jsonify({'error': 'system_id is required'}), 400
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?';
    owner_id_to_set = owner_id if owner_id not in ['0', '', None] else None # Ensure NULL for '0', empty or None
    cursor.execute(f"UPDATE systems SET owner_faction_id = {param} WHERE id = {param}", (owner_id_to_set, system_id))
    conn.commit(); conn.close(); return jsonify({'message': f'System {system_id} owner updated.'})
@app.route('/api/admin/systems')
@admin_required
def get_all_systems():
    conn, cursor = get_db_connection();
    # Cast position to TEXT for consistent JSON output (esp. from NUMERIC)
    position_col = 'CAST(s.position AS TEXT)' if bool(DATABASE_URL) else 's.position'
    cursor.execute(f'SELECT s.id, s.name, {position_col} as position, s.catapult_radius, s.owner_faction_id, f.name as owner_name FROM systems s LEFT JOIN factions f ON s.owner_faction_id = f.id ORDER BY s.position ASC');
    systems_list = cursor.fetchall(); conn.close()
    # Convert Decimal to string if needed (RealDictCursor might handle it)
    for sys in systems_list:
        if isinstance(sys.get('position'), decimal.Decimal):
            sys['position'] = str(sys['position'])
    return jsonify(systems_list)
@app.route('/api/admin/update_system', methods=['POST'])
@admin_required
def update_system():
    data = request.get_json(); system_id, new_radius = data.get('system_id'), data.get('catapult_radius')
    if system_id is None or new_radius is None: return jsonify({'error': 'system_id and catapult_radius are required'}), 400
    try:
         new_radius_float = float(new_radius)
    except ValueError:
         return jsonify({'error': 'catapult_radius must be a number'}), 400
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?'; cursor.execute(f"UPDATE systems SET catapult_radius = {param} WHERE id = {param}", (new_radius_float, system_id)); conn.commit(); conn.close()
    return jsonify({'message': f'System {system_id} updated successfully.'})
@app.route('/api/admin/wormholes')
@admin_required
def get_all_wormholes():
    conn, cursor = get_db_connection(); cursor.execute('SELECT s1.name as name_a, s2.name as name_b, w.system_a_id, w.system_b_id FROM wormholes w JOIN systems s1 ON w.system_a_id = s1.id JOIN systems s2 ON w.system_b_id = s2.id'); wormholes_list = cursor.fetchall(); conn.close()
    return jsonify(wormholes_list)
@app.route('/api/admin/add_wormhole', methods=['POST'])
@admin_required
def add_wormhole():
    data = request.get_json(); id_a_str, id_b_str = data.get('system_a_id'), data.get('system_b_id')
    try:
        id_a, id_b = int(id_a_str), int(id_b_str)
        if id_a == id_b: raise ValueError("System IDs must be different")
    except (ValueError, TypeError):
         return jsonify({'error': 'Both system IDs are required and must be valid numbers'}), 400
    conn, cursor = get_db_connection()
    try:
        param = '%s' if bool(DATABASE_URL) else '?'; cursor.execute(f"INSERT INTO wormholes (system_a_id, system_b_id) VALUES ({param}, {param})", (min(id_a, id_b), max(id_a, id_b))); conn.commit()
    except (sqlite3.IntegrityError, psycopg2.IntegrityError): 
        conn.rollback() # Important to rollback before returning error
        return jsonify({'error': 'Wormhole already exists or invalid system ID'}), 400
    except Exception as e: # Catch other potential DB errors
         conn.rollback()
         return jsonify({'error': f'Database error: {e}'}), 500
    finally: conn.close()
    return jsonify({'message': 'Wormhole added successfully'})
@app.route('/api/admin/delete_wormhole', methods=['POST'])
@admin_required
def delete_wormhole():
    data = request.get_json(); id_a_str, id_b_str = data.get('system_a_id'), data.get('system_b_id')
    try:
        id_a, id_b = int(id_a_str), int(id_b_str)
    except (ValueError, TypeError):
         return jsonify({'error': 'Both system IDs are required and must be valid numbers'}), 400
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?';
    cursor.execute(f"DELETE FROM wormholes WHERE system_a_id = {param} AND system_b_id = {param}", (min(id_a, id_b), max(id_a, id_b))); conn.commit(); conn.close()
    return jsonify({'message': 'Wormhole deleted successfully'})

# --- MODIFIED: Admin Region Effects Endpoints ---
@app.route('/api/admin/region_effects')
@admin_required
def get_region_effects():
    conn, cursor = get_db_connection();
    
    # Join with systems to find the min position for each region
    query = """
        SELECT 
            re.region_name, 
            re.effect_name, 
            MIN(s.position) as min_pos
        FROM 
            region_effects re
        LEFT JOIN 
            systems s ON re.region_name = s.region_name
        GROUP BY 
            re.region_name, re.effect_name
        ORDER BY 
            re.region_name;
    """
    cursor.execute(query)
    effects = cursor.fetchall()
    conn.close()
    
    # Calculate ranges in Python
    output_effects = []
    region_size = decimal.Decimal('50.0')
    region_end_offset = decimal.Decimal('49.99') # for display
    
    for effect in effects:
        effect_data = dict(effect)
        if effect_data['min_pos'] is not None:
            try:
                min_pos_decimal = decimal.Decimal(effect_data['min_pos'])
                region_start = (min_pos_decimal // region_size) * region_size
                region_end_display = region_start + region_end_offset
                effect_data['range_start'] = f"{region_start:.2f}"
                effect_data['range_end'] = f"{region_end_display:.2f}"
            except (decimal.InvalidOperation, TypeError):
                 effect_data['range_start'] = 'Error'
                 effect_data['range_end'] = 'Error'
        else:
            effect_data['range_start'] = 'N/A'
            effect_data['range_end'] = 'N/A'
        
        # Don't need to send min_pos to frontend
        del effect_data['min_pos']
        output_effects.append(effect_data)

    return jsonify(output_effects)

@app.route('/api/admin/add_region_effect', methods=['POST'])
@admin_required
def add_region_effect():
    data = request.get_json()
    region_name, effect_name = data.get('region_name'), data.get('effect_name')
    position_str = data.get('position') # Optional position
    
    if not region_name or not effect_name: 
        return jsonify({'error': 'Region name and effect name are required'}), 400
    
    conn, cursor = get_db_connection()
    pg_compat = bool(DATABASE_URL); param = '%s' if pg_compat else '?'
    systems_updated_count = 0
    message = "Region effect saved."
    
    try:
        # Step 1: Always update the region_effects table
        if pg_compat:
            cursor.execute(f"INSERT INTO region_effects (region_name, effect_name) VALUES ({param}, {param}) ON CONFLICT (region_name) DO UPDATE SET effect_name = EXCLUDED.effect_name", (region_name, effect_name))
        else:
            cursor.execute("INSERT OR REPLACE INTO region_effects (region_name, effect_name) VALUES (?, ?)", (region_name, effect_name))
        
        # Step 2: If position is provided, update systems table
        if position_str:
            try:
                pos_decimal = decimal.Decimal(str(position_str)) # Ensure it's a decimal
                region_size = decimal.Decimal('50.0')
                region_start = (pos_decimal // region_size) * region_size
                region_end = region_start + region_size # Exclusive end
                
                if pg_compat:
                    cursor.execute(f"UPDATE systems SET region_name = {param} WHERE position >= {param} AND position < {param}", (region_name, region_start, region_end))
                else:
                    cursor.execute("UPDATE systems SET region_name = ? WHERE position >= ? AND position < ?", (region_name, float(region_start), float(region_end)))
                
                systems_updated_count = cursor.rowcount
                message = f"Effect saved. Updated {systems_updated_count} systems in range {region_start:.2f} - {region_end-decimal.Decimal('0.01'):.2f} to region '{region_name}'."
            except (decimal.InvalidOperation, ValueError) as e:
                conn.rollback() # Rollback the transaction
                return jsonify({'error': f'Invalid position number: {e}'}), 400
            except Exception as update_err:
                 conn.rollback()
                 return jsonify({'error': f'Error updating systems table: {update_err}'}), 500

        conn.commit()
        return jsonify({'message': message})
        
    except Exception as e:
        conn.rollback(); return jsonify({'error': f'Database error: {e}'}), 500
    finally: conn.close()

@app.route('/api/admin/delete_region_effect', methods=['POST'])
@admin_required
def delete_region_effect():
    data = request.get_json(); region_name = data.get('region_name')
    if not region_name: return jsonify({'error': 'Region name is required'}), 400
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?';
    try:
        # Step 1: Delete from region_effects
        cursor.execute(f"DELETE FROM region_effects WHERE region_name = {param}", (region_name,))
        if cursor.rowcount == 0:
            return jsonify({'message': 'Effect not found, nothing to delete.'})
            
        # Step 2: Unset this region_name from all systems
        cursor.execute(f"UPDATE systems SET region_name = NULL WHERE region_name = {param}", (region_name,))
        systems_updated_count = cursor.rowcount
        
        conn.commit(); 
        return jsonify({'message': f"Region effect '{region_name}' deleted. Unset region from {systems_updated_count} systems."})
    except Exception as e:
         conn.rollback()
         return jsonify({'error': f'Database error: {e}'}), 500
    finally:
         conn.close()
# --- END MODIFIED ---
    
@app.route('/api/systems')
def get_systems_data():
    if 'user_id' not in session: return jsonify({'error': 'Not authenticated'}), 401
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?'
    # Always fetch region_name now
    if session.get('is_developer'):
        cursor.execute('SELECT s.id, s.name, s.x, s.y, s.position, s.catapult_radius, s.owner_faction_id, s.region_name FROM systems s')
    else:
        faction_id = session['faction_id']
        cursor.execute(f'SELECT s.id, s.name, s.x, s.y, s.position, s.catapult_radius, s.owner_faction_id, s.region_name FROM systems s JOIN faction_discovered_systems fds ON s.id = fds.system_id WHERE fds.faction_id = {param}', (faction_id,))
    
    systems_list = cursor.fetchall()
    # Convert position Decimal to string for JSON serialization
    systems_dict = {}
    for row in systems_list:
        sys_data = dict(row)
        if isinstance(sys_data.get('position'), decimal.Decimal):
             sys_data['position'] = str(sys_data['position'])
        systems_dict[sys_data['id']] = sys_data
        
    cursor.execute('SELECT system_a_id, system_b_id FROM wormholes'); all_wormholes = cursor.fetchall()
    system_ids = set(systems_dict.keys())
    visible_wormholes = [(wh['system_a_id'], wh['system_b_id']) for wh in all_wormholes if wh['system_a_id'] in system_ids and wh['system_b_id'] in system_ids]
    conn.close()
    return jsonify({'systems': systems_dict, 'wormholes': visible_wormholes})

# --- NEW: Shared Intel Markers Endpoints ---
@app.route('/api/intel', methods=['GET', 'POST', 'DELETE'])
def handle_intel():
    if 'user_id' not in session: return jsonify({'error': 'Not authenticated'}), 401
    
    conn, cursor = get_db_connection()
    pg_compat = bool(DATABASE_URL)
    param = '%s' if pg_compat else '?'
    user_id = session['user_id']
    faction_id = session['faction_id']
    
    try:
        if request.method == 'GET':
            cursor.execute(f"SELECT id, system_id, x, y, type, note, created_by_user_id FROM faction_intel WHERE faction_id = {param}", (faction_id,))
            markers = cursor.fetchall()
            return jsonify(markers)
            
        elif request.method == 'POST':
            data = request.get_json()
            x, y = data.get('x'), data.get('y')
            m_type = data.get('type')
            note = data.get('note', '')
            system_id = data.get('system_id') # Optional
            
            if x is None or y is None or not m_type:
                return jsonify({'error': 'Missing required fields (x, y, type)'}), 400
            
            if pg_compat:
                cursor.execute(f"INSERT INTO faction_intel (faction_id, system_id, x, y, type, note, created_by_user_id) VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}) RETURNING id", 
                               (faction_id, system_id, x, y, m_type, note, user_id))
                new_id = cursor.fetchone()['id']
            else:
                cursor.execute("INSERT INTO faction_intel (faction_id, system_id, x, y, type, note, created_by_user_id) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                               (faction_id, system_id, x, y, m_type, note, user_id))
                new_id = cursor.lastrowid
            
            conn.commit()
            return jsonify({'message': 'Marker added', 'id': new_id})
            
        elif request.method == 'DELETE':
            data = request.get_json()
            marker_id = data.get('id')
            
            if not marker_id: return jsonify({'error': 'Marker ID required'}), 400
            
            # Only allow deleting markers belonging to own faction
            cursor.execute(f"DELETE FROM faction_intel WHERE id = {param} AND faction_id = {param}", (marker_id, faction_id))
            if cursor.rowcount == 0:
                return jsonify({'error': 'Marker not found or permission denied'}), 404
            
            conn.commit()
            return jsonify({'message': 'Marker deleted'})
            
    except Exception as e:
        conn.rollback()
        print(f"ERROR in /api/intel: {e}", file=sys.stderr)
        return jsonify({'error': f'Database error: {e}'}), 500
    finally:
        conn.close()
# --- END NEW ---

# --- MODIFIED: /api/path with NEW catapult logic AND hostile avoidance ---
@app.route('/api/path', methods=['POST'])
def calculate_path():
    if 'user_id' not in session: return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json(); start_input, end_input = data.get('start_id'), data.get('end_id')
    avoid_slow_regions = data.get('avoid_slow_regions', False)
    
    # --- NEW: Get avoid_hostile flag ---
    avoid_hostile = data.get('avoid_hostile', False)
    # --- END NEW ---

    slow_effect_name = "Null Space Decay" # Define the slow effect name
    penalty_multiplier = 100 # Define the penalty multiplier
    
    if not start_input or not end_input: return jsonify({'error': 'start_id and end_id are required'}), 400
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?';
    user_faction_id = session.get('faction_id')
    relationships = {}
    if user_faction_id:
        cursor.execute(f"SELECT * FROM faction_relationships WHERE faction_a_id = {param} OR faction_b_id = {param}", (user_faction_id, user_faction_id))
        for rel in cursor.fetchall():
            other_fac = rel['faction_b_id'] if rel['faction_a_id'] == user_faction_id else rel['faction_a_id']
            relationships[other_fac] = rel['status']

    # Fetch slow region names ONCE
    slow_region_names = set()
    if avoid_slow_regions:
        cursor.execute(f"SELECT region_name FROM region_effects WHERE effect_name = {param}", (slow_effect_name,))
        slow_region_names = {row['region_name'] for row in cursor.fetchall()}
        print(f"Avoiding slow regions: {slow_region_names}") # Debugging

    # Fetch systems including region_name
    if session.get('is_developer'):
        cursor.execute('SELECT id, name, x, y, position, catapult_radius, owner_faction_id, region_name FROM systems')
    else:
        cursor.execute(f'SELECT s.id, s.name, s.x, s.y, s.position, s.catapult_radius, s.owner_faction_id, s.region_name FROM systems s JOIN faction_discovered_systems fds ON s.id = fds.system_id WHERE fds.faction_id = {param}', (user_faction_id,))
    all_systems_raw = cursor.fetchall(); cursor.execute('SELECT system_a_id, system_b_id FROM wormholes'); all_wormholes = cursor.fetchall(); conn.close()
    
    if not all_systems_raw: return jsonify({'path': [], 'distance': None})
    
    # Build systems_map including region_name and converting position to Decimal
    systems_map = {}
    for r in all_systems_raw:
         try:
             pos = decimal.Decimal(r['position']) if r['position'] is not None else None
             systems_map[str(r['id'])] = {
                 'name': r['name'], 'x': r['x'], 'y': r['y'], 
                 'position': pos, # Store as Decimal
                 'radius': r['catapult_radius'], 'owner': r['owner_faction_id'], 
                 'region_name': r.get('region_name')
             }
         except (decimal.InvalidOperation, TypeError) as e:
              print(f"Warning: Skipping system {r['id']} due to invalid position '{r['position']}'. Error: {e}", file=sys.stderr)

    
    start_id, end_id = None, None
    try:
        if start_input.startswith('pos:'):
            start_id = 'virtual_start'; pos = decimal.Decimal(start_input[4:]); x, y = get_spiral_coords(pos)
            systems_map[start_id] = {'name': f'Coordinate #{pos}', 'x': x, 'y': y, 'position': pos, 'radius': 0, 'owner': None, 'region_name': None}
        else: start_id = start_input.split(':')[1]
        
        if end_input.startswith('pos:'):
            end_id = 'virtual_end'; pos = decimal.Decimal(end_input[4:]); x, y = get_spiral_coords(pos)
            systems_map[end_id] = {'name': f'Coordinate #{pos}', 'x': x, 'y': y, 'position': pos, 'radius': 0, 'owner': None, 'region_name': None}
        else: end_id = end_input.split(':')[1]
    except (decimal.InvalidOperation, IndexError, ValueError) as e:
         return jsonify({'error': f'Invalid start or end input format: {e}'}), 400

    if start_id not in systems_map or end_id not in systems_map: return jsonify({'error': 'Start or end system/coordinate not found in your map.'}), 404
    
    wormhole_pairs = {tuple(sorted((str(wh['system_a_id']), str(wh['system_b_id'])))) for wh in all_wormholes}
    distances = {sys_id: float('inf') for sys_id in systems_map}; predecessors = {sys_id: (None, None) for sys_id in systems_map}
    distances[start_id] = 0; pq = [(0, start_id)]
    
    while pq:
        current_distance, current_id = heapq.heappop(pq)
        if current_distance > distances[current_id]: continue
        if current_id == end_id: break

        current_sys = systems_map[current_id]
        if current_sys['position'] is None: continue # Skip nodes without position

        for neighbor_id in systems_map:
            if neighbor_id == current_id: continue
            
            neighbor_sys = systems_map[neighbor_id]
            if neighbor_sys['position'] is None: continue # Skip neighbors without position

            cost, method = float('inf'), None
            
            # Use Decimal for distance calculation
            sublight_dist = float(abs(current_sys['position'] - neighbor_sys['position']))
            cost = sublight_dist
            method = 'sublight'
            
            # Apply slow region penalty if applicable
            if avoid_slow_regions:
                is_slow_travel = (current_sys.get('region_name') in slow_region_names) or \
                                 (neighbor_sys.get('region_name') in slow_region_names)
                if is_slow_travel:
                    cost = sublight_dist * penalty_multiplier # Apply penalty

            # --- NEW: Apply hostile system penalty ---
            if avoid_hostile:
                current_owner = current_sys.get('owner')
                neighbor_owner = neighbor_sys.get('owner')
                
                is_hostile = (current_owner is not None and relationships.get(current_owner) == 'war') or \
                             (neighbor_owner is not None and relationships.get(neighbor_owner) == 'war')
                
                if is_hostile:
                    cost = cost * penalty_multiplier # Stack penalty if already slow, or apply new one
            # --- END NEW ---

            id_pair = tuple(sorted((current_id, neighbor_id)))
            
            # --- MODIFIED CATAPULT LOGIC ---
            catapult_radius = current_sys.get('radius', 0)
            if catapult_radius > 0:
                owner = current_sys.get('owner')
                is_allowed = (owner is None) or (owner == user_faction_id) or (relationships.get(owner) == 'allied')
                
                if is_allowed:
                    if sublight_dist <= catapult_radius:
                        # Full jump is covered
                        if 0 < cost: 
                            cost, method = 0, 'catapult'
                    else:
                        # Partial jump is covered
                        partial_cost = sublight_dist - catapult_radius
                        if partial_cost < cost: 
                            cost, method = partial_cost, 'catapult_sublight' # <-- NEW METHOD
            # --- END MODIFIED CATAPULT LOGIC ---

            # Check Wormhole (cost 0, overrides sublight/catapult if cheaper)
            if id_pair in wormhole_pairs:
                owner_a = current_sys.get('owner'); owner_b = neighbor_sys.get('owner')
                # Allow if either system has no owner or owner is not at war
                is_at_war = (owner_a is not None and relationships.get(owner_a) == 'war') or \
                            (owner_b is not None and relationships.get(owner_b) == 'war')
                if not is_at_war:
                    # Only take wormhole if it's cheaper
                    if 0 < cost: 
                        cost, method = 0, 'wormhole'

            # Update path if this route is shorter
            new_distance = distances[current_id] + cost
            if new_distance < distances[neighbor_id]:
                distances[neighbor_id] = new_distance
                predecessors[neighbor_id] = (current_id, method); 
                heapq.heappush(pq, (new_distance, neighbor_id))
    
    # Reconstruct path
    full_path_ids = []
    current_node = end_id
    total_distance = distances.get(end_id)

    if total_distance is None or total_distance == float('inf'): 
        return jsonify({'path': [], 'detailed_path': [], 'distance': None})

    while current_node is not None: 
        full_path_ids.append(current_node); 
        predecessor_info = predecessors.get(current_node)
        if predecessor_info:
             current_node, _ = predecessor_info
        else: # Should only happen for the start node
             current_node = None
             
    full_path_ids.reverse()
    
    if not full_path_ids or full_path_ids[0] != start_id: 
        print("Path reconstruction failed or start node mismatch.", file=sys.stderr) # Debugging
        return jsonify({'path': [], 'detailed_path': [], 'distance': None})
    
    path_for_json = []
    for sys_id in full_path_ids:
        node_data = systems_map[sys_id]
        path_for_json.append({
            'id': sys_id, 
            'name': node_data['name'], 
            'x': node_data['x'], 
            'y': node_data['y'], 
            # Send position as string for consistency
            'position': str(node_data['position']) if node_data['position'] is not None else None 
        })
        
    if len(full_path_ids) <= 1: 
        return jsonify({'path': path_for_json, 'detailed_path': [], 'distance': round(total_distance, 2)})

    detailed_path = []
    for i in range(len(full_path_ids) - 1):
        from_node_id = full_path_ids[i]
        to_node_id = full_path_ids[i+1]
        # Get the method used TO reach the 'to_node_id'
        _, method = predecessors.get(to_node_id, (None, 'unknown')) 
        detailed_path.append({'from_id': from_node_id, 'to_id': to_node_id, 'method': method or 'unknown'})
    
    return jsonify({'path': path_for_json, 'detailed_path': detailed_path, 'distance': round(total_distance, 2)})


# Initial setup call
try:
    setup_database_if_needed()
except Exception as setup_err:
     print(f"CRITICAL ERROR during database setup: {setup_err}. Application might not work correctly.", file=sys.stderr)
     # Depending on severity, you might want sys.exit(1) here

if __name__ == '__main__':
    # Consider removing debug=True for production on Render
    app.run(debug=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true', port=int(os.environ.get('PORT', 5000)), host='0.0.0.0')