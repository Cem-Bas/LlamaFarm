/**
 * matrix.js — Matrix Rain Animation for idle terminal panels
 *
 * Renders cascading katakana + hex characters on a canvas overlay.
 * Activated per-agent when status is "idle"; paused when active.
 */

'use strict';

class MatrixRain {
    /**
     * @param {HTMLCanvasElement} canvas
     */
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.running = false;
        this.animFrame = null;
        this.fontSize = 14;
        this.columns = 0;
        this.drops = [];

        // Build character set: katakana (0x30A0–0x30FF) + hex digits
        this.chars = [];
        for (let i = 0x30A0; i <= 0x30FF; i++) {
            this.chars.push(String.fromCharCode(i));
        }
        for (let i = 0; i <= 9; i++) {
            this.chars.push(String(i));
        }
        'ABCDEF'.split('').forEach(function (c) {
            this.chars.push(c);
        }, this);

        this._resize();
    }

    /**
     * Match canvas pixel dimensions to the parent element's layout bounds.
     * Recalculates columns and resets drop positions.
     */
    _resize() {
        var parent = this.canvas.parentElement;
        if (!parent) return;

        var w = parent.clientWidth;
        var h = parent.clientHeight;

        // Only resize if dimensions actually changed to avoid clearing mid-animation
        if (this.canvas.width === w && this.canvas.height === h) return;

        this.canvas.width  = w;
        this.canvas.height = h;
        this.columns = Math.max(1, Math.floor(w / this.fontSize));

        // Initialise all drops at random starting positions for variety
        this.drops = [];
        for (var i = 0; i < this.columns; i++) {
            this.drops.push(Math.floor(Math.random() * -50)); // stagger start above viewport
        }
    }

    /**
     * Core draw loop — called via requestAnimationFrame.
     * Each frame:
     *  1. Overlays a semi-transparent black fill to fade trailing characters.
     *  2. Draws one random character per column at the current drop position.
     *  3. Advances each drop; randomly resets drops that have passed the bottom.
     */
    _draw() {
        if (!this.running) return;

        var ctx    = this.ctx;
        var W      = this.canvas.width;
        var H      = this.canvas.height;
        var fs     = this.fontSize;
        var chars  = this.chars;
        var drops  = this.drops;
        var len    = drops.length;

        // Fading trail — semi-transparent dark fill each frame
        ctx.fillStyle = 'rgba(10, 10, 15, 0.05)';
        ctx.fillRect(0, 0, W, H);

        ctx.font = fs + 'px "JetBrains Mono", monospace';

        for (var i = 0; i < len; i++) {
            var char = chars[Math.floor(Math.random() * chars.length)];
            var x    = i * fs;
            var y    = drops[i] * fs;

            // ~5% chance of a bright "head" character (white flash)
            if (Math.random() < 0.05) {
                ctx.fillStyle = '#ffffff';
            } else if (Math.random() < 0.15) {
                // Slightly brighter green variant for depth
                ctx.fillStyle = '#7fff00';
            } else {
                ctx.fillStyle = '#39ff14';
            }

            ctx.fillText(char, x, y);

            // Reset drop back above the viewport once it passes the bottom
            if (y > H && Math.random() > 0.975) {
                drops[i] = 0;
            }
            drops[i]++;
        }

        // Schedule next frame
        var self = this;
        this.animFrame = requestAnimationFrame(function () { self._draw(); });
    }

    /**
     * Start the animation loop.
     * Resizes canvas to match parent before first draw.
     * No-op if already running.
     */
    start() {
        if (this.running) return;
        this._resize();
        this.running = true;
        this._draw();
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
        // Wipe canvas so there is no residual frame shown when hidden
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }
}

// ---------------------------------------------------------------------------
// Module-level state
// ---------------------------------------------------------------------------

/**
 * Cache of MatrixRain instances keyed by agentId.
 * @type {Object.<string, MatrixRain>}
 */
var matrixInstances = {};

/**
 * Start or stop the matrix rain overlay for a given agent panel.
 *
 * When status is "idle" (or falsy):
 *   - Looks up the .matrix-canvas inside #panel-{agentId}
 *   - Creates a MatrixRain instance if one does not exist
 *   - Makes the canvas visible and starts animation
 *
 * For any active status ("thinking", "acting", …):
 *   - Stops animation and hides the canvas
 *
 * @param {string} agentId   - Agent identifier used to find the panel DOM element
 * @param {string} [status]  - Current agent status string
 */
function updateMatrixRain(agentId, status) {
    var canvas = document.querySelector('#panel-' + agentId + ' .matrix-canvas');
    if (!canvas) return;

    var isIdle = (status === 'idle' || !status);

    if (isIdle) {
        // Create instance on first activation
        if (!matrixInstances[agentId]) {
            matrixInstances[agentId] = new MatrixRain(canvas);
        }

        // Show canvas overlay
        canvas.style.display = 'block';
        canvas.style.opacity = '0.35';

        matrixInstances[agentId].start();
    } else {
        // Stop and hide when agent becomes active
        if (matrixInstances[agentId]) {
            matrixInstances[agentId].stop();
        }

        canvas.style.opacity = '0';
        canvas.style.display = 'none';
    }
}
