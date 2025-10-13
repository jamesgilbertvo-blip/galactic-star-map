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
RELATIONSHIPS_API_URL = "https://play.textspaced.com/api/faction/karma/all"


# --- DATABASE CONNECTION & SETUP ---
def get_db_connection():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
        return conn, conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn = sqlite3.connect('starmap.db')
        conn.row_factory = sqlite3.Row
        return conn, conn.cursor()

def setup_database_if_needed():
    conn, cursor = get_db_connection()
    pg_compat = bool(DATABASE_URL)
    try:
        cursor.execute("SELECT id FROM users LIMIT 1")
    except (sqlite3.OperationalError, psycopg2.errors.UndefinedTable):
        print("Database tables not found. Creating schema from scratch...")
        conn.rollback()
        
        user_id_type = 'SERIAL PRIMARY KEY' if pg_compat else 'INTEGER PRIMARY KEY AUTOINCREMENT'
        faction_id_type = 'SERIAL PRIMARY KEY' if pg_compat else 'INTEGER PRIMARY KEY AUTOINCREMENT'

        cursor.execute(f'CREATE TABLE factions (id {faction_id_type}, name TEXT UNIQUE NOT NULL)')
        cursor.execute(f'''
        CREATE TABLE users (
            id {user_id_type},
            username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, api_key TEXT,
            faction_id INTEGER NOT NULL REFERENCES factions(id),
            is_admin BOOLEAN DEFAULT FALSE NOT NULL,
            is_developer BOOLEAN DEFAULT FALSE NOT NULL
        )''')
        cursor.execute('CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, position REAL NOT NULL UNIQUE, catapult_radius REAL DEFAULT 0, owner_faction_id INTEGER REFERENCES factions(id))')
        cursor.execute('CREATE TABLE faction_discovered_systems (faction_id INTEGER NOT NULL REFERENCES factions(id), system_id INTEGER NOT NULL REFERENCES systems(id), PRIMARY KEY (faction_id, system_id))')
        cursor.execute('CREATE TABLE wormholes (system_a_id INTEGER NOT NULL REFERENCES systems(id), system_b_id INTEGER NOT NULL REFERENCES systems(id), PRIMARY KEY (system_a_id, system_b_id))')
        
        print("Core tables created.")
    
    try:
        cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS faction_relationships (
            faction_a_id INTEGER NOT NULL REFERENCES factions(id),
            faction_b_id INTEGER NOT NULL REFERENCES factions(id),
            status TEXT NOT NULL CHECK (status IN ('allied', 'war')),
            PRIMARY KEY (faction_a_id, faction_b_id),
            CHECK (faction_a_id < faction_b_id)
        )''')
        print("Checked for 'faction_relationships' table.")
    except (sqlite3.OperationalError, psycopg2.errors.UndefinedTable) as e:
        print(f"Error creating faction_relationships table: {e}")
        conn.rollback()

    conn.commit()
    conn.close()
    print("Database setup check complete.")


# --- Admin Decorator & Utilities ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'is_admin' not in session or not session['is_admin']: return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

def get_spiral_coords(position):
    if position is None: return 0, 0
    angle = position * 0.1; radius = position * 50 / 1000
    return radius * math.cos(angle), radius * math.sin(angle)

def fetch_api_data(url, api_key):
    if not api_key: return None
    headers = {'Authorization': f'Bearer {api_key}', 'Accept': 'application/json'}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException: return None

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

        faction_info = fetch_api_data(FACTION_API_URL, api_key)
        faction_name = faction_info.get('info', {}).get('name')
        if not faction_name: return jsonify({'message': 'Could not verify faction with game API.'}), 500

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
        
        relationship_data = fetch_api_data(RELATIONSHIPS_API_URL, api_key)
        if relationship_data:
            cursor.execute(f"DELETE FROM faction_relationships WHERE faction_a_id = {param} OR faction_b_id = {param}", (faction_id, faction_id))
            
            # --- FINAL CORRECTED LOGIC ---
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
                if rel['name'] == faction_name:
                    continue # Skip the user's own faction

                cursor.execute(f"SELECT id FROM factions WHERE name = {param}", (rel['name'],))
                other_fac_row = cursor.fetchone()
                if other_fac_row:
                    other_fac_id = other_fac_row['id']
                else:
                    if pg_compat:
                        cursor.execute(f"INSERT INTO factions (name) VALUES ({param}) RETURNING id", (rel['name'],)); other_fac_id = cursor.fetchone()['id']
                    else:
                        cursor.execute("INSERT INTO factions (name) VALUES (?)", (rel['name'],)); other_fac_id = cursor.lastrowid
                
                fac_a = min(faction_id, other_fac_id)
                fac_b = max(faction_id, other_fac_id)
                
                if pg_compat:
                    cursor.execute(f"INSERT INTO faction_relationships (faction_a_id, faction_b_id, status) VALUES ({param}, {param}, {param}) ON CONFLICT DO NOTHING", (fac_a, fac_b, rel['status']))
                else:
                    cursor.execute("INSERT OR IGNORE INTO faction_relationships (faction_a_id, faction_b_id, status) VALUES (?, ?, ?)", (fac_a, fac_b, rel['status']))
        # --- End of relationship sync ---

        current_system_data = fetch_api_data(CURRENT_SYSTEM_API_URL, api_key)
        systems_data = fetch_api_data(SYSTEMS_API_URL, api_key)
        wormholes_data = fetch_api_data(WORMHOLE_API_URL, api_key)
        structures_data = fetch_api_data(STRUCTURES_API_URL, api_key)

        if not any([current_system_data, systems_data, wormholes_data, structures_data]):
             return jsonify({'message': 'Failed to fetch any data from game API.'}), 500

        all_systems = {}
        if current_system_data and 'system' in current_system_data:
            for sys_id, sys_info in current_system_data['system'].items(): all_systems[int(sys_id)] = {'system_id': int(sys_id), 'system_name': sys_info['system_name'], 'system_position': sys_info['system_position']}
        if systems_data:
            for s in systems_data: all_systems[s['system_id']] = s
        if wormholes_data and 'stable' in wormholes_data:
            stable_wormholes = wormholes_data['stable'].values() if isinstance(wormholes_data['stable'], dict) else wormholes_data['stable']
            for wh in stable_wormholes:
                if wh['from_system_id'] not in all_systems: all_systems[wh['from_system_id']] = {'system_id': wh['from_system_id'], 'system_name': wh['from_system_name'], 'system_position': wh['from_system_position']}
                if wh['to_system_id'] not in all_systems: all_systems[wh['to_system_id']] = {'system_id': wh['to_system_id'], 'system_name': wh['to_system_name'], 'system_position': wh['to_system_position']}
        
        if all_systems:
            systems_to_insert = [(s['system_id'], s.get('system_name') or f"System {s['system_id']}", *get_spiral_coords(s.get('system_position')), s.get('system_position')) for s in all_systems.values()]
            if pg_compat: cursor.executemany(f'INSERT INTO systems (id, name, x, y, position) VALUES ({param}, {param}, {param}, {param}, {param}) ON CONFLICT(id) DO NOTHING', systems_to_insert)
            else: cursor.executemany('INSERT OR IGNORE INTO systems (id, name, x, y, position) VALUES (?, ?, ?, ?, ?)', systems_to_insert)

            if structures_data and current_system_data and 'system' in current_system_data:
                current_system_id = int(list(current_system_data['system'].keys())[0]); max_catapult_radius = 0
                if isinstance(structures_data, dict):
                    for structure in structures_data.values():
                        if structure and isinstance(structure, dict) and structure.get("type_name") == "Null Space Catapult":
                            current_radius = structure.get("quantity", 0)
                            if current_radius > max_catapult_radius: max_catapult_radius = current_radius
                cursor.execute(f"UPDATE systems SET catapult_radius = {param} WHERE id = {param}", (max_catapult_radius, current_system_id))

            if current_system_data and 'system' in current_system_data:
                current_sys_details = list(current_system_data['system'].values())[0]
                current_sys_id = int(list(current_system_data['system'].keys())[0])
                owner_faction_name = current_sys_details.get('system_faction_name')
                owner_db_id = None

                if owner_faction_name:
                    cursor.execute(f"SELECT id FROM factions WHERE name = {param}", (owner_faction_name,))
                    owner_row = cursor.fetchone()
                    if owner_row:
                        owner_db_id = owner_row['id']
                    else: 
                        if pg_compat:
                            cursor.execute(f"INSERT INTO factions (name) VALUES ({param}) RETURNING id", (owner_faction_name,))
                            owner_db_id = cursor.fetchone()['id']
                        else:
                            cursor.execute("INSERT INTO factions (name) VALUES (?)", (owner_faction_name,)); owner_db_id = cursor.lastrowid
                
                cursor.execute(f"UPDATE systems SET owner_faction_id = {param} WHERE id = {param}", (owner_db_id, current_sys_id))

            faction_systems_to_link = [(faction_id, sys_id) for sys_id in all_systems.keys()]
            if pg_compat: cursor.executemany(f'INSERT INTO faction_discovered_systems (faction_id, system_id) VALUES ({param}, {param}) ON CONFLICT (faction_id, system_id) DO NOTHING', faction_systems_to_link)
            else: cursor.executemany('INSERT OR IGNORE INTO faction_discovered_systems (faction_id, system_id) VALUES (?, ?)', faction_systems_to_link)
            
            if wormholes_data and 'stable' in wormholes_data:
                stable_wormholes = wormholes_data['stable'].values() if isinstance(wormholes_data['stable'], dict) else wormholes_data['stable']
                wormholes_to_insert = [(min(wh['from_system_id'], wh['to_system_id']), max(wh['from_system_id'], wh['to_system_id'])) for wh in stable_wormholes]
                if pg_compat: cursor.executemany(f'INSERT INTO wormholes (system_a_id, system_b_id) VALUES ({param}, {param}) ON CONFLICT DO NOTHING', wormholes_to_insert)
                else: cursor.executemany('INSERT OR IGNORE INTO wormholes (system_a_id, system_b_id) VALUES (?, ?)', wormholes_to_insert)
        
        conn.commit()
        return jsonify({'message': 'Sync successful!'})

    except Exception as e:
        conn.rollback(); print(f"ERROR in /api/sync: {e}", file=sys.stderr); return jsonify({'error': 'An internal error occurred during sync.'}), 500
    finally:
        if conn: conn.close()
        
# ... (The rest of the file is unchanged) ...
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
    try:
        cursor.execute("SELECT id FROM users LIMIT 1"); is_first_user = cursor.fetchone() is None
        is_admin_flag = True if is_first_user else False
        cursor.execute(f"SELECT id FROM factions WHERE name = {param}", (faction_name,)); faction = cursor.fetchone()
        if faction: faction_id = faction['id']
        else:
            if pg_compat: cursor.execute(f"INSERT INTO factions (name) VALUES ({param}) RETURNING id", (faction_name,)); faction_id = cursor.fetchone()['id']
            else: cursor.execute("INSERT INTO factions (name) VALUES (?)", (faction_name,)); faction_id = cursor.lastrowid
        encrypted_api_key = fernet.encrypt(api_key.encode()).decode() if api_key else None
        if pg_compat:
            cursor.execute(f"INSERT INTO users (username, password, api_key, faction_id, is_admin, is_developer) VALUES ({param}, {param}, {param}, {param}, {param}, {param}) RETURNING id", (username, password, encrypted_api_key, faction_id, is_admin_flag, is_developer_account))
            user_id = cursor.fetchone()['id']
        else:
            cursor.execute("INSERT INTO users (username, password, api_key, faction_id, is_admin, is_developer) VALUES (?, ?, ?, ?, ?, ?)", (username, password, encrypted_api_key, faction_id, is_admin_flag, is_developer_account)); user_id = cursor.lastrowid
        
        conn.commit(); 
        session['user_id'] = user_id; session['username'] = username; session['faction_id'] = faction_id; session['is_admin'] = is_admin_flag; session['is_developer'] = is_developer_account
        
        return jsonify({
            'message': 'Registration successful',
            'username': username,
            'is_admin': is_admin_flag,
            'is_developer': is_developer_account
        }), 201
    except (sqlite3.IntegrityError, psycopg2.IntegrityError): return jsonify({'message': 'Username already exists.'}), 409
    finally: conn.close()

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(); username, password = data.get('username'), data.get('password')
    conn, cursor = get_db_connection(); cursor.execute(f"SELECT * FROM users WHERE username = {'%s' if bool(DATABASE_URL) else '?'}", (username,)); user = cursor.fetchone(); conn.close()
    if user and user['password'] == password:
        session['user_id'], session['username'], session['faction_id'], session['is_admin'], session['is_developer'] = user['id'], user['username'], user['faction_id'], user['is_admin'], user.get('is_developer', False)
        return jsonify({'message': 'Login successful', 'username': user['username'], 'is_admin': user['is_admin'], 'is_developer': user.get('is_developer', False)})
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
    if 'user_id' in session: return jsonify({'logged_in': True, 'username': session['username'], 'is_admin': session.get('is_admin', False), 'is_developer': session.get('is_developer', False)})
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
    faction_a_id, faction_b_id = min(id_a, id_b), max(id_a, id_b)
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
    faction_a_id, faction_b_id = min(id_a, id_b), max(id_a, id_b)
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?';
    cursor.execute(f"DELETE FROM faction_relationships WHERE faction_a_id = {param} AND faction_b_id = {param}", (faction_a_id, faction_b_id))
    conn.commit(); conn.close(); return jsonify({'message': 'Relationship deleted'})
@app.route('/api/admin/update_system_owner', methods=['POST'])
@admin_required
def update_system_owner():
    data = request.get_json(); system_id, owner_id = data.get('system_id'), data.get('owner_faction_id')
    if system_id is None: return jsonify({'error': 'system_id is required'}), 400
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?';
    cursor.execute(f"UPDATE systems SET owner_faction_id = {param} WHERE id = {param}", (owner_id if owner_id != '0' else None, system_id))
    conn.commit(); conn.close(); return jsonify({'message': f'System {system_id} owner updated.'})
@app.route('/api/admin/systems')
@admin_required
def get_all_systems():
    conn, cursor = get_db_connection();
    cursor.execute('SELECT s.id, s.name, s.position, s.catapult_radius, s.owner_faction_id, f.name as owner_name FROM systems s LEFT JOIN factions f ON s.owner_faction_id = f.id ORDER BY s.position ASC');
    systems_list = cursor.fetchall(); conn.close()
    return jsonify(systems_list)
@app.route('/api/admin/update_system', methods=['POST'])
@admin_required
def update_system():
    data = request.get_json(); system_id, new_radius = data.get('system_id'), data.get('catapult_radius')
    if system_id is None or new_radius is None: return jsonify({'error': 'system_id and catapult_radius are required'}), 400
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?'; cursor.execute(f"UPDATE systems SET catapult_radius = {param} WHERE id = {param}", (new_radius, system_id)); conn.commit(); conn.close()
    return jsonify({'message': f'System {system_id} updated successfully.'})
@app.route('/api/admin/wormholes')
@admin_required
def get_all_wormholes():
    conn, cursor = get_db_connection(); cursor.execute('SELECT s1.name as name_a, s2.name as name_b, w.system_a_id, w.system_b_id FROM wormholes w JOIN systems s1 ON w.system_a_id = s1.id JOIN systems s2 ON w.system_b_id = s2.id'); wormholes_list = cursor.fetchall(); conn.close()
    return jsonify(wormholes_list)
@app.route('/api/admin/add_wormhole', methods=['POST'])
@admin_required
def add_wormhole():
    data = request.get_json(); id_a, id_b = data.get('system_a_id'), data.get('system_b_id')
    if not id_a or not id_b: return jsonify({'error': 'Both system IDs are required'}), 400
    conn, cursor = get_db_connection()
    try:
        param = '%s' if bool(DATABASE_URL) else '?'; cursor.execute(f"INSERT INTO wormholes (system_a_id, system_b_id) VALUES ({param}, {param})", (min(id_a, id_b), max(id_a, id_b))); conn.commit()
    except (sqlite3.IntegrityError, psycopg2.IntegrityError): return jsonify({'error': 'Wormhole already exists or invalid system ID'}), 400
    finally: conn.close()
    return jsonify({'message': 'Wormhole added successfully'})
@app.route('/api/admin/delete_wormhole', methods=['POST'])
@admin_required
def delete_wormhole():
    data = request.get_json(); id_a, id_b = data.get('system_a_id'), data.get('system_b_id')
    if not id_a or not id_b: return jsonify({'error': 'Both system IDs are required'}), 400
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?'; cursor.execute(f"DELETE FROM wormholes WHERE system_a_id = {param} AND system_b_id = {param}", (min(id_a, id_b), max(id_a, id_b))); conn.commit(); conn.close()
    return jsonify({'message': 'Wormhole deleted successfully'})
    
@app.route('/api/systems')
def get_systems_data():
    if 'user_id' not in session: return jsonify({'error': 'Not authenticated'}), 401
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?'
    if session.get('is_developer'):
        cursor.execute('SELECT s.id, s.name, s.x, s.y, s.position, s.catapult_radius, s.owner_faction_id FROM systems s')
    else:
        faction_id = session['faction_id']
        cursor.execute(f'SELECT s.id, s.name, s.x, s.y, s.position, s.catapult_radius, s.owner_faction_id FROM systems s JOIN faction_discovered_systems fds ON s.id = fds.system_id WHERE fds.faction_id = {param}', (faction_id,))
    systems_list = cursor.fetchall(); systems_dict = {row['id']: dict(row) for row in systems_list}
    cursor.execute('SELECT system_a_id, system_b_id FROM wormholes'); all_wormholes = cursor.fetchall()
    system_ids = set(systems_dict.keys())
    visible_wormholes = [(wh['system_a_id'], wh['system_b_id']) for wh in all_wormholes if wh['system_a_id'] in system_ids and wh['system_b_id'] in system_ids]
    conn.close()
    return jsonify({'systems': systems_dict, 'wormholes': visible_wormholes})

@app.route('/api/path', methods=['POST'])
def calculate_path():
    if 'user_id' not in session: return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json(); start_input, end_input = data.get('start_id'), data.get('end_id')
    if not start_input or not end_input: return jsonify({'error': 'start_id and end_id are required'}), 400
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?'
    user_faction_id = session.get('faction_id')
    relationships = {}
    if user_faction_id:
        cursor.execute(f"SELECT * FROM faction_relationships WHERE faction_a_id = {param} OR faction_b_id = {param}", (user_faction_id, user_faction_id))
        for rel in cursor.fetchall():
            other_fac = rel['faction_b_id'] if rel['faction_a_id'] == user_faction_id else rel['faction_a_id']
            relationships[other_fac] = rel['status']
    if session.get('is_developer'):
        cursor.execute('SELECT id, name, x, y, position, catapult_radius, owner_faction_id FROM systems')
    else:
        cursor.execute(f'SELECT s.id, s.name, s.x, s.y, s.position, s.catapult_radius, s.owner_faction_id FROM systems s JOIN faction_discovered_systems fds ON s.id = fds.system_id WHERE fds.faction_id = {param}', (user_faction_id,))
    all_systems_raw = cursor.fetchall(); cursor.execute('SELECT system_a_id, system_b_id FROM wormholes'); all_wormholes = cursor.fetchall(); conn.close()
    if not all_systems_raw: return jsonify({'path': [], 'distance': None})
    systems_map = {str(r['id']): {'name': r['name'], 'x': r['x'], 'y': r['y'], 'position': r['position'], 'radius': r['catapult_radius'], 'owner': r['owner_faction_id']} for r in all_systems_raw}
    start_id, end_id = None, None
    if start_input.startswith('pos:'):
        start_id = 'virtual_start'; pos = float(start_input[4:]); x, y = get_spiral_coords(pos)
        systems_map[start_id] = {'name': f'Coordinate #{pos}', 'x': x, 'y': y, 'position': pos, 'radius': 0, 'owner': None}
    else: start_id = start_input.split(':')[1]
    if end_input.startswith('pos:'):
        end_id = 'virtual_end'; pos = float(end_input[4:]); x, y = get_spiral_coords(pos)
        systems_map[end_id] = {'name': f'Coordinate #{pos}', 'x': x, 'y': y, 'position': pos, 'radius': 0, 'owner': None}
    else: end_id = end_input.split(':')[1]
    if start_id not in systems_map or end_id not in systems_map: return jsonify({'error': 'Start or end system not found in your map.'}), 404
    wormhole_pairs = {tuple(sorted((str(wh['system_a_id']), str(wh['system_b_id'])))) for wh in all_wormholes}
    distances = {sys_id: float('inf') for sys_id in systems_map}; predecessors = {sys_id: (None, None) for sys_id in systems_map}
    distances[start_id] = 0; pq = [(0, start_id)]
    while pq:
        current_distance, current_id = heapq.heappop(pq)
        if current_distance > distances[current_id]: continue
        if current_id == end_id: break
        for neighbor_id in systems_map:
            if neighbor_id == current_id: continue
            cost, method = float('inf'), None; current_sys = systems_map[current_id]; neighbor_sys = systems_map[neighbor_id]
            sublight_dist = abs(current_sys['position'] - neighbor_sys['position']); cost, method = sublight_dist, 'sublight'
            id_pair = tuple(sorted((current_id, neighbor_id)))
            
            if current_sys.get('radius', 0) > 0 and abs(current_sys['position'] - neighbor_sys['position']) <= current_sys['radius']:
                owner = current_sys.get('owner')
                is_allowed = (owner is None) or (owner == user_faction_id) or (relationships.get(owner) == 'allied')
                if is_allowed: cost, method = 0, 'catapult'
            
            if id_pair in wormhole_pairs:
                owner_a = current_sys.get('owner'); owner_b = neighbor_sys.get('owner')
                is_at_war = (relationships.get(owner_a) == 'war') or (relationships.get(owner_b) == 'war')
                if not is_at_war:
                    if 0 < cost: cost, method = 0, 'wormhole'

            if distances[current_id] + cost < distances[neighbor_id]:
                distances[neighbor_id] = distances[current_id] + cost; predecessors[neighbor_id] = (current_id, method); heapq.heappush(pq, (distances[neighbor_id], neighbor_id))
    full_path_ids, current_node, total_distance = [], end_id, distances.get(end_id)
    if total_distance is None or total_distance == float('inf'): return jsonify({'path': [], 'distance': None})
    while current_node is not None: full_path_ids.append(current_node); current_node, _ = predecessors.get(current_node, (None, None))
    full_path_ids.reverse()
    if not full_path_ids or full_path_ids[0] != start_id: return jsonify({'path': [], 'distance': None})
    path_for_json = []
    for sys_id in full_path_ids:
        node_data = systems_map[sys_id]
        path_for_json.append({'id': sys_id, 'name': node_data['name'], 'x': node_data['x'], 'y': node_data['y'], 'position': node_data['position']})
    if len(full_path_ids) <= 1: return jsonify({'path': path_for_json, 'simple_path': [], 'distance': total_distance})
    simple_path = []; current_leg_start_node = full_path_ids[0]; _, current_method = predecessors[full_path_ids[1]]
    for i in range(1, len(full_path_ids)):
        prev_node = full_path_ids[i-1]; current_node = full_path_ids[i]; _, step_method = predecessors[current_node]
        if step_method != current_method:
            simple_path.append({'from_id': current_leg_start_node, 'to_id': prev_node, 'method': current_method}); current_leg_start_node = prev_node; current_method = step_method
    simple_path.append({'from_id': current_leg_start_node, 'to_id': full_path_ids[-1], 'method': current_method})
    return jsonify({'path': path_for_json, 'simple_path': simple_path, 'distance': total_distance})

# This call ensures the database is set up when the app starts.
setup_database_if_needed()

if __name__ == '__main__':
    app.run(debug=True, port=5000)