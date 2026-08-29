// DOM overlay: textbox, battle menus, and modal screens (Pokédex / Party / Bag / Shop).
import { SPECIES, SPECIES_LIST } from './pokedex-data.js';
import { MOVES } from './moves-data.js';
import { drawCreature, typePillColor } from './render.js';

const $ = id => document.getElementById(id);

export const dom = {
  hudMoney: $('hud-money-val'), hudDex: $('hud-dex-val'), hudDexTotal: $('hud-dex-total'), hudParty: $('hud-party'),
  interactHint: $('interact-hint'),
  textbox: $('textbox'), textboxName: $('textbox-name'), textboxText: $('textbox-text'),
  battleScreen: $('battle-screen'),
  enemyName: $('battle-enemy-name'), enemyLevel: $('battle-enemy-level'), enemyHp: $('battle-enemy-hp'),
  playerName: $('battle-player-name'), playerLevel: $('battle-player-level'), playerHp: $('battle-player-hp'), playerHpText: $('battle-player-hp-text'),
  battleMenuArea: $('battle-menu-area'),
  modal: $('modal-screen'), modalTitle: $('modal-title'), modalBody: $('modal-body'), modalClose: $('modal-close'),
  introScreen: $('intro-screen'), introCanvas: $('intro-canvas'), introText: $('intro-text'), introMore: $('intro-more'),
};

// ---------------- Textbox ----------------
let textboxResolver = null;
export function say(text, name = '') {
  dom.textbox.classList.remove('hidden');
  dom.textboxName.textContent = name;
  dom.textboxText.textContent = text;
  return new Promise(resolve => { textboxResolver = resolve; });
}
export function advanceTextbox() {
  if (textboxResolver) { const r = textboxResolver; textboxResolver = null; hideTextbox(); r(); }
}
export function hideTextbox() { dom.textbox.classList.add('hidden'); }
export function textboxOpen() { return !dom.textbox.classList.contains('hidden'); }

dom.textbox.addEventListener('click', advanceTextbox);

// ---------------- HUD ----------------
export function updateHUD(player) {
  dom.hudMoney.textContent = player.money;
  dom.hudDex.textContent = player.pokedex.caught.size;
  dom.hudDexTotal.textContent = SPECIES_LIST.filter(s => s.biome || s.id === 'arceus').length;
  dom.hudParty.innerHTML = '';
  for (const mon of player.party) {
    const c = document.createElement('canvas');
    c.width = 34; c.height = 34; c.className = 'hud-party-icon';
    const ctx = c.getContext('2d');
    if (mon.hp <= 0) ctx.globalAlpha = 0.4;
    drawCreature(ctx, 17, 20, 13, SPECIES[mon.speciesId]);
    dom.hudParty.appendChild(c);
  }
}

export function setInteractHint(show) { dom.interactHint.classList.toggle('hidden', !show); }

// ---------------- Battle HUD ----------------
export function showBattleScreen() { dom.battleScreen.classList.remove('hidden'); }
export function hideBattleScreen() { dom.battleScreen.classList.add('hidden'); dom.battleMenuArea.innerHTML = ''; }

export function updateBattleHUD(playerMon, enemyMon) {
  const psp = SPECIES[playerMon.speciesId], esp = SPECIES[enemyMon.speciesId];
  dom.playerName.textContent = psp.name;
  dom.playerLevel.textContent = `Lv${playerMon.level}`;
  dom.enemyName.textContent = esp.name;
  dom.enemyLevel.textContent = `Lv${enemyMon.level}`;
  const pPct = Math.max(0, playerMon.hp / playerMon.maxHp * 100);
  const ePct = Math.max(0, enemyMon.hp / enemyMon.maxHp * 100);
  dom.playerHp.style.width = pPct + '%';
  dom.enemyHp.style.width = ePct + '%';
  dom.playerHp.style.background = pPct > 50 ? '#4caf50' : pPct > 20 ? '#f2c94c' : '#e0472c';
  dom.enemyHp.style.background = ePct > 50 ? '#4caf50' : ePct > 20 ? '#f2c94c' : '#e0472c';
  dom.playerHpText.textContent = `${Math.max(0, playerMon.hp)} / ${playerMon.maxHp}`;
}

// Granular update used while replaying battle steps, so a step always renders the mon it
// actually happened to — even if `battle`'s active index has since moved on.
export function setSideCard(side, data) {
  const pct = Math.max(0, data.hp / data.maxHp * 100);
  const color = pct > 50 ? '#4caf50' : pct > 20 ? '#f2c94c' : '#e0472c';
  if (side === 'player') {
    dom.playerName.textContent = data.name;
    dom.playerLevel.textContent = `Lv${data.level}`;
    dom.playerHp.style.width = pct + '%';
    dom.playerHp.style.background = color;
    dom.playerHpText.textContent = `${Math.max(0, data.hp)} / ${data.maxHp}`;
  } else {
    dom.enemyName.textContent = data.name;
    dom.enemyLevel.textContent = `Lv${data.level}`;
    dom.enemyHp.style.width = pct + '%';
    dom.enemyHp.style.background = color;
  }
}

function btnGrid(buttons, opts = {}) {
  dom.battleMenuArea.innerHTML = '';
  const grid = document.createElement('div');
  grid.className = 'btn-grid' + (opts.singleCol ? ' single-col' : '');
  for (const b of buttons) {
    const btn = document.createElement('button');
    btn.className = 'game-btn' + (b.cls ? ' ' + b.cls : '');
    btn.innerHTML = b.label;
    btn.disabled = !!b.disabled;
    btn.onclick = b.onClick;
    grid.appendChild(btn);
  }
  dom.battleMenuArea.appendChild(grid);
}

export function showBattleMenu({ onFight, onBag, onParty, onRun, canFlee }) {
  btnGrid([
    { label: '⚔️ Fight', onClick: onFight },
    { label: '🎒 Bag', onClick: onBag },
    { label: '🐾 Party', onClick: onParty },
    { label: canFlee ? '💨 Run' : '🙅 Can\'t Run', cls: canFlee ? '' : 'back-btn', onClick: canFlee ? onRun : () => {}, disabled: !canFlee },
  ]);
}

export function showMoveMenu(moves, onSelect, onBack) {
  const buttons = moves.map(moveId => {
    const m = MOVES[moveId];
    return {
      label: `${m.name} <span class="type-tag" style="background:${typePillColor(m.type)}">${m.type}</span>`,
      cls: 'move-btn',
      onClick: () => onSelect(moveId),
    };
  });
  buttons.push({ label: '↩ Back', cls: 'back-btn', onClick: onBack });
  btnGrid(buttons);
}

export function showBagMenu(player, canCatch, handlers) {
  const buttons = [];
  if (canCatch) {
    buttons.push({ label: `🔴 Poké Ball (${player.items.pokeball})`, onClick: () => handlers.onBall('pokeball'), disabled: player.items.pokeball <= 0 });
    buttons.push({ label: `🟡 Great Ball (${player.items.greatball})`, onClick: () => handlers.onBall('greatball'), disabled: player.items.greatball <= 0 });
  }
  buttons.push({ label: `💊 Potion (${player.items.potion})`, onClick: handlers.onPotion, disabled: player.items.potion <= 0 });
  buttons.push({ label: '↩ Back', cls: 'back-btn', onClick: handlers.onBack });
  btnGrid(buttons, { singleCol: !canCatch });
}

export function showPartySwitchMenu(party, activeIndex, forced, onSelect, onBack) {
  dom.battleMenuArea.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'btn-grid single-col';
  party.forEach((mon, i) => {
    const sp = SPECIES[mon.speciesId];
    const row = document.createElement('button');
    row.className = 'game-btn move-btn';
    row.disabled = mon.hp <= 0 || i === activeIndex;
    row.textContent = `${sp.name} Lv${mon.level} — ${mon.hp}/${mon.maxHp} HP${i === activeIndex ? ' (active)' : mon.hp <= 0 ? ' (fainted)' : ''}`;
    row.onclick = () => onSelect(i);
    wrap.appendChild(row);
  });
  if (!forced) {
    const back = document.createElement('button');
    back.className = 'game-btn back-btn'; back.textContent = '↩ Back';
    back.onclick = onBack;
    wrap.appendChild(back);
  }
  dom.battleMenuArea.appendChild(wrap);
}

// ---------------- Modal (Pokédex / Party / Bag / Shop) ----------------
let modalCloseHandler = null;
export function openModal(title, bodyNode, onClose) {
  dom.modalTitle.textContent = title;
  dom.modalBody.innerHTML = '';
  dom.modalBody.appendChild(bodyNode);
  dom.modal.classList.remove('hidden');
  modalCloseHandler = onClose || (() => {});
}
export function closeModal() {
  dom.modal.classList.add('hidden');
  if (modalCloseHandler) modalCloseHandler();
  modalCloseHandler = null;
}
export function modalOpen() { return !dom.modal.classList.contains('hidden'); }
dom.modalClose.addEventListener('click', closeModal);

export function buildPokedexBody(player) {
  const wrap = document.createElement('div');
  wrap.className = 'dex-grid';
  const wild = SPECIES_LIST.filter(s => s.biome || s.id === 'arceus');
  for (const sp of wild) {
    const cell = document.createElement('div');
    const seen = player.pokedex.seen.has(sp.id);
    const caught = player.pokedex.caught.has(sp.id);
    cell.className = 'dex-cell' + (seen ? '' : ' unseen');
    const c = document.createElement('canvas'); c.width = 64; c.height = 64;
    const ctx = c.getContext('2d');
    drawCreature(ctx, 32, 38, 24, sp);
    cell.appendChild(c);
    const label = document.createElement('div'); label.className = 'dex-name';
    label.textContent = seen ? sp.name : '???';
    cell.appendChild(label);
    if (caught) { const tag = document.createElement('div'); tag.textContent = '✓ Caught'; tag.style.fontSize = '11px'; tag.style.color = '#2e8b3a'; tag.style.fontWeight = '800'; cell.appendChild(tag); }
    wrap.appendChild(cell);
  }
  return wrap;
}

export function buildPartyBody(player) {
  const wrap = document.createElement('div');
  for (const mon of player.party) {
    const sp = SPECIES[mon.speciesId];
    const row = document.createElement('div');
    row.className = 'party-row';
    const c = document.createElement('canvas'); c.width = 56; c.height = 56;
    drawCreature(c.getContext('2d'), 28, 32, 20, sp, { faint: mon.hp <= 0 });
    row.appendChild(c);
    const info = document.createElement('div'); info.className = 'info';
    const pct = Math.max(0, mon.hp / mon.maxHp * 100);
    info.innerHTML = `<div class="name-lv">${sp.name} — Lv${mon.level}</div>
      <div>${sp.types.map(t => `<span class="type-tag" style="background:${typePillColor(t)}">${t}</span>`).join('')}</div>
      <div class="mini-hp-track"><div class="mini-hp-fill" style="width:${pct}%;background:${pct > 50 ? '#4caf50' : pct > 20 ? '#f2c94c' : '#e0472c'}"></div></div>
      <div style="font-size:12px;">${Math.max(0, mon.hp)} / ${mon.maxHp} HP · ATK ${mon.atk} · DEF ${mon.def} · SPD ${mon.spd}</div>`;
    row.appendChild(info);
    wrap.appendChild(row);
  }
  if (player.storage.length) {
    const h = document.createElement('div'); h.style.fontWeight = '800'; h.style.margin = '10px 0 6px';
    h.textContent = `In Storage (${player.storage.length}):`;
    wrap.appendChild(h);
    const names = player.storage.map(m => `${SPECIES[m.speciesId].name} Lv${m.level}`).join(', ');
    const p = document.createElement('div'); p.textContent = names; wrap.appendChild(p);
  }
  return wrap;
}

export function buildShopBody(player, onBuy, refresh) {
  const wrap = document.createElement('div');
  const items = [
    { key: 'pokeball', label: '🔴 Poké Ball', desc: 'Decent catch rate.', price: 30 },
    { key: 'greatball', label: '🟡 Great Ball', desc: 'Better catch rate.', price: 75 },
    { key: 'potion', label: '💊 Potion', desc: 'Heals 50% HP in battle.', price: 40 },
  ];
  for (const it of items) {
    const row = document.createElement('div'); row.className = 'shop-row';
    const left = document.createElement('div');
    left.innerHTML = `<div style="font-weight:800">${it.label} — ${it.price}💰</div><div style="font-size:12px;color:#666">${it.desc} (have ${player.items[it.key]})</div>`;
    row.appendChild(left);
    const btn = document.createElement('button'); btn.className = 'shop-buy-btn'; btn.textContent = 'Buy';
    btn.disabled = player.money < it.price;
    btn.onclick = () => { onBuy(it.key, it.price); refresh(); };
    row.appendChild(btn);
    wrap.appendChild(row);
  }
  return wrap;
}

// ---------------- Intro cutscene ----------------
export function showIntroLine(text) {
  dom.introScreen.classList.remove('hidden');
  dom.introText.textContent = text;
  return new Promise(resolve => {
    const handler = () => { dom.introScreen.removeEventListener('click', handler); resolve(); };
    dom.introScreen.addEventListener('click', handler);
  });
}
export function hideIntro() { dom.introScreen.classList.add('hidden'); }
