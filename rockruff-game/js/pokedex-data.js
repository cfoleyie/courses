// Species definitions: stats, types, evolution chains, biomes, and cute-render params.
import { TYPE_BASIC_MOVE, TYPE_STRONG_MOVE } from './moves-data.js';

export const TYPE_COLORS = {
  normal: '#c9a878', fire: '#e0692c', water: '#4a9dd6', grass: '#5fb84a',
  electric: '#f2d43c', rock: '#a8926a', ground: '#c9a25a', poison: '#a05ac9',
  bug: '#8fbf3c', flying: '#a8c4e0', ice: '#a8dcec', dark: '#5a4a6b',
};

const STAGE_STATS = {
  base:   { hp: 45, atk: 48, def: 42, spd: 48 },
  mid:    { hp: 62, atk: 64, def: 58, spd: 62 },
  final:  { hp: 82, atk: 86, def: 80, spd: 82 },
  legend: { hp: 120, atk: 120, def: 120, spd: 120 },
};

// Raw species list. `biome: null` means it's not found in the wild (evolution-only or legendary).
const RAW = [
  { id: 'rockruff',   name: 'Rockruff',   types: ['rock'],            biome: 'meadow',  catchRate: 190, stage: 'base',
    evolvesTo: 'lycanroc', evolveLevel: 25,
    render: { bodyColor: '#c9935a', secondaryColor: '#6b4a34', earType: 'floppy', tailType: 'fluffy', feature: 'rockCollar', pattern: 'spots' } },
  { id: 'lycanroc',   name: 'Lycanroc',   types: ['rock'],            biome: null, catchRate: 60, stage: 'final',
    statMods: { atk: 10, spd: 15 },
    render: { bodyColor: '#8a6a4a', secondaryColor: '#e0672a', earType: 'pointy', tailType: 'thin', feature: 'spikes', pattern: 'stripes' } },

  { id: 'pikachu',    name: 'Pikachu',    types: ['electric'],        biome: 'meadow', catchRate: 190, stage: 'base', evolvesTo: 'raichu', evolveLevel: 20,
    render: { bodyColor: '#f6d94c', secondaryColor: '#b5892a', earType: 'pointy', tailType: 'thin', feature: 'sparkTail', pattern: 'none' } },
  { id: 'raichu',     name: 'Raichu',     types: ['electric'],        biome: null, catchRate: 75, stage: 'final', statMods: { spd: 15 },
    render: { bodyColor: '#e8a83c', secondaryColor: '#7a4a1a', earType: 'pointy', tailType: 'thin', feature: 'sparkTail', pattern: 'none' } },

  { id: 'eevee',      name: 'Eevee',      types: ['normal'],          biome: 'meadow', catchRate: 190, stage: 'base', evolvesTo: 'flareon', evolveLevel: 18,
    render: { bodyColor: '#c9a06a', secondaryColor: '#f5efe0', earType: 'pointy', tailType: 'fluffy', feature: 'ruff', pattern: 'none' } },
  { id: 'flareon',    name: 'Flareon',    types: ['fire'],            biome: null, catchRate: 60, stage: 'final', statMods: { atk: 12 },
    render: { bodyColor: '#e0672a', secondaryColor: '#ffd24c', earType: 'pointy', tailType: 'flame', feature: 'ruff', pattern: 'none' } },

  { id: 'bulbasaur',  name: 'Bulbasaur',  types: ['grass', 'poison'], biome: 'forest', catchRate: 190, stage: 'base', evolvesTo: 'ivysaur', evolveLevel: 16,
    render: { bodyColor: '#5fb87a', secondaryColor: '#2e7d4f', earType: 'round', tailType: 'none', feature: 'bulb', pattern: 'spots' } },
  { id: 'ivysaur',    name: 'Ivysaur',    types: ['grass', 'poison'], biome: null, catchRate: 120, stage: 'mid', evolvesTo: 'venusaur', evolveLevel: 32,
    render: { bodyColor: '#4a9d68', secondaryColor: '#c65fd6', earType: 'round', tailType: 'none', feature: 'bud', pattern: 'spots' } },
  { id: 'venusaur',   name: 'Venusaur',   types: ['grass', 'poison'], biome: null, catchRate: 45, stage: 'final', statMods: { hp: 15 },
    render: { bodyColor: '#3d8556', secondaryColor: '#d65fe0', earType: 'round', tailType: 'none', feature: 'flower', pattern: 'spots' } },

  { id: 'caterpie',   name: 'Caterpie',   types: ['bug'],             biome: 'forest', catchRate: 255, stage: 'base', evolvesTo: 'metapod', evolveLevel: 7,
    render: { bodyColor: '#8fce4a', secondaryColor: '#2e6b1f', earType: 'none', tailType: 'none', feature: 'antenna', pattern: 'stripes' } },
  { id: 'metapod',    name: 'Metapod',    types: ['bug'],             biome: null, catchRate: 120, stage: 'mid', evolvesTo: 'butterfree', evolveLevel: 10, statMods: { def: 20 },
    render: { bodyColor: '#4a9d3a', secondaryColor: '#2e6b1f', earType: 'none', tailType: 'none', feature: 'shell', pattern: 'none' } },
  { id: 'butterfree', name: 'Butterfree', types: ['bug', 'flying'],   biome: null, catchRate: 45, stage: 'final',
    render: { bodyColor: '#c9c9e8', secondaryColor: '#6a6ad6', earType: 'antenna', tailType: 'none', feature: 'wing', pattern: 'spots' } },

  { id: 'pidgey',     name: 'Pidgey',     types: ['normal', 'flying'], biome: 'forest', catchRate: 255, stage: 'base', evolvesTo: 'pidgeotto', evolveLevel: 18,
    render: { bodyColor: '#c9a878', secondaryColor: '#e04c3c', earType: 'none', tailType: 'thin', feature: 'wing', pattern: 'none' } },
  { id: 'pidgeotto',  name: 'Pidgeotto',  types: ['normal', 'flying'], biome: null, catchRate: 120, stage: 'final', statMods: { spd: 15 },
    render: { bodyColor: '#b8925f', secondaryColor: '#e04c3c', earType: 'none', tailType: 'thin', feature: 'wing', pattern: 'stripes' } },

  { id: 'squirtle',   name: 'Squirtle',   types: ['water'], biome: 'lake', catchRate: 190, stage: 'base', evolvesTo: 'wartortle', evolveLevel: 16,
    render: { bodyColor: '#5cb8e0', secondaryColor: '#f0e0a0', earType: 'none', tailType: 'thin', feature: 'shell', pattern: 'none' } },
  { id: 'wartortle',  name: 'Wartortle',  types: ['water'], biome: null, catchRate: 75, stage: 'final', statMods: { def: 15 },
    render: { bodyColor: '#4a9dc9', secondaryColor: '#f0e0a0', earType: 'none', tailType: 'fluffy', feature: 'shell', pattern: 'none' } },

  { id: 'psyduck',    name: 'Psyduck',    types: ['water'], biome: 'lake', catchRate: 190, stage: 'base', evolvesTo: 'golduck', evolveLevel: 25,
    render: { bodyColor: '#f2e299', secondaryColor: '#d68c2c', earType: 'round', tailType: 'thin', feature: 'none', pattern: 'none' } },
  { id: 'golduck',    name: 'Golduck',    types: ['water'], biome: null, catchRate: 75, stage: 'final', statMods: { spd: 10 },
    render: { bodyColor: '#5fa8c9', secondaryColor: '#2e6b8c', earType: 'round', tailType: 'thin', feature: 'fin', pattern: 'none' } },

  { id: 'magikarp',   name: 'Magikarp',   types: ['water'], biome: 'lake', catchRate: 255, stage: 'base', evolvesTo: 'gyarados', evolveLevel: 20,
    statMods: { atk: -25, def: -10, hp: -5 },
    render: { bodyColor: '#e0592c', secondaryColor: '#b5892a', earType: 'none', tailType: 'fish', feature: 'fin', pattern: 'scales' } },
  { id: 'gyarados',   name: 'Gyarados',   types: ['water', 'flying'], biome: null, catchRate: 45, stage: 'final', statMods: { hp: 25, atk: 25 },
    render: { bodyColor: '#4a6ad6', secondaryColor: '#e0e2f0', earType: 'pointy', tailType: 'fish', feature: 'horn', pattern: 'scales' } },

  { id: 'geodude',    name: 'Geodude',    types: ['rock', 'ground'], biome: 'cave', catchRate: 255, stage: 'base', evolvesTo: 'graveler', evolveLevel: 25,
    statMods: { def: 15, spd: -15 },
    render: { bodyColor: '#a89878', secondaryColor: '#6b5a44', earType: 'none', tailType: 'none', feature: 'spikes', pattern: 'none' } },
  { id: 'graveler',   name: 'Graveler',   types: ['rock', 'ground'], biome: null, catchRate: 120, stage: 'final', statMods: { def: 20, atk: 10 },
    render: { bodyColor: '#8c7a5a', secondaryColor: '#5a4a34', earType: 'none', tailType: 'none', feature: 'spikes', pattern: 'none' } },

  { id: 'zubat',      name: 'Zubat',      types: ['poison', 'flying'], biome: 'cave', catchRate: 255, stage: 'base', evolvesTo: 'golbat', evolveLevel: 22,
    render: { bodyColor: '#7a5ac9', secondaryColor: '#4a2e8c', earType: 'pointy', tailType: 'none', feature: 'wing', pattern: 'none' } },
  { id: 'golbat',     name: 'Golbat',     types: ['poison', 'flying'], biome: null, catchRate: 90, stage: 'final', statMods: { spd: 15 },
    render: { bodyColor: '#6a4ab5', secondaryColor: '#3a1e7c', earType: 'pointy', tailType: 'none', feature: 'wing', pattern: 'none' } },

  { id: 'cubone',     name: 'Cubone',     types: ['ground'], biome: 'cave', catchRate: 190, stage: 'base', evolvesTo: 'marowak', evolveLevel: 28,
    render: { bodyColor: '#e0c99a', secondaryColor: '#b58c5a', earType: 'round', tailType: 'thin', feature: 'bone', pattern: 'spots' } },
  { id: 'marowak',    name: 'Marowak',    types: ['ground'], biome: null, catchRate: 75, stage: 'final', statMods: { def: 15, atk: 10 },
    render: { bodyColor: '#c9a86a', secondaryColor: '#8c5a2e', earType: 'round', tailType: 'thin', feature: 'bone', pattern: 'spots' } },

  { id: 'vulpix',     name: 'Vulpix',     types: ['fire'], biome: 'volcano', catchRate: 190, stage: 'base', evolvesTo: 'ninetales', evolveLevel: 20,
    render: { bodyColor: '#e07a4c', secondaryColor: '#fff0d9', earType: 'pointy', tailType: 'fluffy', feature: 'flameTuft', pattern: 'none' } },
  { id: 'ninetales',  name: 'Ninetales',  types: ['fire'], biome: null, catchRate: 75, stage: 'final', statMods: { spd: 20 },
    render: { bodyColor: '#f0955f', secondaryColor: '#fff0d9', earType: 'pointy', tailType: 'fluffy', feature: 'flameTuft', pattern: 'none' } },

  { id: 'growlithe',  name: 'Growlithe',  types: ['fire'], biome: 'volcano', catchRate: 190, stage: 'base', evolvesTo: 'arcanine', evolveLevel: 24,
    render: { bodyColor: '#e0952c', secondaryColor: '#3a2418', earType: 'pointy', tailType: 'thin', feature: 'ruff', pattern: 'stripes' } },
  { id: 'arcanine',   name: 'Arcanine',   types: ['fire'], biome: null, catchRate: 75, stage: 'final', statMods: { hp: 15, spd: 15 },
    render: { bodyColor: '#d6852c', secondaryColor: '#3a2418', earType: 'pointy', tailType: 'fluffy', feature: 'ruff', pattern: 'stripes' } },

  { id: 'charmander', name: 'Charmander', types: ['fire'], biome: 'volcano', catchRate: 190, stage: 'base', evolvesTo: 'charmeleon', evolveLevel: 16,
    render: { bodyColor: '#e0592c', secondaryColor: '#f2c94c', earType: 'none', tailType: 'flame', feature: 'flameTail', pattern: 'none' } },
  { id: 'charmeleon', name: 'Charmeleon', types: ['fire'], biome: null, catchRate: 120, stage: 'mid', evolvesTo: 'charizard', evolveLevel: 36, statMods: { atk: 10 },
    render: { bodyColor: '#d6452c', secondaryColor: '#f2c94c', earType: 'none', tailType: 'flame', feature: 'flameTail', pattern: 'none' } },
  { id: 'charizard',  name: 'Charizard',  types: ['fire', 'flying'], biome: null, catchRate: 45, stage: 'final', statMods: { atk: 20, hp: 15 },
    render: { bodyColor: '#e0592c', secondaryColor: '#f2c94c', earType: 'pointy', tailType: 'flame', feature: 'wing', pattern: 'none' } },

  { id: 'snorunt',    name: 'Snorunt',    types: ['ice'], biome: 'snow', catchRate: 190, stage: 'base', evolvesTo: 'glalie', evolveLevel: 24,
    render: { bodyColor: '#cfe8f2', secondaryColor: '#3a5a6b', earType: 'none', tailType: 'none', feature: 'hood', pattern: 'none' } },
  { id: 'glalie',     name: 'Glalie',     types: ['ice'], biome: null, catchRate: 75, stage: 'final', statMods: { def: 20 },
    render: { bodyColor: '#a8d9e8', secondaryColor: '#3a5a6b', earType: 'none', tailType: 'none', feature: 'spikes', pattern: 'none' } },

  { id: 'sneasel',    name: 'Sneasel',    types: ['dark', 'ice'], biome: 'snow', catchRate: 120, stage: 'base', evolvesTo: 'weavile', evolveLevel: 30,
    render: { bodyColor: '#5a4a6b', secondaryColor: '#d6304c', earType: 'pointy', tailType: 'thin', feature: 'spikes', pattern: 'none' } },
  { id: 'weavile',    name: 'Weavile',    types: ['dark', 'ice'], biome: null, catchRate: 45, stage: 'final', statMods: { spd: 25, atk: 15 },
    render: { bodyColor: '#3a2e4a', secondaryColor: '#d6304c', earType: 'pointy', tailType: 'thin', feature: 'spikes', pattern: 'none' } },

  { id: 'snom',       name: 'Snom',       types: ['ice', 'bug'], biome: 'snow', catchRate: 190, stage: 'base', evolvesTo: 'frosmoth', evolveLevel: 20,
    render: { bodyColor: '#cfe0e8', secondaryColor: '#6b8ca8', earType: 'none', tailType: 'none', feature: 'antenna', pattern: 'spots' } },
  { id: 'frosmoth',   name: 'Frosmoth',   types: ['ice', 'bug'], biome: null, catchRate: 75, stage: 'final', statMods: { spd: 15 },
    render: { bodyColor: '#e8eef2', secondaryColor: '#7a9ac9', earType: 'antenna', tailType: 'none', feature: 'wing', pattern: 'spots' } },

  { id: 'arceus', name: 'Arceus', types: ['normal'], biome: null, catchRate: 3, stage: 'legend',
    statMods: { hp: 40, atk: 30, def: 30, spd: 20 },
    render: { bodyColor: '#e8e0c9', secondaryColor: '#6ab5d6', earType: 'pointy', tailType: 'thin', feature: 'halo', pattern: 'rings' } },
];

function buildMovepool(types, evolveLevel, stage, extra) {
  const t0 = types[0], t1 = types[1];
  const basicLevel = 1;
  const quickLevel = Math.max(5, Math.floor((evolveLevel || 30) * 0.4));
  const strongLevel = Math.max(10, Math.floor((evolveLevel || 30) * 0.75));
  const secondLevel = (evolveLevel || 30) + (stage === 'final' || stage === 'legend' ? 0 : 4);
  const pool = [
    { level: basicLevel, move: 'growl' },
    { level: basicLevel, move: TYPE_BASIC_MOVE[t0] },
    { level: quickLevel, move: 'quickAttack' },
    { level: strongLevel, move: TYPE_STRONG_MOVE[t0] },
  ];
  if (t1) pool.push({ level: secondLevel, move: TYPE_BASIC_MOVE[t1] });
  if (extra) pool.push(...extra);
  return pool.sort((a, b) => a.level - b.level);
}

export const SPECIES = {};
export const SPECIES_LIST = [];
export const BIOME_TABLE = { meadow: [], forest: [], lake: [], cave: [], volcano: [], snow: [] };

for (const raw of RAW) {
  const base = STAGE_STATS[raw.stage];
  const mods = raw.statMods || {};
  const stats = {
    hp: base.hp + (mods.hp || 0),
    atk: base.atk + (mods.atk || 0),
    def: base.def + (mods.def || 0),
    spd: base.spd + (mods.spd || 0),
  };
  const extraMoves = raw.id === 'arceus' ? [{ level: 1, move: 'judgment' }] : null;
  const species = {
    ...raw,
    baseStats: stats,
    movepool: buildMovepool(raw.types, raw.evolveLevel, raw.stage, extraMoves),
  };
  SPECIES[raw.id] = species;
  SPECIES_LIST.push(species);
  if (raw.biome && BIOME_TABLE[raw.biome]) BIOME_TABLE[raw.biome].push(raw.id);
}

export function movesKnownAt(speciesId, level) {
  const sp = SPECIES[speciesId];
  const known = sp.movepool.filter(m => m.level <= level).map(m => m.move);
  // Most recently learned 4 moves, deduped.
  const uniq = [...new Set(known)];
  return uniq.slice(-4);
}
