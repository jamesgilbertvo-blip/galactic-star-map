import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
import getpass
import os
import sys
import requests

# --- CONFIGURATION ---
DATABASE_URL = os.environ.get('DATABASE_URL')
FACTION_API_URL = "https://play.textspaced.com/api/faction/info/"

def get_db_connection():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
        return conn, conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn = sqlite3.connect('starmap.db')
        conn.row_factory = sqlite3.Row
        return conn, conn.cursor()

def fetch_api_data(url, api_key):
    if not api_key: return None
    headers = {'Authorization': f'Bearer {api_key}', 'Accept': 'application/json'}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException: return None

def add_user():
    print("--- Add New User ---")
    try:
        username = input("Enter a username: ").strip()
        password = getpass.getpass("Enter a password: ").strip()
        api_key = input(f"Enter the API key for {username}: ").strip()

        if not all([username, password, api_key]):
            print("\nError: Username, password, and API key cannot be empty.")
            return

        faction_info = fetch_api_data(FACTION_API_URL, api_key)
        faction_name = faction_info.get('info', {}).get('name')
        if not faction_name:
            print("\n❌ Error: Could not verify your faction with the provided API key.")
            return

        conn, cursor = get_db_connection()
        pg_compat = bool(DATABASE_URL)
        param = '%s' if pg_compat else '?'

        cursor.execute(f"SELECT id FROM factions WHERE name = {param}", (faction_name,))
        faction = cursor.fetchone()
        if faction:
            faction_id = faction['id']
        else:
            if pg_compat:
                cursor.execute(f"INSERT INTO factions (name) VALUES ({param}) RETURNING id", (faction_name,))
                faction_id = cursor.fetchone()['id']
            else:
                cursor.execute(f"INSERT INTO factions (name) VALUES ({param})", (faction_name,))
                faction_id = cursor.lastrowid
        
        if pg_compat:
            cursor.execute(f"INSERT INTO users (username, password, api_key, faction_id) VALUES ({param}, {param}, {param}, {param})", (username, password, api_key, faction_id))
        else:
            cursor.execute("INSERT INTO users (username, password, api_key, faction_id) VALUES (?, ?, ?, ?)", (username, password, api_key, faction_id))

        conn.commit()
        conn.close()

        print(f"\n✅ Success! User '{username}' has been added to faction '{faction_name}'.")

    except (sqlite3.IntegrityError, psycopg2.IntegrityError):
        print(f"\n❌ Error: The username '{username}' already exists.")
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")

if __name__ == "__main__":
    add_user()

