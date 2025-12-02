/**
 * Map Controls Module
 * Handles user input (Mouse, Touch, Keyboard) and modifies view state.
 */

let isMouseDown = false;
let isDragging = false;
let dragStartPos = { x: 0, y: 0 };
let lastDragPosition = { x: 0, y: 0 };
let longPressTimer = null;
let initialTouchDistance = null;
let pingAnimationFrameId = null;

// Helper: Get coordinates relative to canvas
const getEventCoordinates = (canvas, e) => {
    const rect = canvas.getBoundingClientRect();
    if (e.touches && e.touches.length > 0) {
        return { x: e.touches[0].clientX - rect.left, y: e.touches[0].clientY - rect.top };
    }
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
};

/**
 * Initialize all map interaction listeners
 * @param {HTMLCanvasElement} canvas 
 * @param {Object} data - Reference to main data object { systems, ... }
 * @param {Object} state - Reference to mutable state { viewTransform, hoveredSystem, etc. }
 * @param {Object} settings - Reference to settings
 * @param {Object} callbacks - { draw(), onSystemSelect(), onContextMenu() }
 */
export const setupMapInteractions = (canvas, data, state, settings, callbacks) => {

    const handleZoom = (e) => {
        e.preventDefault();
        const scaleAmount = 1.1;
        const rect = canvas.getBoundingClientRect();
        const mX = e.clientX - rect.left;
        const mY = e.clientY - rect.top;
        
        // Calculate mouse position in world space before zoom
        const wX = (mX - state.viewTransform.translateX) / state.viewTransform.scale;
        const wY = (mY - state.viewTransform.translateY) / state.viewTransform.scale;

        if (e.deltaY < 0) {
            state.viewTransform.scale *= scaleAmount; // Zoom In
        } else {
            state.viewTransform.scale /= scaleAmount; // Zoom Out
        }

        // Clamp scale
        state.viewTransform.scale = Math.max(0.05, Math.min(state.viewTransform.scale, 10));

        // Adjust translate so the world point under mouse remains under mouse
        state.viewTransform.translateX = mX - wX * state.viewTransform.scale;
        state.viewTransform.translateY = mY - wY * state.viewTransform.scale;

        // Save and Draw
        localStorage.setItem('mapViewTransform', JSON.stringify(state.viewTransform));
        callbacks.draw();
    };

    const handleStart = (e) => {
        // Close context menu if clicking elsewhere
        if (callbacks.closeContextMenu) callbacks.closeContextMenu(e);

        isMouseDown = true;
        isDragging = false;
        const coords = getEventCoordinates(canvas, e);
        dragStartPos = { x: coords.x, y: coords.y };
        lastDragPosition = { x: coords.x, y: coords.y };

        clearTimeout(longPressTimer);
        longPressTimer = setTimeout(() => {
            if (!isDragging) {
                if (state.hoveredSystem && state.hoveredSystem.catapult_radius > 0) {
                    // Toggle catapult range
                    const sysId = String(state.hoveredSystem.id);
                    if (state.toggledIds.has(sysId)) state.toggledIds.delete(sysId);
                    else state.toggledIds.add(sysId);
                    callbacks.draw();
                } else {
                    // Trigger Context Menu (Long Press)
                    const worldX = (coords.x - state.viewTransform.translateX) / state.viewTransform.scale;
                    const worldY = (coords.y - state.viewTransform.translateY) / state.viewTransform.scale;
                    
                    // Check for hit on existing marker
                    let clickedMarker = null;
                    if (data.intelMarkers) {
                        for (const marker of data.intelMarkers) {
                            const dx = worldX - marker.x;
                            const dy = worldY - marker.y;
                            if (Math.sqrt(dx*dx + dy*dy) < (15 / state.viewTransform.scale)) {
                                clickedMarker = marker;
                                break;
                            }
                        }
                    }
                    callbacks.onContextMenu(coords.x, coords.y, worldX, worldY, clickedMarker);
                }
            }
        }, 500);
    };

    const handleMove = (e) => {
        if (isDragging || (e.touches && e.touches.length > 1)) {
            e.preventDefault();
        }

        const coords = getEventCoordinates(canvas, e);
        const worldX = (coords.x - state.viewTransform.translateX) / state.viewTransform.scale;
        const worldY = (coords.y - state.viewTransform.translateY) / state.viewTransform.scale;

        // 1. Handle Hover Logic
        let currentlyHovering = null;
        // Dynamic hover radius based on zoom
        let minDistSq = Math.pow(10 / state.viewTransform.scale, 2);
        
        // Optimization: Only loop if we have data
        if (data.systems) {
            for (const sys of Object.values(data.systems)) {
                if (typeof sys.x !== 'number') continue;
                const dx = worldX - sys.x;
                const dy = worldY - sys.y;
                const distSq = dx * dx + dy * dy;
                if (distSq < minDistSq) {
                    minDistSq = distSq;
                    currentlyHovering = sys;
                }
            }
        }

        if (state.hoveredSystem !== currentlyHovering) {
            state.hoveredSystem = currentlyHovering;
            callbacks.draw();
        }
        
        // Update cursor
        canvas.style.cursor = state.hoveredSystem ? 'pointer' : (isDragging ? 'grabbing' : 'grab');

        // 2. Handle Pinch Zoom (Touch)
        if (e.touches && e.touches.length === 2) {
            isDragging = false;
            clearTimeout(longPressTimer);
            const t1 = { x: e.touches[0].clientX, y: e.touches[0].clientY };
            const t2 = { x: e.touches[1].clientX, y: e.touches[1].clientY };
            const dist = Math.hypot(t1.x - t2.x, t1.y - t2.y);
            
            if (initialTouchDistance) {
                const scaleFactor = dist / initialTouchDistance;
                const rect = canvas.getBoundingClientRect();
                const midX = (t1.x + t2.x) / 2 - rect.left;
                const midY = (t1.y + t2.y) / 2 - rect.top;
                
                const worldMidX = (midX - state.viewTransform.translateX) / state.viewTransform.scale;
                const worldMidY = (midY - state.viewTransform.translateY) / state.viewTransform.scale;

                state.viewTransform.scale *= scaleFactor;
                state.viewTransform.scale = Math.max(0.05, Math.min(state.viewTransform.scale, 10));

                state.viewTransform.translateX = midX - worldMidX * state.viewTransform.scale;
                state.viewTransform.translateY = midY - worldMidY * state.viewTransform.scale;
                
                callbacks.draw();
            }
            initialTouchDistance = dist;
            return;
        } else {
            initialTouchDistance = null;
        }

        // 3. Handle Panning (Mouse/Single Touch)
        if (isMouseDown && (!e.touches || e.touches.length === 1)) {
            // Check drag threshold
            if (!isDragging && Math.hypot(coords.x - dragStartPos.x, coords.y - dragStartPos.y) > 5) {
                isDragging = true;
                clearTimeout(longPressTimer);
            }
            if (isDragging) {
                const dx = coords.x - lastDragPosition.x;
                const dy = coords.y - lastDragPosition.y;
                state.viewTransform.translateX += dx;
                state.viewTransform.translateY += dy;
                lastDragPosition = { x: coords.x, y: coords.y };
                callbacks.draw();
            }
        }
    };

    const handleEnd = (e) => {
        clearTimeout(longPressTimer);
        
        if (!isDragging) {
            if (state.hoveredSystem) {
                if (e.shiftKey) {
                    // Shift+Click: Toggle Range
                    if (state.hoveredSystem.catapult_radius > 0) {
                        const sysId = String(state.hoveredSystem.id);
                        if (state.toggledIds.has(sysId)) state.toggledIds.delete(sysId);
                        else state.toggledIds.add(sysId);
                    }
                } else {
                    // Normal Click: Select System (for route) or Highlight
                    if (callbacks.onSystemSelect) {
                        callbacks.onSystemSelect(state.hoveredSystem);
                    }
                    // Highlight on map
                    state.highlightedId = state.hoveredSystem.id;
                }
            } else {
                // Clicked empty space -> Clear highlight
                state.highlightedId = null;
            }
            callbacks.draw();
        }

        isMouseDown = false;
        isDragging = false;
        initialTouchDistance = null;
        canvas.style.cursor = state.hoveredSystem ? 'pointer' : 'grab';
        localStorage.setItem('mapViewTransform', JSON.stringify(state.viewTransform));
    };

    const handleContextMenu = (e) => {
        e.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const worldX = (x - state.viewTransform.translateX) / state.viewTransform.scale;
        const worldY = (y - state.viewTransform.translateY) / state.viewTransform.scale;

        // Check hit on existing marker
        let clickedMarker = null;
        if (data.intelMarkers) {
            for (const marker of data.intelMarkers) {
                const dx = worldX - marker.x;
                const dy = worldY - marker.y;
                if (Math.sqrt(dx*dx + dy*dy) < (15 / state.viewTransform.scale)) {
                    clickedMarker = marker;
                    break;
                }
            }
        }
        
        callbacks.onContextMenu(e.clientX, e.clientY, worldX, worldY, clickedMarker);
    };

    // Attach Listeners
    canvas.addEventListener('wheel', handleZoom, { passive: false });
    canvas.addEventListener('mousedown', handleStart);
    canvas.addEventListener('mousemove', handleMove);
    canvas.addEventListener('mouseup', handleEnd);
    canvas.addEventListener('mouseleave', handleEnd);
    canvas.addEventListener('touchstart', handleStart, { passive: false });
    canvas.addEventListener('touchmove', handleMove, { passive: false });
    canvas.addEventListener('touchend', handleEnd);
    canvas.addEventListener('touchcancel', handleEnd);
    canvas.addEventListener('contextmenu', handleContextMenu);
};

// --- View Actions ---

export const centerOnSystem = (canvas, state, system, callbacks) => {
    if (!system || typeof system.x !== 'number') return;
    
    state.viewTransform.scale = 1.5;
    state.viewTransform.translateX = (canvas.width / 2) - (system.x * state.viewTransform.scale);
    state.viewTransform.translateY = (canvas.height / 2) - (system.y * state.viewTransform.scale);
    
    state.highlightedId = system.id;
    localStorage.setItem('mapViewTransform', JSON.stringify(state.viewTransform));
    callbacks.draw();

    // Auto-clear highlight after 2s
    setTimeout(() => {
        if (state.highlightedId === system.id) {
            state.highlightedId = null;
            callbacks.draw();
        }
    }, 2000);
};

export const centerOnLocationWithPing = (canvas, state, system, callbacks) => {
    if (!system) return;

    // 1. Center View
    state.viewTransform.scale = 1.0;
    state.viewTransform.translateX = (canvas.width / 2) - (system.x * state.viewTransform.scale);
    state.viewTransform.translateY = (canvas.height / 2) - (system.y * state.viewTransform.scale);
    
    state.highlightedId = null; // Clear any static highlight
    localStorage.setItem('mapViewTransform', JSON.stringify(state.viewTransform));

    // 2. Setup Ping Animation
    if (pingAnimationFrameId) cancelAnimationFrame(pingAnimationFrameId);
    
    state.pingAnimation = {
        systemId: system.id,
        startTime: Date.now(),
        duration: 1200
    };

    const animate = () => {
        if (!state.pingAnimation) return;
        const elapsed = Date.now() - state.pingAnimation.startTime;
        if (elapsed > state.pingAnimation.duration) {
            state.pingAnimation = null;
            callbacks.draw();
            return;
        }
        callbacks.draw();
        pingAnimationFrameId = requestAnimationFrame(animate);
    };

    animate();
};