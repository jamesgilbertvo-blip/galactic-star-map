/**
 * Map Renderer Module
 * Handles all canvas drawing operations.
 */

const SPIRAL_TIGHTNESS = 0.1;
const SPIRAL_SCALE = 50;
const LOD_THRESHOLD = 0.25; // If scale is below this, hide clutter

// Helper: Calculate spiral coordinates from a linear position
export const getSpiralPoint = (pos) => {
    const p = parseFloat(pos);
    const r = p * SPIRAL_SCALE / 1000;
    const angle = p * SPIRAL_TIGHTNESS;
    return {
        x: r * Math.cos(angle),
        y: r * Math.sin(angle)
    };
};

// Helper: Draw the yellow sublight spiral line between two positions
const drawSublight = (ctx, viewTransform, posA, posB) => {
    if (isNaN(posA) || isNaN(posB)) return;
    
    ctx.strokeStyle = '#f59e0b'; // yellow
    ctx.lineWidth = 3 / viewTransform.scale;
    const s = 1; // Step size for smoothness
    
    ctx.beginPath();
    const startPoint = getSpiralPoint(posA);
    ctx.moveTo(startPoint.x, startPoint.y);

    const dist = Math.abs(posB - posA);
    const sign = Math.sign(posB - posA);

    for (let j = 1; j <= Math.floor(dist / s); j++) {
        const p = posA + (j * s * sign);
        const point = getSpiralPoint(p);
        ctx.lineTo(point.x, point.y);
    }
    const endPoint = getSpiralPoint(posB);
    ctx.lineTo(endPoint.x, endPoint.y);
    ctx.stroke();
};

/**
 * Main Drawing Function
 */
export const drawMap = (ctx, canvas, viewTransform, data, state, settings, dpr = 1) => {
    if (!canvas.width || !ctx) return;

    // 1. Setup Canvas
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.scale(dpr, dpr); // Handle High DPI
    ctx.translate(viewTransform.translateX, viewTransform.translateY);
    ctx.scale(viewTransform.scale, viewTransform.scale);

    const isLowDetail = viewTransform.scale < LOD_THRESHOLD;

    // --- PRE-CALCULATE IMPORTANT IDS ---
    // Create a set of IDs for systems that have wormholes so we can keep them visible
    const wormholeSystemIds = new Set();
    if (data.wormholes) {
        data.wormholes.forEach(wh => {
            wormholeSystemIds.add(wh[0]);
            wormholeSystemIds.add(wh[1]);
        });
    }
    // ------------------------------------

    // 2. Draw Spiral Guide
    const systemPositions = Object.values(data.systems).map(s => parseFloat(s.position)).filter(p => !isNaN(p));
    if (systemPositions.length > 0) {
        let maxPos = Math.max(...systemPositions);
        if (maxPos > 0) {
            ctx.strokeStyle = 'rgba(75,85,99,0.2)';
            ctx.lineWidth = 1 / viewTransform.scale;
            ctx.beginPath();
            const s = 1;
            ctx.moveTo(0, 0);
            for (let p = s; p <= maxPos * 1.1; p += s) {
                const pt = getSpiralPoint(p);
                ctx.lineTo(pt.x, pt.y);
            }
            ctx.stroke();
        }
    }

    // 3. Draw Catapult Ranges
    // MODIFIED: Ranges are now always drawn if enabled, regardless of Zoom level, for context.
    if (settings.showCatapults) {
        Object.values(data.systems).forEach(sys => {
            const sysPos = parseFloat(sys.position);
            const sysRadius = parseFloat(sys.catapult_radius);
            if (isNaN(sysPos) || isNaN(sysRadius) || sysRadius <= 0) return;

            const isToggled = state.toggledIds.has(String(sys.id));
            
            // Logic: Highlight if toggled, highlighted, or hovered
            const isImportant = isToggled || 
                                (state.highlightedId !== null && String(sys.id) === String(state.highlightedId)) || 
                                (state.hoveredSystem && state.hoveredSystem.id === sys.id);

            if (!isToggled) {
                let rangeColor = 'rgba(132, 204, 22, 0.3)';
                if (isImportant) {
                     rangeColor = 'rgba(163, 230, 57, 0.9)';
                }

                ctx.strokeStyle = rangeColor;
                ctx.lineWidth = 2 / viewTransform.scale;
                const startPos = sysPos - sysRadius;
                const endPos = sysPos + sysRadius;
                const step = 1;
                
                ctx.beginPath();
                const startPt = getSpiralPoint(startPos);
                ctx.moveTo(startPt.x, startPt.y);
                for (let pos = startPos + step; pos < endPos; pos += step) {
                    const pt = getSpiralPoint(pos);
                    ctx.lineTo(pt.x, pt.y);
                }
                const endPt = getSpiralPoint(endPos);
                ctx.lineTo(endPt.x, endPt.y);
                ctx.stroke();
            }
        });
    }

    // 4. Draw Wormholes
    if (settings.showWormholes) {
        ctx.strokeStyle = 'rgba(239, 68, 68, 0.4)';
        ctx.lineWidth = 1 / viewTransform.scale;
        ctx.setLineDash([5 / viewTransform.scale, 5 / viewTransform.scale]);
        data.wormholes.forEach(wh => {
            const sA = data.systems[wh[0]]; 
            const sB = data.systems[wh[1]];
            
            if (sA && sB && typeof sA.x === 'number' && typeof sB.x === 'number') {
                ctx.beginPath();
                ctx.moveTo(sA.x, sA.y);
                ctx.lineTo(sB.x, sB.y);
                ctx.stroke();
            }
        });
        ctx.setLineDash([]);
    }

    // 5. Draw Calculated Path
    const calculatedPathIds = new Set(state.pathNodes.map(p => String(p.id)));
    const nodeMap = new Map(state.pathNodes.map(n => [String(n.id), n]));

    if (state.pathLegs.length > 0) {
        state.pathLegs.forEach(leg => {
            const sA = nodeMap.get(String(leg.from_id));
            const sB = nodeMap.get(String(leg.to_id));

            if (!sA || !sB) return;
            const posA = parseFloat(sA.position);
            const posB = parseFloat(sB.position);
            if (isNaN(posA) || isNaN(posB)) return;

            if (leg.method === 'wormhole') {
                ctx.strokeStyle = '#ef4444';
                ctx.lineWidth = 3 / viewTransform.scale;
                ctx.beginPath();
                ctx.moveTo(sA.x, sA.y);
                ctx.lineTo(sB.x, sB.y);
                ctx.stroke();

            } else if (leg.method === 'catapult') {
                ctx.strokeStyle = '#a3e635';
                ctx.lineWidth = 3 / viewTransform.scale;
                ctx.beginPath();
                ctx.moveTo(sA.x, sA.y);
                ctx.lineTo(sB.x, sB.y);
                ctx.stroke();

            } else if (leg.method === 'catapult_sublight') {
                const catapultRadius = data.systems[sA.id]?.catapult_radius || 0;
                const sign = Math.sign(posB - posA);
                const virtualNodePos = posA + (sign * catapultRadius);

                const coordsA = { x: sA.x, y: sA.y };
                const coordsV = getSpiralPoint(virtualNodePos);

                ctx.strokeStyle = '#a3e635';
                ctx.lineWidth = 3 / viewTransform.scale;
                ctx.beginPath();
                ctx.moveTo(coordsA.x, coordsA.y);
                ctx.lineTo(coordsV.x, coordsV.y);
                ctx.stroke();

                drawSublight(ctx, viewTransform, virtualNodePos, posB);

                ctx.fillStyle = '#f59e0b';
                ctx.strokeStyle = '#1f2937';
                ctx.lineWidth = 1 / viewTransform.scale;
                ctx.beginPath();
                ctx.arc(coordsV.x, coordsV.y, 3 / viewTransform.scale, 0, Math.PI * 2);
                ctx.fill();
                ctx.stroke();

            } else {
                drawSublight(ctx, viewTransform, posA, posB);
            }
        });
    }

    // 6. Draw Systems (Dots) - MODIFIED LOD
    Object.values(data.systems).forEach(sys => {
        if (typeof sys.x !== 'number' || typeof sys.y !== 'number') return;
        
        const isOnPath = calculatedPathIds.has(String(sys.id));
        const isHovered = state.hoveredSystem && state.hoveredSystem.id === sys.id;
        const isNewlySynced = state.newlySyncedIds.has(String(sys.id));
        const isSearched = state.highlightedId === sys.id;

        // --- MODIFIED LOD LOGIC ---
        // Always show: Path, Hover, Search, New Sync
        // PLUS: Catapult Owners (sys.catapult_radius > 0)
        // PLUS: Wormhole Endpoints (in wormholeSystemIds)
        const isImportant = isOnPath || isHovered || isSearched || isNewlySynced || 
                            (sys.catapult_radius > 0) || 
                            wormholeSystemIds.has(sys.id);

        if (isLowDetail && !isImportant) return;

        ctx.fillStyle = isOnPath || isSearched ? '#f59e0b' : '#38bdf8';
        ctx.beginPath();
        const radius = (isOnPath || isHovered || isSearched ? 6 : 4) / viewTransform.scale;
        ctx.arc(sys.x, sys.y, radius, 0, Math.PI * 2);
        ctx.fill();

        if (isNewlySynced) {
            ctx.strokeStyle = 'rgba(250, 204, 21, 0.9)';
            ctx.lineWidth = 3 / viewTransform.scale;
            ctx.stroke();
        }
    });

    // 7. Draw Virtual Node Lines
    state.pathNodes.forEach(node => {
        if (node.id.toString().startsWith('virtual')) {
            const size = 8 / viewTransform.scale;
            ctx.strokeStyle = '#f59e0b';
            ctx.lineWidth = 2 / viewTransform.scale;
            ctx.beginPath();
            ctx.moveTo(node.x - size, node.y - size); ctx.lineTo(node.x + size, node.y + size);
            ctx.moveTo(node.x + size, node.y - size); ctx.lineTo(node.x - size, node.y + size);
            ctx.stroke();
        }
    });

    // 8. Draw System Labels - MODIFIED LOD
    Object.values(data.systems).forEach(sys => {
        if (typeof sys.x !== 'number' || typeof sys.y !== 'number') return;
        
        const isOnPath = calculatedPathIds.has(String(sys.id));
        const isHovered = state.hoveredSystem && state.hoveredSystem.id === sys.id;
        const isSearched = state.highlightedId === sys.id;

        // Keep labels consistent with dots for importance
        const isImportant = isOnPath || isHovered || isSearched || 
                            (sys.catapult_radius > 0) || 
                            wormholeSystemIds.has(sys.id);

        if (isLowDetail && !isImportant) return;

        let labelText = sys.name;
        const isDefaultName = labelText && labelText.startsWith("System ");
        if (isDefaultName && typeof sys.position === 'string' && sys.position !== '') {
            labelText = `#${sys.position}`;
        } else if (!labelText) {
            labelText = `ID: ${sys.id}`;
        }

        let shouldShowLabel = (isImportant || viewTransform.scale > 0.8);
        if (isDefaultName && !settings.showUnclaimed && !isImportant) {
            shouldShowLabel = false;
        }

        if (shouldShowLabel) {
            ctx.fillStyle = isImportant ? '#ffffff' : '#e5e7eb';
            ctx.font = `${(isImportant ? 12 : 10) / viewTransform.scale}px Inter`;
            ctx.textAlign = 'center';
            ctx.fillText(labelText, sys.x, sys.y - ((isImportant ? 10 : 8) / viewTransform.scale));
        }
    });

    // 9. Draw Virtual Node Labels
    state.pathNodes.forEach(node => {
        if (node.id.toString().startsWith('virtual')) {
            const size = 8 / viewTransform.scale;
            ctx.fillStyle = '#ffffff';
            ctx.font = `${12 / viewTransform.scale}px Inter`;
            ctx.textAlign = 'center';
            ctx.fillText(node.name, node.x, node.y - (size + 4 / viewTransform.scale));
        }
    });

    // 10. Draw Ping Animation
    const ping = state.pingAnimation;
    if (ping && data.systems[ping.systemId]) {
        const sys = data.systems[ping.systemId];
        if (typeof sys.x === 'number' && typeof sys.y === 'number') {
            const elapsed = Date.now() - ping.startTime;
            const progress = elapsed / ping.duration;
            
            const maxRadius = (Math.max(canvas.width, canvas.height) / 2) / viewTransform.scale;
            const currentRadius = Math.max(0, maxRadius * (1 - progress));
            const currentAlpha = Math.max(0, 1 - (progress * 0.8));

            if (currentRadius > 0 && currentAlpha > 0) {
                ctx.strokeStyle = `rgba(245, 158, 11, ${currentAlpha})`;
                ctx.lineWidth = 4 / viewTransform.scale;
                ctx.beginPath();
                ctx.arc(sys.x, sys.y, currentRadius, 0, Math.PI * 2);
                ctx.stroke();
            }

            const delay = 150;
            if (elapsed > delay) {
                const progress2 = (elapsed - delay) / (ping.duration - delay);
                const currentRadius2 = Math.max(0, maxRadius * (1 - progress2));
                const currentAlpha2 = Math.max(0, 1 - (progress2 * 0.8));

                if (currentRadius2 > 0 && currentAlpha2 > 0) {
                    ctx.lineWidth = 2 / viewTransform.scale;
                    ctx.strokeStyle = `rgba(245, 158, 11, ${currentAlpha2})`;
                    ctx.beginPath();
                    ctx.arc(sys.x, sys.y, currentRadius2, 0, Math.PI * 2);
                    ctx.stroke();
                }
            }
        }
    }

    // 11. Draw Intel Markers
    if (data.intelMarkers) {
        data.intelMarkers.forEach(marker => {
            if (typeof marker.x === 'number' && typeof marker.y === 'number') {
                ctx.save();
                ctx.translate(marker.x, marker.y);
                const size = Math.max(6, 12 / viewTransform.scale);

                if (marker.type === "Mining Rich") {
                    ctx.fillStyle = '#22d3ee'; // Cyan
                    ctx.fillRect(-size / 2, -size / 2, size, size);
                } else if (marker.type === "Hazard") {
                    ctx.fillStyle = '#fb923c'; // Orange
                    ctx.beginPath();
                    ctx.moveTo(0, -size / 2);
                    ctx.lineTo(size / 2, size / 2);
                    ctx.lineTo(-size / 2, size / 2);
                    ctx.closePath();
                    ctx.fill();
                } else if (marker.type === "Point of Interest") {
                    ctx.fillStyle = '#c084fc'; // Purple
                    ctx.beginPath();
                    ctx.arc(0, 0, size / 2, 0, Math.PI * 2);
                    ctx.fill();
                }
                ctx.restore();
            }
        });
    }

    ctx.restore();
};