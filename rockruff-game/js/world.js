// Procedurally generated overworld: seven regions around a home town, connected by paths.
export const TILE = 40;
export const WORLD_W = 64;
export const WORLD_H = 48;

export const BLOCKING = new Set([
  'tree', 'pineTree', 'water', 'caveWall', 'lava', 'ashRock', 'mart', 'healingCenter', 'npc', 'sign', 'shrineWall',
]);

export const TILE_BIOME = {
  tallGrass: 'meadow',
  forestGrass: 'forest',
  shoreGrass: 'lake',
  caveFloor: 'cave',
  volcanoGround: 'volcano',
  snow: 'snow',
};

function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function inRect(x, y, r) { return x >= r.x0 && x <= r.x1 && y >= r.y0 && y <= r.y1; }

export function generateWorld() {
  const rng = mulberry32(1337);
  const tiles = [];
  for (let y = 0; y < WORLD_H; y++) {
    const row = [];
    for (let x = 0; x < WORLD_W; x++) row.push({ type: 'grass' });
    tiles.push(row);
  }
  const set = (x, y, type) => { if (x >= 0 && x < WORLD_W && y >= 0 && y < WORLD_H) tiles[y][x].type = type; };
  const get = (x, y) => (x >= 0 && x < WORLD_W && y >= 0 && y < WORLD_H) ? tiles[y][x] : null;

  const regions = {
    forest: { x0: 1, y0: 1, x1: 19, y1: 29 },
    lake: { x0: 44, y0: 1, x1: 62, y1: 29 },
    snow: { x0: 20, y0: 1, x1: 43, y1: 15 },
    town: { x0: 24, y0: 17, x1: 39, y1: 30 },
    cave: { x0: 1, y0: 30, x1: 19, y1: 46 },
    volcano: { x0: 44, y0: 30, x1: 62, y1: 46 },
    sacred: { x0: 20, y0: 32, x1: 43, y1: 46 },
  };

  // Reserve a walkable lattice (every 4th row/col within a region) so scatter never seals areas off.
  const laneClear = (x, y) => (x % 4 === 0 || y % 4 === 0);

  // ---- Forest ----
  for (let y = regions.forest.y0; y <= regions.forest.y1; y++) {
    for (let x = regions.forest.x0; x <= regions.forest.x1; x++) {
      if (laneClear(x, y)) continue;
      const r = rng();
      if (r < 0.16) set(x, y, 'tree');
      else if (r < 0.55) set(x, y, 'forestGrass');
    }
  }
  // ---- Lake ----
  const lakeCx = (regions.lake.x0 + regions.lake.x1) / 2, lakeCy = (regions.lake.y0 + regions.lake.y1) / 2;
  for (let y = regions.lake.y0; y <= regions.lake.y1; y++) {
    for (let x = regions.lake.x0; x <= regions.lake.x1; x++) {
      const d = Math.hypot(x - lakeCx, y - lakeCy);
      if (laneClear(x, y) && d < 7) continue;
      if (d < 6.5) set(x, y, 'water');
      else if (d < 8.5) set(x, y, rng() < 0.5 ? 'sand' : 'shoreGrass');
      else if (rng() < 0.25) set(x, y, 'shoreGrass');
    }
  }
  // ---- Snow ----
  for (let y = regions.snow.y0; y <= regions.snow.y1; y++) {
    for (let x = regions.snow.x0; x <= regions.snow.x1; x++) {
      set(x, y, 'snow');
      if (laneClear(x, y)) continue;
      const r = rng();
      if (r < 0.1) set(x, y, 'pineTree');
      else if (r < 0.15) set(x, y, 'iceRock');
      else if (r < 0.45) set(x, y, 'snow');
    }
  }
  // ---- Cave ----
  for (let y = regions.cave.y0; y <= regions.cave.y1; y++) {
    for (let x = regions.cave.x0; x <= regions.cave.x1; x++) {
      set(x, y, 'caveFloor');
      if (laneClear(x, y)) continue;
      const r = rng();
      if (r < 0.18) set(x, y, 'caveWall');
    }
  }
  // ---- Volcano ----
  for (let y = regions.volcano.y0; y <= regions.volcano.y1; y++) {
    for (let x = regions.volcano.x0; x <= regions.volcano.x1; x++) {
      set(x, y, 'volcanoGround');
      if (laneClear(x, y)) continue;
      const r = rng();
      if (r < 0.12) set(x, y, 'lava');
      else if (r < 0.2) set(x, y, 'ashRock');
    }
  }
  // ---- Sacred Hollow ----
  for (let y = regions.sacred.y0; y <= regions.sacred.y1; y++) {
    for (let x = regions.sacred.x0; x <= regions.sacred.x1; x++) {
      set(x, y, 'sacredGround');
    }
  }

  // ---- Town ----
  for (let y = regions.town.y0; y <= regions.town.y1; y++) {
    for (let x = regions.town.x0; x <= regions.town.x1; x++) set(x, y, 'path');
  }
  const martPos = { x: 27, y: 21 };
  const healPos = { x: 36, y: 21 };
  set(martPos.x, martPos.y, 'mart');
  set(healPos.x, healPos.y, 'healingCenter');

  // ---- Paths connecting town to each region ----
  const townCenter = { x: 31, y: 24 };
  function carvePath(from, to) {
    let { x, y } = from;
    while (x !== to.x) { set(x, y, 'path'); set(x, y + 1, 'path'); x += x < to.x ? 1 : -1; }
    while (y !== to.y) { set(x, y, 'path'); set(x + 1, y, 'path'); y += y < to.y ? 1 : -1; }
    set(to.x, to.y, 'path');
  }
  carvePath(townCenter, { x: 10, y: 24 }); // to forest
  carvePath(townCenter, { x: 53, y: 24 }); // to lake
  carvePath(townCenter, { x: 31, y: 15 }); // to snow
  carvePath(townCenter, { x: 10, y: 38 }); // to cave
  carvePath(townCenter, { x: 53, y: 38 }); // to volcano
  carvePath(townCenter, { x: 31, y: 31 }); // to sacred gate

  // ---- Trainers ----
  const trainers = [
    { id: 'jules', name: 'Rival Jules', x: 31, y: 19, palette: { cap: '#3caee0', shirt: '#e0472c' },
      team: [{ species: 'pikachu', level: 8 }],
      taunt: "Hey! I've been training too, you know. Let's see whose Pokémon is tougher!",
      defeatLine: "Whoa! You beat me already?! Ok ok, here's some money, don't tell anyone.",
      reward: 80, biome: 'meadow' },
    { id: 'timmy', name: 'Bug Catcher Timmy', x: 10, y: 15, palette: { cap: '#8fbf3c', shirt: '#4a9d3a' },
      team: [{ species: 'caterpie', level: 9 }, { species: 'bulbasaur', level: 10 }],
      taunt: "Bugs rule the forest! I'm gonna squash your team, watch!",
      defeatLine: "Oh my gosh! Ok ok, here's fifty monies, that was awesome!",
      reward: 100, biome: 'forest' },
    { id: 'kai', name: 'Swimmer Kai', x: 53, y: 12, palette: { cap: '#4a9dd6', shirt: '#5cb8e0' },
      team: [{ species: 'psyduck', level: 12 }, { species: 'squirtle', level: 11 }],
      taunt: "Dive in if you dare! My Pokémon and I made a splash all summer!",
      defeatLine: "Oh wow, oh wow! You got me! Here, take this — great battle!",
      reward: 130, biome: 'lake' },
    { id: 'bruno', name: 'Hiker Bruno', x: 10, y: 38, palette: { cap: '#a8926a', shirt: '#8c7a5a' },
      team: [{ species: 'geodude', level: 14 }, { species: 'cubone', level: 13 }],
      taunt: "These caves built me tough as rock! I'm gonna crush you, no offense!",
      defeatLine: "Oh my goodness... solid as rock and you still won. Here's your prize.",
      reward: 150, biome: 'cave' },
    { id: 'rosa', name: 'Ember Cadet Rosa', x: 53, y: 38, palette: { cap: '#e0472c', shirt: '#f2942c' },
      team: [{ species: 'vulpix', level: 17 }, { species: 'growlithe', level: 18 }],
      taunt: "Feel the heat! I'm gonna light your whole team up!",
      defeatLine: "Oh my goodness, that was blazing hot! Take this, well earned!",
      reward: 180, biome: 'volcano' },
    { id: 'mika', name: 'Skater Mika', x: 31, y: 8, palette: { cap: '#a8dcec', shirt: '#5a4a6b' },
      team: [{ species: 'snorunt', level: 16 }, { species: 'sneasel', level: 17 }],
      taunt: "Cool moves incoming! I'm gonna freeze you in your tracks!",
      defeatLine: "Oh my gosh, my icy heart just melted. Great job, here's your reward!",
      reward: 170, biome: 'snow' },
  ];
  for (const t of trainers) set(t.x, t.y, 'npc');

  // ---- Elder gate to Sacred Hollow ----
  const elder = {
    x: 31, y: 31, name: 'Elder Ren', unlocked: false, requiredCaught: 15,
  };
  set(elder.x, elder.y, 'npc');

  // ---- Arceus shrine ----
  const shrine = { x: 31, y: 42 };
  set(shrine.x, shrine.y, 'shrine');

  // ---- Signs ----
  const signs = [
    { x: 30, y: 26, text: "Welcome to Hearth Town! Rockruff at your side, Pokémon everywhere to discover." },
    { x: 33, y: 26, text: "The Poké Mart sells Poké Balls & Potions. The Center to the east heals your team for free." },
    { x: 10, y: 20, text: "Tall grass rustles... wild Pokémon could be hiding anywhere in here!" },
    { x: 31, y: 30, text: "Beyond this point lies the Sacred Hollow. Legend says Arceus itself walks there." },
  ];
  for (const s of signs) if (get(s.x, s.y).type !== 'npc') set(s.x, s.y, 'sign');

  return {
    tiles, trainers, elder, shrine, signs, martPos, healPos,
    start: { x: 31, y: 23 },
    regions,
  };
}

export function tileAt(world, x, y) {
  if (x < 0 || y < 0 || x >= WORLD_W || y >= WORLD_H) return null;
  return world.tiles[y][x];
}
