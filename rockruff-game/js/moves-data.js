// Move definitions and type effectiveness chart.

export const MOVES = {
  tackle:        { name: 'Tackle',        type: 'normal',   power: 40, accuracy: 100 },
  quickAttack:   { name: 'Quick Attack',  type: 'normal',   power: 40, accuracy: 100, priority: 1 },
  scratch:       { name: 'Scratch',       type: 'normal',   power: 40, accuracy: 100 },
  growl:         { name: 'Growl',         type: 'normal',   power: 0,  accuracy: 100, effect: { stat: 'atk', target: 'enemy', stages: -1 } },
  leer:          { name: 'Leer',          type: 'normal',   power: 0,  accuracy: 100, effect: { stat: 'def', target: 'enemy', stages: -1 } },
  howl:          { name: 'Howl',          type: 'normal',   power: 0,  accuracy: 100, effect: { stat: 'atk', target: 'self',  stages: 1 } },
  hyperBeam:     { name: 'Hyper Beam',    type: 'normal',   power: 90, accuracy: 90 },
  ember:         { name: 'Ember',         type: 'fire',     power: 40, accuracy: 100 },
  flamethrower:  { name: 'Flamethrower',  type: 'fire',     power: 70, accuracy: 100 },
  waterGun:      { name: 'Water Gun',     type: 'water',    power: 40, accuracy: 100 },
  hydroPump:     { name: 'Hydro Pump',    type: 'water',    power: 80, accuracy: 90 },
  vineWhip:      { name: 'Vine Whip',     type: 'grass',    power: 45, accuracy: 100 },
  solarBeam:     { name: 'Solar Beam',    type: 'grass',    power: 75, accuracy: 95 },
  thunderShock:  { name: 'Thunder Shock', type: 'electric', power: 40, accuracy: 100 },
  thunderbolt:   { name: 'Thunderbolt',   type: 'electric', power: 70, accuracy: 100 },
  rockThrow:     { name: 'Rock Throw',    type: 'rock',     power: 50, accuracy: 90 },
  rockSlide:     { name: 'Rock Slide',    type: 'rock',     power: 65, accuracy: 90 },
  bite:          { name: 'Bite',          type: 'dark',     power: 45, accuracy: 100 },
  darkPulse:     { name: 'Dark Pulse',    type: 'dark',     power: 70, accuracy: 100 },
  peck:          { name: 'Peck',          type: 'flying',   power: 35, accuracy: 100 },
  gust:          { name: 'Gust',          type: 'flying',   power: 45, accuracy: 100 },
  iceShard:      { name: 'Ice Shard',     type: 'ice',      power: 45, accuracy: 100, priority: 1 },
  iceBeam:       { name: 'Ice Beam',      type: 'ice',      power: 70, accuracy: 100 },
  poisonSting:   { name: 'Poison Sting',  type: 'poison',   power: 35, accuracy: 100 },
  sludge:        { name: 'Sludge',        type: 'poison',   power: 55, accuracy: 100 },
  boneClub:      { name: 'Bone Club',     type: 'ground',   power: 45, accuracy: 100 },
  earthquake:    { name: 'Earthquake',    type: 'ground',   power: 75, accuracy: 100 },
  bugBite:       { name: 'Bug Bite',      type: 'bug',      power: 40, accuracy: 100 },
  signalBeam:    { name: 'Signal Beam',   type: 'bug',      power: 60, accuracy: 100 },
  judgment:      { name: 'Judgment',      type: 'normal',   power: 100, accuracy: 100 },
};

export const TYPE_BASIC_MOVE = {
  normal: 'tackle', fire: 'ember', water: 'waterGun', grass: 'vineWhip',
  electric: 'thunderShock', rock: 'rockThrow', ground: 'boneClub',
  poison: 'poisonSting', bug: 'bugBite', flying: 'peck', ice: 'iceShard', dark: 'bite',
};

export const TYPE_STRONG_MOVE = {
  normal: 'hyperBeam', fire: 'flamethrower', water: 'hydroPump', grass: 'solarBeam',
  electric: 'thunderbolt', rock: 'rockSlide', ground: 'earthquake',
  poison: 'sludge', bug: 'signalBeam', flying: 'gust', ice: 'iceBeam', dark: 'darkPulse',
};

// attackingType -> { defendingType: multiplier }
export const TYPE_CHART = {
  normal:   { rock: 0.5 },
  fire:     { grass: 2, water: 0.5, ice: 2, bug: 2, rock: 0.5, fire: 0.5 },
  water:    { fire: 2, rock: 2, ground: 2, grass: 0.5, water: 0.5 },
  grass:    { water: 2, ground: 2, rock: 2, fire: 0.5, flying: 0.5, bug: 0.5, poison: 0.5, grass: 0.5 },
  electric: { water: 2, flying: 2, ground: 0, electric: 0.5 },
  rock:     { fire: 2, ice: 2, flying: 2, bug: 2, ground: 0.5, rock: 1 },
  ground:   { fire: 2, electric: 2, rock: 2, poison: 2, grass: 0.5, bug: 0.5, flying: 0 },
  poison:   { grass: 2, rock: 0.5, ground: 0.5, bug: 0.5, poison: 0.5 },
  bug:      { grass: 2, dark: 2, fire: 0.5, flying: 0.5, rock: 0.5 },
  flying:   { grass: 2, bug: 2, electric: 0.5, rock: 0.5 },
  ice:      { grass: 2, ground: 2, flying: 2, fire: 0.5, water: 0.5, ice: 0.5 },
  dark:     { dark: 0.5 },
};

export function typeEffectiveness(attackType, defendTypes) {
  const chart = TYPE_CHART[attackType] || {};
  let mult = 1;
  for (const t of defendTypes) mult *= (chart[t] ?? 1);
  return mult;
}
