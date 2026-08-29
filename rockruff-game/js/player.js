// Player, party & Pokémon instance state — leveling, XP, evolution.
import { SPECIES, movesKnownAt } from './pokedex-data.js';

function statAt(base, level, isHp) {
  if (isHp) return Math.floor((base * level) / 8) + level + 12;
  return Math.floor((base * level) / 14) + 5;
}

export function xpToNext(level) {
  return Math.floor(level * level * 5 + 20);
}

export function createPokemon(speciesId, level, opts = {}) {
  const sp = SPECIES[speciesId];
  const maxHp = statAt(sp.baseStats.hp, level, true);
  return {
    speciesId,
    level,
    xp: 0,
    hp: maxHp,
    maxHp,
    atk: statAt(sp.baseStats.atk, level, false),
    def: statAt(sp.baseStats.def, level, false),
    spd: statAt(sp.baseStats.spd, level, false),
    atkStage: 0,
    defStage: 0,
    moves: movesKnownAt(speciesId, level),
    caughtWith: opts.caught ? 'ball' : null,
    uid: `${speciesId}-${Math.random().toString(36).slice(2, 8)}`,
  };
}

export function recomputeStats(pokemon) {
  const sp = SPECIES[pokemon.speciesId];
  const oldMax = pokemon.maxHp;
  const newMax = statAt(sp.baseStats.hp, pokemon.level, true);
  pokemon.hp = Math.max(1, pokemon.hp + (newMax - oldMax));
  pokemon.maxHp = newMax;
  pokemon.atk = statAt(sp.baseStats.atk, pokemon.level, false);
  pokemon.def = statAt(sp.baseStats.def, pokemon.level, false);
  pokemon.spd = statAt(sp.baseStats.spd, pokemon.level, false);
  pokemon.moves = movesKnownAt(pokemon.speciesId, pokemon.level);
}

// Returns { leveledUp, evolvedFrom, evolvedTo } describing what happened.
export function gainXP(pokemon, amount) {
  const result = { leveledUp: false, evolvedFrom: null, evolvedTo: null, newLevel: pokemon.level };
  pokemon.xp += amount;
  while (pokemon.level < 100 && pokemon.xp >= xpToNext(pokemon.level)) {
    pokemon.xp -= xpToNext(pokemon.level);
    pokemon.level += 1;
    result.leveledUp = true;
    recomputeStats(pokemon);
    const sp = SPECIES[pokemon.speciesId];
    if (sp.evolvesTo && sp.evolveLevel && pokemon.level >= sp.evolveLevel) {
      result.evolvedFrom = sp.name;
      pokemon.speciesId = sp.evolvesTo;
      recomputeStats(pokemon);
      result.evolvedTo = SPECIES[pokemon.speciesId].name;
    }
  }
  result.newLevel = pokemon.level;
  return result;
}

export function xpReward(defeatedPokemon, isTrainerBattle) {
  const sp = SPECIES[defeatedPokemon.speciesId];
  const total = (sp.baseStats.hp + sp.baseStats.atk + sp.baseStats.def + sp.baseStats.spd);
  const base = Math.floor((total * defeatedPokemon.level) / 22);
  return Math.max(4, isTrainerBattle ? Math.floor(base * 1.5) : base);
}

export function createPlayer() {
  const starter = createPokemon('rockruff', 5);
  return {
    name: 'You',
    x: 31, y: 23,
    facing: 'down',
    money: 300,
    items: { pokeball: 8, greatball: 0, potion: 3 },
    party: [starter],
    storage: [],
    pokedex: { seen: new Set(['rockruff']), caught: new Set(['rockruff']) },
    trainersDefeated: new Set(),
    arceusCaught: false,
    arceusEncountered: false,
    playTicks: 0,
  };
}

export function healParty(player) {
  for (const p of player.party) {
    p.hp = p.maxHp;
    p.atkStage = 0;
    p.defStage = 0;
  }
}

export function firstAlive(party) {
  return party.find(p => p.hp > 0) || null;
}

export function addCapturedPokemon(player, pokemon) {
  player.pokedex.caught.add(pokemon.speciesId);
  if (player.party.length < 6) {
    player.party.push(pokemon);
    return 'party';
  }
  player.storage.push(pokemon);
  return 'storage';
}
