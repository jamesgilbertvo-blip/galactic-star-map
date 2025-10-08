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
from urllib.parse import urlparse

# --- CONFIGURATION ---
DATABASE_URL = os.environ.get('DATABASE_URL') 
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__) 
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-key-for-dev') 
CORS(app, supports_credentials=True)

# API endpoints
SYSTEMS_API_URL = "https://play.textspaced.com/api/lookup/nearby/stream/"
WORMHOLE_API_URL = "https://play.textspaced.com/api/lookup/nearby/wormholes/"
STRUCTURES_API_URL = "https://play.textspaced.com/api/system/structures/"
CURRENT_SYSTEM_API_URL = "https://play.textspaced.com/api/system/"
FACTION_API_URL = "https://play.textspaced.com/api/faction/info/"

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
    # This function is now only for local development.
    # The initial setup on Render is handled by the first deployment.
    if DATABASE_URL: return
    
    conn, cursor = get_db_connection()
    try:
        cursor.execute("SELECT id FROM users LIMIT 1")
        print("Database tables already exist.")
        conn.close()
        return
    except sqlite3.OperationalError:
        print("Database tables not found. Creating schema...")
        conn.rollback()
    
    user_id_type = 'INTEGER PRIMARY KEY AUTOINCREMENT'
    faction_id_type = 'INTEGER PRIMARY KEY AUTOINCREMENT'

    cursor.execute(f'CREATE TABLE factions (id {faction_id_type}, name TEXT UNIQUE NOT NULL)')
    cursor.execute(f'''
    CREATE TABLE users (
        id {user_id_type},
        username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, api_key TEXT,
        faction_id INTEGER NOT NULL REFERENCES factions(id),
        is_admin BOOLEAN DEFAULT 0 NOT NULL,
        is_developer BOOLEAN DEFAULT 0 NOT NULL
    )''')
    cursor.execute('CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, position REAL NOT NULL UNIQUE, catapult_radius REAL DEFAULT 0)')
    cursor.execute('CREATE TABLE faction_discovered_systems (faction_id INTEGER NOT NULL REFERENCES factions(id), system_id INTEGER NOT NULL REFERENCES systems(id), PRIMARY KEY (faction_id, system_id))')
    cursor.execute('CREATE TABLE wormholes (system_a_id INTEGER NOT NULL REFERENCES systems(id), system_b_id INTEGER NOT NULL REFERENCES systems(id), PRIMARY KEY (system_a_id, system_b_id))')
    
    conn.commit()
    conn.close()
    print("Database schema created.")

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

# --- DATA SYNC ---
def sync_faction_database(current_system_data, systems_data, wormholes_data, structures_data, faction_id):
    conn, cursor = get_db_connection(); pg_compat = bool(DATABASE_URL); param = '%s' if pg_compat else '?'
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
    if not all_systems: conn.close(); return
    
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
    
    faction_systems_to_link = [(faction_id, sys_id) for sys_id in all_systems.keys()]
    if pg_compat: cursor.executemany(f'INSERT INTO faction_discovered_systems (faction_id, system_id) VALUES ({param}, {param}) ON CONFLICT DO NOTHING', faction_systems_to_link)
    else: cursor.executemany('INSERT OR IGNORE INTO faction_discovered_systems (faction_id, system_id) VALUES (?, ?)', faction_systems_to_link)
    
    if wormholes_data and 'stable' in wormholes_data:
        stable_wormholes = wormholes_data['stable'].values() if isinstance(wormholes_data['stable'], dict) else wormholes_data['stable']
        wormholes_to_insert = [(min(wh['from_system_id'], wh['to_system_id']), max(wh['from_system_id'], wh['to_system_id'])) for wh in stable_wormholes]
        if pg_compat: cursor.executemany(f'INSERT INTO wormholes (system_a_id, system_b_id) VALUES ({param}, {param}) ON CONFLICT DO NOTHING', wormholes_to_insert)
        else: cursor.executemany('INSERT OR IGNORE INTO wormholes (system_a_id, system_b_id) VALUES (?, ?)', wormholes_to_insert)
    conn.commit(); conn.close()

# --- ROUTES ---
@app.route('/api/sync', methods=['POST'])
def sync_data():
    if 'user_id' not in session or session.get('is_developer'): return jsonify({'error': 'Not authenticated or developer accounts cannot sync'}), 401
    user_id = session['user_id']; conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?'; cursor.execute(f"SELECT api_key, faction_id FROM users WHERE id = {param}", (user_id,)); user = cursor.fetchone(); conn.close()
    if not user or not user['api_key']: return jsonify({'message': 'API key not found.'}), 400
    faction_info = fetch_api_data(FACTION_API_URL, user['api_key']); faction_name = faction_info.get('info', {}).get('name')
    if not faction_name: return jsonify({'message': 'Could not verify faction.'}), 500
    conn, cursor = get_db_connection(); cursor.execute(f"SELECT id FROM factions WHERE name = {param}", (faction_name,)); faction_row = cursor.fetchone()
    if faction_row: faction_id = faction_row['id']
    else:
        if bool(DATABASE_URL): cursor.execute(f"INSERT INTO factions (name) VALUES ({param}) RETURNING id", (faction_name,)); faction_id = cursor.fetchone()['id']
        else: cursor.execute("INSERT INTO factions (name) VALUES (?)", (faction_name,)); faction_id = cursor.lastrowid
        conn.commit()
    if user['faction_id'] != faction_id: cursor.execute(f"UPDATE users SET faction_id = {param} WHERE id = {param}", (faction_id, user_id)); conn.commit(); session['faction_id'] = faction_id
    conn.close()
    data_sources = [fetch_api_data(url, user['api_key']) for url in [CURRENT_SYSTEM_API_URL, SYSTEMS_API_URL, WORMHOLE_API_URL, STRUCTURES_API_URL]]
    if any(data_sources):
        sync_faction_database(*data_sources, faction_id)
        return jsonify({'message': 'Sync successful!'})
    else: return jsonify({'message': 'Failed to fetch data.'}), 500

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json(); username, password, api_key = data.get('username'), data.get('password'), data.get('api_key')
    conn, cursor = get_db_connection(); pg_compat = bool(DATABASE_URL); param = '%s' if pg_compat else '?'
    
    is_developer_account = not api_key
    if not username or not password or (not is_developer_account and not api_key):
        return jsonify({'message': 'Username, password, and API key are required for normal users.'}), 400
    
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
        
        if pg_compat:
            cursor.execute(f"INSERT INTO users (username, password, api_key, faction_id, is_admin, is_developer) VALUES ({param}, {param}, {param}, {param}, {param}, {param}) RETURNING id", (username, password, api_key or None, faction_id, is_admin_flag, is_developer_account))
            user_id = cursor.fetchone()['id']
        else:
            cursor.execute("INSERT INTO users (username, password, api_key, faction_id, is_admin, is_developer) VALUES (?, ?, ?, ?, ?, ?)", (username, password, api_key or None, faction_id, is_admin_flag, is_developer_account))
            user_id = cursor.lastrowid
        
        conn.commit(); session['user_id'], session['username'], session['faction_id'], session['is_admin'], session['is_developer'] = user_id, username, faction_id, is_admin_flag, is_developer_account
        return jsonify({'message': 'Registration successful'}), 201
    except (sqlite3.IntegrityError, psycopg2.IntegrityError): return jsonify({'message': 'Username already exists.'}), 409
    finally: conn.close()

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(); username, password = data.get('username'), data.get('password')
    conn, cursor = get_db_connection(); cursor.execute(f"SELECT * FROM users WHERE username = {'%s' if bool(DATABASE_URL) else '?'}", (username,)); user = cursor.fetchone(); conn.close()
    if user and user['password'] == password:
        session['user_id'], session['username'], session['faction_id'], session['is_admin'], session['is_developer'] = user['id'], user['username'], user['faction_id'], user['is_admin'], user['is_developer']
        return jsonify({'message': 'Login successful', 'username': user['username'], 'is_admin': user['is_admin'], 'is_developer': user['is_developer']})
    return jsonify({'message': 'Invalid username or password'}), 401

@app.route('/')
def serve_index(): return send_from_directory(STATIC_DIR, 'index.html')
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
        return jsonify(dict(user) if user else {})
    elif request.method == 'POST':
        data = request.get_json(); updates, params = [], []
        if data.get('api_key'): updates.append("api_key = %s"); params.append(data.get('api_key'))
        if data.get('password'): updates.append("password = %s"); params.append(data.get('password'))
        if not updates: return jsonify({'message': 'No changes provided.'}), 400
        params.append(user_id); query = f"UPDATE users SET {', '.join(updates)} WHERE id = {param}"
        cursor.execute(query, tuple(params)); conn.commit(); conn.close()
        return jsonify({'message': 'Profile updated successfully.'})

@app.route('/api/admin/systems')
@admin_required
def get_all_systems():
    conn, cursor = get_db_connection(); cursor.execute('SELECT id, name, position, catapult_radius FROM systems ORDER BY position ASC'); systems_list = cursor.fetchall(); conn.close()
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
        cursor.execute('SELECT s.id, s.name, s.x, s.y, s.position, s.catapult_radius FROM systems s')
    else:
        faction_id = session['faction_id']
        cursor.execute(f'SELECT s.id, s.name, s.x, s.y, s.position, s.catapult_radius FROM systems s JOIN faction_discovered_systems fds ON s.id = fds.system_id WHERE fds.faction_id = {param}', (faction_id,))
    
    systems_list = cursor.fetchall(); systems_dict = {row['id']: dict(row) for row in systems_list}
    cursor.execute('SELECT system_a_id, system_b_id FROM wormholes'); all_wormholes = cursor.fetchall()
    system_ids = set(systems_dict.keys())
    visible_wormholes = [(wh['system_a_id'], wh['system_b_id']) for wh in all_wormholes if wh['system_a_id'] in system_ids and wh['system_b_id'] in system_ids]
    conn.close()
    return jsonify({'systems': systems_dict, 'wormholes': visible_wormholes})

@app.route('/api/path', methods=['POST'])
def calculate_path():
    if 'user_id' not in session: return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json(); start_id, end_id = data.get('start_id'), data.get('end_id')
    if not start_id or not end_id: return jsonify({'error': 'start_id and end_id are required'}), 400
    conn, cursor = get_db_connection(); param = '%s' if bool(DATABASE_URL) else '?'

    if session.get('is_developer'):
        cursor.execute('SELECT id, position, catapult_radius FROM systems')
    else:
        faction_id = session['faction_id']
        cursor.execute(f'SELECT s.id, s.position, s.catapult_radius FROM systems s JOIN faction_discovered_systems fds ON s.id = fds.system_id WHERE fds.faction_id = {param}', (faction_id,))
    
    all_systems = cursor.fetchall()
    cursor.execute('SELECT system_a_id, system_b_id FROM wormholes'); all_wormholes = cursor.fetchall(); conn.close()
    if not all_systems: return jsonify({'path': [], 'distance': None})
    systems_map = {str(r['id']): {'position': r['position'], 'radius': r['catapult_radius']} for r in all_systems}
    
    wormhole_pairs = {tuple(sorted((str(wh['system_a_id']), str(wh['system_b_id'])))) for wh in all_wormholes}
    distances = {sys_id: float('inf') for sys_id in systems_map}; predecessors = {sys_id: (None, None) for sys_id in systems_map}
    if start_id not in systems_map: return jsonify({'error': 'Start system not in your faction map'}), 404
    distances[start_id] = 0; pq = [(0, start_id)]
    while pq:
        current_distance, current_id = heapq.heappop(pq)
        if current_distance > distances[current_id]: continue
        if current_id == end_id: break
        for neighbor_id in systems_map:
            if neighbor_id == current_id: continue
            sublight_dist = abs(systems_map[current_id]['position'] - systems_map[neighbor_id]['position'])
            if current_distance + sublight_dist < distances[neighbor_id]:
                distances[neighbor_id] = current_distance + sublight_dist; predecessors[neighbor_id] = (current_id, 'sublight'); heapq.heappush(pq, (distances[neighbor_id], neighbor_id))
            id_pair = tuple(sorted((current_id, neighbor_id)))
            if id_pair in wormhole_pairs:
                if current_distance < distances[neighbor_id]:
                    distances[neighbor_id] = current_distance; predecessors[neighbor_id] = (current_id, 'wormhole'); heapq.heappush(pq, (distances[neighbor_id], neighbor_id))
            current_sys_info = systems_map[current_id]
            if current_sys_info['radius'] > 0 and abs(current_sys_info['position'] - systems_map[neighbor_id]['position']) <= current_sys_info['radius']:
                if current_distance < distances[neighbor_id]:
                    distances[neighbor_id] = current_distance; predecessors[neighbor_id] = (current_id, 'catapult'); heapq.heappush(pq, (distances[neighbor_id], neighbor_id))
    full_path_ids, current_id, total_distance = [], end_id, distances.get(end_id)
    if total_distance is None or total_distance == float('inf'): return jsonify({'path': [], 'distance': None})
    while current_id: full_path_ids.append(current_id); current_id, _ = predecessors.get(current_id, (None, None))
    full_path_ids.reverse()
    if not full_path_ids or full_path_ids[0] != start_id: return jsonify({'path': [], 'distance': None})
    if len(full_path_ids) <= 1: return jsonify({'path': full_path_ids, 'simple_path': [], 'distance': total_distance})
    simple_path = []; current_leg_start_id = full_path_ids[0]; _, current_method = predecessors[full_path_ids[1]]
    for i in range(1, len(full_path_ids)):
        _, step_method = predecessors[full_path_ids[i]]
        if step_method != current_method:
            simple_path.append({'from_id': current_leg_start_id, 'to_id': full_path_ids[i-1], 'method': current_method})
            current_leg_start_id = full_path_ids[i-1]; current_method = step_method
    simple_path.append({'from_id': current_leg_start_id, 'to_id': full_path_ids[-1], 'method': current_method})
    return jsonify({'path': full_path_ids, 'simple_path': simple_path, 'distance': total_distance})

# This call ensures the database is set up when the app starts.
setup_database_if_needed()

if __name__ == '__main__':
    app.run(debug=True, port=5000)

