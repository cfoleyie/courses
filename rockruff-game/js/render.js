// All "cute, not-pixely" procedural canvas art: creatures, tiles, player & trainer sprites.
import { TYPE_COLORS } from './pokedex-data.js';

function lighten(hex, amt) {
  const n = parseInt(hex.slice(1), 16);
  let r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  r = Math.min(255, Math.round(r + (255 - r) * amt));
  g = Math.min(255, Math.round(g + (255 - g) * amt));
  b = Math.min(255, Math.round(b + (255 - b) * amt));
  return `rgb(${r},${g},${b})`;
}
function darken(hex, amt) {
  const n = parseInt(hex.slice(1), 16);
  let r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  r = Math.round(r * (1 - amt)); g = Math.round(g * (1 - amt)); b = Math.round(b * (1 - amt));
  return `rgb(${r},${g},${b})`;
}

// Draws an adorable chibi blob-creature centered at (cx, cy). `s` = overall scale (body radius-ish).
export function drawCreature(ctx, cx, cy, s, species, opts = {}) {
  const { flip = false, bob = 0, blink = false, faint = false, walk = null } = opts;
  const r = species.render;
  const body = r.bodyColor, sec = r.secondaryColor;
  ctx.save();
  ctx.translate(cx, cy + bob);
  if (flip) ctx.scale(-1, 1);
  if (faint) { ctx.globalAlpha = 0.35; ctx.rotate(Math.PI / 2); }

  ctx.save();
  ctx.globalAlpha = 0.22;
  ctx.fillStyle = '#000';
  ctx.beginPath();
  ctx.ellipse(0, s * 0.92, s * 0.85, s * 0.22, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  // ---- tail (drawn behind body) ----
  drawTail(ctx, r.tailType, s, sec, body);

  // ---- back features (behind body outline) ----
  if (['wing'].includes(r.feature)) drawFeature(ctx, r.feature, s, body, sec);

  // ---- legs (mostly hidden under the body, just the feet peek out at the bottom) ----
  drawLegs(ctx, s, body, walk);

  // ---- body ----
  const grad = ctx.createRadialGradient(-s * 0.3, -s * 0.35, s * 0.2, 0, 0, s * 1.1);
  grad.addColorStop(0, lighten(body, 0.35));
  grad.addColorStop(1, body);
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.ellipse(0, 0, s * 0.72, s * 0.68, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = darken(body, 0.35);
  ctx.lineWidth = Math.max(1.5, s * 0.045);
  ctx.stroke();

  // belly patch
  ctx.fillStyle = lighten(body, 0.55);
  ctx.beginPath();
  ctx.ellipse(0, s * 0.22, s * 0.42, s * 0.32, 0, 0, Math.PI * 2);
  ctx.fill();

  drawPattern(ctx, r.pattern, s, sec, body);

  // ---- glossy vinyl-toy sheen (manga-kawaii sticker shine) ----
  ctx.save();
  ctx.globalAlpha = 0.4;
  const glossGrad = ctx.createLinearGradient(-s * 0.4, -s * 0.5, -s * 0.1, -s * 0.1);
  glossGrad.addColorStop(0, 'rgba(255,255,255,0.9)');
  glossGrad.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = glossGrad;
  ctx.beginPath();
  ctx.ellipse(-s * 0.26, -s * 0.32, s * 0.24, s * 0.15, -0.55, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  // ---- arms ----
  drawArms(ctx, s, body, walk);

  // ---- ears ----
  drawEars(ctx, r.earType, s, body, sec);

  // ---- front features ----
  if (!['wing'].includes(r.feature)) drawFeature(ctx, r.feature, s, body, sec);

  // ---- face (big manga-kawaii eyes: colored iris, double sparkle, lash line) ----
  const eyeY = -s * 0.08, eyeDX = s * 0.27;
  const eyeH = blink ? s * 0.02 : s * 0.19;
  const irisTone = lighten(darken(sec, 0.25), 0.05);
  for (const side of [-1, 1]) {
    ctx.save();
    ctx.translate(side * eyeDX, eyeY);
    // sclera
    ctx.fillStyle = '#fff';
    ctx.beginPath();
    ctx.ellipse(0, 0, s * 0.155, eyeH, 0, 0, Math.PI * 2);
    ctx.fill();
    if (!blink) {
      // iris
      const irisGrad = ctx.createRadialGradient(side * s * 0.01, -s * 0.015, s * 0.01, 0, s * 0.02, eyeH * 0.95);
      irisGrad.addColorStop(0, lighten(irisTone, 0.3));
      irisGrad.addColorStop(1, darken(irisTone, 0.2));
      ctx.fillStyle = irisGrad;
      ctx.beginPath();
      ctx.ellipse(side * s * 0.012, s * 0.02, s * 0.125, eyeH * 0.86, 0, 0, Math.PI * 2);
      ctx.fill();
      // pupil
      ctx.fillStyle = '#241a1e';
      ctx.beginPath();
      ctx.ellipse(side * s * 0.02, s * 0.045, s * 0.062, eyeH * 0.44, 0, 0, Math.PI * 2);
      ctx.fill();
      // lash line along the top lid
      ctx.strokeStyle = darken(irisTone, 0.55);
      ctx.lineWidth = Math.max(1, s * 0.022);
      ctx.beginPath();
      ctx.arc(0, 0, s * 0.15, Math.PI * 1.08, Math.PI * 1.92);
      ctx.stroke();
      // big primary sparkle + small secondary sparkle
      ctx.fillStyle = '#fff';
      ctx.beginPath();
      ctx.ellipse(-side * s * 0.05, -s * 0.055, s * 0.048, s * 0.06, -0.3, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 0.85;
      ctx.beginPath();
      ctx.arc(side * s * 0.06, s * 0.07, s * 0.022, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
    }
    ctx.restore();
  }

  // small kawaii sparkle accent
  drawSparkle(ctx, s * 0.58, -s * 0.62, s * 0.07, '#fff8d9');

  // blush
  ctx.fillStyle = 'rgba(255,110,140,0.5)';
  for (const side of [-1, 1]) {
    ctx.beginPath();
    ctx.ellipse(side * s * 0.46, s * 0.14, s * 0.13, s * 0.075, 0, 0, Math.PI * 2);
    ctx.fill();
  }
  // smile
  ctx.strokeStyle = darken(body, 0.5);
  ctx.lineWidth = Math.max(1.2, s * 0.032);
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.arc(0, s * 0.12, s * 0.11, Math.PI * 0.2, Math.PI * 0.8);
  ctx.stroke();

  ctx.restore();
}

function drawSparkle(ctx, x, y, size, color) {
  ctx.save();
  ctx.translate(x, y);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(0, -size);
  ctx.quadraticCurveTo(size * 0.18, -size * 0.18, size, 0);
  ctx.quadraticCurveTo(size * 0.18, size * 0.18, 0, size);
  ctx.quadraticCurveTo(-size * 0.18, size * 0.18, -size, 0);
  ctx.quadraticCurveTo(-size * 0.18, -size * 0.18, 0, -size);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

// Diagonal quadruped gait: a limb's phase decides how far forward/back and how high it swings.
// Front-left pairs with back-right (same phase), front-right pairs with back-left (phase + PI) —
// like a running puppy's trot. `walk` is null for a standing/still creature (neutral pose).
function limbSwing(walk, side, swingX, liftY) {
  if (walk == null) return { dx: 0, dy: 0 };
  const phase = walk + (side === 1 ? 0 : Math.PI);
  return { dx: Math.cos(phase) * swingX, dy: -Math.max(0, Math.sin(phase)) * liftY };
}

function drawLegs(ctx, s, body, walk) {
  const shade = darken(body, 0.18);
  const positions = [];
  for (const side of [-1, 1]) {
    // legs pair with the opposite-side arm for the diagonal gait, so flip the phase here
    const { dx, dy } = limbSwing(walk, -side, s * 0.14, s * 0.1);
    positions.push({ side, x: side * s * 0.3 + dx, y: s * 0.68 + dy });
  }
  ctx.fillStyle = shade;
  ctx.strokeStyle = darken(body, 0.4);
  ctx.lineWidth = Math.max(1, s * 0.025);
  for (const p of positions) {
    ctx.beginPath();
    ctx.ellipse(p.x, p.y, s * 0.17, s * 0.16, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
  // little toes
  ctx.fillStyle = darken(body, 0.32);
  for (const p of positions) {
    for (const toe of [-0.08, 0, 0.08]) {
      ctx.beginPath();
      ctx.ellipse(p.x + toe * s, p.y + s * 0.12, s * 0.035, s * 0.03, 0, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function drawArms(ctx, s, body, walk) {
  ctx.fillStyle = body;
  ctx.strokeStyle = darken(body, 0.32);
  ctx.lineWidth = Math.max(1, s * 0.03);
  for (const side of [-1, 1]) {
    const { dx, dy } = limbSwing(walk, side, s * 0.16, s * 0.12);
    ctx.save();
    ctx.translate(side * s * 0.66 + dx, s * 0.2 + dy);
    ctx.rotate(side * 0.35);
    ctx.beginPath();
    ctx.ellipse(0, 0, s * 0.15, s * 0.22, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
    // little paw
    ctx.fillStyle = lighten(body, 0.3);
    ctx.beginPath();
    ctx.ellipse(side * s * 0.72 + dx, s * 0.36 + dy, s * 0.09, s * 0.08, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = body;
  }
}

function drawEars(ctx, type, s, body, sec) {
  if (type === 'none') return;
  ctx.fillStyle = body;
  ctx.strokeStyle = darken(body, 0.35);
  ctx.lineWidth = Math.max(1.2, s * 0.03);
  for (const side of [-1, 1]) {
    ctx.save();
    ctx.translate(side * s * 0.48, -s * 0.55);
    if (type === 'round') {
      ctx.beginPath(); ctx.arc(0, 0, s * 0.22, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    } else if (type === 'pointy') {
      ctx.beginPath();
      ctx.moveTo(-s * 0.16, s * 0.1); ctx.lineTo(0, -s * 0.5); ctx.lineTo(s * 0.16, s * 0.1);
      ctx.closePath(); ctx.fill(); ctx.stroke();
      ctx.fillStyle = lighten(sec, 0.1);
      ctx.beginPath();
      ctx.moveTo(-s * 0.06, s * 0.02); ctx.lineTo(0, -s * 0.3); ctx.lineTo(s * 0.06, s * 0.02);
      ctx.closePath(); ctx.fill();
      ctx.fillStyle = body;
    } else if (type === 'floppy') {
      ctx.rotate(side * 0.5);
      ctx.beginPath(); ctx.ellipse(0, s * 0.2, s * 0.15, s * 0.32, 0, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    } else if (type === 'antenna') {
      ctx.strokeStyle = darken(body, 0.4);
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.quadraticCurveTo(side * s * 0.1, -s * 0.4, side * s * 0.05, -s * 0.6);
      ctx.stroke();
      ctx.fillStyle = sec;
      ctx.beginPath(); ctx.arc(side * s * 0.05, -s * 0.6, s * 0.07, 0, Math.PI * 2); ctx.fill();
    }
    ctx.restore();
  }
}

function drawTail(ctx, type, s, sec, body) {
  if (type === 'none') return;
  ctx.save();
  ctx.translate(-s * 0.55, s * 0.25);
  if (type === 'fluffy') {
    ctx.fillStyle = lighten(body, 0.1);
    for (let i = 0; i < 3; i++) {
      ctx.beginPath();
      ctx.arc(-i * s * 0.18, -i * s * 0.08, s * 0.28 - i * s * 0.02, 0, Math.PI * 2);
      ctx.fill();
    }
  } else if (type === 'thin') {
    ctx.strokeStyle = body; ctx.lineWidth = s * 0.12; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.quadraticCurveTo(-s * 0.5, -s * 0.1, -s * 0.55, -s * 0.55); ctx.stroke();
  } else if (type === 'flame') {
    ctx.strokeStyle = body; ctx.lineWidth = s * 0.1; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.quadraticCurveTo(-s * 0.4, 0, -s * 0.5, -s * 0.35); ctx.stroke();
    const g = ctx.createLinearGradient(-s * 0.75, -s * 0.75, -s * 0.35, -s * 0.2);
    g.addColorStop(0, '#fff3b0'); g.addColorStop(1, '#f2942c');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.moveTo(-s * 0.45, -s * 0.3);
    ctx.quadraticCurveTo(-s * 0.85, -s * 0.5, -s * 0.65, -s * 0.85);
    ctx.quadraticCurveTo(-s * 0.55, -s * 0.55, -s * 0.35, -s * 0.45);
    ctx.closePath(); ctx.fill();
  } else if (type === 'fish') {
    ctx.fillStyle = sec;
    ctx.beginPath();
    ctx.moveTo(0, -s * 0.2); ctx.lineTo(-s * 0.55, -s * 0.45); ctx.lineTo(-s * 0.45, 0);
    ctx.lineTo(-s * 0.55, s * 0.45); ctx.lineTo(0, s * 0.2); ctx.closePath(); ctx.fill();
  }
  ctx.restore();
}

function drawFeature(ctx, feature, s, body, sec) {
  ctx.fillStyle = sec;
  ctx.strokeStyle = darken(sec, 0.3);
  ctx.lineWidth = Math.max(1, s * 0.03);
  switch (feature) {
    case 'rockCollar':
      for (let i = -2; i <= 2; i++) {
        ctx.beginPath();
        ctx.moveTo(i * s * 0.16, s * 0.5);
        ctx.lineTo(i * s * 0.16 - s * 0.06, s * 0.68);
        ctx.lineTo(i * s * 0.16 + s * 0.06, s * 0.68);
        ctx.closePath(); ctx.fill();
      }
      break;
    case 'ruff':
      ctx.beginPath();
      ctx.ellipse(0, s * 0.42, s * 0.55, s * 0.22, 0, 0, Math.PI * 2);
      ctx.fill();
      break;
    case 'bulb':
    case 'bud':
    case 'flower': {
      ctx.save();
      ctx.translate(0, -s * 0.15);
      ctx.fillStyle = darken(body, 0.15);
      ctx.beginPath(); ctx.ellipse(0, 0, s * 0.32, s * 0.28, 0, 0, Math.PI * 2); ctx.fill();
      if (feature !== 'bulb') {
        ctx.fillStyle = feature === 'flower' ? '#f06fb0' : '#e0c94c';
        for (let i = 0; i < 5; i++) {
          const a = (i / 5) * Math.PI * 2;
          ctx.beginPath();
          ctx.ellipse(Math.cos(a) * s * 0.18, Math.sin(a) * s * 0.18, s * 0.13, s * 0.08, a, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.fillStyle = '#fff6c9';
        ctx.beginPath(); ctx.arc(0, 0, s * 0.1, 0, Math.PI * 2); ctx.fill();
      }
      ctx.restore();
      break;
    }
    case 'antenna':
      for (const side of [-1, 1]) {
        ctx.strokeStyle = darken(body, 0.4);
        ctx.beginPath(); ctx.moveTo(side * s * 0.1, -s * 0.55); ctx.quadraticCurveTo(side * s * 0.3, -s * 0.85, side * s * 0.15, -s * 0.95);
        ctx.stroke();
        ctx.fillStyle = sec;
        ctx.beginPath(); ctx.arc(side * s * 0.15, -s * 0.95, s * 0.06, 0, Math.PI * 2); ctx.fill();
      }
      break;
    case 'shell':
      ctx.fillStyle = sec;
      ctx.beginPath(); ctx.ellipse(0, s * 0.05, s * 0.6, s * 0.5, 0, Math.PI, 0); ctx.fill(); ctx.stroke();
      break;
    case 'wing':
      for (const side of [-1, 1]) {
        ctx.save();
        ctx.translate(side * s * 0.5, -s * 0.05);
        ctx.rotate(side * 0.3);
        ctx.fillStyle = 'rgba(255,255,255,0.55)';
        ctx.beginPath();
        ctx.ellipse(0, 0, s * 0.4, s * 0.22, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = darken(sec, 0.2); ctx.stroke();
        ctx.restore();
      }
      break;
    case 'fin':
      ctx.beginPath();
      ctx.moveTo(0, -s * 0.55); ctx.lineTo(-s * 0.15, -s * 0.85); ctx.lineTo(s * 0.15, -s * 0.85);
      ctx.closePath(); ctx.fill(); ctx.stroke();
      break;
    case 'spikes':
      for (let i = -1; i <= 1; i++) {
        ctx.beginPath();
        ctx.moveTo(i * s * 0.25, -s * 0.5);
        ctx.lineTo(i * s * 0.25 - s * 0.08, -s * 0.75);
        ctx.lineTo(i * s * 0.25 + s * 0.08, -s * 0.75);
        ctx.closePath(); ctx.fill();
      }
      break;
    case 'bone':
      ctx.save();
      ctx.translate(s * 0.65, s * 0.1);
      ctx.rotate(-0.6);
      ctx.fillStyle = '#f2ecd2';
      ctx.strokeStyle = '#c9c0a0';
      ctx.fillRect(-s * 0.32, -s * 0.06, s * 0.64, s * 0.12);
      for (const dx of [-s * 0.32, s * 0.32]) {
        for (const dy of [-s * 0.08, s * 0.08]) {
          ctx.beginPath(); ctx.arc(dx, dy, s * 0.08, 0, Math.PI * 2); ctx.fill();
        }
      }
      ctx.restore();
      break;
    case 'flameTuft':
    case 'flameTail': {
      const pos = feature === 'flameTail' ? [-s * 0.55, -s * 0.35] : [0, -s * 0.65];
      const g = ctx.createLinearGradient(pos[0], pos[1] - s * 0.35, pos[0], pos[1] + s * 0.1);
      g.addColorStop(0, '#fff3b0'); g.addColorStop(1, '#f2692c');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.moveTo(pos[0] - s * 0.15, pos[1] + s * 0.1);
      ctx.quadraticCurveTo(pos[0] - s * 0.3, pos[1] - s * 0.3, pos[0], pos[1] - s * 0.45);
      ctx.quadraticCurveTo(pos[0] + s * 0.3, pos[1] - s * 0.3, pos[0] + s * 0.15, pos[1] + s * 0.1);
      ctx.closePath(); ctx.fill();
      break;
    }
    case 'hood':
      ctx.fillStyle = sec;
      ctx.beginPath(); ctx.ellipse(0, -s * 0.35, s * 0.55, s * 0.4, 0, Math.PI, 0); ctx.fill();
      break;
    case 'horn':
      ctx.fillStyle = '#f2e299';
      ctx.beginPath();
      ctx.moveTo(-s * 0.08, -s * 0.4); ctx.lineTo(0, -s * 0.85); ctx.lineTo(s * 0.08, -s * 0.4);
      ctx.closePath(); ctx.fill();
      break;
    case 'halo':
      ctx.save();
      ctx.strokeStyle = sec;
      ctx.lineWidth = s * 0.06;
      ctx.globalAlpha = 0.85;
      ctx.beginPath(); ctx.ellipse(0, -s * 0.95, s * 0.4, s * 0.14, 0, 0, Math.PI * 2); ctx.stroke();
      ctx.shadowColor = sec; ctx.shadowBlur = s * 0.3;
      ctx.stroke();
      ctx.restore();
      break;
    default: break;
  }
}

function drawPattern(ctx, pattern, s, sec, body) {
  ctx.fillStyle = darken(sec === body ? body : sec, 0.05);
  ctx.globalAlpha = 0.55;
  if (pattern === 'spots') {
    const spots = [[-0.3, -0.1, 0.1], [0.28, -0.2, 0.08], [0, 0.35, 0.09], [-0.15, 0.4, 0.06]];
    for (const [x, y, rr] of spots) {
      ctx.beginPath(); ctx.arc(x * s, y * s, rr * s, 0, Math.PI * 2); ctx.fill();
    }
  } else if (pattern === 'stripes') {
    for (let i = -1; i <= 1; i++) {
      ctx.beginPath();
      ctx.ellipse(i * s * 0.28, -s * 0.1, s * 0.08, s * 0.5, 0.3, 0, Math.PI * 2);
      ctx.fill();
    }
  } else if (pattern === 'rings') {
    ctx.strokeStyle = ctx.fillStyle;
    ctx.lineWidth = s * 0.08;
    ctx.beginPath(); ctx.ellipse(0, s * 0.05, s * 0.55, s * 0.5, 0, 0, Math.PI * 2); ctx.stroke();
  } else if (pattern === 'scales') {
    for (let row = -1; row <= 1; row++) {
      for (let col = -1; col <= 1; col++) {
        ctx.beginPath();
        ctx.arc(col * s * 0.22, row * s * 0.22 + s * 0.05, s * 0.09, Math.PI, 0);
        ctx.fill();
      }
    }
  }
  ctx.globalAlpha = 1;
}

export function typePillColor(t) { return TYPE_COLORS[t] || '#999'; }

// ---------------- Player & trainer sprites ----------------
export function drawPersonSprite(ctx, cx, cy, size, opts = {}) {
  const { facing = 'down', walkFrame = 0, cap = '#e0472c', shirt = '#3c7bd6', skin = '#f2c9a0', hair = '#4a3222', accent = '#fff' } = opts;
  const s = size;
  ctx.save();
  ctx.translate(cx, cy);

  ctx.save();
  ctx.globalAlpha = 0.22; ctx.fillStyle = '#000';
  ctx.beginPath(); ctx.ellipse(0, s * 0.62, s * 0.32, s * 0.1, 0, 0, Math.PI * 2); ctx.fill();
  ctx.restore();

  const legOffset = walkFrame === 1 ? s * 0.12 : (walkFrame === 2 ? -s * 0.12 : 0);
  ctx.fillStyle = '#2c3550';
  ctx.beginPath(); ctx.ellipse(-s * 0.1 + legOffset, s * 0.52, s * 0.09, s * 0.16, 0, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.ellipse(s * 0.1 - legOffset, s * 0.52, s * 0.09, s * 0.16, 0, 0, Math.PI * 2); ctx.fill();

  // body
  ctx.fillStyle = shirt;
  ctx.beginPath(); ctx.ellipse(0, s * 0.2, s * 0.26, s * 0.3, 0, 0, Math.PI * 2); ctx.fill();
  // backpack peek
  ctx.fillStyle = darken(shirt, 0.3);
  ctx.beginPath(); ctx.ellipse(0, s * 0.28, s * 0.14, s * 0.16, 0, 0, Math.PI * 2); ctx.fill();

  // head
  ctx.fillStyle = skin;
  ctx.beginPath(); ctx.arc(0, -s * 0.18, s * 0.24, 0, Math.PI * 2); ctx.fill();

  // hair
  ctx.fillStyle = hair;
  ctx.beginPath(); ctx.arc(0, -s * 0.24, s * 0.24, Math.PI, 0); ctx.fill();

  // cap
  ctx.fillStyle = cap;
  ctx.beginPath(); ctx.arc(0, -s * 0.28, s * 0.24, Math.PI * 1.05, Math.PI * 1.95); ctx.fill();
  ctx.beginPath();
  const brimDx = facing === 'left' ? -1 : facing === 'right' ? 1 : 0;
  ctx.ellipse(brimDx * s * 0.2, -s * 0.14, s * 0.16, s * 0.06, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = accent;
  ctx.beginPath(); ctx.arc(0, -s * 0.4, s * 0.05, 0, Math.PI * 2); ctx.fill();

  // face (only when facing down/left/right, hidden when facing up/back)
  if (facing !== 'up') {
    ctx.fillStyle = '#2a2a2a';
    const eyeDx = facing === 'left' ? -s * 0.06 : facing === 'right' ? s * 0.06 : s * 0.07;
    ctx.beginPath(); ctx.arc(eyeDx, -s * 0.16, s * 0.03, 0, Math.PI * 2); ctx.fill();
    if (facing === 'down') { ctx.beginPath(); ctx.arc(-eyeDx, -s * 0.16, s * 0.03, 0, Math.PI * 2); ctx.fill(); }
  }

  // arms
  ctx.fillStyle = shirt;
  const armSwing = walkFrame === 1 ? -1 : walkFrame === 2 ? 1 : 0;
  ctx.beginPath(); ctx.ellipse(-s * 0.24, s * 0.12 + armSwing * s * 0.05, s * 0.07, s * 0.16, 0.15, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.ellipse(s * 0.24, s * 0.12 - armSwing * s * 0.05, s * 0.07, s * 0.16, -0.15, 0, Math.PI * 2); ctx.fill();

  ctx.restore();
}

// ---------------- Tiles ----------------
export function drawTile(ctx, type, x, y, size, t) {
  const wobble = Math.sin(t * 2 + x * 0.7 + y * 0.3);
  switch (type) {
    case 'grass':
      ctx.fillStyle = '#7bc45c';
      ctx.fillRect(x, y, size, size);
      ctx.fillStyle = 'rgba(255,255,255,0.08)';
      ctx.fillRect(x, y, size, size / 2);
      break;
    case 'tallGrass':
      ctx.fillStyle = '#5fae44';
      ctx.fillRect(x, y, size, size);
      ctx.strokeStyle = '#3f8a2c';
      ctx.lineWidth = 2;
      for (let i = 0; i < 3; i++) {
        const bx = x + size * (0.2 + i * 0.3) + wobble * 1.5;
        ctx.beginPath();
        ctx.moveTo(bx, y + size * 0.9);
        ctx.quadraticCurveTo(bx + wobble * 2, y + size * 0.5, bx, y + size * 0.25);
        ctx.stroke();
      }
      break;
    case 'forestGrass':
      ctx.fillStyle = '#4a9d3a';
      ctx.fillRect(x, y, size, size);
      ctx.strokeStyle = '#2e6b1f';
      ctx.lineWidth = 2;
      for (let i = 0; i < 3; i++) {
        const bx = x + size * (0.2 + i * 0.3) + wobble * 1.5;
        ctx.beginPath();
        ctx.moveTo(bx, y + size * 0.9);
        ctx.quadraticCurveTo(bx + wobble * 2, y + size * 0.5, bx, y + size * 0.25);
        ctx.stroke();
      }
      break;
    case 'shoreGrass':
      ctx.fillStyle = '#eddca0';
      ctx.fillRect(x, y, size, size);
      ctx.strokeStyle = '#3f8a2c';
      ctx.lineWidth = 2;
      for (let i = 0; i < 2; i++) {
        const bx = x + size * (0.3 + i * 0.35) + wobble * 1.5;
        ctx.beginPath();
        ctx.moveTo(bx, y + size * 0.85);
        ctx.quadraticCurveTo(bx + wobble * 2, y + size * 0.5, bx, y + size * 0.3);
        ctx.stroke();
      }
      break;
    case 'path':
      ctx.fillStyle = '#e0c58c';
      ctx.fillRect(x, y, size, size);
      ctx.fillStyle = 'rgba(150,110,60,0.25)';
      if ((x / size + y / size) % 3 === 0) ctx.fillRect(x + size * 0.3, y + size * 0.6, size * 0.15, size * 0.1);
      break;
    case 'sand':
      ctx.fillStyle = '#eddca0';
      ctx.fillRect(x, y, size, size);
      break;
    case 'tree':
      ctx.fillStyle = '#7bc45c'; ctx.fillRect(x, y, size, size);
      ctx.fillStyle = '#8a5a2e';
      ctx.fillRect(x + size * 0.42, y + size * 0.55, size * 0.16, size * 0.4);
      ctx.fillStyle = '#3f8a2c';
      ctx.beginPath(); ctx.arc(x + size * 0.5, y + size * 0.4, size * 0.38, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#4fae3c';
      ctx.beginPath(); ctx.arc(x + size * 0.38, y + size * 0.32, size * 0.22, 0, Math.PI * 2); ctx.fill();
      break;
    case 'pineTree':
      ctx.fillStyle = '#dff0f5'; ctx.fillRect(x, y, size, size);
      ctx.fillStyle = '#5a4a34';
      ctx.fillRect(x + size * 0.44, y + size * 0.65, size * 0.12, size * 0.3);
      ctx.fillStyle = '#2e6b5a';
      for (let i = 0; i < 3; i++) {
        ctx.beginPath();
        ctx.moveTo(x + size * 0.5, y + size * (0.1 + i * 0.16));
        ctx.lineTo(x + size * (0.25 - i * 0.02), y + size * (0.35 + i * 0.16));
        ctx.lineTo(x + size * (0.75 + i * 0.02), y + size * (0.35 + i * 0.16));
        ctx.closePath(); ctx.fill();
      }
      break;
    case 'water':
      ctx.fillStyle = '#4a9dd6'; ctx.fillRect(x, y, size, size);
      ctx.strokeStyle = 'rgba(255,255,255,0.35)'; ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x + size * 0.1, y + size * 0.5 + wobble * 2);
      ctx.quadraticCurveTo(x + size * 0.5, y + size * 0.35 - wobble * 2, x + size * 0.9, y + size * 0.5 + wobble * 2);
      ctx.stroke();
      break;
    case 'caveFloor':
      ctx.fillStyle = '#8c7a68'; ctx.fillRect(x, y, size, size);
      ctx.fillStyle = 'rgba(0,0,0,0.12)';
      ctx.beginPath(); ctx.arc(x + size * 0.3, y + size * 0.6, size * 0.06, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.arc(x + size * 0.7, y + size * 0.3, size * 0.05, 0, Math.PI * 2); ctx.fill();
      break;
    case 'caveWall':
      ctx.fillStyle = '#544838'; ctx.fillRect(x, y, size, size);
      ctx.strokeStyle = 'rgba(255,255,255,0.08)'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x + size * 0.2, y); ctx.lineTo(x + size * 0.5, y + size * 0.5); ctx.lineTo(x + size * 0.3, y + size); ctx.stroke();
      break;
    case 'snow':
      ctx.fillStyle = '#eef7fb'; ctx.fillRect(x, y, size, size);
      ctx.fillStyle = 'rgba(150,190,210,0.4)';
      ctx.beginPath(); ctx.arc(x + size * 0.6, y + size * 0.65, size * 0.04, 0, Math.PI * 2); ctx.fill();
      break;
    case 'iceRock':
      ctx.fillStyle = '#eef7fb'; ctx.fillRect(x, y, size, size);
      ctx.fillStyle = '#bfe2ef';
      ctx.beginPath();
      ctx.moveTo(x + size * 0.3, y + size * 0.85); ctx.lineTo(x + size * 0.4, y + size * 0.35);
      ctx.lineTo(x + size * 0.65, y + size * 0.5); ctx.lineTo(x + size * 0.7, y + size * 0.85);
      ctx.closePath(); ctx.fill();
      break;
    case 'volcanoGround':
      ctx.fillStyle = '#4a3a34'; ctx.fillRect(x, y, size, size);
      ctx.fillStyle = 'rgba(255,120,60,0.12)';
      ctx.fillRect(x, y, size, size * 0.4);
      break;
    case 'lava':
      ctx.fillStyle = '#c9401f'; ctx.fillRect(x, y, size, size);
      ctx.fillStyle = `rgba(255,${180 + wobble * 30},60,0.6)`;
      ctx.beginPath(); ctx.arc(x + size * 0.5, y + size * 0.5, size * 0.25 + wobble * 2, 0, Math.PI * 2); ctx.fill();
      break;
    case 'ashRock':
      ctx.fillStyle = '#4a3a34'; ctx.fillRect(x, y, size, size);
      ctx.fillStyle = '#2e2420';
      ctx.beginPath(); ctx.ellipse(x + size * 0.5, y + size * 0.6, size * 0.3, size * 0.22, 0, 0, Math.PI * 2); ctx.fill();
      break;
    case 'sacredGround':
      ctx.fillStyle = '#efe6f7'; ctx.fillRect(x, y, size, size);
      ctx.strokeStyle = `rgba(150,120,220,${0.15 + Math.abs(wobble) * 0.15})`;
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(x + size * 0.5, y + size * 0.5, size * 0.3, 0, Math.PI * 2); ctx.stroke();
      break;
    case 'shrine':
      ctx.fillStyle = '#efe6f7'; ctx.fillRect(x, y, size, size);
      ctx.fillStyle = '#c9b8e0';
      ctx.fillRect(x + size * 0.2, y + size * 0.5, size * 0.6, size * 0.4);
      ctx.fillStyle = `rgba(120,200,240,${0.5 + Math.abs(wobble) * 0.4})`;
      ctx.beginPath(); ctx.arc(x + size * 0.5, y + size * 0.4, size * 0.28, 0, Math.PI * 2); ctx.fill();
      break;
    case 'mart':
      ctx.fillStyle = '#e0c58c'; ctx.fillRect(x, y, size, size);
      ctx.fillStyle = '#f2f2f2'; ctx.fillRect(x + size * 0.1, y + size * 0.35, size * 0.8, size * 0.55);
      ctx.fillStyle = '#e0472c'; ctx.fillRect(x, y, size, size * 0.4);
      ctx.fillStyle = '#fff'; ctx.font = `bold ${size * 0.32}px sans-serif`; ctx.textAlign = 'center';
      ctx.fillText('$', x + size * 0.5, y + size * 0.72);
      break;
    case 'healingCenter':
      ctx.fillStyle = '#e0c58c'; ctx.fillRect(x, y, size, size);
      ctx.fillStyle = '#f2f2f2'; ctx.fillRect(x + size * 0.1, y + size * 0.35, size * 0.8, size * 0.55);
      ctx.fillStyle = '#f06f9c'; ctx.fillRect(x, y, size, size * 0.4);
      ctx.strokeStyle = '#f06f9c'; ctx.lineWidth = size * 0.08;
      ctx.beginPath();
      ctx.moveTo(x + size * 0.5, y + size * 0.5); ctx.lineTo(x + size * 0.5, y + size * 0.78);
      ctx.moveTo(x + size * 0.36, y + size * 0.64); ctx.lineTo(x + size * 0.64, y + size * 0.64);
      ctx.stroke();
      break;
    case 'sign':
      ctx.fillStyle = '#7bc45c'; ctx.fillRect(x, y, size, size);
      ctx.fillStyle = '#8a5a2e'; ctx.fillRect(x + size * 0.44, y + size * 0.5, size * 0.12, size * 0.4);
      ctx.fillStyle = '#c9a06a'; ctx.fillRect(x + size * 0.2, y + size * 0.25, size * 0.6, size * 0.3);
      break;
    default:
      ctx.fillStyle = '#7bc45c'; ctx.fillRect(x, y, size, size);
  }
}
