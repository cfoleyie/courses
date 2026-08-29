// Wild Pokémon that actually roam the map, visible before you battle them.
import { tileAt, TILE, BLOCKING, TILE_BIOME } from './world.js';
import { BIOME_TABLE } from './pokedex-data.js';

const SPAWNS_PER_BIOME = 4;
const LEASH = 4;
const WANDER_DUR = 0.32;
const LEVEL_RANGE = {
  meadow: [3, 7], forest: [3, 8], lake: [4, 9], cave: [6, 13], volcano: [10, 18], snow: [9, 17],
};

function biomeTileCache(world) {
  if (world._biomeTiles) return world._biomeTiles;
  const cache = {};
  for (let y = 0; y < world.tiles.length; y++) {
    for (let x = 0; x < world.tiles[y].length; x++) {
      const biome = TILE_BIOME[world.tiles[y][x].type];
      if (!biome) continue;
      (cache[biome] ||= []).push({ x, y });
    }
  }
  world._biomeTiles = cache;
  return cache;
}

function pickLevel(biome) {
  const [lo, hi] = LEVEL_RANGE[biome] || [3, 8];
  return lo + Math.floor(Math.random() * (hi - lo + 1));
}

function makeSpawn(biome, x, y) {
  const pool = BIOME_TABLE[biome];
  const speciesId = pool[Math.floor(Math.random() * pool.length)];
  const px = x * TILE + TILE / 2, py = y * TILE + TILE / 2;
  return {
    uid: `${speciesId}-${Math.random().toString(36).slice(2, 8)}`,
    speciesId, level: pickLevel(biome), biome,
    x, y, homeX: x, homeY: y,
    px, py, moving: false, t: 0, fromX: px, fromY: py, toX: px, toY: py,
    wanderAt: performance.now() + 500 + Math.random() * 2500,
    seed: Math.random() * 10,
  };
}

export function populateWildSpawns(world) {
  const cache = biomeTileCache(world);
  const spawns = [];
  for (const biome of Object.keys(cache)) {
    const candidates = cache[biome];
    if (!candidates.length || !BIOME_TABLE[biome]?.length) continue;
    for (let i = 0; i < SPAWNS_PER_BIOME; i++) {
      const spot = candidates[Math.floor(Math.random() * candidates.length)];
      spawns.push(makeSpawn(biome, spot.x, spot.y));
    }
  }
  world.wildSpawns = spawns;
}

// Queue a fresh spawn of the same biome to appear again after a short delay.
export function scheduleRespawn(world, biome) {
  const cache = biomeTileCache(world);
  const candidates = cache[biome];
  if (!candidates || !candidates.length) return;
  setTimeout(() => {
    const spot = candidates[Math.floor(Math.random() * candidates.length)];
    world.wildSpawns.push(makeSpawn(biome, spot.x, spot.y));
  }, 9000 + Math.random() * 9000);
}

export function removeSpawn(world, uid) {
  world.wildSpawns = world.wildSpawns.filter(s => s.uid !== uid);
}

function canWander(world, x, y) {
  const tile = tileAt(world, x, y);
  if (!tile) return false;
  return !BLOCKING.has(tile.type);
}

const DIRS = [[0, -1], [0, 1], [-1, 0], [1, 0]];

export function updateWildSpawns(world, dt, now) {
  for (const s of world.wildSpawns) {
    if (s.moving) {
      s.t = Math.min(1, s.t + dt / WANDER_DUR);
      s.px = s.fromX + (s.toX - s.fromX) * s.t;
      s.py = s.fromY + (s.toY - s.fromY) * s.t;
      if (s.t >= 1) { s.moving = false; s.wanderAt = now + 1500 + Math.random() * 3000; }
      continue;
    }
    if (now < s.wanderAt) continue;
    if (Math.random() < 0.4) {
      const [dx, dy] = DIRS[Math.floor(Math.random() * DIRS.length)];
      const nx = s.x + dx, ny = s.y + dy;
      const withinLeash = Math.abs(nx - s.homeX) <= LEASH && Math.abs(ny - s.homeY) <= LEASH;
      if (withinLeash && canWander(world, nx, ny)) {
        s.x = nx; s.y = ny;
        s.fromX = s.px; s.fromY = s.py;
        s.toX = nx * TILE + TILE / 2; s.toY = ny * TILE + TILE / 2;
        s.moving = true; s.t = 0;
        continue;
      }
    }
    s.wanderAt = now + 1200 + Math.random() * 2000;
  }
}

export function spawnAtTile(world, x, y) {
  return world.wildSpawns.find(s => s.x === x && s.y === y);
}
