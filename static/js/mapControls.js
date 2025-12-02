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

// Utility to get coordinates (Returns Logical CSS Pixels)
const getEventCoordinates = (canvas, e) => {
    const rect = canvas.getBoundingClientRect();
    let x, y;
    // If it's a raw TouchEvent (has touches array)
    if (e.touches && e.touches.length > 0) {
        x = e.touches[0].clientX - rect.left;
        y = e.touches[0].clientY - rect.top;
    } 
    // If it's a MouseEvent or a single Touch object passed from adapter
    else {
        x = e.clientX - rect.left;
        y = e.clientY - rect.top;
    }
    return { x, y }; 
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
    const clickToleranceSq = (10 / state.viewTransform.scale) ** 2; 

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

const findIntelMarkerUnderCursor = (worldX, worldY, markers) => {
    let nearest = null;
    let minDistanceSq = Infinity;
    const clickToleranceSq = (15 / state.viewTransform.scale) ** 2;

    if (!markers) return null;

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

// --- Event Handlers ---

const handleMouseDown = (e) => {
    // Allow panning if Left Click (0) OR if button is undefined (Touch event)
    if (e.button !== 0 && e.button !== undefined) return;

    e.preventDefault();
    
    isPanning = true;
    canvas.style.cursor = 'grabbing';
    lastPoint = getEventCoordinates(canvas, e);
    
    // Right click is handled by 'contextmenu' listener
};

const handleMouseMove = (e) => {
    e.preventDefault();
    const currentPoint = getEventCoordinates(canvas, e);
    const worldCoords = toWorldCoords(currentPoint.x, currentPoint.y);
    
    // 1. Handle Panning
    if (isPanning) {
        const dx = currentPoint.x - lastPoint.x;
        const dy = currentPoint.y - lastPoint.y;
        state.viewTransform.translateX += dx;
        state.viewTransform.translateY += dy;
        lastPoint = currentPoint;
        callbacks.draw();
    } 
    
    // 2. Handle Hover
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
};

const handleMouseUp = (e) => {
    // Allow finish if Left Click (0) OR if button is undefined (Touch event)
    if (e.button !== 0 && e.button !== undefined) return;

    e.preventDefault();
    isPanning = false;
    canvas.style.cursor = state.hoveredSystem ? 'pointer' : 'grab';
};

const handleMouseClick = (e) => {
    if (e.button !== 0 || isPanning) return; 

    const point = getEventCoordinates(canvas, e);
    const worldCoords = toWorldCoords(point.x, point.y);
    const selected = findSystemUnderCursor(worldCoords.x, worldCoords.y, data.systems);

    if (selected) {
        if (e.shiftKey) {
            const systemId = String(selected.id);
            if (state.toggledIds.has(systemId)) {
                state.toggledIds.delete(systemId);
            } else {
                state.toggledIds.add(systemId);
            }
        } else {
            state.highlightedId = selected.id;
            callbacks.onSystemSelect(selected);
        }
        state.hoveredSystem = null; 
        callbacks.draw();
    }
};

const handleWheel = (e) => {
    e.preventDefault();
    
    // --- ZOOM FIX: Use multiplicative scaling for speed ---
    const scaleAmount = 1.1; // Adjust this for speed
    const point = getEventCoordinates(canvas, e);
    
    // Calculate world point BEFORE zoom
    const wX = (point.x - state.viewTransform.translateX) / state.viewTransform.scale;
    const wY = (point.y - state.viewTransform.translateY) / state.viewTransform.scale;

    if (e.deltaY < 0) {
        state.viewTransform.scale *= scaleAmount; // Zoom In
    } else {
        state.viewTransform.scale /= scaleAmount; // Zoom Out
    }

    // Clamp scale
    state.viewTransform.scale = Math.min(Math.max(state.viewTransform.scale, 0.05), 10);

    // Adjust translate so the world point remains under mouse
    state.viewTransform.translateX = point.x - (wX * state.viewTransform.scale);
    state.viewTransform.translateY = point.y - (wY * state.viewTransform.scale);

    localStorage.setItem('mapViewTransform', JSON.stringify(state.viewTransform));
    callbacks.draw();
};

const handleContextMenu = (e) => {
    e.preventDefault();
    const point = getEventCoordinates(canvas, e);
    const worldCoords = toWorldCoords(point.x, point.y);
    
    const existingIntel = findIntelMarkerUnderCursor(worldCoords.x, worldCoords.y, data.intelMarkers || []);
    callbacks.onContextMenu(e.clientX, e.clientY, worldCoords.x, worldCoords.y, existingIntel);
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
    canvas.addEventListener('wheel', handleWheel, { passive: false });
    canvas.addEventListener('contextmenu', handleContextMenu);
    
    // Touch Adapters
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

    // Pinch Zoom logic
    const handleTouchStart = (e) => {
        e.preventDefault();
        touchPoints = [
            getEventCoordinates(canvas, { clientX: e.touches[0].clientX, clientY: e.touches[0].clientY }), 
            getEventCoordinates(canvas, { clientX: e.touches[1].clientX, clientY: e.touches[1].clientY })
        ];
        pinchDistance = Math.hypot(touchPoints[0].x - touchPoints[1].x, touchPoints[0].y - touchPoints[1].y);
    };

    const handleTouchMove = (e) => {
        e.preventDefault();
        const p1 = getEventCoordinates(canvas, { clientX: e.touches[0].clientX, clientY: e.touches[0].clientY });
        const p2 = getEventCoordinates(canvas, { clientX: e.touches[1].clientX, clientY: e.touches[1].clientY });
        const currentPinchDistance = Math.hypot(p1.x - p2.x, p1.y - p2.y);
        
        if (pinchDistance) {
            const zoomFactor = currentPinchDistance / pinchDistance;
            const centerPointX = (touchPoints[0].x + touchPoints[1].x) / 2;
            const centerPointY = (touchPoints[0].y + touchPoints[1].y) / 2;
            const wX = (centerPointX - state.viewTransform.translateX) / state.viewTransform.scale;
            const wY = (centerPointY - state.viewTransform.translateY) / state.viewTransform.scale;

            state.viewTransform.scale *= zoomFactor;
            state.viewTransform.scale = Math.min(Math.max(state.viewTransform.scale, 0.05), 10);
            
            state.viewTransform.translateX = centerPointX - (wX * state.viewTransform.scale);
            state.viewTransform.translateY = centerPointY - (wY * state.viewTransform.scale);

            pinchDistance = currentPinchDistance;
            touchPoints = [p1, p2];
        }
        callbacks.draw();
        localStorage.setItem('mapViewTransform', JSON.stringify(state.viewTransform));
    };

    const handleTouchEnd = () => {
        pinchDistance = null;
        touchPoints = [];
    };
};

export const centerOnLocationWithPing = (canvasEl, appState, system, eventCallbacks) => {
    const dpr = appState.dpr || 1;
    const canvasCX = (canvasEl.width / dpr) / 2; 
    const canvasCY = (canvasEl.height / dpr) / 2;
    
    appState.viewTransform.translateX = canvasCX - (system.x * appState.viewTransform.scale);
    appState.viewTransform.translateY = canvasCY - (system.y * appState.viewTransform.scale);

    appState.pingAnimation = {
        systemId: system.id,
        startTime: Date.now(),
        duration: 2000 
    };

    const animate = () => {
        if (!appState.pingAnimation) return;
        if (Date.now() - appState.pingAnimation.startTime > appState.pingAnimation.duration) {
            appState.pingAnimation = null;
            eventCallbacks.draw();
            return;
        }
        eventCallbacks.draw();
        requestAnimationFrame(animate);
    };
    animate();
    localStorage.setItem('mapViewTransform', JSON.stringify(appState.viewTransform));
};

export const centerOnSystem = (canvasEl, appState, system, eventCallbacks) => {
    const dpr = appState.dpr || 1;
    const canvasCX = (canvasEl.width / dpr) / 2;
    const canvasCY = (canvasEl.height / dpr) / 2;
    
    appState.viewTransform.translateX = canvasCX - (system.x * appState.viewTransform.scale);
    appState.viewTransform.translateY = canvasCY - (system.y * appState.viewTransform.scale);
    appState.highlightedId = system.id;
    
    eventCallbacks.draw();
    localStorage.setItem('mapViewTransform', JSON.stringify(appState.viewTransform));
};