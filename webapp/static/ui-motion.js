/* ui-motion.js — efectos de cursor para CMMS Infraestructura.
   Sin dependencias. Todo por delegación en document, así funciona también
   con contenido cargado después (fetch, htmx, plantillas nuevas).
   Uso:  <script src="{{ url_for('static', filename='ui-motion.js') }}" defer></script> */
(function () {
  if (window.__cmmsMotion) return;
  window.__cmmsMotion = true;

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var MAG = 'a.btn, button.btn, .btn-outline, .btn-danger, .fab, .icon-btn, .view-switcher a, .hamburger-btn';
  var TILT = '.card';

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    if (reduce) return;

    /* 1. Halo que sigue al cursor, con inercia */
    var glow = document.createElement('div');
    glow.id = 'cursor-glow';
    document.body.appendChild(glow);
    var tx = -9999, ty = -9999, cx = -9999, cy = -9999;
    (function loop() {
      cx += (tx - cx) * 0.13; cy += (ty - cy) * 0.13;
      glow.style.transform = 'translate3d(' + cx + 'px,' + cy + 'px,0)';
      requestAnimationFrame(loop);
    })();

    /* 2. Botones magnéticos + inclinación 3D de tarjetas (un solo listener) */
    var mags = [], magsAt = 0;
    document.addEventListener('mousemove', function (e) {
      tx = e.clientX; ty = e.clientY;

      var now = performance.now();
      if (now - magsAt > 400) { mags = [].slice.call(document.querySelectorAll(MAG)); magsAt = now; }
      for (var i = 0; i < mags.length; i++) {
        var el = mags[i], r = el.getBoundingClientRect();
        if (!r.width) continue;
        var dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
        var near = Math.hypot(dx, dy) < Math.max(r.width, r.height) * 1.15;
        el.style.setProperty('--mx', (near ? dx * 0.22 : 0).toFixed(1) + 'px');
        el.style.setProperty('--my', (near ? dy * 0.22 : 0).toFixed(1) + 'px');
      }

      var card = e.target.closest && e.target.closest(TILT);
      if (card) {
        var cr = card.getBoundingClientRect();
        var px = (e.clientX - cr.left) / cr.width - 0.5;
        var py = (e.clientY - cr.top) / cr.height - 0.5;
        var amp = cr.width > 520 ? 2.5 : 5;   // tarjetas anchas se inclinan menos
        card.style.setProperty('--ry', (px * amp).toFixed(2) + 'deg');
        card.style.setProperty('--rx', (-py * amp).toFixed(2) + 'deg');
        card.setAttribute('data-tilted', '');
      }
    }, { passive: true });

    document.addEventListener('mouseout', function (e) {
      var card = e.target.closest && e.target.closest(TILT);
      if (card && !card.contains(e.relatedTarget)) {
        card.removeAttribute('data-tilted');
        card.style.setProperty('--rx', '0deg');
        card.style.setProperty('--ry', '0deg');
      }
    }, true);

    /* 3. Onda al pulsar botones */
    document.addEventListener('pointerdown', function (e) {
      var b = e.target.closest && e.target.closest('a.btn, button.btn, .fab, .btn-outline, .btn-danger');
      if (!b) return;
      var r = b.getBoundingClientRect(), d = Math.max(r.width, r.height);
      var s = document.createElement('span');
      s.className = 'ripple';
      s.style.width = s.style.height = d + 'px';
      s.style.left = (e.clientX - r.left - d / 2) + 'px';
      s.style.top = (e.clientY - r.top - d / 2) + 'px';
      if (b.classList.contains('btn-outline')) s.style.background = 'rgba(45,127,249,.28)';
      b.appendChild(s);
      setTimeout(function () { s.remove(); }, 600);
    });

    /* 4. Aparición al entrar en pantalla (con respaldo si no hay observer) */
    var items = [];
    var show = function (el) { el.setAttribute('data-shown', ''); };
    var inView = function (el) {
      var r = el.getBoundingClientRect();
      return r.top < innerHeight * 0.96 && r.bottom > 0;
    };
    var io = null;
    try {
      io = new IntersectionObserver(function (es) {
        es.forEach(function (en) { if (en.isIntersecting) { show(en.target); io.unobserve(en.target); } });
      }, { threshold: 0.05 });
    } catch (err) { io = null; }

    function scanReveal() {
      [].slice.call(document.querySelectorAll('main .card, main .kpi > div')).forEach(function (el, i) {
        if (el.hasAttribute('data-reveal')) return;
        el.setAttribute('data-reveal', '');
        el.style.animationDelay = (i % 6) * 60 + 'ms';
        items.push(el);
        if (inView(el)) show(el);
        else if (io) io.observe(el);
        else show(el);
      });
    }
    scanReveal();
    addEventListener('load', scanReveal);
    setTimeout(scanReveal, 700);
    setTimeout(function () { scanReveal(); items.forEach(show); }, 2500);
    addEventListener('scroll', function () {
      items.forEach(function (el) { if (!el.hasAttribute('data-shown') && inView(el)) show(el); });
    }, { passive: true });

    /* 5. Conteo animado de los KPI y crecimiento de las barras de progreso */
    function countUp(el) {
      if (el.dataset.counted) return;
      el.dataset.counted = '1';
      var raw = el.textContent.trim();
      var m = raw.match(/-?\d+(?:[.,]\d+)?/);
      if (!m) return;
      var end = parseFloat(m[0].replace(',', '.')), t0 = null;
      var pre = raw.slice(0, m.index), post = raw.slice(m.index + m[0].length);
      var dec = (m[0].split(/[.,]/)[1] || '').length;
      requestAnimationFrame(function step(t) {
        if (t0 === null) t0 = t;
        var k = Math.min((t - t0) / 900, 1);
        var e2 = 1 - Math.pow(1 - k, 3);
        el.textContent = pre + (end * e2).toFixed(dec) + post;
        if (k < 1) requestAnimationFrame(step);
      });
    }
    function scanNums() {
      [].slice.call(document.querySelectorAll('.kpi .num')).forEach(countUp);
      [].slice.call(document.querySelectorAll('.progress-bar-fill')).forEach(function (el) {
        if (el.dataset.grown) return;
        el.dataset.grown = '1';
        var w = el.style.width || getComputedStyle(el).width;
        el.style.width = '0';
        requestAnimationFrame(function () { requestAnimationFrame(function () { el.style.width = w; }); });
      });
    }
    scanNums();
    addEventListener('load', scanNums);
    setTimeout(scanNums, 700);
  });
})();
