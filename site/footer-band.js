// Footer band: Plank's things in a row (planks, braces, a prompt, the tower, a hammer, a chain link), cut like a line
// engraving in plain 2D canvas. Faint rules run across the band; inside the glyphs they thicken, and thicken again on
// the edge facing away from the light, so the glyphs look cut into the page. Drawn once per size and theme.
// Animated in plain 2D (the old WebGL shader rendered as a black box on iPhone): each glyph bobs on its own beat and
// the light circles slowly, so the cut edge creeps around every glyph. Runs only while the band is on screen, at 30fps;
// reduced motion gets the still engraving.
(function () {
  var band = document.querySelector('.word-band'), canvas = band && band.querySelector('canvas');
  if (!canvas) return;


  // Each glyph is drawn white on a 100 unit square.
  var GLYPHS = [
    function (c) { // a stack of planks, the mark's idea
      [[14, 24, 72], [22, 44, 64], [10, 64, 76]].forEach(function (p) { c.beginPath(); c.roundRect(p[0], p[1], p[2], 13, 6.5); c.fill(); });
    },
    function (c) { // braces
      c.lineWidth = 7; c.lineCap = 'round'; c.lineJoin = 'round';
      [[38, 1], [62, -1]].forEach(function (p) { var x = p[0], k = p[1]; c.beginPath(); c.moveTo(x, 16); c.quadraticCurveTo(x - 10 * k, 16, x - 10 * k, 28); c.lineTo(x - 10 * k, 42); c.quadraticCurveTo(x - 10 * k, 50, x - 18 * k, 50); c.quadraticCurveTo(x - 10 * k, 50, x - 10 * k, 58); c.lineTo(x - 10 * k, 72); c.quadraticCurveTo(x - 10 * k, 84, x, 84); c.stroke(); });
    },
    function (c) { // a prompt
      c.lineWidth = 9; c.lineCap = 'round'; c.lineJoin = 'round';
      c.beginPath(); c.moveTo(18, 30); c.lineTo(42, 50); c.lineTo(18, 70); c.stroke();
      c.fillRect(50, 66, 34, 9);
    },
    function (c) { // the tower of Babel, in tiers
      for (var i = 0; i < 6; i++) { var w = 76 - i * 11, y = 84 - (i + 1) * 12; c.beginPath(); c.roundRect(50 - w / 2, y, w, 10, 2); c.fill(); }
    },
    function (c) { // a hammer
      c.save(); c.translate(50, 50); c.rotate(-0.6);
      c.beginPath(); c.roundRect(-5, -10, 10, 52, 4); c.fill();
      c.beginPath(); c.roundRect(-24, -26, 48, 18, 4); c.fill();
      c.restore();
    },
    function (c) { // a chain link: the linker's last step
      c.lineWidth = 8;
      c.save(); c.translate(50, 50); c.rotate(-0.6);
      c.beginPath(); c.roundRect(-34, -11, 40, 22, 11); c.stroke();
      c.beginPath(); c.roundRect(-6, -11, 40, 22, 11); c.stroke();
      c.restore();
    }
  ];
  // Lays the glyphs out evenly across a w by h 2D context, in the given colour: one row, or two on a narrow band.
  function grid(w, h) {
    var n = GLYPHS.length, rows = w < h * 3 ? 2 : 1, per = Math.ceil(n / rows);
    return { rows: rows, per: per, cell: Math.min(h / rows * 0.86, w / per) };
  }
  function paint(c, w, h, colour, t) {
    var g = grid(w, h), gap = (w - g.cell * g.per) / g.per, rowH = h / g.rows;
    GLYPHS.forEach(function (draw, i) {
      var col = i % g.per, row = Math.floor(i / g.per), bob = Math.sin(t * 1.3 + i * 0.9) * g.cell * 0.05, tilt = Math.sin(t * 0.8 + i * 1.7) * 0.05;
      c.save(); c.translate(gap / 2 + col * (g.cell + gap) + g.cell / 2, row * rowH + (rowH - g.cell) / 2 + rowH * 0.04 + bob + g.cell / 2);
      c.rotate(tilt); c.translate(-g.cell / 2, -g.cell / 2); c.scale(g.cell / 100, g.cell / 100);
      c.fillStyle = c.strokeStyle = colour; draw(c); c.restore();
    });
  }

  var ctx = canvas.getContext('2d');
  if (!ctx) return;
  function layer(w, h) { var c = document.createElement('canvas'); c.width = w; c.height = h; return c; }
  // Horizontal rules `t` px thick, one every `pitch` px, kept only where `mask` is drawn (everywhere when null).
  function rules(w, h, pitch, t, colour, mask) {
    var c = layer(w, h), x = c.getContext('2d');
    x.fillStyle = colour;
    for (var y = 0; y < h; y += pitch) x.fillRect(0, Math.round(y + (pitch - t) / 2), w, Math.max(1, Math.round(t)));
    if (mask) { x.globalCompositeOperation = 'destination-in'; x.drawImage(mask, 0, 0); }
    return c;
  }
  var drawnW = 0, size = null, still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  // per size and theme: the rules, cached; per frame only the glyph mask, its shadow side and two composites change
  function setup() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2), w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
    if (!w || !h) { size = null; return; }
    drawnW = w; canvas.width = w; canvas.height = h;
    var colour = getComputedStyle(band).color, pitch = Math.min(5 * dpr, Math.max(3 * dpr, grid(w, h).cell / 22));
    size = { w: w, h: h, s: Math.max(2, h * 0.014), base: rules(w, h, pitch, dpr * 0.75, colour, null), inner: rules(w, h, pitch, pitch * 0.32, colour, null),
             edge: rules(w, h, pitch, pitch * 0.6, colour, null), glyphs: layer(w, h), shade: layer(w, h), cut: layer(w, h) };
  }
  function masked(src, mask) {
    var c = size.cut, x = c.getContext('2d');
    x.globalCompositeOperation = 'copy'; x.drawImage(src, 0, 0);
    x.globalCompositeOperation = 'destination-in'; x.drawImage(mask, 0, 0);
    return c;
  }
  function frame(t) {
    if (!size) return;
    var w = size.w, h = size.h, gc = size.glyphs.getContext('2d'), sc = size.shade.getContext('2d');
    gc.clearRect(0, 0, w, h); paint(gc, w, h, '#fff', t);
    // the shadow side: glyph pixels whose neighbour toward the light is outside the glyph; the light circles slowly
    var a = Math.PI / 4 + Math.sin(t * 0.35) * 1.1, dx = Math.cos(a) * size.s, dy = Math.sin(a) * size.s;
    sc.globalCompositeOperation = 'copy'; sc.drawImage(size.glyphs, 0, 0);
    sc.globalCompositeOperation = 'destination-out'; sc.drawImage(size.glyphs, -dx, -dy);
    ctx.globalCompositeOperation = 'source-over'; ctx.clearRect(0, 0, w, h);
    ctx.globalAlpha = 0.28; ctx.drawImage(size.base, 0, 0);
    ctx.globalAlpha = 1; ctx.drawImage(masked(size.inner, size.glyphs), 0, 0);
    ctx.drawImage(masked(size.edge, size.shade), 0, 0);
    // fade out toward the legal line
    var g = ctx.createLinearGradient(0, h * 0.88, 0, h);
    g.addColorStop(0, '#000'); g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.globalCompositeOperation = 'destination-in'; ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    ctx.globalCompositeOperation = 'source-over';
  }
  function redraw() { setup(); frame(performance.now() / 1000); }
  band.classList.add('live');
  redraw();
  var seen = false, last = 0;
  if (!still && 'IntersectionObserver' in window) {
    new IntersectionObserver(function (es) { var was = seen; seen = es[0].isIntersecting; if (seen && !was) requestAnimationFrame(tick); }).observe(band);
  }
  function tick(now) {
    if (!seen || document.hidden) return;
    if (now - last > 33) { last = now; frame(now / 1000); }
    requestAnimationFrame(tick);
  }
  document.addEventListener('visibilitychange', function () { if (!document.hidden && seen) requestAnimationFrame(tick); });
  // iOS fires resize as the toolbar slides; only a width change needs a redraw
  window.addEventListener('resize', function () { if (Math.round(canvas.clientWidth * Math.min(window.devicePixelRatio || 1, 2)) !== drawnW) redraw(); });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redraw);
})();
