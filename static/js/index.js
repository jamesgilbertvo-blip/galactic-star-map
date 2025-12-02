/**
 * Main Application Entry Point
 * Ties together API, UI, Map Rendering, and Map Controls.
 */

import * as API from './api.js';
import * as UI from './ui.js';
import * as MapRenderer from './mapRenderer.js';
import * as MapControls from './mapControls.js';

// --- Central State ---
const state = {
    systems: {},
    wormholes: [],
    intelMarkers: [],
    
    // View State
    viewTransform: { scale: 1, translateX: 0, translateY: 0 },
    
    // Pathfinding State
    pathNodes: [],
    pathLegs: [],
    
    // Interaction State
    hoveredSystem: null,
    highlightedId: null,
    toggledIds: new Set(),
    newlySyncedIds: new Set(),
    
    // Animation State
    pingAnimation: null,
    
    // Route Planner State
    activeRouteInput: null,

    // Intel Context State
    pendingIntelCoords: null
};

// --- Settings ---
const settings = {
    showCatapults: true,
    showWormholes: true,
    showUnclaimed: false,
    avoidSlow: false,
    avoidHostile: false
};

// --- Initialization ---

document.addEventListener('DOMContentLoaded', () => {
    // 1. Restore View
    try {
        const saved = localStorage.getItem('mapViewTransform');
        if (saved) state.viewTransform = JSON.parse(saved);
    } catch (e) { console.error("Error loading view state", e); }

    // 2. Setup UI Listeners
    setupGlobalListeners();

    // 3. Setup Map Canvas
    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();

    // 4. Check Login & Start
    checkLogin();
});

// --- Listener Setup ---

function setupGlobalListeners() {
    // Simple UI Toggles
    UI.setupSimpleUIListeners({
        onInputFocus: (input) => { state.activeRouteInput = input; },
        onClearRoute: () => {
            state.pathNodes = [];
            state.pathLegs = [];
            UI.clearRouteDisplay();
            draw();
        }
    });

    // --- LOGIN FORM (Moved here so it works when logged out) ---
    UI.elements.loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const user = UI.elements.loginForm.username.value;
        const pass = UI.elements.loginForm.password.value;
        try {
            const res = await API.login(user, pass);
            const data = await res.json();
            if (res.ok) {
                UI.showMap(data);
                await loadMapData(false);
                setupMapInteractions(); // Initialize map controls
            } else {
                UI.elements.loginError.textContent = data.message;
            }
        } catch (err) { UI.elements.loginError.textContent = "Connection failed."; }
    });

    // --- REGISTER FORM (Added back) ---
    UI.elements.registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            username: UI.elements.registerForm.username.value,
            password: UI.elements.registerForm.password.value,
            api_key: UI.elements.registerForm.api_key.value
        };
        try {
            const res = await API.register(payload);
            const data = await res.json();
            if (res.ok) {
                UI.showMap(data);
                // New user needs a fresh sync or initial data
                draw(); 
                setupMapInteractions();
            } else {
                UI.elements.registerError.textContent = data.message;
            }
        } catch (err) { UI.elements.registerError.textContent = "Connection failed."; }
    });
}

// --- Core Functions ---

function draw() {
    const ctx = UI.elements.canvas.getContext('2d');
    MapRenderer.drawMap(
        ctx, 
        UI.elements.canvas, 
        state.viewTransform, 
        { systems: state.systems, wormholes: state.wormholes, intelMarkers: state.intelMarkers }, 
        state, 
        settings
    );
}

function resizeCanvas() {
    if (UI.elements.canvas.parentElement.clientWidth > 0) {
        UI.elements.canvas.width = UI.elements.canvas.parentElement.clientWidth;
        UI.elements.canvas.height = UI.elements.canvas.parentElement.clientHeight;
        draw();
    }
}

async function checkLogin() {
    try {
        const res = await API.checkStatus();
        const data = await res.json();
        if (data.logged_in) {
            UI.showMap(data);
            await loadMapData(false); 
            setupMapInteractions();
        } else {
            UI.showLogin();
        }
    } catch (e) {
        console.error("Login check failed", e);
        UI.showLogin();
    }
}

async function loadMapData(shouldFit = true, oldSystemIds = null) {
    try {
        const [sysRes, intelRes] = await Promise.all([
            API.getSystems(),
            API.getIntel()
        ]);

        if (sysRes.status === 401) { window.location.reload(); return; }
        
        const sysData = await sysRes.json();
        state.systems = sysData.systems;
        state.wormholes = sysData.wormholes;

        if (intelRes.ok) {
            state.intelMarkers = await intelRes.json();
        }

        UI.populateSystemList(state.systems);

        if (oldSystemIds) {
            state.newlySyncedIds.clear();
            Object.keys(state.systems).forEach(id => {
                if (!oldSystemIds.has(id)) state.newlySyncedIds.add(id);
            });
            if (state.newlySyncedIds.size > 0) {
                setTimeout(() => {
                    state.newlySyncedIds.clear();
                    draw();
                }, 2000);
            }
        }

        if (shouldFit) fitMapToView();
        draw();

    } catch (e) {
        console.error("Failed to load map data:", e);
    }
}

function fitMapToView() {
    if (Object.keys(state.systems).length === 0) return;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    Object.values(state.systems).forEach(s => {
        if (typeof s.x === 'number') {
            minX = Math.min(minX, s.x); maxX = Math.max(maxX, s.x);
            minY = Math.min(minY, s.y); maxY = Math.max(maxY, s.y);
        }
    });
    if (!isFinite(minX)) return;
    
    const mapW = maxX - minX || 1;
    const mapH = maxY - minY || 1;
    const mapCX = minX + mapW / 2;
    const mapCY = minY + mapH / 2;
    
    const scale = Math.min(
        UI.elements.canvas.width / (mapW * 1.2), 
        UI.elements.canvas.height / (mapH * 1.2)
    ) || 1;

    state.viewTransform = {
        scale,
        translateX: (UI.elements.canvas.width / 2) - (mapCX * scale),
        translateY: (UI.elements.canvas.height / 2) - (mapCY * scale)
    };
    localStorage.setItem('mapViewTransform', JSON.stringify(state.viewTransform));
    draw();
}

// --- Interaction Setup ---

function setupMapInteractions() {
    // Only set up map controls once logged in
    MapControls.setupMapInteractions(UI.elements.canvas, { systems: state.systems, intelMarkers: state.intelMarkers }, state, settings, {
        draw: draw,
        onSystemSelect: (system) => {
            if (state.activeRouteInput) {
                const sysPosStr = state.systems[system.id]?.position;
                if (system.name.startsWith("System ") && sysPosStr) {
                    state.activeRouteInput.value = `#${sysPosStr}`;
                } else {
                    state.activeRouteInput.value = system.name;
                }
                // Auto-advance focus
                if (state.activeRouteInput === UI.elements.startSystemInput) UI.elements.endSystemInput.focus();
                else UI.elements.routeForm.querySelector('button[type="submit"]').focus();
                
                state.activeRouteInput = null; 
            }
        },
        onContextMenu: (screenX, screenY, worldX, worldY, existingMarker) => {
            state.pendingIntelCoords = existingMarker ? existingMarker : { x: worldX, y: worldY };
            
            if (!existingMarker) {
                let nearest = null, minDist = Infinity;
                Object.values(state.systems).forEach(s => {
                    const d = Math.hypot(worldX - s.x, worldY - s.y);
                    if (d < minDist) { minDist = d; nearest = s; }
                });
                if (nearest && minDist < (10/state.viewTransform.scale)) {
                    state.pendingIntelCoords.system_id = nearest.id;
                }
            }
            UI.openIntelMenu(screenX, screenY, { x: worldX, y: worldY }, existingMarker);
        },
        closeContextMenu: () => UI.closeIntelMenu()
    });

    // Sync Button
    UI.elements.syncButton.addEventListener('click', async () => {
        const oldIds = new Set(Object.keys(state.systems));
        UI.elements.syncStatus.textContent = "Syncing...";
        UI.elements.syncButton.disabled = true;
        try {
            const res = await API.syncMap();
            const data = await res.json();
            UI.elements.syncStatus.textContent = data.message || data.error;
            if (res.ok) {
                const statusRes = await API.checkStatus();
                const statusData = await statusRes.json();
                await loadMapData(false, oldIds);
            }
        } catch (e) {
            UI.elements.syncStatus.textContent = "Error syncing.";
        } finally {
            UI.elements.syncButton.disabled = false;
            setTimeout(() => UI.elements.syncStatus.textContent = '', 5000);
        }
    });

    // Route Calculation
    UI.elements.routeForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        await handlePathfinding();
    });

    // Filters
    const updateFilters = () => {
        settings.showCatapults = UI.elements.filterCatapults.checked;
        settings.showWormholes = UI.elements.filterWormholes.checked;
        settings.showUnclaimed = UI.elements.toggleUnclaimedNames.checked;
        settings.avoidSlow = UI.elements.filterAvoidSlow.checked;
        settings.avoidHostile = UI.elements.filterAvoidHostile.checked;
        draw();
    };
    UI.elements.filterCatapults.addEventListener('change', updateFilters);
    UI.elements.filterWormholes.addEventListener('change', updateFilters);
    UI.elements.toggleUnclaimedNames.addEventListener('change', updateFilters);
    UI.elements.filterAvoidSlow.addEventListener('change', updateFilters);
    UI.elements.filterAvoidHostile.addEventListener('change', updateFilters);

    // Intel Actions
    UI.elements.saveIntelBtn.addEventListener('click', async () => {
        if (!state.pendingIntelCoords) return; 
        const type = UI.elements.intelTypeInput.value;
        const note = UI.elements.intelNoteInput.value;

        try {
            const res = await API.createIntel({
                x: state.pendingIntelCoords.x,
                y: state.pendingIntelCoords.y,
                system_id: state.pendingIntelCoords.system_id,
                type,
                note
            });
            if (res.ok) {
                UI.closeIntelMenu();
                await loadMapData(false); 
            } else {
                alert("Failed to save.");
            }
        } catch (e) { console.error(e); }
    });

    UI.elements.deleteIntelBtn.addEventListener('click', async () => {
        if (!state.pendingIntelCoords || !state.pendingIntelCoords.id) return;
        if (!confirm("Delete marker?")) return;
        
        try {
            const res = await API.deleteIntel(state.pendingIntelCoords.id);
            if (res.ok) {
                UI.closeIntelMenu();
                await loadMapData(false); 
            }
        } catch (e) { console.error(e); }
    });

    // Center On Me
    UI.elements.centerMeButton.addEventListener('click', async () => {
        const res = await API.checkStatus();
        const d = await res.json();
        if (d.last_known_system_id && state.systems[d.last_known_system_id]) {
            MapControls.centerOnLocationWithPing(UI.elements.canvas, state, state.systems[d.last_known_system_id], { draw });
        } else {
            alert("Location unknown. Please sync.");
        }
    });

    // Search
    UI.elements.searchForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const query = UI.elements.searchForm.querySelector('input').value.trim().toLowerCase();
        const found = Object.values(state.systems).find(s => 
            (s.name && s.name.toLowerCase() === query) || 
            (s.position && `#${s.position}` === query)
        );
        if (found) {
            MapControls.centerOnSystem(UI.elements.canvas, state, found, { draw });
        } else {
            alert("System not found.");
        }
    });
}

// --- Pathfinding ---
async function handlePathfinding() {
    const startVal = UI.elements.startSystemInput.value.trim();
    const endVal = UI.elements.endSystemInput.value.trim();
    const waypoints = [];
    UI.elements.waypointsContainer.querySelectorAll('input').forEach(inp => {
        if(inp.value.trim()) waypoints.push(inp.value.trim());
    });

    if (!startVal || !endVal) {
        UI.elements.routeDetailsContainer.innerHTML = "Please define Start and End.";
        return;
    }

    const stops = [startVal, ...waypoints, endVal];
    UI.elements.routeDetailsContainer.innerHTML = "Calculating...";

    try {
        const parseInput = (val) => {
             if (val.match(/^#\d+(\.\d+)?$/)) { 
                 const pos = parseFloat(val.substring(1)); 
                 return !isNaN(pos) ? `pos:${pos}` : null; 
             }
             const system = Object.values(state.systems).find(s => 
                 (s.name && s.name.toLowerCase() === val.toLowerCase()) || 
                 (s.position && `#${s.position}` === val)
             );
             return system ? `sys:${system.id}` : null;
        };

        const requests = [];
        for (let i = 0; i < stops.length - 1; i++) {
            const sId = parseInput(stops[i]);
            const eId = parseInput(stops[i+1]);
            if (!sId || !eId) throw new Error("Invalid system.");
            requests.push(API.calculatePath(sId, eId, settings.avoidSlow, settings.avoidHostile));
        }

        const responses = await Promise.all(requests);
        let combinedPathNodes = [];
        let combinedPathLegs = [];
        let totalDist = 0;

        for (const r of responses) {
            const d = await r.json();
            if (!r.ok || d.distance === null) throw new Error("Path calculation failed.");
            totalDist += d.distance;
            combinedPathNodes = combinedPathNodes.concat(d.path);
            combinedPathLegs = combinedPathLegs.concat(d.detailed_path);
        }

        state.pathNodes = combinedPathNodes;
        state.pathLegs = combinedPathLegs;

        UI.displayRouteResults({
            distance: totalDist,
            path: combinedPathNodes,
            detailed_path: combinedPathLegs
        }, stops, state.systems); 

        draw(); 
    } catch (e) {
        UI.elements.routeDetailsContainer.innerHTML = "Route failed: " + e.message;
    }
}