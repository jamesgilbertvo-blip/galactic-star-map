/**
 * UI Module
 * Handles DOM manipulation, view switching, and HTML updates.
 */

// Cache DOM elements for performance
export const elements = {
    loginView: document.getElementById('login-view'),
    registerView: document.getElementById('register-view'),
    mapView: document.getElementById('map-view'),
    profileView: document.getElementById('profile-view'),
    
    loginForm: document.getElementById('login-form'),
    registerForm: document.getElementById('register-form'),
    profileForm: document.getElementById('profile-form'),
    routeForm: document.getElementById('route-form'),
    searchForm: document.getElementById('search-form'),
    
    canvas: document.getElementById('map-canvas'),
    
    loginError: document.getElementById('login-error'),
    registerError: document.getElementById('register-error'),
    profileStatus: document.getElementById('profile-status'),
    syncStatus: document.getElementById('sync-status'),
    welcomeMessage: document.getElementById('welcome-message'),
    
    logoutButton: document.getElementById('logout-button'),
    syncButton: document.getElementById('sync-button'),
    syncContainer: document.getElementById('sync-container'),
    profileButton: document.getElementById('profile-button'),
    closeProfileButton: document.getElementById('close-profile-button'),
    bulkSyncButton: document.getElementById('bulk-sync-button'),
    bulkSyncText: document.getElementById('bulk-sync-text'),
    menuButton: document.getElementById('menu-button'),
    centerMeButton: document.getElementById('center-me-button'),
    resetViewButton: document.getElementById('reset-view-button'),
    
    startSystemInput: document.getElementById('start-system-input'),
    endSystemInput: document.getElementById('end-system-input'),
    waypointsContainer: document.getElementById('waypoints-container'),
    addWaypointBtn: document.getElementById('add-waypoint-btn'),
    systemDataList: document.getElementById('system-list'),
    routeDetailsContainer: document.getElementById('route-details'),
    
    // Filters & Options
    filterCatapults: document.getElementById('filter-catapults'),
    filterWormholes: document.getElementById('filter-wormholes'),
    filterAvoidSlow: document.getElementById('filter-avoid-slow'),
    filterAvoidHostile: document.getElementById('filter-avoid-hostile'),
    toggleUnclaimedNames: document.getElementById('toggle-unclaimed-names'),
    
    // Profile Inputs
    apiKeyInput: document.getElementById('api-key-input'),
    newPasswordInput: document.getElementById('new-password-input'),
    
    // User Controls Container
    userControls: document.getElementById('user-controls'),
    sidePanel: document.getElementById('side-panel'),

    // Intel Context Menu
    intelContextMenu: document.getElementById('intel-context-menu'),
    intelMenuTitle: document.getElementById('intel-menu-title'),
    intelCoordsDisplay: document.getElementById('intel-coords-display'),
    intelTypeInput: document.getElementById('intel-type-input'),
    intelNoteInput: document.getElementById('intel-note-input'),
    cancelIntelBtn: document.getElementById('cancel-intel-btn'),
    saveIntelBtn: document.getElementById('save-intel-btn'),
    deleteIntelBtn: document.getElementById('delete-intel-btn')
};

// --- View Management ---

export const showLogin = () => {
    elements.mapView.classList.add('hidden');
    elements.registerView.classList.add('hidden');
    elements.loginView.classList.remove('hidden');
};

export const showRegister = () => {
    elements.mapView.classList.add('hidden');
    elements.loginView.classList.add('hidden');
    elements.registerView.classList.remove('hidden');
};

export const showMap = (userData) => {
    elements.loginView.classList.add('hidden');
    elements.registerView.classList.add('hidden');
    elements.mapView.classList.remove('hidden');
    
    elements.welcomeMessage.textContent = `Welcome, ${userData.username}`;
    
    // Handle Admin Button
    let adminBtn = document.getElementById('admin-button');
    if (userData.is_admin && !adminBtn) {
        adminBtn = document.createElement('a');
        adminBtn.id = 'admin-button';
        adminBtn.href = '/admin';
        adminBtn.textContent = 'Admin';
        adminBtn.className = 'px-3 py-1 text-sm font-medium text-white bg-purple-600 rounded-md hover:bg-purple-700';
        elements.userControls.prepend(adminBtn);
    } else if (!userData.is_admin && adminBtn) {
        adminBtn.remove();
    }

    // Handle Developer Mode (Hide Sync)
    if (userData.is_developer) {
        elements.syncContainer.classList.add('hidden');
    } else {
        elements.syncContainer.classList.remove('hidden');
    }
};

export const toggleSidePanel = () => {
    const isExpanded = elements.menuButton.getAttribute('aria-expanded') === 'true';
    elements.sidePanel.classList.toggle('-translate-x-full');
    elements.menuButton.setAttribute('aria-expanded', !isExpanded);
};

// --- Profile Modal ---

export const openProfile = (apiKeySet, showBulkSync) => {
    elements.profileStatus.textContent = '';
    elements.newPasswordInput.value = '';
    elements.apiKeyInput.value = apiKeySet ? '(Key is set and encrypted)' : '';
    elements.apiKeyInput.placeholder = apiKeySet ? 'Enter a new key to overwrite' : 'Enter your game API key';

    if (showBulkSync) {
        elements.bulkSyncButton.classList.remove('hidden');
        elements.bulkSyncText.classList.remove('hidden');
        elements.bulkSyncButton.disabled = false;
    } else {
        elements.bulkSyncButton.classList.add('hidden');
        elements.bulkSyncText.classList.add('hidden');
    }
    elements.profileView.classList.remove('hidden');
};

export const closeProfile = () => {
    elements.profileView.classList.add('hidden');
};

// --- Map Data Updates ---

export const populateSystemList = (systems) => {
    elements.systemDataList.innerHTML = '';
    const options = new Set();
    Object.values(systems).forEach(s => {
        if (s.name) options.add(s.name);
        if (s.position) options.add(`#${s.position}`);
    });
    Array.from(options).sort().forEach(val => {
        const o = document.createElement('option');
        o.value = val;
        elements.systemDataList.appendChild(o);
    });
};

// --- Intel Context Menu ---

export const openIntelMenu = (screenX, screenY, worldCoords, existingMarker = null) => {
    // Basic Positioning logic
    const menuWidth = 200;
    const menuHeight = 250;
    const screenW = window.innerWidth;
    const screenH = window.innerHeight;
    
    let left = screenX;
    let top = screenY;
    
    if (left + menuWidth > screenW) left = screenW - menuWidth - 10;
    if (top + menuHeight > screenH) top = screenH - menuHeight - 10;

    elements.intelContextMenu.style.left = `${left}px`;
    elements.intelContextMenu.style.top = `${top}px`;

    if (existingMarker) {
        // View/Delete Mode
        elements.intelMenuTitle.textContent = "Intel Details";
        elements.intelTypeInput.value = existingMarker.type;
        elements.intelTypeInput.disabled = true;
        elements.intelNoteInput.value = existingMarker.note || "";
        elements.intelNoteInput.disabled = true;
        
        elements.intelCoordsDisplay.textContent = `Coordinates: ${existingMarker.x.toFixed(0)}, ${existingMarker.y.toFixed(0)}`;
        
        elements.deleteIntelBtn.classList.remove('hidden');
        elements.saveIntelBtn.classList.add('hidden');
    } else {
        // Add Mode
        elements.intelMenuTitle.textContent = "Add Intel Marker";
        elements.intelTypeInput.value = "Mining Rich"; // Default
        elements.intelTypeInput.disabled = false;
        elements.intelNoteInput.value = "";
        elements.intelNoteInput.disabled = false;

        let coordText = `Coordinates: ${worldCoords.x.toFixed(0)}, ${worldCoords.y.toFixed(0)}`;
        if (worldCoords.system_id) {
             // Note: system name isn't passed here easily without lookups, simplified for refactor
             coordText += ` (Near System)`; 
        }
        elements.intelCoordsDisplay.textContent = coordText;

        elements.deleteIntelBtn.classList.add('hidden');
        elements.saveIntelBtn.classList.remove('hidden');
    }

    elements.intelContextMenu.classList.remove('hidden');
};

export const closeIntelMenu = () => {
    elements.intelContextMenu.classList.add('hidden');
};

// --- Route Planner ---

export const addWaypointInput = (focusListener) => {
    const div = document.createElement('div');
    div.className = 'relative flex items-center space-x-2';
    
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'route-input w-full bg-gray-700 border-gray-600 rounded-md py-2 px-3 text-white focus:outline-none focus:ring-indigo-500';
    input.placeholder = 'Waypoint...';
    input.setAttribute('list', 'system-list');
    
    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'text-red-400 hover:text-red-300';
    removeBtn.innerHTML = '&times;';
    removeBtn.title = 'Remove Waypoint';
    removeBtn.onclick = () => div.remove();

    div.appendChild(input);
    div.appendChild(removeBtn);
    elements.waypointsContainer.appendChild(div);
    
    if (focusListener) input.addEventListener('focus', () => focusListener(input));
};

export const displayRouteResults = (result, routeStopsInput, systems) => {
    const container = elements.routeDetailsContainer;
    container.innerHTML = '';

    const legs = result.detailed_path || [];
    
    // Clear inputs? No, keep them for editing.
    // But we might want to clear them if it was a fresh "click to map" action.
    // For now, let's replicate exact behavior: keep them.

    if (legs.length > 0 && result.distance != null) {
        // Summary Stats
        const counts = { sublight: 0, catapult: 0, catapult_sublight: 0, wormhole: 0 };
        legs.forEach(leg => {
            if (counts[leg.method] !== undefined) counts[leg.method]++;
            else counts.sublight++;
        });

        const summaryParts = [];
        if (counts.catapult > 0) summaryParts.push(`${counts.catapult} Catapult`);
        if (counts.catapult_sublight > 0) summaryParts.push(`${counts.catapult_sublight} Catapult+Sublight`);
        if (counts.wormhole > 0) summaryParts.push(`${counts.wormhole} Wormhole`);
        if (counts.sublight > 0) summaryParts.push(`${counts.sublight} Sublight`);
        const summaryString = `<strong>Total Jumps: ${legs.length}</strong> (${summaryParts.join(', ')})`;

        let titleText = "Route";
        if (routeStopsInput.length > 0) {
            titleText = `Route: ${routeStopsInput[0]} &rarr; ${routeStopsInput[routeStopsInput.length-1]}`;
        }

        // Build HTML
        let html = `<div class="flex justify-between items-center"><h2 class="text-lg font-semibold text-white truncate" title="${titleText}">${titleText}</h2><button id="clear-route-button" class="text-sm text-gray-400 hover:text-white focus:outline-none whitespace-nowrap ml-2">&times; Clear</button></div>`;
        html += `<p class="text-sm text-gray-400">Total Distance: ${result.distance.toFixed(2)}</p>`;
        html += `<p class="text-xs text-gray-500 mb-2">${summaryString}</p>`;
        html += `<ol class="mt-2 space-y-2 text-sm max-h-60 overflow-y-auto pr-2">`;

        // Helper to get name from ID
        const getName = (id) => {
            const sys = systems[id]; // Direct lookup if we have systems object passed in
            if (sys) return sys.name.startsWith("System ") ? `#${sys.position}` : sys.name;
            if (id.toString().startsWith('virtual')) return 'Virtual Node';
            return 'Unknown';
        };

        // Start Node
        if (legs.length > 0) {
             html += `<li class="text-gray-300">1. Start at: <span class="font-semibold text-white">${getName(legs[0].from_id)}</span></li>`;
        }

        legs.forEach((leg, index) => {
            let method = leg.method.charAt(0).toUpperCase() + leg.method.slice(1);
            let color = 'text-amber-400';
            if (leg.method === 'wormhole') { color = 'text-red-400'; method = 'Wormhole'; }
            else if (leg.method === 'catapult') { color = 'text-lime-400'; method = 'Catapult'; }
            else if (leg.method === 'catapult_sublight') { color = 'text-lime-400'; method = 'Catapult + Sublight'; }
            else { method = 'Sublight'; }

            html += `<li class="text-gray-300">${index + 2}. <span class="font-semibold ${color}">${method}</span> to <span class="font-semibold text-white">${getName(leg.to_id)}</span></li>`;
        });

        html += `</ol>`;
        container.innerHTML = html;
    } else {
        container.innerHTML = `<h2 class="text-lg font-semibold text-white">No Route Found</h2><p class="text-yellow-400">A path could not be found. Check inputs or adjust filters.</p>`;
    }
};

export const clearRouteDisplay = () => {
    elements.routeDetailsContainer.innerHTML = '';
    elements.startSystemInput.value = '';
    elements.endSystemInput.value = '';
    elements.waypointsContainer.innerHTML = '';
};

// --- Listener Setup ---
// Hooks up simple UI events (toggles, close buttons) that don't require deep logic.
// Complex logic (Forms, Map clicks) is handled in index.js

export const setupSimpleUIListeners = (callbacks) => {
    // Views
    document.getElementById('show-register-view-button').onclick = showRegister;
    document.getElementById('show-login-view-button').onclick = showLogin;
    
    // Panel
    elements.menuButton.onclick = toggleSidePanel;
    elements.closeProfileButton.onclick = closeProfile;
    
    // Waypoints
    elements.addWaypointBtn.onclick = () => addWaypointInput(callbacks.onInputFocus);
    
    // Focus listeners for start/end (for map click population)
    elements.startSystemInput.addEventListener('focus', () => callbacks.onInputFocus(elements.startSystemInput));
    elements.endSystemInput.addEventListener('focus', () => callbacks.onInputFocus(elements.endSystemInput));

    // Clear Route button (Dynamic, needs event delegation)
    elements.routeDetailsContainer.addEventListener('click', (e) => {
        if (e.target && e.target.id === 'clear-route-button') {
            callbacks.onClearRoute();
        }
    });
    
    // Intel Cancel
    elements.cancelIntelBtn.onclick = closeIntelMenu;
};