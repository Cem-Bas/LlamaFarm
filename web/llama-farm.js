/**
 * llama-farm.js — 3D Isometric Llama Farm Visualization
 *
 * Renders swarm agents as cute voxel llamas on a green farm.
 * Inspired by "Llama Go!" style isometric game art.
 * Requires Three.js (r160+) loaded globally.
 */
(function () {
    'use strict';

    /* ================================================================
       Constants
       ================================================================ */

    var LLAMA_PALETTE = [
        0xf5f5f0, // white
        0xffaabb, // pink
        0x88bbff, // blue
        0x88ffaa, // green
        0xffbb66, // orange
        0xcc88ff, // purple
        0x66ffdd, // teal
        0xffff88, // yellow
    ];

    var ORCH_COLOR = 0xffd700; // gold

    var WORKER_SPOTS = [
        { x: -5, z: -4, ry:  0.3 },
        { x:  5, z: -4, ry: -0.4 },
        { x: -4, z:  5, ry:  0.8 },
        { x:  4, z:  5, ry: -0.6 },
        { x: -7, z:  1, ry:  1.2 },
        { x:  7, z:  1, ry: -1.0 },
        { x:  0, z: -7, ry:  0.1 },
        { x:  0, z:  7, ry:  2.8 },
    ];

    // Warm farm palette status colors
    var STATUS_COLORS = {
        idle:         0x9B8B7A, // warm grey-brown
        thinking:     0xFFD700, // golden yellow
        acting:       0x7EC850, // farm green
        error:        0xE85D4A, // warm red
        orchestrator: 0xD4A574, // warm tan
    };

    // Speech bubble messages per status
    var SPEECH_BUBBLES = {
        spawn: [
            'Blaaa~!',
            'Hiii!',
            '*stretches*',
            'Ready!',
            'Llama time!',
            'Reporting!',
            '*yawn*',
            'Let\'s go!',
        ],
        thinking: [
            'Hmm...',
            'Thinking...',
            'Blaaa?',
            'Let me see...',
            '*chewing*',
            'Processing...',
            'Hmmmm~',
            'One sec...',
        ],
        acting: [
            'On it!',
            'Working~',
            'Blaaa!',
            '*typing*',
            'Busy busy!',
            'Got it!',
            '*tap tap*',
            'Running...',
        ],
        error: [
            'Oops!',
            'Blaaa?!',
            'Oh no...',
            '*confused*',
            'Help!',
            'Uh oh...',
            '*panics*',
            'Error!',
        ],
        idle: [
            '*munches*',
            'Zzz...',
            '...',
            '*looks around*',
            'Blaaa~',
            '*tail wag*',
            '*ear twitch*',
            'Chillin\'',
        ],
        orchestrator: [
            'Overseeing!',
            'All good~',
            'Keep going!',
            '*nods*',
            'Good work!',
            'Blaaa!',
            '*surveys*',
            'Carry on!',
            'Proud of you!',
            'Great team!',
            'You can do it!',
            'Nice job~',
            'Stay strong!',
            '*happy bleat*',
            'My llamas!',
            'Love you all~',
        ],
    };

    var BUBBLE_DURATION = 4.0; // seconds to show each bubble
    var BUBBLE_DURATION_ACTION = 5.0; // longer for actual action text
    var BUBBLE_COOLDOWN = 2.0; // minimum seconds between bubbles
    var BUBBLE_MAX_CHARS = 28; // max characters before truncation

    // Wander system
    var WANDER_RADIUS = 6; // max distance from current position
    var WANDER_SPEED = 0.8;  // units per second
    var FARM_BOUNDS = 10;    // keep within this radius

    /* ================================================================
       Utility
       ================================================================ */

    function darkenColor(hex, amt) {
        var r = ((hex >> 16) & 0xff) * (1 - amt);
        var g = ((hex >>  8) & 0xff) * (1 - amt);
        var b = (hex & 0xff) * (1 - amt);
        return (Math.round(r) << 16) | (Math.round(g) << 8) | Math.round(b);
    }

    function roundRect(ctx, x, y, w, h, r) {
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.quadraticCurveTo(x + w, y, x + w, y + r);
        ctx.lineTo(x + w, y + h - r);
        ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
        ctx.lineTo(x + r, y + h);
        ctx.quadraticCurveTo(x, y + h, x, y + h - r);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
    }

    function easeOutBack(t) {
        var c1 = 1.70158;
        var c3 = c1 + 1;
        return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
    }

    function pickRandom(arr) {
        return arr[Math.floor(Math.random() * arr.length)];
    }

    /**
     * Format an Ollama action dict into a short speech bubble string.
     * e.g. {action:"type", value:"ls -la"} -> "$ ls -la"
     *      {action:"key", value:"Enter"}   -> "[Enter]"
     *      {action:"wait", value:2}         -> null (skip)
     */
    function formatActionText(action) {
        if (!action || typeof action !== 'object') return null;
        var act = action.action || '';
        var val = action.value;

        if (act === 'wait') return null; // boring, skip

        var text = '';
        if (act === 'type' && typeof val === 'string') {
            // Show what the llama is typing
            text = '$ ' + val;
        } else if (act === 'key' && typeof val === 'string') {
            text = '[' + val + ']';
        } else if (act === 'keys' && Array.isArray(val)) {
            text = val.map(function (k) { return '[' + k + ']'; }).join(' ');
        } else if (act === 'command' && typeof val === 'string') {
            text = val;
        } else if (act === 'spawn' || act === 'assign' || act === 'kill') {
            // Orchestrator commands
            var target = action.worker || action.goal || '';
            text = act + ': ' + target;
        } else {
            // Generic fallback
            text = act + (val ? ': ' + String(val) : '');
        }

        if (!text) return null;

        // Truncate with ellipsis
        if (text.length > BUBBLE_MAX_CHARS) {
            text = text.substring(0, BUBBLE_MAX_CHARS - 3) + '...';
        }
        return text;
    }

    /* ================================================================
       LlamaFarm Class
       ================================================================ */

    function LlamaFarm(container) {
        this.container = container;
        this.llamas = {};
        this._colorIdx = 0;
        this._spotIdx = 0;
        this._clock = new THREE.Clock();
        this._cameraAngle = Math.PI / 4;
        this._isDragging = false;
        this._prevMouseX = 0;
        this._paused = false;
        this._disposed = false;
        this._selectedAgentId = null;
        this._selectionRing = null;
        this._raycaster = new THREE.Raycaster();
        this._mouseVec = new THREE.Vector2();
        this._mouseDownPos = { x: 0, y: 0 };
        this.onLlamaClick = null; // callback: function(agentId)

        this._initScene();
        this._initCamera();
        this._initLighting();
        this._buildGround();
        this._addDecorations();
        this._initRenderer();
        this._initMouseControls();

        this._animate = this._animate.bind(this);
        this._onResize = this._onResize.bind(this);
        window.addEventListener('resize', this._onResize);
        this._animate();
    }

    /* ------ Scene ------ */

    LlamaFarm.prototype._initScene = function () {
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x87ceeb);
        this.scene.fog = new THREE.FogExp2(0x87ceeb, 0.007);
    };

    /* ------ Camera (orthographic isometric) ------ */

    LlamaFarm.prototype._initCamera = function () {
        var w = this.container.clientWidth || 800;
        var h = this.container.clientHeight || 600;
        var aspect = w / h;
        this._frustumSize = 10;
        var s = this._frustumSize;
        this.camera = new THREE.OrthographicCamera(
            -s * aspect, s * aspect, s, -s, 0.1, 200
        );
        this._updateCameraPosition();
    };

    LlamaFarm.prototype._updateCameraPosition = function () {
        var r = 30, h = 22;
        this.camera.position.set(
            Math.cos(this._cameraAngle) * r,
            h,
            Math.sin(this._cameraAngle) * r
        );
        this.camera.lookAt(0, 0, 0);
    };

    /* ------ Lighting ------ */

    LlamaFarm.prototype._initLighting = function () {
        this.scene.add(new THREE.AmbientLight(0xffffff, 0.65));

        var sun = new THREE.DirectionalLight(0xfff5e0, 0.8);
        sun.position.set(15, 30, 10);
        this.scene.add(sun);

        var fill = new THREE.DirectionalLight(0xcceeff, 0.25);
        fill.position.set(-10, 15, -10);
        this.scene.add(fill);
    };

    /* ------ Ground ------ */

    LlamaFarm.prototype._buildGround = function () {
        // Main green pasture — use a single mesh with vertex colors for variation
        var groundGeo = new THREE.PlaneGeometry(60, 60, 20, 20);
        var colors = [];
        var baseR = 0x7e / 255, baseG = 0xc8 / 255, baseB = 0x50 / 255;
        var posAttr = groundGeo.getAttribute('position');
        for (var i = 0; i < posAttr.count; i++) {
            var variation = 0.85 + Math.random() * 0.3;
            colors.push(baseR * variation, baseG * variation, baseB * variation);
        }
        groundGeo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
        var groundMat = new THREE.MeshLambertMaterial({ vertexColors: true });
        var ground = new THREE.Mesh(groundGeo, groundMat);
        ground.rotation.x = -Math.PI / 2;
        ground.position.y = 0;
        this.scene.add(ground);

        // Dirt paths — use 3D boxes instead of planes to avoid z-fighting
        var pathMat = new THREE.MeshLambertMaterial({ color: 0xc9a868 });

        var path = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.06, 24), pathMat);
        path.position.set(-2, 0.03, 0);
        this.scene.add(path);

        var path2 = new THREE.Mesh(new THREE.BoxGeometry(20, 0.06, 1.5), pathMat);
        path2.position.set(0, 0.03, -2);
        this.scene.add(path2);
    };

    /* ------ Decorations ------ */

    LlamaFarm.prototype._addDecorations = function () {
        var self = this;

        // Trees
        var treePos = [
            [-12, -10], [12, -9], [-11, 10], [14, 8],
            [-15,   3], [10,-14], [16,   1], [-8,-15],
            [  0,  14], [-14,-6], [15, -4],  [-6, 15],
        ];
        treePos.forEach(function (p) {
            self.scene.add(self._createTree(p[0], p[1]));
        });

        // Fences
        this._addFence(-13, -12, 13, -12);
        this._addFence(-13,  12, 13,  12);
        this._addFence(-13, -12,-13,  12);
        this._addFence( 13, -12, 13,  12);

        // Obstacles list for collision avoidance (x, z, radius)
        this._obstacles = [];

        // Flowers
        for (var i = 0; i < 35; i++) {
            var fx = (Math.random() - 0.5) * 26;
            var fz = (Math.random() - 0.5) * 26;
            this.scene.add(this._createFlower(fx, fz));
            this._obstacles.push({ x: fx, z: fz, r: 0.3 });
        }

        // Rocks
        for (var j = 0; j < 12; j++) {
            var rx = (Math.random() - 0.5) * 28;
            var rz = (Math.random() - 0.5) * 28;
            this.scene.add(this._createRock(rx, rz));
            this._obstacles.push({ x: rx, z: rz, r: 0.8 });
        }

        // Hay bales
        this.scene.add(this._createHayBale(8, -7));
        this._obstacles.push({ x: 8, z: -7, r: 1.2 });
        this.scene.add(this._createHayBale(9, -6.5));
        this._obstacles.push({ x: 9, z: -6.5, r: 1.2 });
        this.scene.add(this._createHayBale(-9, 6));
        this._obstacles.push({ x: -9, z: 6, r: 1.2 });

        // Water trough
        this.scene.add(this._createTrough(3, -1));
        this._obstacles.push({ x: 3, z: -1, r: 1.5 });

        // Farm sign
        this.scene.add(this._createSign(-2, -12.5));

        // Wolf lurking outside the fence
        this._addWolf();

        // Goose wandering around
        this._addGoose();

        // Clouds
        this._addClouds();
    };

    LlamaFarm.prototype._createTree = function (x, z) {
        var g = new THREE.Group();
        var trunkMat = new THREE.MeshLambertMaterial({ color: 0x8b6b3d });
        var trunk = new THREE.Mesh(new THREE.BoxGeometry(0.5, 2.2, 0.5), trunkMat);
        trunk.position.set(0, 1.1, 0);
        g.add(trunk);

        // Keep leaf colors in the green range — safe per-channel random
        var lr = 0x1a + Math.floor(Math.random() * 0x30);
        var lg = 0x70 + Math.floor(Math.random() * 0x50);
        var lb = 0x20 + Math.floor(Math.random() * 0x25);
        var leafMat = new THREE.MeshLambertMaterial({ color: (lr << 16) | (lg << 8) | lb });

        var l1 = new THREE.Mesh(new THREE.BoxGeometry(2.8, 1.2, 2.8), leafMat);
        l1.position.set(0, 2.8, 0);
        g.add(l1);

        var l2 = new THREE.Mesh(new THREE.BoxGeometry(2, 1, 2), leafMat);
        l2.position.set(0, 3.6, 0);
        g.add(l2);

        var l3 = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.8, 1.2), leafMat);
        l3.position.set(0, 4.3, 0);
        g.add(l3);

        g.position.set(x, 0, z);
        var scale = 0.7 + Math.random() * 0.5;
        g.scale.set(scale, scale, scale);
        return g;
    };

    LlamaFarm.prototype._addFence = function (x1, z1, x2, z2) {
        var woodMat = new THREE.MeshLambertMaterial({ color: 0xa0703a });
        var dx = x2 - x1, dz = z2 - z1;
        var len = Math.sqrt(dx * dx + dz * dz);
        var numPosts = Math.ceil(len / 2.5);
        var g = new THREE.Group();

        for (var i = 0; i <= numPosts; i++) {
            var t = i / numPosts;
            var post = new THREE.Mesh(new THREE.BoxGeometry(0.15, 1.2, 0.15), woodMat);
            post.position.set(x1 + dx * t, 0.6, z1 + dz * t);
            g.add(post);
        }

        var angle = Math.atan2(dz, dx);
        var mx = (x1 + x2) / 2, mz = (z1 + z2) / 2;
        var railGeo = new THREE.BoxGeometry(len, 0.08, 0.08);

        var rail1 = new THREE.Mesh(railGeo, woodMat);
        rail1.position.set(mx, 0.4, mz);
        rail1.rotation.y = -angle;
        g.add(rail1);

        var rail2 = new THREE.Mesh(railGeo, woodMat);
        rail2.position.set(mx, 0.9, mz);
        rail2.rotation.y = -angle;
        g.add(rail2);

        this.scene.add(g);
    };

    LlamaFarm.prototype._createFlower = function (x, z) {
        var g = new THREE.Group();
        var stemMat = new THREE.MeshLambertMaterial({ color: 0x228822 });
        var stem = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.3, 0.05), stemMat);
        stem.position.set(0, 0.15, 0);
        g.add(stem);

        var cols = [0xff4466, 0xffdd44, 0xffffff, 0xff88cc, 0x88aaff, 0xff8844];
        var fCol = cols[Math.floor(Math.random() * cols.length)];
        var fMat = new THREE.MeshLambertMaterial({ color: fCol });
        var flower = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.18, 0.18), fMat);
        flower.position.set(0, 0.35, 0);
        flower.rotation.y = Math.random() * Math.PI;
        g.add(flower);

        g.position.set(x, 0, z);
        return g;
    };

    LlamaFarm.prototype._createRock = function (x, z) {
        var shade = 0x666666 + Math.floor(Math.random() * 0x222222);
        var mat = new THREE.MeshLambertMaterial({ color: shade });
        var w = 0.3 + Math.random() * 0.5;
        var h = 0.2 + Math.random() * 0.3;
        var d = 0.3 + Math.random() * 0.4;
        var rock = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
        rock.position.set(x, h / 2, z);
        rock.rotation.y = Math.random() * Math.PI;
        return rock;
    };

    LlamaFarm.prototype._createHayBale = function (x, z) {
        var mat = new THREE.MeshLambertMaterial({ color: 0xddbb55 });
        var darkMat = new THREE.MeshLambertMaterial({ color: 0xbb9933 });
        var g = new THREE.Group();

        var bale = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.8, 0.8), mat);
        bale.position.set(0, 0.4, 0);
        g.add(bale);

        // Straw band
        var band = new THREE.Mesh(new THREE.BoxGeometry(1.22, 0.12, 0.82), darkMat);
        band.position.set(0, 0.4, 0);
        g.add(band);

        g.position.set(x, 0, z);
        g.rotation.y = Math.random() * 0.5;
        return g;
    };

    LlamaFarm.prototype._createTrough = function (x, z) {
        var g = new THREE.Group();
        var woodMat = new THREE.MeshLambertMaterial({ color: 0x8b6b3d });
        var waterMat = new THREE.MeshLambertMaterial({
            color: 0x4488cc, transparent: true, opacity: 0.7
        });

        // Bottom
        var bottom = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.1, 0.6), woodMat);
        bottom.position.set(0, 0.3, 0);
        g.add(bottom);

        // Sides
        var s1 = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.4, 0.1), woodMat);
        s1.position.set(0, 0.4, 0.3);
        g.add(s1);
        var s2 = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.4, 0.1), woodMat);
        s2.position.set(0, 0.4, -0.3);
        g.add(s2);

        // Ends
        var e1 = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.4, 0.6), woodMat);
        e1.position.set(0.75, 0.4, 0);
        g.add(e1);
        var e2 = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.4, 0.6), woodMat);
        e2.position.set(-0.75, 0.4, 0);
        g.add(e2);

        // Water
        var water = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.12, 0.4), waterMat);
        water.position.set(0, 0.42, 0);
        g.add(water);

        // Legs
        var legMat = new THREE.MeshLambertMaterial({ color: 0x6b4b2d });
        [[-0.6, -0.2], [-0.6, 0.2], [0.6, -0.2], [0.6, 0.2]].forEach(function (lp) {
            var leg = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.3, 0.12), legMat);
            leg.position.set(lp[0], 0.15, lp[1]);
            g.add(leg);
        });

        g.position.set(x, 0, z);
        return g;
    };

    LlamaFarm.prototype._createSign = function (x, z) {
        var g = new THREE.Group();
        var woodMat = new THREE.MeshLambertMaterial({ color: 0x8b6b3d });

        // Posts
        var post1 = new THREE.Mesh(new THREE.BoxGeometry(0.2, 2.2, 0.2), woodMat);
        post1.position.set(-1.1, 1.1, 0);
        g.add(post1);
        var post2 = new THREE.Mesh(new THREE.BoxGeometry(0.2, 2.2, 0.2), woodMat);
        post2.position.set(1.1, 1.1, 0);
        g.add(post2);

        // Sign board
        var boardMat = new THREE.MeshLambertMaterial({ color: 0xc49a4a });
        var board = new THREE.Mesh(new THREE.BoxGeometry(2.6, 0.8, 0.15), boardMat);
        board.position.set(0, 1.9, 0);
        g.add(board);

        // Text via canvas texture
        var canvas = document.createElement('canvas');
        canvas.width = 256;
        canvas.height = 64;
        var ctx = canvas.getContext('2d');
        ctx.fillStyle = '#c49a4a';
        ctx.fillRect(0, 0, 256, 64);
        ctx.fillStyle = '#3a2210';
        ctx.font = 'bold 26px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('LLAMA FARM', 128, 32);

        var tex = new THREE.CanvasTexture(canvas);
        var signMat = new THREE.MeshBasicMaterial({ map: tex });
        var face = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 0.65), signMat);
        face.position.set(0, 1.9, 0.08);
        g.add(face);

        g.position.set(x, 0, z);
        return g;
    };

    /* ------ Wolf ------ */

    LlamaFarm.prototype._createVoxelWolf = function () {
        var g = new THREE.Group();
        // Light grey palette
        var furMat   = new THREE.MeshLambertMaterial({ color: 0xb0b0b0 });
        var darkMat  = new THREE.MeshLambertMaterial({ color: 0x8a8a8a });
        var bellyMat = new THREE.MeshLambertMaterial({ color: 0xc8c8c8 });
        var eyeMat   = new THREE.MeshLambertMaterial({ color: 0xffcc00 });
        var pupilMat = new THREE.MeshLambertMaterial({ color: 0x111111 });
        var noseMat  = new THREE.MeshLambertMaterial({ color: 0x222222 });

        // Body — same structure as llama but longer, lower
        var body = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.8, 1.0), furMat);
        body.position.set(0, 1.0, 0);
        g.add(body);

        // Belly
        var belly = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.2, 0.6), bellyMat);
        belly.position.set(0, 0.6, 0);
        g.add(belly);

        // Neck — shorter than llama, angled forward
        var neck = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.6, 0.4), furMat);
        neck.position.set(0.6, 1.5, 0);
        neck.rotation.z = 0.25;
        g.add(neck);

        // Head
        var head = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.45, 0.55), furMat);
        head.position.set(0.85, 1.85, 0);
        g.add(head);

        // Snout — longer than llama
        var snout = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.25, 0.35), darkMat);
        snout.position.set(1.2, 1.75, 0);
        g.add(snout);

        // Nose
        var nose = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.1, 0.12), noseMat);
        nose.position.set(1.38, 1.78, 0);
        g.add(nose);

        // Eyes — yellow
        var ewL = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.13, 0.06), eyeMat);
        ewL.position.set(1.05, 1.95, 0.2);
        g.add(ewL);
        var ewR = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.13, 0.06), eyeMat);
        ewR.position.set(1.05, 1.95, -0.2);
        g.add(ewR);

        var eyeL = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.07, 0.06), pupilMat);
        eyeL.position.set(1.08, 1.95, 0.2);
        g.add(eyeL);
        var eyeR = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.07, 0.06), pupilMat);
        eyeR.position.set(1.08, 1.95, -0.2);
        g.add(eyeR);

        // Ears — pointed, upright (like llama but triangular)
        var earL = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.35, 0.12), furMat);
        earL.position.set(0.85, 2.25, 0.17);
        earL.rotation.z = 0.15;
        g.add(earL);
        var earR = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.35, 0.12), furMat);
        earR.position.set(0.85, 2.25, -0.17);
        earR.rotation.z = -0.15;
        g.add(earR);

        // Legs — same pattern as llama
        var legGeo = new THREE.BoxGeometry(0.25, 0.6, 0.25);
        var fl = new THREE.Mesh(legGeo, darkMat); fl.position.set( 0.5, 0.3,  0.28); g.add(fl);
        var fr = new THREE.Mesh(legGeo, darkMat); fr.position.set( 0.5, 0.3, -0.28); g.add(fr);
        var bl = new THREE.Mesh(legGeo, darkMat); bl.position.set(-0.5, 0.3,  0.28); g.add(bl);
        var br = new THREE.Mesh(legGeo, darkMat); br.position.set(-0.5, 0.3, -0.28); g.add(br);

        // Tail — bushy, drooping
        var tail = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.4, 0.15), furMat);
        tail.position.set(-0.95, 0.9, 0);
        tail.rotation.z = 0.4;
        g.add(tail);
        var tailTip = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.25, 0.18), bellyMat);
        tailTip.position.set(-1.05, 0.6, 0);
        tail.rotation.z = 0.5;
        g.add(tailTip);

        // Store refs for animation
        g._legs = { fl: fl, fr: fr, bl: bl, br: br };
        g._tail = tail;
        g._tailTip = tailTip;

        return g;
    };

    LlamaFarm.prototype._addWolf = function () {
        var wolf = this._createVoxelWolf();
        wolf.position.set(17, 0, 0);
        // Model faces +X; start walking toward +Z
        wolf.rotation.y = -Math.PI / 2;
        this.scene.add(wolf);

        this._wolf = {
            group: wolf,
            pathZ: [-10, 10],
            direction: 1,
            speed: 0.8,
            currentZ: 0,
            stareTimer: 0,
            stareDuration: 0,
            isStaring: false,
        };
    };

    LlamaFarm.prototype._animateWolf = function (time) {
        var w = this._wolf;
        if (!w) return;
        var g = w.group;
        var dt = 0.016;

        if (w.isStaring) {
            w.stareTimer += dt;
            if (w.stareTimer > w.stareDuration) {
                w.isStaring = false;
                // Restore walk direction so it doesn't crab-walk
                g.rotation.y = w.direction > 0 ? -Math.PI / 2 : Math.PI / 2;
            } else {
                g.position.y = Math.sin(time * 2) * 0.02;
                // Stop leg swing while staring
                var legs = g._legs;
                legs.fl.rotation.x = 0; legs.fl.rotation.z = 0;
                legs.fr.rotation.x = 0; legs.fr.rotation.z = 0;
                legs.bl.rotation.x = 0; legs.bl.rotation.z = 0;
                legs.br.rotation.x = 0; legs.br.rotation.z = 0;
                return;
            }
        }

        // Prowl along the fence
        w.currentZ += w.direction * w.speed * dt;

        // Model faces +X. To walk +Z: rotate -PI/2. To walk -Z: rotate PI/2.
        // To stare at farm (-X): rotate PI.
        if (w.currentZ >= w.pathZ[1]) {
            w.currentZ = w.pathZ[1];
            w.direction = -1;
            g.rotation.y = Math.PI / 2; // face -Z (snout toward -Z)
            if (Math.random() < 0.4) {
                w.isStaring = true;
                w.stareTimer = 0;
                w.stareDuration = 2 + Math.random() * 3;
                g.rotation.y = Math.PI; // face the farm
            }
        } else if (w.currentZ <= w.pathZ[0]) {
            w.currentZ = w.pathZ[0];
            w.direction = 1;
            g.rotation.y = -Math.PI / 2; // face +Z
            if (Math.random() < 0.4) {
                w.isStaring = true;
                w.stareTimer = 0;
                w.stareDuration = 2 + Math.random() * 3;
                g.rotation.y = Math.PI; // face the farm
            }
        }

        g.position.z = w.currentZ;

        // Leg swing — swing around Z to move forward/backward
        var legSwing = Math.sin(time * 6) * 0.3;
        var legs = g._legs;
        legs.fl.rotation.z =  legSwing;
        legs.br.rotation.z =  legSwing;
        legs.fr.rotation.z = -legSwing;
        legs.bl.rotation.z = -legSwing;

        // Tail sway
        g._tail.rotation.x = Math.sin(time * 3) * 0.2;
        g._tailTip.rotation.x = Math.sin(time * 3) * 0.3;

        // Body bob
        g.position.y = Math.abs(Math.sin(time * 6)) * 0.04;
    };

    /* ------ Goose ------ */

    LlamaFarm.prototype._createVoxelGoose = function () {
        var g = new THREE.Group();
        var whiteMat = new THREE.MeshLambertMaterial({ color: 0xf5f5f0 });
        var orangeMat = new THREE.MeshLambertMaterial({ color: 0xff8800 });
        var eyeMat = new THREE.MeshLambertMaterial({ color: 0x111111 });

        // Body — oval-ish
        var body = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.35, 0.35), whiteMat);
        body.position.set(0, 0.4, 0);
        g.add(body);

        // Neck — tall, thin
        var neck = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.4, 0.12), whiteMat);
        neck.position.set(0.2, 0.75, 0);
        neck.rotation.z = -0.2;
        g.add(neck);

        // Head — small
        var head = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.15, 0.18), whiteMat);
        head.position.set(0.25, 1.0, 0);
        g.add(head);

        // Beak
        var beak = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.06, 0.1), orangeMat);
        beak.position.set(0.38, 0.97, 0);
        g.add(beak);

        // Eyes
        var eyeL = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.04, 0.04), eyeMat);
        eyeL.position.set(0.32, 1.03, 0.08);
        g.add(eyeL);
        var eyeR = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.04, 0.04), eyeMat);
        eyeR.position.set(0.32, 1.03, -0.08);
        g.add(eyeR);

        // Legs
        var legL = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.2, 0.06), orangeMat);
        legL.position.set(0, 0.12, 0.1);
        g.add(legL);
        var legR = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.2, 0.06), orangeMat);
        legR.position.set(0, 0.12, -0.1);
        g.add(legR);

        // Feet
        var footL = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.03, 0.1), orangeMat);
        footL.position.set(0.02, 0.02, 0.1);
        g.add(footL);
        var footR = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.03, 0.1), orangeMat);
        footR.position.set(0.02, 0.02, -0.1);
        g.add(footR);

        // Tail feathers
        var tail = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.2, 0.2), whiteMat);
        tail.position.set(-0.3, 0.5, 0);
        tail.rotation.z = 0.3;
        g.add(tail);

        // Store refs
        g._head = head;
        g._neck = neck;
        g._beak = beak;
        g._legL = legL;
        g._legR = legR;

        return g;
    };

    LlamaFarm.prototype._addGoose = function () {
        var goose = this._createVoxelGoose();
        goose.position.set(-4, 0, 5);
        this.scene.add(goose);

        this._goose = {
            group: goose,
            pos: { x: -4, z: 5 },
            target: { x: 2, z: -3 },
            facing: 0,
            speed: 1.2,
            state: 'walk',
            timer: 0,
            duration: 3,
        };
    };

    LlamaFarm.prototype._animateGoose = function (time) {
        var gs = this._goose;
        if (!gs) return;
        var g = gs.group;
        var dt = 0.016;

        if (gs.state === 'walk') {
            // Move toward target
            var dx = gs.target.x - gs.pos.x;
            var dz = gs.target.z - gs.pos.z;
            var dist = Math.sqrt(dx * dx + dz * dz);

            if (dist < 0.2) {
                // Pick new target
                if (Math.random() < 0.3) {
                    gs.state = 'idle';
                    gs.timer = time;
                    gs.duration = 1 + Math.random() * 2;
                } else {
                    var angle = Math.random() * Math.PI * 2;
                    var r = 3 + Math.random() * 6;
                    gs.target.x = Math.cos(angle) * r;
                    gs.target.z = Math.sin(angle) * r;
                    gs.target.x = Math.max(-FARM_BOUNDS, Math.min(FARM_BOUNDS, gs.target.x));
                    gs.target.z = Math.max(-FARM_BOUNDS, Math.min(FARM_BOUNDS, gs.target.z));
                }
            } else {
                var nx = dx / dist, nz = dz / dist;
                gs.pos.x += nx * gs.speed * dt;
                gs.pos.z += nz * gs.speed * dt;
                gs.facing = Math.atan2(dx, dz) - Math.PI / 2;
            }

            g.position.x = gs.pos.x;
            g.position.z = gs.pos.z;
            g.rotation.y = gs.facing;

            // Waddle walk
            var waddle = Math.sin(time * 10) * 0.15;
            g._legL.rotation.z = waddle;
            g._legR.rotation.z = -waddle;
            g.position.y = Math.abs(Math.sin(time * 10)) * 0.03;

            // Head bob
            g._head.position.y = 1.0 + Math.sin(time * 10) * 0.03;
            g._neck.position.y = 0.75 + Math.sin(time * 10) * 0.02;
            g._head.rotation.y = 0;

        } else {
            // Idle — look around
            g.position.x = gs.pos.x;
            g.position.z = gs.pos.z;
            g.position.y = 0;
            g.rotation.y = gs.facing;
            g._legL.rotation.z = 0;
            g._legR.rotation.z = 0;
            g._head.rotation.y = Math.sin(time * 2) * 0.4;

            if (time - gs.timer > gs.duration) {
                gs.state = 'walk';
                var angle = Math.random() * Math.PI * 2;
                var r = 3 + Math.random() * 6;
                gs.target.x = Math.cos(angle) * r;
                gs.target.z = Math.sin(angle) * r;
                gs.target.x = Math.max(-FARM_BOUNDS, Math.min(FARM_BOUNDS, gs.target.x));
                gs.target.z = Math.max(-FARM_BOUNDS, Math.min(FARM_BOUNDS, gs.target.z));
            }
        }
    };

    LlamaFarm.prototype._checkGooseScare = function (e) {
        var gs = this._goose;
        if (!gs) return;
        var rect = this.renderer.domElement.getBoundingClientRect();
        var mx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        var my = -((e.clientY - rect.top) / rect.height) * 2 + 1;
        this._raycaster.setFromCamera({ x: mx, y: my }, this.camera);
        var intersects = this._raycaster.intersectObjects(gs.group.children, false);
        if (intersects.length > 0) {
            // Cooldown: only count as new scare every 1.5s
            var now = Date.now();
            if (now - (gs._lastScareTime || 0) < 1500) return;
            gs._lastScareTime = now;
            gs._scareCount = (gs._scareCount || 0) + 1;
            // Flee away from camera ray hit point
            var hit = intersects[0].point;
            var fleeAngle = Math.atan2(gs.pos.z - hit.z, gs.pos.x - hit.x);
            var fleeDist = 5 + Math.random() * 4;
            gs.target.x = gs.pos.x + Math.cos(fleeAngle) * fleeDist;
            gs.target.z = gs.pos.z + Math.sin(fleeAngle) * fleeDist;
            gs.target.x = Math.max(-FARM_BOUNDS, Math.min(FARM_BOUNDS, gs.target.x));
            gs.target.z = Math.max(-FARM_BOUNDS, Math.min(FARM_BOUNDS, gs.target.z));
            gs.state = 'walk';
            gs.speed = 3.5; // run!
            // Show angry bubble after 2 scares
            if (gs._scareCount > 2) {
                var msgs = ['Leave me alone!', 'HISSSSS!', 'HONK HONK!', 'Cluck cluck cluck!'];
                var msg = msgs[Math.floor(Math.random() * msgs.length)];
                this._showGooseBubble(msg);
            }
            // Slow back down after a bit
            var self = this;
            clearTimeout(gs._slowTimer);
            gs._slowTimer = setTimeout(function () { gs.speed = 1.2; }, 2000);
        }
    };

    LlamaFarm.prototype._showGooseBubble = function (text) {
        var gs = this._goose;
        if (!gs) return;
        // Remove existing bubble
        if (gs._bubble) {
            gs.group.remove(gs._bubble);
            gs._bubble.material.map.dispose();
            gs._bubble.material.dispose();
            gs._bubble.geometry.dispose();
            gs._bubble = null;
        }
        var bubble = this._createSpeechBubble(text);
        bubble.position.set(0, 2.0, 0);
        gs.group.add(bubble);
        gs._bubble = bubble;
        // Remove after 2.5 seconds
        var self = this;
        clearTimeout(gs._bubbleTimer);
        gs._bubbleTimer = setTimeout(function () {
            if (gs._bubble) {
                gs.group.remove(gs._bubble);
                gs._bubble.material.map.dispose();
                gs._bubble.material.dispose();
                gs._bubble.geometry.dispose();
                gs._bubble = null;
            }
        }, 2500);
    };

    LlamaFarm.prototype._addClouds = function () {
        var cloudMat = new THREE.MeshLambertMaterial({
            color: 0xffffff, transparent: true, opacity: 0.75
        });

        var cloudData = [
            { x: -12, y: 16, z: -10, s: 1.4 },
            { x:  10, y: 18, z:   6, s: 1.1 },
            { x:  -5, y: 20, z:  14, s: 1.0 },
            { x:  16, y: 17, z:  -5, s: 1.3 },
            { x: -18, y: 19, z:   5, s: 0.9 },
        ];

        var self = this;
        self._clouds = [];

        cloudData.forEach(function (cd) {
            var g = new THREE.Group();

            var main = new THREE.Mesh(new THREE.BoxGeometry(3.5, 1, 2.5), cloudMat);
            g.add(main);

            var bump1 = new THREE.Mesh(new THREE.BoxGeometry(2.2, 1.2, 1.8), cloudMat);
            bump1.position.set(-0.5, 0.5, 0);
            g.add(bump1);

            var bump2 = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.9, 1.4), cloudMat);
            bump2.position.set(0.8, 0.4, 0.3);
            g.add(bump2);

            g.position.set(cd.x, cd.y, cd.z);
            g.scale.multiplyScalar(cd.s);
            self.scene.add(g);
            self._clouds.push({ group: g, baseX: cd.x, speed: 0.1 + Math.random() * 0.15 });
        });
    };

    /* ------ Voxel Llama Builder ------ */

    LlamaFarm.prototype._createVoxelLlama = function (color, isOrchestrator) {
        var g = new THREE.Group();
        var mat = new THREE.MeshLambertMaterial({ color: color });
        var darkMat = new THREE.MeshLambertMaterial({ color: darkenColor(color, 0.2) });
        var noseMat = new THREE.MeshLambertMaterial({ color: darkenColor(color, 0.1) });

        // Body
        var body = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.0, 1.0), mat);
        body.position.set(0, 1.2, 0);
        g.add(body);

        // Neck
        var neck = new THREE.Mesh(new THREE.BoxGeometry(0.4, 1.0, 0.4), mat);
        neck.position.set(0.55, 2.0, 0);
        g.add(neck);

        // Head
        var head = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.5, 0.55), mat);
        head.position.set(0.55, 2.75, 0);
        g.add(head);

        // Snout
        var snout = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.25, 0.35), noseMat);
        snout.position.set(0.9, 2.65, 0);
        g.add(snout);

        // Eyes
        var eyeMat = new THREE.MeshLambertMaterial({ color: 0x111111 });
        var eyeWhiteMat = new THREE.MeshLambertMaterial({ color: 0xffffff });

        var ewL = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.13, 0.06), eyeWhiteMat);
        ewL.position.set(0.83, 2.82, 0.17);
        g.add(ewL);
        var ewR = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.13, 0.06), eyeWhiteMat);
        ewR.position.set(0.83, 2.82, -0.17);
        g.add(ewR);

        var eyeL = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.07, 0.06), eyeMat);
        eyeL.position.set(0.86, 2.83, 0.17);
        g.add(eyeL);
        var eyeR = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.07, 0.06), eyeMat);
        eyeR.position.set(0.86, 2.83, -0.17);
        g.add(eyeR);

        // Ears
        var earL = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.35, 0.12), mat);
        earL.position.set(0.55, 3.15, 0.17);
        earL.rotation.z = 0.15;
        g.add(earL);
        var earR = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.35, 0.12), mat);
        earR.position.set(0.55, 3.15, -0.17);
        earR.rotation.z = -0.15;
        g.add(earR);

        // Legs
        var legGeo = new THREE.BoxGeometry(0.25, 0.7, 0.25);
        var fl = new THREE.Mesh(legGeo, darkMat); fl.position.set( 0.5, 0.35,  0.28); g.add(fl);
        var fr = new THREE.Mesh(legGeo, darkMat); fr.position.set( 0.5, 0.35, -0.28); g.add(fr);
        var bl = new THREE.Mesh(legGeo, darkMat); bl.position.set(-0.5, 0.35,  0.28); g.add(bl);
        var br = new THREE.Mesh(legGeo, darkMat); br.position.set(-0.5, 0.35, -0.28); g.add(br);

        // Tail
        var tail = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.4, 0.15), mat);
        tail.position.set(-0.95, 1.5, 0);
        tail.rotation.z = -0.3;
        g.add(tail);

        // Fluffy chest wool
        var woolMat = new THREE.MeshLambertMaterial({ color: darkenColor(color, -0.05) || color });
        var wool = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.5, 0.6), woolMat);
        wool.position.set(0.7, 1.5, 0);
        g.add(wool);

        // Sheriff star for orchestrator — floating golden badge
        if (isOrchestrator) {
            var starGroup = new THREE.Group();
            var starMat = new THREE.MeshLambertMaterial({ color: 0xffd700 });
            var starDarkMat = new THREE.MeshLambertMaterial({ color: 0xdaa520 });
            var starShinyMat = new THREE.MeshLambertMaterial({ color: 0xffec80 });

            // Build a 6-pointed sheriff star from overlapping rotated boxes
            var starR = 0.42; // outer radius
            var starThick = 0.08;
            // 3 overlapping diamonds at 60-degree intervals create a 6-point star
            for (var si = 0; si < 3; si++) {
                var blade = new THREE.Mesh(
                    new THREE.BoxGeometry(starR * 2, starThick, starR * 0.55), starMat
                );
                blade.rotation.y = (si * Math.PI) / 3;
                starGroup.add(blade);
            }

            // Center circle badge
            var badge = new THREE.Mesh(
                new THREE.BoxGeometry(0.32, starThick + 0.02, 0.32), starDarkMat
            );
            badge.rotation.y = Math.PI / 4; // diamond orientation
            starGroup.add(badge);

            // Inner highlight
            var inner = new THREE.Mesh(
                new THREE.BoxGeometry(0.18, starThick + 0.04, 0.18), starShinyMat
            );
            inner.rotation.y = Math.PI / 4;
            starGroup.add(inner);

            // Tiny center gem
            var gemMat = new THREE.MeshLambertMaterial({ color: 0xff2244 });
            var centerGem = new THREE.Mesh(
                new THREE.BoxGeometry(0.08, starThick + 0.06, 0.08), gemMat
            );
            starGroup.add(centerGem);

            // Position floating above head, tilted to face camera
            starGroup.position.set(0.55, 3.35, 0);
            starGroup.rotation.x = -Math.PI / 6; // tilt forward slightly
            g.add(starGroup);
            g._sheriffStar = starGroup;
        }

        // Blob shadow — use polygonOffset to avoid z-fighting with ground
        var shadowGeo = new THREE.CircleGeometry(0.9, 16);
        var shadowMat = new THREE.MeshBasicMaterial({
            color: 0x000000, transparent: true, opacity: 0.15,
            depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1
        });
        var shadow = new THREE.Mesh(shadowGeo, shadowMat);
        shadow.rotation.x = -Math.PI / 2;
        shadow.position.set(0, 0.05, 0);
        g.add(shadow);

        // Store part references for animation
        g.userData.parts = {
            body: body, neck: neck, head: head, snout: snout,
            ears: [earL, earR],
            legs: { fl: fl, fr: fr, bl: bl, br: br },
            tail: tail, shadow: shadow,
        };

        return g;
    };

    /* ------ Label Sprite (farm-themed parchment style) ------ */

    LlamaFarm.prototype._createLabel = function (text, statusColorHex) {
        var canvas = document.createElement('canvas');
        var ctx = canvas.getContext('2d');
        canvas.width = 256;
        canvas.height = 64;

        // Parchment background
        ctx.fillStyle = 'rgba(245, 230, 200, 0.85)';
        roundRect(ctx, 4, 4, 248, 56, 10);
        ctx.fill();

        // Warm border
        ctx.strokeStyle = statusColorHex || '#9B8B7A';
        ctx.lineWidth = 3;
        roundRect(ctx, 4, 4, 248, 56, 10);
        ctx.stroke();

        // Text — brown on parchment
        ctx.fillStyle = '#4A3520';
        ctx.font = 'bold 20px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(text.substring(0, 18), 128, 32);

        var texture = new THREE.CanvasTexture(canvas);
        texture.minFilter = THREE.LinearFilter;
        var material = new THREE.SpriteMaterial({
            map: texture, transparent: true, depthTest: false
        });
        var sprite = new THREE.Sprite(material);
        sprite.scale.set(2.8, 0.7, 1);
        return sprite;
    };

    /* ------ Speech Bubble Sprite ------ */

    LlamaFarm.prototype._createSpeechBubble = function (text) {
        var canvas = document.createElement('canvas');
        var ctx = canvas.getContext('2d');
        canvas.width = 256;
        canvas.height = 128;

        // Auto-size font based on text length
        var fontSize = text.length > 18 ? 16 : text.length > 12 ? 19 : 22;
        ctx.font = 'bold ' + fontSize + 'px sans-serif';
        var metrics = ctx.measureText(text);
        var textWidth = Math.min(metrics.width + 32, 244);
        var bubbleX = (256 - textWidth) / 2;
        var bubbleW = textWidth;
        var bubbleH = 48;
        var bubbleY = 8;

        // White bubble with rounded corners
        ctx.fillStyle = '#FFFFFF';
        roundRect(ctx, bubbleX, bubbleY, bubbleW, bubbleH, 14);
        ctx.fill();

        // Subtle brown border
        ctx.strokeStyle = '#C4956A';
        ctx.lineWidth = 2.5;
        roundRect(ctx, bubbleX, bubbleY, bubbleW, bubbleH, 14);
        ctx.stroke();

        // Speech tail (triangle pointing down)
        var tailX = 128;
        var tailY = bubbleY + bubbleH;
        ctx.fillStyle = '#FFFFFF';
        ctx.beginPath();
        ctx.moveTo(tailX - 8, tailY - 1);
        ctx.lineTo(tailX, tailY + 14);
        ctx.lineTo(tailX + 8, tailY - 1);
        ctx.closePath();
        ctx.fill();
        // Tail border
        ctx.strokeStyle = '#C4956A';
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.moveTo(tailX - 8, tailY);
        ctx.lineTo(tailX, tailY + 14);
        ctx.lineTo(tailX + 8, tailY);
        ctx.stroke();
        // Cover the border inside bubble where tail meets
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(tailX - 9, tailY - 3, 18, 4);

        // Text
        ctx.fillStyle = '#4A3520';
        ctx.font = 'bold ' + fontSize + 'px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(text, 128, bubbleY + bubbleH / 2);

        var texture = new THREE.CanvasTexture(canvas);
        texture.minFilter = THREE.LinearFilter;
        var material = new THREE.SpriteMaterial({
            map: texture, transparent: true, depthTest: false, opacity: 1.0
        });
        var sprite = new THREE.Sprite(material);
        sprite.scale.set(3.2, 1.6, 1);
        return sprite;
    };

    /* ------ Status Ring ------ */

    LlamaFarm.prototype._createStatusRing = function (color) {
        var geo = new THREE.RingGeometry(1.0, 1.3, 32);
        var mat = new THREE.MeshBasicMaterial({
            color: color, transparent: true, opacity: 0.35,
            side: THREE.DoubleSide, depthWrite: false,
            polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2
        });
        var ring = new THREE.Mesh(geo, mat);
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.06;
        return ring;
    };

    /* ================================================================
       Speech Bubble Management
       ================================================================ */

    LlamaFarm.prototype._showBubble = function (agentId, text, isAction) {
        var llama = this.llamas[agentId];
        if (!llama) return;

        // Remove existing bubble
        this._hideBubble(agentId);

        var bubble = this._createSpeechBubble(text);
        bubble.position.set(0, 5.0, 0);
        llama.group.add(bubble);

        llama._bubble = bubble;
        llama._bubbleTime = this._clock.getElapsedTime();
        llama._bubbleText = text;
        llama._bubbleIsAction = !!isAction;
    };

    LlamaFarm.prototype._hideBubble = function (agentId) {
        var llama = this.llamas[agentId];
        if (!llama || !llama._bubble) return;

        llama.group.remove(llama._bubble);
        if (llama._bubble.material.map) llama._bubble.material.map.dispose();
        llama._bubble.material.dispose();
        llama._bubble = null;
        llama._bubbleTime = 0;
        llama._bubbleText = '';
        llama._bubbleIsAction = false;
    };

    LlamaFarm.prototype._triggerStatusBubble = function (agentId, status) {
        var llama = this.llamas[agentId];
        if (!llama) return;

        // Respect cooldown
        var now = this._clock.getElapsedTime();
        if (llama._lastBubbleTime && (now - llama._lastBubbleTime) < BUBBLE_COOLDOWN) return;

        var pool = llama.isOrchestrator ? SPEECH_BUBBLES.orchestrator : (SPEECH_BUBBLES[status] || SPEECH_BUBBLES.idle);
        var msg = pickRandom(pool);
        this._showBubble(agentId, msg);
        llama._lastBubbleTime = now;
    };

    /* ================================================================
       Public API
       ================================================================ */

    LlamaFarm.prototype.addLlama = function (agentId, isOrchestrator) {
        console.log('[LlamaFarm] addLlama called:', agentId, 'isOrch:', isOrchestrator, 'existing:', !!this.llamas[agentId]);
        if (this.llamas[agentId]) return;

        var color = isOrchestrator
            ? ORCH_COLOR
            : LLAMA_PALETTE[this._colorIdx % LLAMA_PALETTE.length];
        if (!isOrchestrator) this._colorIdx++;

        var group = this._createVoxelLlama(color, isOrchestrator);

        // Position
        var pos, ry;
        if (isOrchestrator) {
            pos = { x: 0, z: 0 };
            ry = 0;
        } else {
            var spot = WORKER_SPOTS[this._spotIdx % WORKER_SPOTS.length];
            this._spotIdx++;
            pos = { x: spot.x, z: spot.z };
            ry = spot.ry;
        }

        group.position.set(pos.x, 0, pos.z);
        group.rotation.y = ry || 0;

        // Label — orchestrator gets a royal name
        var displayName = isOrchestrator ? 'Llama King' : agentId.replace(/^llama-/, 'Llama-');
        var label = this._createLabel(displayName, '#9B8B7A');
        label.position.set(0, 3.8, 0);
        group.add(label);

        // Status ring
        var ring = this._createStatusRing(STATUS_COLORS.idle);
        group.add(ring);

        // Spawn animation — start tiny
        group.scale.set(0.01, 0.01, 0.01);

        this.scene.add(group);

        var now = this._clock.getElapsedTime();
        this.llamas[agentId] = {
            group: group,
            label: label,
            ring: ring,
            color: color,
            isOrchestrator: isOrchestrator,
            basePos: { x: pos.x, z: pos.z },
            baseRy: ry || 0,
            status: 'idle',
            goal: '',
            spawnTime: now,
            _animPhase: Math.random() * Math.PI * 2,
            // Speech bubble state
            _bubble: null,
            _bubbleTime: 0,
            _bubbleText: '',
            _bubbleIsAction: false,
            _lastBubbleTime: 0,
            _lastActionStr: '',
            // Wander state
            _wanderState: 'walk',
            _wanderTarget: { x: pos.x, z: pos.z },
            _wanderStartPos: { x: pos.x, z: pos.z },
            _wanderCurrentPos: { x: pos.x, z: pos.z },
            _wanderFacing: ry || 0,
            _wanderMoveAngle: (ry || 0) + Math.PI / 2, // initial straight direction
            _wanderTimer: now,
            _wanderDuration: 0.1, // arrive immediately, triggers first real walk
        };

        // Kick off first walk with a proper straight-line target
        this._startWanderWalk(llama, now);

        // Show spawn speech bubble
        var spawnMsg = pickRandom(SPEECH_BUBBLES.spawn);
        // Delay bubble slightly so it appears after grow animation
        var self = this;
        setTimeout(function () {
            self._showBubble(agentId, spawnMsg);
            if (self.llamas[agentId]) {
                self.llamas[agentId]._lastBubbleTime = self._clock.getElapsedTime();
            }
        }, 700);

        console.log('[LlamaFarm] Llama added OK:', agentId, 'at', pos.x, pos.z, 'total:', Object.keys(this.llamas).length);
    };

    LlamaFarm.prototype.removeLlama = function (agentId) {
        var llama = this.llamas[agentId];
        if (!llama) return;
        // Clean up speech bubble
        this._hideBubble(agentId);
        this.scene.remove(llama.group);
        llama.group.traverse(function (child) {
            if (child.geometry) child.geometry.dispose();
            if (child.material) {
                if (child.material.map) child.material.map.dispose();
                child.material.dispose();
            }
        });
        delete this.llamas[agentId];
    };

    LlamaFarm.prototype.updateLlama = function (agentId, state) {
        var llama = this.llamas[agentId];
        if (!llama) return;

        var newStatus = state.status || 'idle';
        var newGoal = state.goal || '';
        var statusChanged = llama.status !== newStatus;

        if (statusChanged || llama.goal !== newGoal) {
            // Update ring color
            var statusCol = llama.isOrchestrator
                ? STATUS_COLORS.orchestrator
                : (STATUS_COLORS[newStatus] || STATUS_COLORS.idle);
            llama.ring.material.color.setHex(statusCol);

            // Update label — just the name, no goal text
            var labelText = llama.isOrchestrator ? 'Llama King' : agentId.replace(/^llama-/, 'Llama-');
            var colorStr = '#' + statusCol.toString(16).padStart(6, '0');

            llama.group.remove(llama.label);
            if (llama.label.material.map) llama.label.material.map.dispose();
            llama.label.material.dispose();

            llama.label = this._createLabel(labelText, colorStr);
            llama.label.position.set(0, 3.8, 0);
            llama.group.add(llama.label);
        }

        // Show real Ollama action as speech bubble, cute sounds as fallback
        var actionText = formatActionText(state.lastAction);
        var now = this._clock.getElapsedTime();
        var cooldownOk = !llama._lastBubbleTime || (now - llama._lastBubbleTime) >= BUBBLE_COOLDOWN;
        var actionChanged = actionText && actionText !== llama._lastActionStr;

        if (actionChanged && cooldownOk) {
            // New action from Ollama — show it
            this._showBubble(agentId, actionText, true);
            llama._lastBubbleTime = now;
            llama._lastActionStr = actionText;
        } else if (statusChanged && cooldownOk) {
            // No new action but status changed — cute sound
            this._triggerStatusBubble(agentId, newStatus);
        }

        // Reset wander when entering idle so llama doesn't snap to old wander pos
        if (statusChanged && newStatus === 'idle') {
            llama._wanderState = 'rest';
            llama._wanderTimer = this._clock.getElapsedTime();
            llama._wanderDuration = 1 + Math.random() * 3;
            // Keep current position as wander pos
            llama._wanderCurrentPos.x = llama.group.position.x;
            llama._wanderCurrentPos.z = llama.group.position.z;
        }

        llama.status = newStatus;
        llama.goal = newGoal;
    };

    /* ================================================================
       Renderer
       ================================================================ */

    LlamaFarm.prototype._initRenderer = function () {
        this.renderer = new THREE.WebGLRenderer({ antialias: true });
        this.renderer.setSize(
            this.container.clientWidth || 800,
            this.container.clientHeight || 600
        );
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.container.appendChild(this.renderer.domElement);
    };

    /* ================================================================
       Mouse Controls (drag to orbit)
       ================================================================ */

    LlamaFarm.prototype._initMouseControls = function () {
        var self = this;
        var el = this.renderer.domElement;
        var CLICK_THRESHOLD = 5;

        el.addEventListener('mousedown', function (e) {
            self._isDragging = true;
            self._prevMouseX = e.clientX;
            self._mouseDownPos = { x: e.clientX, y: e.clientY };
        });
        el.addEventListener('mousemove', function (e) {
            // Check goose scare
            self._checkGooseScare(e);
            if (!self._isDragging) return;
            var dx = e.clientX - self._prevMouseX;
            self._cameraAngle += dx * 0.005;
            self._prevMouseX = e.clientX;
            self._updateCameraPosition();
        });
        el.addEventListener('mouseup', function (e) {
            var wasDrag = self._isDragging &&
                (Math.abs(e.clientX - self._mouseDownPos.x) > CLICK_THRESHOLD ||
                 Math.abs(e.clientY - self._mouseDownPos.y) > CLICK_THRESHOLD);
            self._isDragging = false;
            if (!wasDrag) self._handleClick(e);
        });
        el.addEventListener('mouseleave', function () { self._isDragging = false; });

        // Touch support
        el.addEventListener('touchstart', function (e) {
            if (e.touches.length === 1) {
                self._isDragging = true;
                self._prevMouseX = e.touches[0].clientX;
                self._mouseDownPos = { x: e.touches[0].clientX, y: e.touches[0].clientY };
            }
        });
        el.addEventListener('touchmove', function (e) {
            if (!self._isDragging || e.touches.length !== 1) return;
            var dx = e.touches[0].clientX - self._prevMouseX;
            self._cameraAngle += dx * 0.005;
            self._prevMouseX = e.touches[0].clientX;
            self._updateCameraPosition();
        });
        el.addEventListener('touchend', function (e) {
            var touch = e.changedTouches[0];
            var wasDrag = Math.abs(touch.clientX - self._mouseDownPos.x) > CLICK_THRESHOLD ||
                          Math.abs(touch.clientY - self._mouseDownPos.y) > CLICK_THRESHOLD;
            self._isDragging = false;
            if (!wasDrag) self._handleClick({ clientX: touch.clientX, clientY: touch.clientY });
        });

        el.style.cursor = 'grab';
    };

    /* ================================================================
       Click -> Raycast to find llama
       ================================================================ */

    LlamaFarm.prototype._handleClick = function (e) {
        var rect = this.renderer.domElement.getBoundingClientRect();
        this._mouseVec.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        this._mouseVec.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
        this._raycaster.setFromCamera(this._mouseVec, this.camera);

        var allMeshes = [];
        var meshToAgent = {};
        var ids = Object.keys(this.llamas);
        for (var i = 0; i < ids.length; i++) {
            var agentId = ids[i];
            var llama = this.llamas[agentId];
            llama.group.traverse(function (child) {
                if (child.isMesh) {
                    allMeshes.push(child);
                    meshToAgent[child.id] = agentId;
                }
            });
        }

        var intersects = this._raycaster.intersectObjects(allMeshes, false);
        if (intersects.length > 0) {
            var hitAgentId = meshToAgent[intersects[0].object.id];
            if (hitAgentId) {
                this.selectLlama(hitAgentId);
                if (this.onLlamaClick) this.onLlamaClick(hitAgentId);
            }
        }
    };

    /* ================================================================
       Selection highlight
       ================================================================ */

    LlamaFarm.prototype.selectLlama = function (agentId) {
        if (this._selectionRing && this._selectedAgentId && this.llamas[this._selectedAgentId]) {
            this.llamas[this._selectedAgentId].group.remove(this._selectionRing);
        }
        if (this._selectionRing) {
            if (this._selectionRing.geometry) this._selectionRing.geometry.dispose();
            if (this._selectionRing.material) this._selectionRing.material.dispose();
            this._selectionRing = null;
        }
        this._selectedAgentId = agentId;
        var llama = this.llamas[agentId];
        if (!llama) return;

        var geo = new THREE.RingGeometry(1.6, 1.9, 32);
        var mat = new THREE.MeshBasicMaterial({
            color: 0x4FC3F7, side: THREE.DoubleSide,
            transparent: true, opacity: 0.7,
        });
        this._selectionRing = new THREE.Mesh(geo, mat);
        this._selectionRing.rotation.x = -Math.PI / 2;
        this._selectionRing.position.y = 0.05;
        llama.group.add(this._selectionRing);
    };

    LlamaFarm.prototype.deselectLlama = function () {
        if (this._selectionRing && this._selectedAgentId && this.llamas[this._selectedAgentId]) {
            this.llamas[this._selectedAgentId].group.remove(this._selectionRing);
        }
        if (this._selectionRing) {
            if (this._selectionRing.geometry) this._selectionRing.geometry.dispose();
            if (this._selectionRing.material) this._selectionRing.material.dispose();
            this._selectionRing = null;
        }
        this._selectedAgentId = null;
    };

    /* ================================================================
       Animation Loop
       ================================================================ */

    LlamaFarm.prototype._animate = function () {
        if (this._paused || this._disposed) return;
        requestAnimationFrame(this._animate);

        var time = this._clock.getElapsedTime();

        // Slow auto-rotate camera
        if (!this._isDragging) {
            this._cameraAngle += 0.00008;
            this._updateCameraPosition();
        }

        // Animate clouds
        if (this._clouds) {
            for (var c = 0; c < this._clouds.length; c++) {
                var cloud = this._clouds[c];
                cloud.group.position.x = cloud.baseX + Math.sin(time * cloud.speed) * 3;
            }
        }

        // Animate llamas
        var ids = Object.keys(this.llamas);
        for (var i = 0; i < ids.length; i++) {
            var llama = this.llamas[ids[i]];
            this._animateLlama(llama, time);
            this._animateBubble(llama, time);
        }

        // Animate wolf
        this._animateWolf(time);

        // Animate goose
        this._animateGoose(time);

        this.renderer.render(this.scene, this.camera);
    };

    LlamaFarm.prototype._pickWanderTarget = function (llama) {
        var cx = llama._wanderCurrentPos.x;
        var cz = llama._wanderCurrentPos.z;
        // Use stored movement angle for forward bias
        var lastAngle = llama._wanderMoveAngle || (Math.random() * Math.PI * 2);
        var dist = 4 + Math.random() * 5;
        // 80% forward-ish, 20% random turn
        var angle;
        if (Math.random() < 0.8) {
            angle = lastAngle + (Math.random() - 0.5) * 0.8; // ±23° deviation
        } else {
            angle = lastAngle + (Math.random() - 0.5) * Math.PI; // bigger turn
        }
        var x = cx + Math.cos(angle) * dist;
        var z = cz + Math.sin(angle) * dist;
        // If out of bounds, turn toward center
        if (x < -FARM_BOUNDS + 1 || x > FARM_BOUNDS - 1 || z < -FARM_BOUNDS + 1 || z > FARM_BOUNDS - 1) {
            angle = Math.atan2(-cz, -cx) + (Math.random() - 0.5) * 0.6;
            x = cx + Math.cos(angle) * dist;
            z = cz + Math.sin(angle) * dist;
        }
        x = Math.max(-FARM_BOUNDS, Math.min(FARM_BOUNDS, x));
        z = Math.max(-FARM_BOUNDS, Math.min(FARM_BOUNDS, z));
        llama._wanderMoveAngle = angle;
        return { x: x, z: z };
    };

    LlamaFarm.prototype._startWanderWalk = function (llama, time) {
        llama._wanderTarget = this._pickWanderTarget(llama);
        llama._wanderStartPos = { x: llama._wanderCurrentPos.x, z: llama._wanderCurrentPos.z };
        var dx = llama._wanderTarget.x - llama._wanderStartPos.x;
        var dz = llama._wanderTarget.z - llama._wanderStartPos.z;
        var dist = Math.sqrt(dx * dx + dz * dz);
        llama._wanderDuration = Math.max(dist / WANDER_SPEED, 0.5);
        llama._wanderTimer = time;
        llama._wanderState = 'walk';
    };

    LlamaFarm.prototype._animateBubble = function (llama, time) {
        if (!llama._bubble) return;

        var age = time - llama._bubbleTime;
        var dur = llama._bubbleIsAction ? BUBBLE_DURATION_ACTION : BUBBLE_DURATION;

        // Fade in during first 0.3s
        if (age < 0.3) {
            var fadeIn = age / 0.3;
            llama._bubble.material.opacity = fadeIn;
            llama._bubble.position.y = 4.5 + fadeIn * 0.5;
        }
        // Visible — gentle bob
        else if (age < dur - 0.5) {
            llama._bubble.material.opacity = 1.0;
            llama._bubble.position.y = 5.0 + Math.sin(time * 2) * 0.08;
        }
        // Fade out during last 0.5s
        else if (age < dur) {
            var fadeOut = 1.0 - (age - (dur - 0.5)) / 0.5;
            llama._bubble.material.opacity = Math.max(0, fadeOut);
            llama._bubble.position.y = 5.0 + (1 - fadeOut) * 0.3;
        }
        // Remove
        else {
            var agentId = null;
            var llamaIds = Object.keys(this.llamas);
            for (var k = 0; k < llamaIds.length; k++) {
                if (this.llamas[llamaIds[k]] === llama) {
                    agentId = llamaIds[k];
                    break;
                }
            }
            if (agentId) this._hideBubble(agentId);
        }
    };

    LlamaFarm.prototype._animateLlama = function (llama, time) {
        var g = llama.group;
        var p = g.userData.parts;
        var t = time + llama._animPhase;
        var status = llama.status;

        // Spawn bounce animation
        var age = time - llama.spawnTime;
        if (age < 0.6) {
            var s = easeOutBack(Math.min(age / 0.6, 1));
            g.scale.set(s, s, s);
            return;
        } else if (g.scale.x < 0.99) {
            g.scale.set(1, 1, 1);
        }

        // Spin sheriff star if present
        if (g._sheriffStar) {
            g._sheriffStar.rotation.z = t * 0.8;
            g._sheriffStar.position.y = 3.35 + Math.sin(t * 1.5) * 0.08;
        }

        if (status === 'thinking' || (llama.isOrchestrator && status !== 'error' && status !== 'acting')) {
            // Return to base
            g.position.x = llama.basePos.x;
            g.position.z = llama.basePos.z;
            g.rotation.y = llama.baseRy;
            // Head bob — looking around
            p.head.position.y = 2.75 + Math.sin(t * 3) * 0.1;
            p.head.rotation.y = 0; p.head.rotation.z = 0;
            p.neck.position.y = 2.0 + Math.sin(t * 3) * 0.05;
            // Ear wiggle
            p.ears[0].rotation.z =  0.15 + Math.sin(t * 5) * 0.2;
            p.ears[1].rotation.z = -0.15 - Math.sin(t * 5 + 1) * 0.2;
            // Ring pulse
            llama.ring.material.opacity = 0.25 + Math.sin(t * 4) * 0.2;
            llama.ring.rotation.z = t * 0.5;
            // Gentle body sway
            p.body.position.y = 1.2 + Math.sin(t * 2) * 0.02;
            // Reset legs
            p.legs.fl.rotation.x = 0; p.legs.fl.rotation.z = 0;
            p.legs.fr.rotation.x = 0; p.legs.fr.rotation.z = 0;
            p.legs.bl.rotation.x = 0; p.legs.bl.rotation.z = 0;
            p.legs.br.rotation.x = 0; p.legs.br.rotation.z = 0;
            p.tail.rotation.z = -0.3 + Math.sin(t * 2) * 0.08;

        } else if (status === 'acting') {
            // Walking in a small circle
            var wr = 1.3;
            var ws = t * 1.5;
            g.position.x = llama.basePos.x + Math.sin(ws) * wr;
            g.position.z = llama.basePos.z + Math.cos(ws) * wr;
            g.rotation.y = ws + Math.PI / 2;
            // Leg swing — model faces +x, so swing around Z
            var legSwing = Math.sin(t * 8) * 0.4;
            p.legs.fl.rotation.z =  legSwing;
            p.legs.br.rotation.z =  legSwing;
            p.legs.fr.rotation.z = -legSwing;
            p.legs.bl.rotation.z = -legSwing;
            // Body bounce
            p.body.position.y = 1.2 + Math.abs(Math.sin(t * 8)) * 0.08;
            // Tail wag
            p.tail.rotation.z = -0.3 + Math.sin(t * 6) * 0.25;
            // Head steady
            p.head.position.y = 2.75;
            p.head.rotation.y = 0; p.head.rotation.z = 0;
            p.neck.position.y = 2.0;
            p.ears[0].rotation.z = 0.15;
            p.ears[1].rotation.z = -0.15;
            // Ring glow
            llama.ring.material.opacity = 0.5;
            llama.ring.rotation.z = t * 2;

        } else if (status === 'error') {
            // Shake at base
            g.position.x = llama.basePos.x + Math.sin(t * 20) * 0.1;
            g.position.z = llama.basePos.z + Math.cos(t * 17) * 0.05;
            g.rotation.y = llama.baseRy;
            // Droop head
            p.head.position.y = 2.65;
            p.head.rotation.y = 0; p.head.rotation.z = 0;
            p.neck.position.y = 1.95;
            // Flat ears
            p.ears[0].rotation.z =  0.5;
            p.ears[1].rotation.z = -0.5;
            // Red flash ring
            llama.ring.material.opacity = 0.3 + Math.sin(t * 6) * 0.3;
            // Reset legs
            p.legs.fl.rotation.x = 0; p.legs.fl.rotation.z = 0;
            p.legs.fr.rotation.x = 0; p.legs.fr.rotation.z = 0;
            p.legs.bl.rotation.x = 0; p.legs.bl.rotation.z = 0;
            p.legs.br.rotation.x = 0; p.legs.br.rotation.z = 0;
            p.body.position.y = 1.2;
            p.tail.rotation.z = -0.5;

        } else {
            /* ============================================================
               Idle — Wander and Rest
               ============================================================ */
            var wState = llama._wanderState;
            var sinceW = time - llama._wanderTimer;

            if (wState === 'walk') {
                // --- Walking toward target ---
                var progress = Math.min(sinceW / llama._wanderDuration, 1);
                var ease = progress * (2 - progress); // ease-out quad
                var wx = llama._wanderStartPos.x + (llama._wanderTarget.x - llama._wanderStartPos.x) * ease;
                var wz = llama._wanderStartPos.z + (llama._wanderTarget.z - llama._wanderStartPos.z) * ease;
                g.position.x = wx;
                g.position.z = wz;
                llama._wanderCurrentPos.x = wx;
                llama._wanderCurrentPos.z = wz;
                // Face direction of movement (model faces +x, so subtract PI/2)
                var fdx = llama._wanderTarget.x - llama._wanderStartPos.x;
                var fdz = llama._wanderTarget.z - llama._wanderStartPos.z;
                if (Math.abs(fdx) > 0.01 || Math.abs(fdz) > 0.01) {
                    llama._wanderFacing = Math.atan2(fdx, fdz) - Math.PI / 2;
                }
                g.rotation.y = llama._wanderFacing;
                // Leg swing (slow casual walk) — model faces +x, so swing around Z
                var wLeg = Math.sin(t * 6) * 0.25;
                p.legs.fl.rotation.z =  wLeg;
                p.legs.br.rotation.z =  wLeg;
                p.legs.fr.rotation.z = -wLeg;
                p.legs.bl.rotation.z = -wLeg;
                // Body bounce
                p.body.position.y = 1.2 + Math.abs(Math.sin(t * 6)) * 0.04;
                // Head steady, looking forward
                p.head.position.y = 2.75;
                p.head.rotation.y = 0; p.head.rotation.z = 0;
                p.neck.position.y = 2.0;
                p.ears[0].rotation.z = 0.15;
                p.ears[1].rotation.z = -0.15;
                p.tail.rotation.z = -0.3 + Math.sin(t * 3) * 0.15;
                llama.ring.material.opacity = 0.15;
                // Arrived? Rest briefly or walk again
                if (progress >= 1) {
                    if (Math.random() < 0.35) {
                        llama._wanderState = 'rest';
                        llama._wanderDuration = 1.5 + Math.random() * 3;
                        llama._wanderTimer = time;
                    } else {
                        this._startWanderWalk(llama, time);
                    }
                }

            } else {
                // --- Resting — gentle breathing at current spot ---
                g.position.x = llama._wanderCurrentPos.x;
                g.position.z = llama._wanderCurrentPos.z;
                g.rotation.y = llama._wanderFacing;
                p.body.position.y = 1.2 + Math.sin(t * 1.5) * 0.03;
                p.head.position.y = 2.75;
                p.head.rotation.y = 0; p.head.rotation.z = 0;
                p.neck.position.y = 2.0;
                // Occasional ear twitch
                if (Math.sin(t * 0.7) > 0.92) {
                    p.ears[0].rotation.z = 0.15 + Math.sin(t * 12) * 0.2;
                } else {
                    p.ears[0].rotation.z = 0.15;
                }
                p.ears[1].rotation.z = -0.15;
                p.tail.rotation.z = -0.3 + Math.sin(t * 0.8) * 0.06;
                p.legs.fl.rotation.x = 0; p.legs.fl.rotation.z = 0;
                p.legs.fr.rotation.x = 0; p.legs.fr.rotation.z = 0;
                p.legs.bl.rotation.x = 0; p.legs.bl.rotation.z = 0;
                p.legs.br.rotation.x = 0; p.legs.br.rotation.z = 0;
                llama.ring.material.opacity = 0.12;
                // Done resting? Start walking
                if (sinceW > llama._wanderDuration) {
                    this._startWanderWalk(llama, time);
                }
            }
        }

        // Random idle chatter — occasionally show a bubble even without status change
        if (!llama._bubble && llama.status !== 'error') {
            var now = time;
            var sinceLast = now - (llama._lastBubbleTime || 0);
            // Random chance every ~12-20 seconds
            if (sinceLast > 12 && Math.random() < 0.002) {
                var agentIdForBubble = null;
                var llamaIds = Object.keys(this.llamas);
                for (var k = 0; k < llamaIds.length; k++) {
                    if (this.llamas[llamaIds[k]] === llama) {
                        agentIdForBubble = llamaIds[k];
                        break;
                    }
                }
                if (!agentIdForBubble) return;

                var msg;
                // Orchestrator occasionally cheers specific workers by name
                if (llama.isOrchestrator && Math.random() < 0.4) {
                    var workerIds = [];
                    for (var w = 0; w < llamaIds.length; w++) {
                        if (llamaIds[w] !== 'orchestrator') workerIds.push(llamaIds[w]);
                    }
                    if (workerIds.length > 0) {
                        var target = pickRandom(workerIds);
                        var cheers = [
                            'Go ' + target + '!',
                            target + ' rocks!',
                            'Nice, ' + target + '~',
                            target + ', keep it up!',
                            'Yay ' + target + '!',
                            target + ' is the best!',
                            'Love u ' + target,
                            '*cheers ' + target + '*',
                        ];
                        msg = pickRandom(cheers);
                    } else {
                        msg = pickRandom(SPEECH_BUBBLES.orchestrator);
                    }
                } else {
                    var pool = llama.isOrchestrator ? SPEECH_BUBBLES.orchestrator : (SPEECH_BUBBLES[llama.status] || SPEECH_BUBBLES.idle);
                    msg = pickRandom(pool);
                }

                this._showBubble(agentIdForBubble, msg);
                llama._lastBubbleTime = now;
            }
        }
    };

    /* ================================================================
       Resize / Pause / Dispose
       ================================================================ */

    LlamaFarm.prototype._onResize = function () {
        var w = this.container.clientWidth;
        var h = this.container.clientHeight;
        if (w === 0 || h === 0) return;

        var aspect = w / h;
        var s = this._frustumSize;
        this.camera.left   = -s * aspect;
        this.camera.right  =  s * aspect;
        this.camera.top    =  s;
        this.camera.bottom = -s;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(w, h);
    };

    LlamaFarm.prototype.resize = function () { this._onResize(); };

    LlamaFarm.prototype.pause = function () { this._paused = true; };

    LlamaFarm.prototype.resume = function () {
        if (this._paused) {
            this._paused = false;
            this._clock.getDelta(); // reset delta so animations don't jump
            this._animate();
        }
    };

    LlamaFarm.prototype.dispose = function () {
        this._disposed = true;
        window.removeEventListener('resize', this._onResize);
        var ids = Object.keys(this.llamas);
        for (var i = 0; i < ids.length; i++) {
            this.removeLlama(ids[i]);
        }
        this.renderer.dispose();
        if (this.renderer.domElement.parentNode) {
            this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
        }
    };

    /* Export */
    window.LlamaFarm = LlamaFarm;
})();
