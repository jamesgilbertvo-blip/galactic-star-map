/**
 * Map Controls Module
 * Handles all mouse and touch interactions (pan, zoom, hover, click).
 */

let canvas;
let data; // systems, intelMarkers
let state; // viewTransform, pathNodes, hoveredSystem, highlightedId, toggledIds
let settings;
let callbacks;

let isPanning = false;
let lastPoint = { x: 0, y: 0 };
let pinchDistance = null;
let touchPoints = [];

// Utility to get coordinates, scaled by DPR to match the internal canvas resolution
const getEventCoordinates = (canvas, e) => {
    const rect = canvas.getBoundingClientRect();
    // Retrieve DPR here to scale CSS pixel coordinates to match internal canvas coordinates
    const dpr = window.devicePixelRatio || 1; 
    
    let x, y;
    if (e.touches && e.touches.length > 0) {
        x = e.touches[0].clientX - rect.left;
        y = e.touches[0].clientY - rect.top;
    } else {
        x = e.clientX - rect.left;
        y = e.clientY - rect.top;
    }
    
    // Scale the CSS pixel coordinates to match the internal canvas pixel coordinates
    return { x: x * dpr, y: y * dpr }; 
};

// Utility to convert canvas pixel coordinates to map world coordinates
const toWorldCoords = (screenX, screenY) => {
    return {
        x: (screenX / state.viewTransform.scale) - (state.viewTransform.translateX / state.viewTransform.scale),
        y: (screenY / state.viewTransform.scale) - (state.viewTransform.translateY / state.viewTransform.scale)
    };
};

const findSystemUnderCursor = (worldX, worldY, systems) => {
    let nearest = null;
    let minDistanceSq = Infinity;
    const clickToleranceSq = (10 / state.viewTransform.scale) ** 2; // Tolerance increases when zoomed out

    Object.values(systems).forEach(sys => {
        if (typeof sys.x === 'number' && typeof sys.y === 'number') {
            const dx = worldX - sys.x;
            const dy = worldY - sys.y;
            const distanceSq = dx * dx + dy * dy;

            if (distanceSq < clickToleranceSq && distanceSq < minDistanceSq) {
                minDistanceSq = distanceSq;
                nearest = sys;
            }
        }
    });
    return nearest;
};

// --- Event Handlers ---

const handleMouseDown = (e) => {
    e.preventDefault();
    if (e.button === 0) { // Left click
        isPanning = true;
        canvas.style.cursor = 'grabbing';
        lastPoint = getEventCoordinates(canvas, e);
    }
    if (e.button === 2) { // Right click (to show context menu)
        handleContextMenu(e);
    }
};

const handleMouseMove = (e) => {
    e.preventDefault();
    const currentPoint = getEventCoordinates(canvas, e);
    const worldCoords = toWorldCoords(currentPoint.x, currentPoint.y);
    
    // 1. Handle Panning
    if (isPanning) {
        state.viewTransform.translateX += (currentPoint.x - lastPoint.x);
        state.viewTransform.translateY += (currentPoint.y - lastPoint.y);
        lastPoint = currentPoint;
        callbacks.draw();
    } 
    
    // 2. Handle Hover/Tooltip (even when panning, for fluidity)
    const hovered = findSystemUnderCursor(worldCoords.x, worldCoords.y, data.systems);
    
    if (hovered && state.hoveredSystem !== hovered) {
        state.hoveredSystem = hovered;
        callbacks.draw();
        canvas.style.cursor = 'pointer';
    } else if (!hovered && state.hoveredSystem !== null) {
        state.hoveredSystem = null;
        callbacks.draw();
        if (!isPanning) canvas.style.cursor = 'grab';
    }

    // Close context menu if moving away
    if (state.pendingIntelCoords) {
        callbacks.closeContextMenu();
        state.pendingIntelCoords = null;
    }
};

const handleMouseUp = (e) => {
    e.preventDefault();
    if (e.button === 0) { // Left click release
        isPanning = false;
        canvas.style.cursor = state.hoveredSystem ? 'pointer' : 'grab';
    }
};

const handleMouseClick = (e) => {
    if (e.button !== 0 || isPanning) return; // Only process non-panning left clicks

    const point = getEventCoordinates(canvas, e);
    const worldCoords = toWorldCoords(point.x, point.y);
    const selected = findSystemUnderCursor(worldCoords.x, worldCoords.y, data.systems);

    if (selected) {
        // Shift+Click for range rings
        if (e.shiftKey) {
            const systemId = String(selected.id);
            if (state.toggledIds.has(systemId)) {
                state.toggledIds.delete(systemId);
            } else {
                state.toggledIds.add(systemId);
            }
        } else {
            // Regular click: Set system as highlighted and notify UI for route input
            state.highlightedId = selected.id;
            callbacks.onSystemSelect(selected);
        }
        state.hoveredSystem = null; // Clear hover state
        callbacks.draw();
    }
};

const handleWheel = (e) => {
    e.preventDefault();
    const delta = e.deltaY * -0.001; // Scale factor for zoom
    const zoomFactor = 1 + delta;

    const point = getEventCoordinates(canvas, e);
    const worldCoordsBefore = toWorldCoords(point.x, point.y);

    // Apply zoom
    state.viewTransform.scale *= zoomFactor;
    state.viewTransform.scale = Math.min(Math.max(state.viewTransform.scale, 0.05), 10); // Clamp zoom

    // Reposition to zoom around the cursor
    state.viewTransform.translateX = point.x - (worldCoordsBefore.x * state.viewTransform.scale);
    state.viewTransform.translateY = point.y - (worldCoordsBefore.y * state.viewTransform.scale);

    localStorage.setItem('mapViewTransform', JSON.stringify(state.viewTransform));
    callbacks.draw();
};

const handleContextMenu = (e) => {
    e.preventDefault();
    const point = getEventCoordinates(canvas, e);
    const worldCoords = toWorldCoords(point.x, point.y);
    
    // Check if the click landed on an existing Intel Marker
    const existingIntel = findIntelMarkerUnderCursor(worldCoords.x, worldCoords.y, data.intelMarkers);

    callbacks.onContextMenu(e.clientX, e.clientY, worldCoords.x, worldCoords.y, existingIntel);
};

const findIntelMarkerUnderCursor = (worldX, worldY, markers) => {
    let nearest = null;
    let minDistanceSq = Infinity;
    // Intel marker size is slightly larger than systems
    const clickToleranceSq = (15 / state.viewTransform.scale) ** 2;

    markers.forEach(marker => {
        if (typeof marker.x === 'number' && typeof marker.y === 'number') {
            const dx = worldX - marker.x;
            const dy = worldY - marker.y;
            const distanceSq = dx * dx + dy * dy;

            if (distanceSq < clickToleranceSq && distanceSq < minDistanceSq) {
                minDistanceSq = distanceSq;
                nearest = marker;
            }
        }
    });
    return nearest;
};

// --- Public Setup Function ---

export const setupMapInteractions = (canvasEl, mapData, appState, mapSettings, eventCallbacks) => {
    canvas = canvasEl;
    data = mapData;
    state = appState;
    settings = mapSettings;
    callbacks = eventCallbacks;

    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('mouseup', handleMouseUp);
    canvas.addEventListener('click', handleMouseClick);
    canvas.addEventListener('wheel', handleWheel);
    canvas.addEventListener('contextmenu', handleContextMenu);
    
    // Prevent default touch actions (scrolling, zooming page)
    canvas.addEventListener('touchstart', (e) => { 
        if (e.touches.length === 1) handleMouseDown(e.touches[0]); 
        if (e.touches.length === 2) handleTouchStart(e);
    }, { passive: false });
    
    canvas.addEventListener('touchmove', (e) => { 
        if (e.touches.length === 1) handleMouseMove(e.touches[0]);
        if (e.touches.length === 2) handleTouchMove(e);
    }, { passive: false });
    
    canvas.addEventListener('touchend', (e) => {
        if (e.touches.length === 0) handleMouseUp(e.changedTouches[0]);
        if (e.touches.length < 2) handleTouchEnd(e);
    });

    // Handle touch events for multi-touch (pinch-zoom)
    const handleTouchStart = (e) => {
        e.preventDefault();
        touchPoints = [getEventCoordinates(canvas, { clientX: e.touches[0].clientX, clientY: e.touches[0].clientY }), getEventCoordinates(canvas, { clientX: e.touches[1].clientX, clientY: e.touches[1].clientY })];
        pinchDistance = Math.hypot(touchPoints[0].x - touchPoints[1].x, touchPoints[0].y - touchPoints[1].y);
    };

    const handleTouchMove = (e) => {
        e.preventDefault();
        const currentTouchPoints = [getEventCoordinates(canvas, { clientX: e.touches[0].clientX, clientY: e.touches[0].clientY }), getEventCoordinates(canvas, { clientX: e.touches[1].clientX, clientY: e.touches[1].clientY })];
        const currentPinchDistance = Math.hypot(currentTouchPoints[0].x - currentTouchPoints[1].x, currentTouchPoints[0].y - currentTouchPoints[1].y);
        
        // Pinch Zoom
        if (pinchDistance) {
            const zoomFactor = currentPinchDistance / pinchDistance;
            
            const centerPointX = (touchPoints[0].x + touchPoints[1].x) / 2;
            const centerPointY = (touchPoints[0].y + touchPoints[1].y) / 2;

            const worldCoordsBefore = toWorldCoords(centerPointX, centerPointY);

            state.viewTransform.scale *= zoomFactor;
            state.viewTransform.scale = Math.min(Math.max(state.viewTransform.scale, 0.05), 10);
            
            state.viewTransform.translateX = centerPointX - (worldCoordsBefore.x * state.viewTransform.scale);
            state.viewTransform.translateY = centerPointY - (worldCoordsBefore.y * state.viewTransform.scale);

            pinchDistance = currentPinchDistance;
            touchPoints = currentTouchPoints;
        }

        callbacks.draw();
        localStorage.setItem('mapViewTransform', JSON.stringify(state.viewTransform));
    };

    const handleTouchEnd = () => {
        pinchDistance = null;
        touchPoints = [];
    };
    
    // Initialize view based on state (must run draw on successful load)
    if (state.viewTransform.scale === 1 && state.viewTransform.translateX === 0) {
        // If the view hasn't been set yet, fit map to view
        // Note: This needs to be handled by index.js after data load, not here.
    }
};

// Center on a location with a ping animation
export const centerOnLocationWithPing = (canvasEl, appState, system, eventCallbacks) => {
    const dpr = window.devicePixelRatio || 1; 
    const targetX = system.x;
    const targetY = system.y;

    const canvasCX = (canvasEl.width / 2) / dpr;
    const canvasCY = (canvasEl.height / 2) / dpr;
    
    appState.viewTransform.translateX = canvasCX - (targetX * appState.viewTransform.scale);
    appState.viewTransform.translateY = canvasCY - (targetY * appState.viewTransform.scale);

    appState.pingAnimation = {
        systemId: system.id,
        startTime: Date.now(),
        duration: 2000 
    };

    const interval = setInterval(() => {
        if (Date.now() - appState.pingAnimation.startTime > appState.pingAnimation.duration) {
            clearInterval(interval);
            appState.pingAnimation = null;
        }
        eventCallbacks.draw();
    }, 1000 / 60); // 60 FPS
    
    eventCallbacks.draw();
    localStorage.setItem('mapViewTransform', JSON.stringify(appState.viewTransform));
};

// Center on a system without ping
export const centerOnSystem = (canvasEl, appState, system, eventCallbacks) => {
    const dpr = window.devicePixelRatio || 1; 
    const targetX = system.x;
    const targetY = system.y;

    const canvasCX = (canvasEl.width / 2) / dpr;
    const canvasCY = (canvasEl.height / 2) / dpr;
    
    appState.viewTransform.translateX = canvasCX - (targetX * appState.viewTransform.scale);
    appState.viewTransform.translateY = canvasCY - (targetY * appState.viewTransform.scale);
    appState.highlightedId = system.id;
    
    eventCallbacks.draw();
    localStorage.setItem('mapViewTransform', JSON.stringify(appState.viewTransform));
};