/**
 * API Module
 * Handles all communication with the backend server.
 */

// Internal helper for consistent fetch options
const apiFetch = async (url, options = {}) => {
    options.credentials = 'include';
    return fetch(url, options);
};

// --- Authentication ---

export const login = async (username, password) => {
    return apiFetch('/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
    });
};

export const register = async (payload) => {
    // payload: { username, password, api_key }
    return apiFetch('/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
};

export const logout = async () => {
    return apiFetch('/logout', { method: 'POST' });
};

export const checkStatus = async () => {
    return apiFetch('/status');
};

// --- Data Syncing ---

export const syncMap = async () => {
    return apiFetch('/api/sync', { method: 'POST' });
};

export const bulkSyncFaction = async () => {
    return apiFetch('/api/bulk_sync_faction_systems', { method: 'POST' });
};

// --- User Profile ---

export const getProfile = async () => {
    return apiFetch('/api/profile');
};

export const updateProfile = async (payload) => {
    // payload: { api_key, password }
    return apiFetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
};

// --- Map Data ---

export const getSystems = async () => {
    return apiFetch('/api/systems');
};

// --- Intel Markers ---

export const getIntel = async () => {
    return apiFetch('/api/intel');
};

export const createIntel = async (payload) => {
    // payload: { x, y, system_id, type, note }
    return apiFetch('/api/intel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
};

export const deleteIntel = async (id) => {
    return apiFetch('/api/intel', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id })
    });
};

// --- Pathfinding ---

export const calculatePath = async (startId, endId, avoidSlow, avoidHostile) => {
    return apiFetch('/api/path', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            start_id: startId,
            end_id: endId,
            avoid_slow_regions: avoidSlow,
            avoid_hostile: avoidHostile
        })
    });
};