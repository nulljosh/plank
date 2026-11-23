// The book page: copy buttons, a guess-the-output mode, the chapter list following you, a reading bar. Plain DOM, no state but one
// localStorage flag, and the page reads the same with all of it off.
(function () {
  var store = { get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
                set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };

  document.querySelectorAll("pre.code").forEach(function (pre) {
    var b = document.createElement("button"); b.type = "button"; b.className = "copy"; b.textContent = "Copy";
    b.onclick = function () {
      navigator.clipboard.writeText(pre.querySelector("code").textContent).then(function () {
        b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy"; }, 1400);
      });
    };
    pre.appendChild(b);
  });

  // guess mode: every output hides behind a button; the reader predicts, then looks
  var quiz = document.getElementById("quiz");
  document.querySelectorAll("pre.output").forEach(function (pre) {
    pre.tabIndex = 0;
    pre.addEventListener("click", function () { pre.classList.add("shown"); });
    pre.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pre.classList.add("shown"); } });
  });
  function setQuiz(on) {
    document.body.classList.toggle("quizzing", on); quiz.setAttribute("aria-pressed", on);
    document.querySelectorAll("pre.output.shown").forEach(function (p) { p.classList.remove("shown"); });
    store.set("plank-book-quiz", on ? "1" : "");
  }
  quiz.onclick = function () { setQuiz(!document.body.classList.contains("quizzing")); };
  if (store.get("plank-book-quiz")) setQuiz(true);

  // the chapter list marks the one you are in
  var links = {};
  document.querySelectorAll(".toc a").forEach(function (a) { links[a.hash.slice(1)] = a; });
  var seen = new IntersectionObserver(function (es) {
    es.forEach(function (e) {
      if (!e.isIntersecting) return;
      var id = e.target.querySelector("h1").id;
      Object.keys(links).forEach(function (k) { links[k].classList.toggle("here", k === id); });
    });
  }, { rootMargin: "-40% 0px -55% 0px" });
  document.querySelectorAll(".chapter").forEach(function (c) { seen.observe(c); });

  var bar = document.getElementById("progress"), ticking = false;
  addEventListener("scroll", function () {
    if (ticking) return; ticking = true;
    requestAnimationFrame(function () {
      var h = document.documentElement; bar.style.transform = "scaleX(" + (h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight)) + ")";
      ticking = false;
    });
  }, { passive: true });
})();
