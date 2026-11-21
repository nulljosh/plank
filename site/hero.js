// Hero scene, after Keyrate. The editor under the title types a real example from demo.js (generated from examples/
// by the compiler) a character at a time; when it is typed, the four stages light in turn (lex, parse, emit, link),
// the lines flash as each stage passes over them, and the program's real output prints in the strip below. The
// readout under the buttons says the same in one line. Loose tokens drift at three depths. Every layer eases toward
// the scroll position at its own speed and leans away from the pointer on desktop. Reduced motion gets a still scene.
(function () {
  var D = window.PLANK_DEMO; if (!D) return;
  var still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var el = function (t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
  var wait = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  var KW = /\b(fn|let|var|if|else|while|for|in|return|break|continue|true|false|and|or|not|struct|enum|match|nil|import|try|catch|throw|self|tool)\b/g;
  var esc = function (s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;'); };
  var paint = function (s) {
    var hash = s.indexOf('#'), code = hash >= 0 ? s.slice(0, hash) : s, note = hash >= 0 ? s.slice(hash) : '';
    return esc(code).replace(/"(?:\\.|[^"\\])*"/g, '<span class="s">$&</span>').replace(KW, '<span class="k">$1</span>') +
      (note ? '<span class="c">' + esc(note) + '</span>' : '');
  };

  // programs short enough to read on the desk: no header comments, at most 12 lines
  var ex = D.examples.filter(function (e) { return e.out && e.src; }).map(function (e) {
    var lines = e.src.split('\n').filter(function (l) { return l.trim() && !/^#/.test(l.trim()); });
    return { name: e.name, src: lines, out: e.out.split('\n').filter(Boolean) };
  }).filter(function (e) { return e.src.length <= 12; });
  if (!ex.length) return;

  var board = document.getElementById('board'), ground = document.querySelector('.ground');
  var code, term, file, stages = [];
  if (board) {
    var ed = board.appendChild(el('div', 'ed')), bar = ed.appendChild(el('div', 'ed-bar'));
    bar.appendChild(el('i')); bar.appendChild(el('i')); bar.appendChild(el('i'));
    file = bar.appendChild(el('b'));
    var st = bar.appendChild(el('span', 'stages'));
    ['lex', 'parse', 'emit', 'link'].forEach(function (s) { stages.push(st.appendChild(el('span', '', s))); });
    code = ed.appendChild(el('pre', 'code')); term = ed.appendChild(el('pre', 'term'));
  }
  var cmd = document.getElementById('rCmd'), said = document.getElementById('rSaid');

  var onscreen = true, hero = document.querySelector('.hero');
  if ('IntersectionObserver' in window && hero) new IntersectionObserver(function (es) { onscreen = es[0].isIntersecting; }).observe(hero);
  var awake = function () { return (document.hidden || !onscreen) ? wait(400).then(awake) : Promise.resolve(); };

  function draw(lines, caret) {
    code.innerHTML = '';
    lines.forEach(function (l, i) { var d = code.appendChild(el('div')); d.innerHTML = paint(l) || ' '; if (caret && i === lines.length - 1) d.className = 'caret'; });
  }
  function lit(n) { stages.forEach(function (s, i) { s.className = i < n ? 'done' : i === n ? 'on' : ''; }); }

  function play(e) {
    file.textContent = e.name + '.pk'; term.textContent = ''; lit(-1);
    if (cmd) cmd.textContent = 'plank run ' + e.name + '.pk'; if (said) said.textContent = '';
    if (still) { draw(e.src); lit(4); term.innerHTML = '<b>$ plank run ' + e.name + '.pk</b>\n' + esc(e.out.slice(0, 3).join('\n')); if (said) said.textContent = e.out[0]; return Promise.resolve(); }
    var typed = [''];
    var q = wait(400);
    e.src.forEach(function (line, li) {
      for (var c = 0; c < line.length; c++) (function (ch) {
        q = q.then(awake).then(function () { typed[typed.length - 1] += ch; draw(typed, true); return wait(ch === ' ' ? 18 : 26 + Math.random() * 30); });
      })(line[c]);
      q = q.then(function () { if (li < e.src.length - 1) typed.push(''); return wait(120); });
    });
    return q.then(function () { draw(typed); })
      .then(function () {
        // each stage sweeps the lines it reads
        return [0, 1, 2, 3].reduce(function (p, s) {
          return p.then(function () {
            lit(s); if (said) said.textContent = ['lexing', 'parsing', 'emitting LLVM IR', 'linking'][s] + '...';
            var rows = code.children, k = 0;
            return (function sweep() {
              if (k > 0) rows[k - 1].classList.remove('hot');
              if (k >= rows.length) return wait(90);
              rows[k++].classList.add('hot'); return wait(Math.max(28, 260 / rows.length)).then(sweep);
            })();
          });
        }, Promise.resolve());
      })
      .then(function () {
        lit(4); term.innerHTML = '<b>$ plank run ' + esc(e.name) + '.pk</b>';
        return e.out.slice(0, 3).reduce(function (p, l) {
          return p.then(function () { term.innerHTML += '\n' + esc(l); if (said) said.textContent = l; return wait(260); });
        }, Promise.resolve());
      })
      .then(function () { return wait(3200); });
  }
  if (board) {
    var start = Math.max(0, ex.findIndex(function (e) { return e.name === 'fib'; }));
    if (still) play(ex[start]);
    else (function loop(i) { play(ex[i % ex.length]).then(function () { loop(i + 1); }); })(start);
  }

  // loose tokens at three depths; the middle stays clear for the title
  var sky = document.getElementById('sky'), layers = [];
  if (sky) {
    var seed = 11, rnd = function () { return (seed = (seed * 16807) % 2147483647) / 2147483647; };
    var few = innerWidth < 600;
    var words = ['fn', 'let', 'var', 'match', '=>', '->', '{ }', '[ ]', '?', '??', 'enum', 'struct', 'int', 'str', '.pk', '\\( )', 'try', 'for', 'in', '0..n', '!', 'nil'];
    var depths = [
      { cls: 'far', n: 12, size: 22, lag: .7, o: .45, tilt: 10, spin: .02 },
      { cls: 'mid', n: 9, size: 36, lag: .35, o: .75, tilt: 20, spin: .04 },
      { cls: 'near', n: 6, size: 60, lag: -.35, o: .95, tilt: 34, spin: .08 }
    ];
    depths.forEach(function (d, di) {
      var layer = sky.appendChild(el('div', 'layer ' + d.cls));
      var n = few ? (d.cls === 'near' ? 0 : Math.ceil(d.n / 2)) : d.n;
      for (var i = 0; i < n; i++) {
        // stratified: alternate sides, each token its own slice of height, jittered so none pile up
        var side = i % 2, slot = Math.floor(i / 2), slots = Math.ceil(n / 2);
        var band = d.cls === 'far' ? 24 : 13;
        var x = side ? 96 - band + rnd() * band - 4 : 2 + rnd() * band;
        var y = 4 + (slot + .15 + rnd() * .7) * (64 / slots);
        var hot = d.cls !== 'far' && rnd() < .25;
        var t = layer.appendChild(el('span', 'tok' + (hot ? ' hot' : ''), words[(i * 7 + di * 5 + 2) % words.length]));
        t.style.cssText = 'left:' + x.toFixed(1) + '%;top:' + y.toFixed(1) + '%;--s:' + d.size + 'px;opacity:' + d.o + ';' +
          'animation-duration:' + (5 + rnd() * 5).toFixed(1) + 's;animation-delay:' + (-rnd() * 10).toFixed(1) + 's;--r:' + Math.round(rnd() * 30 - 15) + 'deg';
        t.dataset.spin = ((rnd() < .5 ? -1 : 1) * d.spin * (.6 + rnd() * .8)).toFixed(3);
      }
      layers.push({ layer: layer, lag: d.lag, tilt: d.tilt, toks: Array.prototype.slice.call(layer.children) });
    });
  }

  // parallax, eased toward the target each frame so a flick of the wheel glides; the copy lifts and fades
  var copy = document.querySelector('.hero-copy');
  if (still) return;
  var now = { y: scrollY, px: 0, py: 0 }, goal = { y: scrollY, px: 0, py: 0 }, running = false;
  function frame() {
    var moving = false;
    for (var k in now) { var dd = goal[k] - now[k]; now[k] = Math.abs(dd) < .05 ? goal[k] : now[k] + dd * .12; if (now[k] !== goal[k]) moving = true; }
    var y = now.y;
    if (y < innerHeight * 1.4) {
      if (ground) ground.style.transform = 'translate3d(' + (now.px * 8).toFixed(2) + 'px,' + (y * .55 + now.py * 5).toFixed(2) + 'px,0)';
      layers.forEach(function (L) {
        L.layer.style.transform = 'translate3d(' + (now.px * L.tilt).toFixed(2) + 'px,' + (y * L.lag + now.py * L.tilt * .6).toFixed(2) + 'px,0)';
        L.toks.forEach(function (t) { t.style.rotate = (y * t.dataset.spin).toFixed(2) + 'deg'; });
      });
      if (copy) { copy.style.transform = 'translate3d(0,' + (y * .2).toFixed(2) + 'px,0)'; copy.style.opacity = Math.max(0, 1 - y / (innerHeight * .7)); }
    }
    running = moving;
    if (moving) requestAnimationFrame(frame);
  }
  function kick() { if (!running) { running = true; requestAnimationFrame(frame); } }
  addEventListener('scroll', function () { goal.y = scrollY; kick(); }, { passive: true });
  if (matchMedia('(pointer: fine)').matches) addEventListener('pointermove', function (e) {
    goal.px = -(e.clientX / innerWidth - .5) * 2; goal.py = -(e.clientY / innerHeight - .5) * 2; kick();
  }, { passive: true });
})();
