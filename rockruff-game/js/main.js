// Game loop, input, world state machine — the glue holding Rockruff together.
import { generateWorld, tileAt, TILE, WORLD_W, WORLD_H, BLOCKING } from './world.js';
import { SPECIES } from './pokedex-data.js';
import { createPlayer, healParty, addCapturedPokemon } from './player.js';
import {
  startWildBattle, startTrainerBattle, startLegendaryBattle, resolveTurn,
  activePlayerMon, activeEnemyMon, switchActive, attemptFlee, attemptCatch, usePotion, enemyFreeTurn,
} from './battle.js';
import { drawTile, drawPersonSprite, drawCreature } from './render.js';
import { populateWildSpawns, updateWildSpawns, scheduleRespawn, removeSpawn, spawnAtTile } from './wild.js';
import * as ui from './ui.js';

const canvas = document.getElementById('game-canvas');
const ctx = canvas.getContext('2d');
const CANVAS_W = canvas.width, CANVAS_H = canvas.height;
const ANIM_DUR = 0.16;

// #game-root is laid out at a fixed 880x600 design size, then scaled as one unit to fit
// whatever viewport it's in — keeps the canvas crisp and every DOM overlay proportional
// instead of stretching on a phone's portrait aspect ratio.
function fitToViewport() {
  const root = document.getElementById('game-root');
  const pad = 16;
  const scale = Math.min((window.innerWidth - pad) / CANVAS_W, (window.innerHeight - pad) / CANVAS_H);
  root.style.transform = `scale(${Math.max(0.25, scale)})`;
}
window.addEventListener('resize', fitToViewport);
window.addEventListener('orientationchange', fitToViewport);
fitToViewport();

const DIR_VEC = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
const KEY_DIR = {
  ArrowUp: 'up', KeyW: 'up', ArrowDown: 'down', KeyS: 'down',
  ArrowLeft: 'left', KeyA: 'left', ArrowRight: 'right', KeyD: 'right',
};

let world, player;
let mode = 'BOOT'; // BOOT | INTRO | OVERWORLD | BUSY | BATTLE
const anim = { px: 0, py: 0, moving: false, t: 0, fromX: 0, fromY: 0, toX: 0, toY: 0 };
const partner = { px: 0, py: 0 };
const trail = [];
let timeAcc = 0;
const dirStack = [];

function pushDir(d) { if (!dirStack.includes(d)) dirStack.push(d); }
function popDir(d) { const i = dirStack.indexOf(d); if (i >= 0) dirStack.splice(i, 1); }
function currentDir() { return dirStack[dirStack.length - 1] || null; }
function lerp(a, b, t) { return a + (b - a) * t; }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function canWalk(x, y) {
  const tile = tileAt(world, x, y);
  if (!tile) return false;
  if (x === world.elder.x && y === world.elder.y) return world.elder.unlocked;
  return !BLOCKING.has(tile.type);
}

function facingTile() {
  const [dx, dy] = DIR_VEC[player.facing];
  return { x: player.x + dx, y: player.y + dy };
}

// ---------------- Save / load ----------------
const SAVE_KEY = 'rockruff-save-v1';
function saveGame() {
  try {
    const data = {
      x: player.x, y: player.y, facing: player.facing, money: player.money, items: player.items,
      party: player.party, storage: player.storage,
      seen: [...player.pokedex.seen], caught: [...player.pokedex.caught],
      trainersDefeated: [...player.trainersDefeated],
      arceusCaught: player.arceusCaught, arceusEncountered: player.arceusEncountered,
      elderUnlocked: world.elder.unlocked,
    };
    localStorage.setItem(SAVE_KEY, JSON.stringify(data));
  } catch (e) { /* storage unavailable */ }
}
function loadGame() {
  try {
    const raw = localStorage.getItem(SAVE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    const p = createPlayer();
    p.x = data.x; p.y = data.y; p.facing = data.facing || 'down';
    p.money = data.money; p.items = data.items;
    p.party = data.party; p.storage = data.storage || [];
    p.pokedex.seen = new Set(data.seen); p.pokedex.caught = new Set(data.caught);
    p.trainersDefeated = new Set(data.trainersDefeated || []);
    p.arceusCaught = !!data.arceusCaught; p.arceusEncountered = !!data.arceusEncountered;
    world.elder.unlocked = !!data.elderUnlocked;
    return p;
  } catch (e) { return null; }
}
function eraseSave() { try { localStorage.removeItem(SAVE_KEY); } catch (e) {} }

// ---------------- Movement ----------------
function updateMovement(dt) {
  if (!anim.moving) {
    const dir = currentDir();
    if (dir) {
      player.facing = dir;
      const [dx, dy] = DIR_VEC[dir];
      const nx = player.x + dx, ny = player.y + dy;
      if (canWalk(nx, ny)) {
        anim.moving = true; anim.t = 0;
        anim.fromX = player.x * TILE + TILE / 2; anim.fromY = player.y * TILE + TILE / 2;
        anim.toX = nx * TILE + TILE / 2; anim.toY = ny * TILE + TILE / 2;
        player.x = nx; player.y = ny;
      }
    }
  } else {
    anim.t = Math.min(1, anim.t + dt / ANIM_DUR);
    anim.px = lerp(anim.fromX, anim.toX, anim.t);
    anim.py = lerp(anim.fromY, anim.toY, anim.t);
    if (anim.t >= 1) { anim.moving = false; onArrive(player.x, player.y); }
  }
  if (!anim.moving) { anim.px = player.x * TILE + TILE / 2; anim.py = player.y * TILE + TILE / 2; }
}

function updatePartner(dt) {
  trail.push({ px: anim.px, py: anim.py });
  if (trail.length > 26) trail.shift();
  const target = trail[Math.max(0, trail.length - 16)] || trail[0];
  partner.px += (target.px - partner.px) * Math.min(1, dt * 6);
  partner.py += (target.py - partner.py) * Math.min(1, dt * 6);
}

function onArrive(x, y) {
  const tile = tileAt(world, x, y);
  if (!tile) return;
  if (x === world.shrine.x && y === world.shrine.y) { triggerShrine(); return; }
  const spawn = spawnAtTile(world, x, y);
  if (spawn && mode === 'OVERWORLD') triggerWildEncounter(spawn);
}

// ---------------- Interaction ----------------
function handleInteract() {
  if (mode !== 'OVERWORLD' || anim.moving) return;
  const { x: fx, y: fy } = facingTile();
  const tile = tileAt(world, fx, fy);
  if (!tile) return;
  if (fx === world.elder.x && fy === world.elder.y) { triggerElder(); return; }
  const trainer = world.trainers.find(t => t.x === fx && t.y === fy);
  if (trainer) { triggerTrainer(trainer); return; }
  if (tile.type === 'sign') {
    const s = world.signs.find(s => s.x === fx && s.y === fy);
    if (s) triggerSign(s.text);
    return;
  }
  if (tile.type === 'mart') { triggerMart(); return; }
  if (tile.type === 'healingCenter') { triggerHealingCenter(); return; }
  if (fx === world.shrine.x && fy === world.shrine.y) { triggerShrine(); return; }
}

function interactableHere() {
  const { x: fx, y: fy } = facingTile();
  const tile = tileAt(world, fx, fy);
  if (!tile) return false;
  if (fx === world.elder.x && fy === world.elder.y) return true;
  if (world.trainers.some(t => t.x === fx && t.y === fy)) return true;
  return ['sign', 'mart', 'healingCenter', 'shrine'].includes(tile.type);
}

// ---------------- Triggers ----------------
async function triggerSign(text) {
  mode = 'BUSY';
  await ui.say(text);
  mode = 'OVERWORLD';
}

async function triggerMart() {
  mode = 'BUSY';
  await ui.say('Welcome to the Poké Mart! Take a look around.', 'Shopkeeper');
  await new Promise(resolve => {
    const body = document.createElement('div');
    function onBuy(key, price) {
      if (player.money >= price) { player.money -= price; player.items[key] += 1; ui.updateHUD(player); saveGame(); }
    }
    function refresh() { body.innerHTML = ''; body.appendChild(ui.buildShopBody(player, onBuy, refresh)); }
    refresh();
    ui.openModal('Poké Mart', body, resolve);
  });
  mode = 'OVERWORLD';
}

async function triggerHealingCenter() {
  mode = 'BUSY';
  await ui.say('Let your Pokémon rest a while...', 'Nurse');
  healParty(player);
  ui.updateHUD(player);
  saveGame();
  await ui.say('All better! Your team is fighting fit. Good luck out there!', 'Nurse');
  mode = 'OVERWORLD';
}

async function triggerElder() {
  mode = 'BUSY';
  const need = world.elder.requiredCaught;
  if (world.elder.unlocked) {
    await ui.say('The path to the Sacred Hollow is open. Go gently, chosen one.', world.elder.name);
    mode = 'OVERWORLD';
    return;
  }
  const caught = player.pokedex.caught.size;
  if (caught >= need) {
    world.elder.unlocked = true;
    await ui.say(`You've bonded with ${caught} Pokémon... I can feel it too, now. You are ready.`, world.elder.name);
    await ui.say('The Sacred Hollow opens before you. Arceus awaits at its heart.', world.elder.name);
    saveGame();
  } else {
    await ui.say(`Only a Trainer who has bonded with ${need} Pokémon may pass. You have ${caught} so far — keep exploring!`, world.elder.name);
  }
  mode = 'OVERWORLD';
}

async function triggerShrine() {
  mode = 'BUSY';
  if (player.arceusCaught) {
    await ui.say('The shrine glows softly. Arceus rests contentedly in your party.');
    mode = 'OVERWORLD';
    return;
  }
  if (player.pokedex.caught.size < world.elder.requiredCaught) {
    await ui.say('A powerful, unseen force gently turns you away. You are not ready yet.');
    mode = 'OVERWORLD';
    return;
  }
  await ui.say('The air shimmers... a radiant, many-colored light descends before you.');
  await ui.say('ARCEUS: "You have walked far, and grown strong beside many companions. Now — prove your bond."', 'Arceus');
  const battle = startLegendaryBattle(player);
  const outcome = await runBattle(battle);
  if (outcome === 'caught') {
    await endingSequence();
  } else if (outcome === 'lose') {
    await ui.say('Arceus watches on in silence as you retreat to heal. Return when you are ready.');
  } else if (outcome === 'ran') {
    // Arceus cannot be fled from — should not occur.
  } else {
    await ui.say('Arceus regards you a moment longer... then the light fades. Perhaps another time.');
  }
  mode = 'OVERWORLD';
  saveGame();
}

async function triggerTrainer(trainer) {
  mode = 'BUSY';
  if (player.trainersDefeated.has(trainer.id)) {
    await ui.say('Good game out there, Trainer! Catch you around.', trainer.name);
    mode = 'OVERWORLD';
    return;
  }
  await ui.say(trainer.taunt, trainer.name);
  const battle = startTrainerBattle(player, trainer);
  const outcome = await runBattle(battle);
  if (outcome === 'win') {
    await ui.say(`${trainer.defeatLine} Here's $${trainer.reward}!`, trainer.name);
  }
  ui.updateHUD(player);
  mode = 'OVERWORLD';
  saveGame();
}

async function triggerWildEncounter(spawn) {
  mode = 'BUSY';
  removeSpawn(world, spawn.uid);
  await ui.say(`Wild ${SPECIES[spawn.speciesId].name} appeared!`);
  const battle = startWildBattle(player, spawn.speciesId, spawn.level);
  await runBattle(battle);
  ui.updateHUD(player);
  scheduleRespawn(world, spawn.biome);
  mode = 'OVERWORLD';
  saveGame();
}

// ---------------- Battle orchestration ----------------
function chooseBattleAction(battle) {
  return new Promise(resolve => {
    const openMain = () => {
      ui.showBattleMenu({
        canFlee: battle.canFlee,
        onFight: openMoves, onBag: openBag, onParty: () => openParty(), onRun: () => resolve({ type: 'run' }),
      });
    };
    const openMoves = () => {
      ui.showMoveMenu(activePlayerMon(battle).moves, moveId => resolve({ type: 'fight', move: moveId }), openMain);
    };
    const openBag = () => {
      ui.showBagMenu(player, battle.canCatch, {
        onBall: ball => resolve({ type: 'ball', ball }),
        onPotion: () => resolve({ type: 'potion' }),
        onBack: openMain,
      });
    };
    const openParty = () => {
      ui.showPartySwitchMenu(player.party, battle.playerActive, false, idx => resolve({ type: 'switch', index: idx }), openMain);
    };
    openMain();
  });
}

async function playSteps(steps) {
  for (const step of steps) {
    if (step.type === 'text') await ui.say(step.text);
    else if (step.type === 'hpChange') { ui.setSideCard(step.side, step); await sleep(320); }
    else if (step.type === 'sendout') ui.setSideCard(step.side, step);
    else if (step.type === 'faint') await ui.say(`${step.name} fainted!`);
    else if (step.type === 'levelup') { await ui.say(`${step.name} grew to level ${step.level}!`); ui.updateHUD(player); }
    else if (step.type === 'evolve') {
      await ui.say(`What?! ${step.from} is evolving!`);
      await ui.say(`Congratulations! Your ${step.from} evolved into ${step.to}!`);
      ui.updateHUD(player);
    }
  }
}

async function runBattle(battle) {
  mode = 'BATTLE';
  ui.showBattleScreen();
  ui.updateBattleHUD(activePlayerMon(battle), activeEnemyMon(battle));
  while (!battle.finished) {
    const action = await chooseBattleAction(battle);
    if (action.type === 'fight') {
      await playSteps(resolveTurn(battle, action.move));
    } else if (action.type === 'ball') {
      const res = attemptCatch(battle, action.ball);
      player.items[action.ball] -= 1;
      ui.updateHUD(player);
      if (res.success) {
        await ui.say(`Gotcha! ${SPECIES[res.pokemon.speciesId].name} was caught!`);
        const dest = addCapturedPokemon(player, res.pokemon);
        if (res.pokemon.speciesId === 'arceus') player.arceusCaught = true;
        ui.updateHUD(player);
        if (dest === 'storage') await ui.say(`${SPECIES[res.pokemon.speciesId].name} was sent to storage — your party is full.`);
      } else {
        await ui.say(`Argh! The wild ${SPECIES[res.pokemon.speciesId].name} broke free!`);
        await playSteps(enemyFreeTurn(battle));
      }
    } else if (action.type === 'potion') {
      if (usePotion(battle)) {
        ui.updateBattleHUD(activePlayerMon(battle), activeEnemyMon(battle));
        await ui.say('HP restored!');
      } else {
        await ui.say("You don't have any Potions!");
      }
      await playSteps(enemyFreeTurn(battle));
    } else if (action.type === 'switch') {
      switchActive(battle, action.index);
      ui.updateBattleHUD(activePlayerMon(battle), activeEnemyMon(battle));
      await ui.say(`Go, ${SPECIES[activePlayerMon(battle).speciesId].name}!`);
      await playSteps(enemyFreeTurn(battle));
    } else if (action.type === 'run') {
      if (attemptFlee(battle)) await ui.say('Got away safely!');
      else { await ui.say("Couldn't get away!"); await playSteps(enemyFreeTurn(battle)); }
    }
  }
  ui.hideBattleScreen();
  ui.updateHUD(player);
  if (battle.outcome === 'lose') await blackout();
  saveGame();
  mode = 'OVERWORLD';
  return battle.outcome;
}

async function blackout() {
  await ui.say('You blacked out! Your team was rushed back to Hearth Town...');
  const lost = Math.floor(player.money * 0.5);
  player.money -= lost;
  healParty(player);
  player.x = 31; player.y = 23; player.facing = 'down';
  anim.px = player.x * TILE + TILE / 2; anim.py = player.y * TILE + TILE / 2; anim.moving = false;
  ui.updateHUD(player);
  await ui.say(`You lost $${lost} and hurried home to heal up. Don't give up!`);
}

// ---------------- Intro & ending ----------------
let introRafId = null;
function startIntroAnim(subject) {
  const ictx = ui.dom.introCanvas.getContext('2d');
  let t = 0;
  function frame() {
    t += 0.02;
    ictx.clearRect(0, 0, CANVAS_W, CANVAS_H);
    const g = ictx.createRadialGradient(CANVAS_W / 2, CANVAS_H / 2, 50, CANVAS_W / 2, CANVAS_H / 2, 520);
    g.addColorStop(0, '#3a2e6b'); g.addColorStop(1, '#0a0a18');
    ictx.fillStyle = g; ictx.fillRect(0, 0, CANVAS_W, CANVAS_H);
    for (let i = 0; i < 46; i++) {
      const sx = (i * 97) % CANVAS_W, sy = (i * 53 + i * i) % CANVAS_H;
      const tw = 0.3 + 0.6 * Math.abs(Math.sin(t * 1.3 + i));
      ictx.fillStyle = `rgba(255,255,255,${tw})`;
      ictx.beginPath(); ictx.arc(sx, sy, 1.6, 0, Math.PI * 2); ictx.fill();
    }
    ictx.save();
    ictx.globalAlpha = 0.35 + 0.15 * Math.sin(t * 1.5);
    ictx.fillStyle = '#8fd6ff';
    ictx.beginPath(); ictx.arc(CANVAS_W / 2, CANVAS_H / 2, 220 + 10 * Math.sin(t), 0, Math.PI * 2); ictx.fill();
    ictx.restore();
    drawCreature(ictx, CANVAS_W / 2, CANVAS_H / 2 + Math.sin(t * 1.2) * 8, 150, subject);
    introRafId = requestAnimationFrame(frame);
  }
  frame();
}
function stopIntroAnim() { if (introRafId) cancelAnimationFrame(introRafId); introRafId = null; }

async function playIntro() {
  startIntroAnim(SPECIES.arceus);
  const lines = [
    'Your journey begins in a quiet dream — a vast white void.',
    'Within it, a radiant, thousand-colored shape stirs to life before you.',
    'ARCEUS: "I am Arceus... said by some to have shaped this world, Pokémon and human alike."',
    'ARCEUS: "A darkness stirs at the edges of both our worlds. I cannot face it alone — and I have chosen you."',
    'ARCEUS: "Walk among Pokémon. Learn them. Befriend them. Grow strong together, side by side."',
    'ARCEUS: "Only a Trainer who has bonded closely with many companions may ever stand before me as an equal."',
    'The light fades. You wake in Hearth Town — your loyal partner Rockruff curled up beside you.',
    'Your Pokémon journey, and the fate of two worlds, starts now. Good luck, Trainer!',
  ];
  for (const line of lines) await ui.showIntroLine(line);
  stopIntroAnim();
  ui.hideIntro();
}

async function endingSequence() {
  startIntroAnim(SPECIES.arceus);
  const lines = [
    'Arceus lowers its head before you, golden light wrapping around its newest companion.',
    `${player.name}, Trainer of Hearth Town, has done the impossible — Arceus walks at your side.`,
    `Pokédex progress: ${player.pokedex.caught.size} Pokémon bonded with. The legend is fulfilled.`,
    'Humanity and Pokémon alike are safe... for now. But adventure never truly ends — keep exploring, keep training!',
  ];
  for (const line of lines) await ui.showIntroLine(line);
  stopIntroAnim();
  ui.hideIntro();
}

// ---------------- Pause menu ----------------
function openPauseMenu() {
  const body = document.createElement('div');
  const tabs = document.createElement('div');
  tabs.style.cssText = 'display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;';
  const content = document.createElement('div');
  function showTab(name) {
    content.innerHTML = '';
    if (name === 'party') content.appendChild(ui.buildPartyBody(player));
    else if (name === 'dex') content.appendChild(ui.buildPokedexBody(player));
    else if (name === 'bag') {
      const d = document.createElement('div');
      d.innerHTML = `<p>💰 Money: <b>${player.money}</b></p><p>🔴 Poké Balls: <b>${player.items.pokeball}</b></p>
        <p>🟡 Great Balls: <b>${player.items.greatball}</b></p><p>💊 Potions: <b>${player.items.potion}</b></p>
        <p style="margin-top:14px;font-size:12px;color:#777">Elder's requirement: ${player.pokedex.caught.size}/${world.elder.requiredCaught} Pokémon caught to reach the Sacred Hollow.</p>`;
      content.appendChild(d);
      const resetBtn = document.createElement('button');
      resetBtn.className = 'game-btn danger'; resetBtn.style.marginTop = '10px';
      resetBtn.textContent = '🗑 Erase Save & Start Over';
      resetBtn.onclick = () => {
        if (confirm('Erase your save and start a brand new journey?')) {
          eraseSave();
          location.reload();
        }
      };
      content.appendChild(resetBtn);
    }
  }
  for (const [key, label] of [['party', '🐾 Party'], ['dex', '📘 Pokédex'], ['bag', '🎒 Bag']]) {
    const b = document.createElement('button');
    b.className = 'game-btn'; b.style.padding = '8px 14px'; b.textContent = label;
    b.onclick = () => showTab(key);
    tabs.appendChild(b);
  }
  body.appendChild(tabs); body.appendChild(content);
  showTab('party');
  ui.openModal('Menu', body, () => { mode = 'OVERWORLD'; });
  mode = 'BUSY';
}

// ---------------- Rendering ----------------
function drawOverworld(t) {
  const camX = Math.max(0, Math.min(anim.px - CANVAS_W / 2, WORLD_W * TILE - CANVAS_W));
  const camY = Math.max(0, Math.min(anim.py - CANVAS_H / 2, WORLD_H * TILE - CANVAS_H));
  const x0 = Math.max(0, Math.floor(camX / TILE) - 1), x1 = Math.min(WORLD_W - 1, Math.ceil((camX + CANVAS_W) / TILE) + 1);
  const y0 = Math.max(0, Math.floor(camY / TILE) - 1), y1 = Math.min(WORLD_H - 1, Math.ceil((camY + CANVAS_H) / TILE) + 1);

  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      drawTile(ctx, world.tiles[y][x].type, x * TILE - camX, y * TILE - camY, TILE, t);
    }
  }

  const entities = [];
  for (const tr of world.trainers) {
    if (tr.x < x0 || tr.x > x1 || tr.y < y0 || tr.y > y1) continue;
    entities.push({ y: tr.y, draw: () => drawPersonSprite(ctx, tr.x * TILE - camX + TILE / 2, tr.y * TILE - camY + TILE / 2, TILE * 0.85, { facing: 'down', cap: tr.palette.cap, shirt: tr.palette.shirt }) });
  }
  for (const s of world.wildSpawns) {
    if (s.x < x0 || s.x > x1 || s.y < y0 || s.y > y1) continue;
    const wp = t * 12 + s.seed * 4;
    entities.push({
      y: s.y - 0.2,
      draw: () => drawCreature(ctx, s.px - camX, s.py - camY + TILE * 0.12, TILE * 0.32, SPECIES[s.speciesId], {
        walk: s.moving ? wp : null,
        bob: s.moving ? Math.abs(Math.sin(wp)) * 2.5 : Math.sin(t * 3 + s.seed) * 2,
      }),
    });
  }
  entities.push({ y: world.elder.y, draw: () => drawPersonSprite(ctx, world.elder.x * TILE - camX + TILE / 2, world.elder.y * TILE - camY + TILE / 2, TILE * 0.85, { facing: 'down', cap: '#cfd6e0', shirt: '#8a7ab5', hair: '#e8e8e8' }) });
  entities.push({
    y: player.y - 0.4,
    draw: () => drawCreature(ctx, partner.px - camX, partner.py - camY + TILE * 0.28, TILE * 0.42, SPECIES[player.party[0].speciesId], {
      walk: anim.moving ? t * 14 : null,
      bob: anim.moving ? Math.abs(Math.sin(t * 14)) * 3 : Math.sin(t * 6) * 2,
    }),
  });
  entities.push({
    y: player.y,
    draw: () => drawPersonSprite(ctx, anim.px - camX, anim.py - camY, TILE * 0.85, {
      facing: player.facing,
      walkFrame: anim.moving ? (Math.floor(t * 9) % 2 === 0 ? 1 : 2) : 0,
    }),
  });
  entities.sort((a, b) => a.y - b.y);
  for (const e of entities) e.draw();
}

function loop(now) {
  const dt = Math.min(0.05, (now - (loop.last || now)) / 1000);
  loop.last = now;
  timeAcc += dt;
  if (mode === 'OVERWORLD') {
    updateMovement(dt);
    updateWildSpawns(world, dt, now);
    if (mode === 'OVERWORLD' && !anim.moving) {
      const bumpedInto = spawnAtTile(world, player.x, player.y);
      if (bumpedInto) triggerWildEncounter(bumpedInto);
    }
  }
  updatePartner(dt);
  if (mode === 'OVERWORLD' || mode === 'BUSY' || mode === 'BATTLE') {
    ctx.clearRect(0, 0, CANVAS_W, CANVAS_H);
    drawOverworld(timeAcc);
    ui.setInteractHint(mode === 'OVERWORLD' && !anim.moving && interactableHere());
  }
  requestAnimationFrame(loop);
}

// ---------------- Input ----------------
document.addEventListener('keydown', e => {
  if (ui.textboxOpen()) {
    if (['Enter', 'Space', 'KeyE'].includes(e.code)) { e.preventDefault(); ui.advanceTextbox(); }
    return;
  }
  if (ui.modalOpen()) {
    if (e.code === 'Escape') ui.closeModal();
    return;
  }
  if (e.code === 'Escape' && mode === 'OVERWORLD') { openPauseMenu(); return; }
  const dir = KEY_DIR[e.code];
  if (dir) { pushDir(dir); e.preventDefault(); return; }
  if (['KeyE', 'Enter', 'Space'].includes(e.code) && mode === 'OVERWORLD') { handleInteract(); e.preventDefault(); }
});
document.addEventListener('keyup', e => {
  const dir = KEY_DIR[e.code];
  if (dir) popDir(dir);
});

function setupMobileControls() {
  const dpad = document.getElementById('dpad');
  dpad.querySelectorAll('button').forEach(btn => {
    const dir = btn.dataset.dir;
    const start = ev => { ev.preventDefault(); pushDir(dir); };
    const end = ev => { ev.preventDefault(); popDir(dir); };
    btn.addEventListener('touchstart', start); btn.addEventListener('touchend', end);
    btn.addEventListener('mousedown', start); btn.addEventListener('mouseup', end); btn.addEventListener('mouseleave', end);
  });
  document.getElementById('mobile-interact').addEventListener('click', () => {
    if (ui.textboxOpen()) ui.advanceTextbox();
    else handleInteract();
  });
  if ('ontouchstart' in window) document.getElementById('mobile-controls').classList.remove('hidden');
}

// ---------------- Boot ----------------
function init() {
  world = generateWorld();
  populateWildSpawns(world);
  const saved = loadGame();
  const isNew = !saved;
  player = saved || createPlayer();
  anim.px = player.x * TILE + TILE / 2; anim.py = player.y * TILE + TILE / 2; anim.moving = false;
  partner.px = anim.px; partner.py = anim.py;
  ui.updateHUD(player);
  setupMobileControls();
  requestAnimationFrame(loop);
  if (isNew) {
    mode = 'INTRO';
    playIntro().then(() => { mode = 'OVERWORLD'; saveGame(); });
  } else {
    mode = 'OVERWORLD';
  }
}
init();
