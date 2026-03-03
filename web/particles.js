/**
 * particles.js — Particle Data Flow Lines and Hex Grid Background
 *
 * Two classes:
 *   HexBackground  — Static hexagonal grid drawn once on load and on resize.
 *   ParticleSystem — Animated neon particles flowing between agent panels,
 *                    plus radial flash bursts on state transitions.
 *
 * Cyberpunk aesthetic: neon dots with shadowBlur glow traveling between
 * panels like data packets, subtle hex grid in background.
 */

'use strict';

/* ============================================================
   HexBackground — static atmospheric hex grid
   ============================================================ */

class HexBackground {
    /**
     * @param {HTMLCanvasElement} canvas  — the #canvas-hex element
     */
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');

        this._resize();
        this.draw();

        var self = this;
        window.addEventListener('resize', function () {
            self._resize();
            self.draw();
        });
    }

    /**
     * Match canvas pixel dimensions to window size.
     */
    _resize() {
        this.canvas.width  = window.innerWidth;
        this.canvas.height = window.innerHeight;
    }

    /**
     * Draw the full hex grid across the canvas.
     * Uses a very low opacity (0.03–0.05) cyan for a subtle atmospheric look.
     */
    draw() {
        var ctx    = this.ctx;
        var W      = this.canvas.width;
        var H      = this.canvas.height;
        var size   = 32;                       // hex circumradius in px
        var hexW   = size * 2;                 // flat-top hex width
        var hexH   = Math.sqrt(3) * size;     // flat-top hex height
        var colW   = hexW * 0.75;             // horizontal step between hex centers

        ctx.clearRect(0, 0, W, H);
        ctx.strokeStyle = '#00fff5';
        ctx.lineWidth   = 0.6;
        ctx.globalAlpha = 0.04;

        var col = 0;
        for (var x = -size; x < W + size * 2; x += colW, col++) {
            var offsetY = (col % 2 === 0) ? 0 : hexH / 2;
            for (var y = -hexH + offsetY; y < H + hexH; y += hexH) {
                this._drawHex(ctx, x, y, size);
            }
        }

        ctx.globalAlpha = 1;
    }

    /**
     * Draw a single flat-top hexagon outline.
     * @param {CanvasRenderingContext2D} ctx
     * @param {number} cx  — center x
     * @param {number} cy  — center y
     * @param {number} r   — circumradius
     */
    _drawHex(ctx, cx, cy, r) {
        ctx.beginPath();
        for (var i = 0; i < 6; i++) {
            var angle = (Math.PI / 180) * (60 * i);
            var px = cx + r * Math.cos(angle);
            var py = cy + r * Math.sin(angle);
            if (i === 0) {
                ctx.moveTo(px, py);
            } else {
                ctx.lineTo(px, py);
            }
        }
        ctx.closePath();
        ctx.stroke();
    }
}

/* ============================================================
   ParticleSystem — neon flow particles and flash bursts
   ============================================================ */

class ParticleSystem {
    /**
     * @param {HTMLCanvasElement} canvas  — the #canvas-particles element
     */
    constructor(canvas) {
        this.canvas   = canvas;
        this.ctx      = canvas.getContext('2d');
        this.running  = false;
        this.animFrame = null;

        /**
         * Active flow lines.
         * Each entry: { sourceId, targetId, color, spawnTimer, spawnInterval }
         * @type {Array<Object>}
         */
        this.flows = [];

        /**
         * Live particles (both flow and flash types).
         * Each entry: {
         *   type: 'flow'|'flash',
         *   x, y,             — current position
         *   vx, vy,           — velocity (flash only)
         *   tx, ty,           — target position (flow only)
         *   sx, sy,           — source position (flow only)
         *   t,                — interpolation progress 0..1 (flow only)
         *   speed,            — travel speed per frame (flow only)
         *   color,            — neon hex string
         *   alpha,            — current opacity
         *   size,             — dot radius in px
         *   noiseOffsetX,     — per-particle noise x offset (flow)
         *   noiseOffsetY,     — per-particle noise y offset (flow)
         * }
         * @type {Array<Object>}
         */
        this.particles = [];

        this._resize();

        var self = this;
        window.addEventListener('resize', function () {
            self._resize();
        });
    }

    /* ----------------------------------------------------------
       Resize
       ---------------------------------------------------------- */

    /**
     * Match canvas pixel dimensions to the window.
     */
    _resize() {
        this.canvas.width  = window.innerWidth;
        this.canvas.height = window.innerHeight;
    }

    /* ----------------------------------------------------------
       Panel Center Lookup
       ---------------------------------------------------------- */

    /**
     * Return the viewport-relative center {x, y} of a DOM element by ID.
     * Returns null if the element is not found.
     * @param {string} panelId
     * @returns {{x: number, y: number}|null}
     */
    _getPanelCenter(panelId) {
        var el = document.getElementById(panelId);
        if (!el) return null;
        var rect = el.getBoundingClientRect();
        return {
            x: rect.left + rect.width  / 2,
            y: rect.top  + rect.height / 2,
        };
    }

    /* ----------------------------------------------------------
       Flow Line Registry
       ---------------------------------------------------------- */

    /**
     * Register an animated data-flow line between two panels.
     * Particles will spawn at sourceId and travel toward targetId.
     * If the line already exists it is not duplicated.
     * @param {string} sourceId  — DOM element ID of source panel
     * @param {string} targetId  — DOM element ID of target panel
     * @param {string} color     — neon hex color string
     */
    addFlowLine(sourceId, targetId, color) {
        var exists = this.flows.some(function (f) {
            return f.sourceId === sourceId && f.targetId === targetId;
        });
        if (exists) return;

        this.flows.push({
            sourceId:      sourceId,
            targetId:      targetId,
            color:         color || '#00fff5',
            spawnTimer:    0,
            // Spawn a new particle every ~400–700 ms (at 60 fps ≈ 24–42 frames)
            spawnInterval: 30 + Math.random() * 20,
        });
    }

    /**
     * Remove a specific flow line.
     * @param {string} sourceId
     * @param {string} targetId
     */
    removeFlowLine(sourceId, targetId) {
        this.flows = this.flows.filter(function (f) {
            return !(f.sourceId === sourceId && f.targetId === targetId);
        });
    }

    /**
     * Remove all registered flow lines.
     */
    clearFlowLines() {
        this.flows = [];
    }

    /* ----------------------------------------------------------
       Flash Effect
       ---------------------------------------------------------- */

    /**
     * Spawn a radial burst of particles at the center of panelId.
     * @param {string} panelId
     * @param {string} color
     */
    flash(panelId, color) {
        var center = this._getPanelCenter(panelId);
        if (!center) return;

        var count = 12;
        var col   = color || '#39ff14';

        for (var i = 0; i < count; i++) {
            var angle  = (Math.PI * 2 * i) / count + (Math.random() - 0.5) * 0.4;
            var speed  = 1.5 + Math.random() * 3;
            var size   = 3 + Math.random() * 3;   // 3–6px

            this.particles.push({
                type:  'flash',
                x:     center.x,
                y:     center.y,
                vx:    Math.cos(angle) * speed,
                vy:    Math.sin(angle) * speed,
                color: col,
                alpha: 0.9,
                size:  size,
                // Flash particles decay quickly: ~0.5–0.8 s at 60 fps
                decay: 0.025 + Math.random() * 0.015,
            });
        }
    }

    /* ----------------------------------------------------------
       Flow Particle Spawning
       ---------------------------------------------------------- */

    /**
     * Spawn a single flow particle for a given flow line.
     * @param {Object} flow
     */
    _spawnFlowParticle(flow) {
        var src = this._getPanelCenter(flow.sourceId);
        var dst = this._getPanelCenter(flow.targetId);
        if (!src || !dst) return;

        // Small random jitter at spawn point for organic feel
        var jitter = 10;

        this.particles.push({
            type:         'flow',
            x:            src.x + (Math.random() - 0.5) * jitter,
            y:            src.y + (Math.random() - 0.5) * jitter,
            sx:           src.x,
            sy:           src.y,
            tx:           dst.x,
            ty:           dst.y,
            t:            0,
            // Speed: travels 0-to-1 interpolation over ~1–2 s at 60 fps
            speed:        0.008 + Math.random() * 0.006,
            color:        flow.color,
            alpha:        0.7 + Math.random() * 0.25,
            size:         2 + Math.random() * 1.5,   // 2–3.5px
            // Per-particle noise offsets for wavy path
            noiseOffsetX: (Math.random() - 0.5) * 80,
            noiseOffsetY: (Math.random() - 0.5) * 80,
        });
    }

    /* ----------------------------------------------------------
       Update
       ---------------------------------------------------------- */

    /**
     * Advance all particles one frame; remove expired ones;
     * tick spawn timers and spawn new flow particles.
     */
    _update() {
        var self = this;

        /* Advance flow spawn timers */
        this.flows.forEach(function (flow) {
            flow.spawnTimer += 1;
            if (flow.spawnTimer >= flow.spawnInterval) {
                flow.spawnTimer = 0;
                // Randomise next interval slightly
                flow.spawnInterval = 30 + Math.random() * 20;
                self._spawnFlowParticle(flow);
            }
        });

        /* Update particles */
        this.particles = this.particles.filter(function (p) {
            if (p.type === 'flash') {
                p.x    += p.vx;
                p.y    += p.vy;
                p.vx   *= 0.94;   // drag
                p.vy   *= 0.94;
                p.alpha -= p.decay;
                p.size  *= 0.97;  // shrink
                return p.alpha > 0.01;

            } else {
                // Flow particle: lerp from source to target with sin-curve noise
                p.t += p.speed;

                // Compute straight-line position
                var lx = p.sx + (p.tx - p.sx) * p.t;
                var ly = p.sy + (p.ty - p.sy) * p.t;

                // Add sinusoidal noise perpendicular to direction
                var dx   = p.tx - p.sx;
                var dy   = p.ty - p.sy;
                var len  = Math.sqrt(dx * dx + dy * dy) || 1;
                var nx   = -dy / len;
                var ny   =  dx / len;
                var wave = Math.sin(p.t * Math.PI * 3) * 12;

                p.x = lx + nx * wave + p.noiseOffsetX * Math.sin(p.t * Math.PI);
                p.y = ly + ny * wave + p.noiseOffsetY * Math.sin(p.t * Math.PI);

                // Fade in at start, fade out near target
                if (p.t < 0.15) {
                    p.alpha = p.t / 0.15 * 0.85;
                } else if (p.t > 0.8) {
                    p.alpha = (1 - p.t) / 0.2 * 0.85;
                }

                return p.t < 1.0;
            }
        });
    }

    /* ----------------------------------------------------------
       Draw
       ---------------------------------------------------------- */

    /**
     * Render all particles to the canvas.
     * Flow particles get a glow (shadowBlur); flash particles use alpha fade.
     */
    _draw() {
        var ctx = this.ctx;
        var W   = this.canvas.width;
        var H   = this.canvas.height;

        ctx.clearRect(0, 0, W, H);

        /* Save default shadow state */
        ctx.shadowBlur  = 0;
        ctx.shadowColor = 'transparent';

        var particles = this.particles;
        var len       = particles.length;

        for (var i = 0; i < len; i++) {
            var p = particles[i];

            ctx.globalAlpha = Math.max(0, Math.min(1, p.alpha));
            ctx.fillStyle   = p.color;

            if (p.type === 'flow') {
                /* Glow effect — two passes: wide soft glow then sharp core */
                ctx.shadowColor = p.color;
                ctx.shadowBlur  = 10;
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.size * 1.5, 0, Math.PI * 2);
                ctx.fill();

                ctx.shadowBlur  = 4;
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
                ctx.fill();

            } else {
                /* Flash particles — bright core, outer glow */
                ctx.shadowColor = p.color;
                ctx.shadowBlur  = 14;
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
                ctx.fill();

                ctx.shadowBlur  = 0;
            }
        }

        /* Reset context state */
        ctx.globalAlpha = 1;
        ctx.shadowBlur  = 0;
        ctx.shadowColor = 'transparent';
    }

    /* ----------------------------------------------------------
       Animation Loop
       ---------------------------------------------------------- */

    /**
     * Start the requestAnimationFrame loop.
     * No-op if already running.
     */
    start() {
        if (this.running) return;
        this.running = true;

        var self = this;
        function loop() {
            if (!self.running) return;
            self._update();
            self._draw();
            self.animFrame = requestAnimationFrame(loop);
        }
        loop();
    }

    /**
     * Stop the animation loop and clear the canvas.
     */
    stop() {
        this.running = false;
        if (this.animFrame !== null) {
            cancelAnimationFrame(this.animFrame);
            this.animFrame = null;
        }
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }
}

/* ============================================================
   Module Bootstrap
   ============================================================ */

(function () {
    var hexCanvas       = document.getElementById('canvas-hex');
    var particleCanvas  = document.getElementById('canvas-particles');

    if (!hexCanvas || !particleCanvas) {
        // Elements not present — nothing to initialise
        return;
    }

    /* Instantiate hex background (draws itself immediately) */
    window.hexBackground = new HexBackground(hexCanvas);

    /* Instantiate and start the particle system */
    window.particleSystem = new ParticleSystem(particleCanvas);
    window.particleSystem.start();
}());
