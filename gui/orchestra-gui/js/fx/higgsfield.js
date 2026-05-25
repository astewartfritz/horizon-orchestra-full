// Orchestra — Higgsfield-inspired ambient FX
// Cursor glow trail, ambient particles, ripple on click
(function () {
  'use strict';

  const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ── Cursor Glow ─────────────────────────────────────────────── */
  function initCursorGlow() {
    if (REDUCED) return;

    const el = document.createElement('div');
    el.id = 'orchestra-cursor-glow';
    Object.assign(el.style, {
      position: 'fixed',
      width: '500px',
      height: '500px',
      borderRadius: '50%',
      background: 'radial-gradient(circle, rgba(110,110,245,.055) 0%, rgba(0,201,184,.028) 40%, transparent 70%)',
      pointerEvents: 'none',
      zIndex: '0',
      willChange: 'transform',
      transition: 'opacity .4s ease',
      opacity: '0',
    });
    document.body.appendChild(el);

    let mx = -2000, my = -2000;
    let rx = -2000, ry = -2000;

    document.addEventListener('mousemove', (e) => {
      mx = e.clientX; my = e.clientY;
      el.style.opacity = '1';
    }, { passive: true });
    document.addEventListener('mouseleave', () => { el.style.opacity = '0'; });

    (function tick() {
      rx += (mx - rx) * 0.07;
      ry += (my - ry) * 0.07;
      el.style.transform = `translate(${rx - 250}px, ${ry - 250}px)`;
      requestAnimationFrame(tick);
    })();
  }

  /* ── Ambient Particles ───────────────────────────────────────── */
  function initParticles() {
    if (REDUCED) return;

    const canvas = document.createElement('canvas');
    canvas.id = 'orchestra-particles';
    Object.assign(canvas.style, {
      position: 'fixed',
      inset: '0',
      width: '100vw',
      height: '100vh',
      pointerEvents: 'none',
      zIndex: '0',
      opacity: '1',
    });
    document.body.insertBefore(canvas, document.body.firstChild);

    const ctx = canvas.getContext('2d');
    const PALETTE = [
      [110, 110, 245],  // accent indigo
      [0,   201, 184],  // teal
      [168, 85,  247],  // purple
      [59,  130, 246],  // blue
    ];
    const COUNT = 40;
    let W, H;

    function resize() {
      W = canvas.width  = window.innerWidth;
      H = canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener('resize', resize, { passive: true });

    class Particle {
      constructor(randomY) {
        this.reset();
        if (randomY) this.y = Math.random() * H;
      }
      reset() {
        this.x = Math.random() * W;
        this.y = H + 8;
        this.r = Math.random() * 1.2 + 0.4;
        this.vy = -(Math.random() * 0.25 + 0.08);
        this.vx = (Math.random() - 0.5) * 0.18;
        this.maxAlpha = Math.random() * 0.22 + 0.04;
        this.color = PALETTE[Math.floor(Math.random() * PALETTE.length)];
      }
      update() {
        this.y += this.vy;
        this.x += this.vx;
        const prog = 1 - (this.y / H);
        this.alpha = this.maxAlpha * Math.sin(prog * Math.PI);
        if (this.y < -10 || this.x < -20 || this.x > W + 20) this.reset();
      }
      draw() {
        const [r, g, b] = this.color;
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${r},${g},${b},${this.alpha})`;
        ctx.fill();
      }
    }

    const particles = Array.from({ length: COUNT }, (_, i) => new Particle(i < COUNT * 0.7));

    (function loop() {
      ctx.clearRect(0, 0, W, H);
      particles.forEach(p => { p.update(); p.draw(); });
      requestAnimationFrame(loop);
    })();
  }

  /* ── Ripple on Click ─────────────────────────────────────────── */
  function initRipple() {
    document.addEventListener('click', (e) => {
      const host = e.target.closest(
        '.btn--liquid, .btn--glow, .btn--primary, .cmd-miles-btn, .ripple-host'
      );
      if (!host) return;

      const rect = host.getBoundingClientRect();
      const wave = document.createElement('span');
      wave.className = 'ripple-wave';
      wave.style.left = (e.clientX - rect.left)  + 'px';
      wave.style.top  = (e.clientY - rect.top)   + 'px';

      host.style.position = 'relative';
      host.style.overflow = 'hidden';
      host.appendChild(wave);
      setTimeout(() => wave.remove(), 700);
    });
  }

  /* ── Aurora Background Orbs ─────────────────────────────────── */
  function initAuroraOrbs() {
    if (REDUCED) return;

    const orbs = document.createElement('div');
    orbs.id = 'orchestra-aurora-orbs';
    Object.assign(orbs.style, {
      position: 'fixed',
      inset: '0',
      pointerEvents: 'none',
      zIndex: '0',
      overflow: 'hidden',
    });

    const orbDefs = [
      { w: '70vw', h: '60vh', top: '-15%', left: '-10%',  color: 'rgba(110,110,245,.05)', dur: '22s', delay: '0s' },
      { w: '55vw', h: '55vh', top: '40%',  right: '-15%', color: 'rgba(0,201,184,.04)',   dur: '28s', delay: '-8s' },
      { w: '50vw', h: '50vh', top: '60%',  left: '20%',   color: 'rgba(168,85,247,.035)', dur: '18s', delay: '-4s' },
    ];

    orbDefs.forEach(({ w, h, top, left, right, color, dur, delay }) => {
      const orb = document.createElement('div');
      Object.assign(orb.style, {
        position: 'absolute',
        width: w, height: h,
        top: top || 'auto', left: left || 'auto', right: right || 'auto',
        background: `radial-gradient(ellipse, ${color} 0%, transparent 70%)`,
        borderRadius: '50%',
        animation: `floatSlow ${dur} ease-in-out infinite`,
        animationDelay: delay,
        filter: 'blur(40px)',
      });
      orbs.appendChild(orb);
    });

    document.body.insertBefore(orbs, document.body.firstChild);
  }

  /* ── Card Hover Glow ─────────────────────────────────────────── */
  function initCardHoverGlow() {
    document.addEventListener('mousemove', (e) => {
      const card = e.target.closest('.card--aurora, .cmd-widget, .glass');
      if (!card) return;
      const rect = card.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width  * 100).toFixed(1);
      const y = ((e.clientY - rect.top)  / rect.height * 100).toFixed(1);
      card.style.setProperty('--mouse-x', x + '%');
      card.style.setProperty('--mouse-y', y + '%');
    }, { passive: true });
  }

  /* ── Boot ────────────────────────────────────────────────────── */
  function boot() {
    initCursorGlow();
    initParticles();
    initAuroraOrbs();
    initRipple();
    initCardHoverGlow();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
