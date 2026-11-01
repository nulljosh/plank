// Hero wall: Plank's real examples (demo.js, generated from examples/ by the compiler). Each card types a different
// program, runs it, and shows the first lines of its real output. Never the same program twice at once.
(function () {
  var wall = document.getElementById('kwall'), D = window.PLANK_DEMO; if (!wall || !D) return;
  var still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var n = innerWidth <= 560 ? 4 : innerWidth <= 900 ? 6 : 9;
  // skip the comment header and blank lines, keep programs short enough to read on a card
  var ex = D.examples.filter(function (e) { return e.out && e.src; }).map(function (e) {
    var lines = e.src.split('\n').filter(function (l) { return l.trim() && !/^#/.test(l.trim()); }).map(function (l) { return l.length > 46 ? l.slice(0, 45) + '…' : l; });
    return { name: e.name, src: lines.slice(0, 7), out: e.out.split('\n').filter(Boolean).slice(0, 3) };
  });
  var m = Math.min(n, ex.length);
  var el = function (t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
  var wait = function (ms) { return new Promise(function (r) { setTimeout(r, still ? 0 : ms); }); };
  for (var i = 0; i < m; i++) (function (i) {
    var a = wall.appendChild(el('article', 'pk')), h = a.appendChild(el('h3')), src = a.appendChild(el('pre')), out = a.appendChild(el('pre', 'out')), k = i;
    function play() {
      var e = ex[k % ex.length]; k += m;
      h.textContent = e.name + '.pk'; src.textContent = ''; out.textContent = '';
      var typed = [];
      return e.src.reduce(function (q, l) { return q.then(function () { typed.push(l); src.textContent = typed.join('\n'); return wait(260 + l.length * 10); }); }, wait(300))
        .then(function () { out.appendChild(el('b', '', '$ plank ' + e.name + '.pk')); return wait(700); })
        .then(function () { out.appendChild(document.createTextNode('\n' + e.out.join('\n'))); return wait(3600); });
    }
    if (still) play(); else wait(i * 240).then(function loop() { return play().then(loop); });
  })(i);
})();

// Hero parallax: the wall drifts at 0.45, the copy lifts at 0.2 and fades. Off under reduced motion.
(function () {
  var bg = document.querySelector('.hero-bg'), copy = document.querySelector('.hero-copy');
  if (!bg || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  var t = 0;
  addEventListener('scroll', function () {
    if (t) return;
    t = requestAnimationFrame(function () {
      t = 0; var y = scrollY, h = innerHeight; if (y > h * 1.2) return;
      bg.style.setProperty('--py', (y * .45) + 'px');
      copy.style.transform = 'translate3d(0,' + (y * .2) + 'px,0)'; copy.style.opacity = Math.max(0, 1 - y / (h * .7));
    });
  }, { passive: true });
})();
