// Turn-based battle engine: damage calc, catching, trainer battles, and the Arceus showdown.
import { SPECIES } from './pokedex-data.js';
import { MOVES, typeEffectiveness } from './moves-data.js';
import { createPokemon, gainXP, xpReward, firstAlive } from './player.js';

export function startWildBattle(player, speciesId, level) {
  const wild = createPokemon(speciesId, level);
  player.pokedex.seen.add(speciesId);
  return makeBattle('wild', player, [wild], { canFlee: true, canCatch: true });
}

export function startLegendaryBattle(player) {
  const arceus = createPokemon('arceus', 60);
  player.pokedex.seen.add('arceus');
  player.arceusEncountered = true;
  return makeBattle('legendary', player, [arceus], { canFlee: false, canCatch: true });
}

export function startTrainerBattle(player, trainerDef) {
  const team = trainerDef.team.map(t => createPokemon(t.species, t.level));
  for (const p of team) player.pokedex.seen.add(p.speciesId);
  return makeBattle('trainer', player, team, { canFlee: false, canCatch: false, trainer: trainerDef });
}

function makeBattle(kind, player, enemyTeam, opts) {
  return {
    kind,
    player,
    playerActive: player.party.findIndex(p => p.hp > 0),
    enemyTeam,
    enemyActive: 0,
    canFlee: !!opts.canFlee,
    canCatch: !!opts.canCatch,
    trainer: opts.trainer || null,
    finished: false,
    outcome: null,
    moneyWon: 0,
  };
}

export function activePlayerMon(battle) { return battle.player.party[battle.playerActive]; }
export function activeEnemyMon(battle) { return battle.enemyTeam[battle.enemyActive]; }

function stageMult(stage) { return (2 + Math.max(0, stage)) / (2 + Math.max(0, -stage)); }

function computeDamage(attacker, attackerSpeciesId, defender, move) {
  if (move.power <= 0) return 0;
  const sp = SPECIES[attackerSpeciesId];
  const stab = sp.types.includes(move.type) ? 1.5 : 1;
  const eff = typeEffectiveness(move.type, SPECIES[defender.speciesId].types);
  const atk = attacker.atk * stageMult(attacker.atkStage);
  const def = Math.max(1, defender.def * stageMult(defender.defStage));
  const level = attacker.level;
  const base = ((2 * level / 5 + 2) * move.power * (atk / def)) / 50 + 2;
  const variance = 0.85 + Math.random() * 0.15;
  const dmg = Math.max(1, Math.floor(base * stab * eff * variance));
  return { dmg, eff };
}

function useMove(battle, isPlayer, moveId, steps) {
  const attacker = isPlayer ? activePlayerMon(battle) : activeEnemyMon(battle);
  const defender = isPlayer ? activeEnemyMon(battle) : activePlayerMon(battle);
  const attackerName = SPECIES[attacker.speciesId].name;
  const defenderName = SPECIES[defender.speciesId].name;
  const move = MOVES[moveId];
  if (attacker.hp <= 0) return;

  const enemyPrefix = battle.kind === 'trainer' ? `${battle.trainer.name}'s ` : 'Wild ';
  steps.push({ type: 'text', text: `${isPlayer ? attackerName : enemyPrefix + attackerName} used ${move.name}!` });

  if (Math.random() * 100 > move.accuracy) {
    steps.push({ type: 'text', text: `${attackerName}'s attack missed!` });
    return;
  }

  if (move.power > 0) {
    const { dmg, eff } = computeDamage(attacker, attacker.speciesId, defender, move);
    defender.hp = Math.max(0, defender.hp - dmg);
    steps.push({ type: 'hpChange', side: isPlayer ? 'enemy' : 'player', name: defenderName, level: defender.level, hp: defender.hp, maxHp: defender.maxHp });
    if (eff > 1) steps.push({ type: 'text', text: "It's super effective!" });
    else if (eff < 1 && eff > 0) steps.push({ type: 'text', text: "It's not very effective..." });
    else if (eff === 0) steps.push({ type: 'text', text: `It had no effect on ${defenderName}...` });
    if (defender.hp <= 0) {
      steps.push({ type: 'faint', side: isPlayer ? 'enemy' : 'player', name: defenderName });
    }
  } else if (move.effect) {
    const target = move.effect.target === 'self' ? attacker : defender;
    const targetIsPlayer = move.effect.target === 'self' ? isPlayer : !isPlayer;
    const key = move.effect.stat === 'atk' ? 'atkStage' : 'defStage';
    target[key] = Math.max(-4, Math.min(4, target[key] + move.effect.stages));
    const targetName = targetIsPlayer ? attackerName : defenderName;
    const dir = move.effect.stages > 0 ? 'rose' : 'fell';
    steps.push({ type: 'text', text: `${targetName}'s ${move.effect.stat === 'atk' ? 'Attack' : 'Defense'} ${dir}!` });
  }
}

function enemyPickMove(enemy) {
  const moves = enemy.moves.length ? enemy.moves : ['tackle'];
  return moves[Math.floor(Math.random() * moves.length)];
}

// Resolves one full round given the player's chosen move id. Returns an array of "steps" for the UI to play out.
export function resolveTurn(battle, playerMoveId) {
  const steps = [];
  const p = activePlayerMon(battle);
  const e = activeEnemyMon(battle);
  const pMove = MOVES[playerMoveId];
  const eMoveId = enemyPickMove(e);
  const eMove = MOVES[eMoveId];

  const pPriority = pMove.priority || 0;
  const ePriority = eMove.priority || 0;
  let playerFirst;
  if (pPriority !== ePriority) playerFirst = pPriority > ePriority;
  else playerFirst = p.spd === e.spd ? Math.random() < 0.5 : p.spd > e.spd;

  const order = playerFirst ? [true, false] : [false, true];
  for (const isPlayer of order) {
    if (battle.finished) break;
    if (isPlayer && p.hp <= 0) continue;
    if (!isPlayer && e.hp <= 0) continue;
    useMove(battle, isPlayer, isPlayer ? playerMoveId : eMoveId, steps);
    resolveFaintCheck(battle, steps);
    if (battle.finished) break;
  }
  return steps;
}

function resolveFaintCheck(battle, steps) {
  const e = activeEnemyMon(battle);
  const p = activePlayerMon(battle);
  if (e.hp <= 0) {
    const xpGain = xpReward(e, battle.kind === 'trainer');
    for (const mon of battle.player.party) {
      if (mon.hp <= 0) continue;
      const res = gainXP(mon, xpGain);
      steps.push({ type: 'xp', name: SPECIES[mon.speciesId].name, amount: xpGain });
      if (res.leveledUp) steps.push({ type: 'levelup', name: SPECIES[mon.speciesId].name, level: res.newLevel });
      if (res.evolvedTo) steps.push({ type: 'evolve', from: res.evolvedFrom, to: res.evolvedTo });
    }
    if (battle.enemyActive < battle.enemyTeam.length - 1) {
      battle.enemyActive += 1;
      const nm = activeEnemyMon(battle);
      steps.push({ type: 'text', text: `${battle.trainer?.name || 'The wild Pokémon'} sent out ${SPECIES[nm.speciesId].name}!` });
      steps.push({ type: 'sendout', side: 'enemy', name: SPECIES[nm.speciesId].name, level: nm.level, hp: nm.hp, maxHp: nm.maxHp });
    } else {
      battle.finished = true;
      battle.outcome = 'win';
      if (battle.kind === 'trainer') {
        battle.moneyWon = battle.trainer.reward;
        battle.player.money += battle.trainer.reward;
        battle.player.trainersDefeated.add(battle.trainer.id);
        steps.push({ type: 'trainerDefeat', trainer: battle.trainer });
      } else {
        steps.push({ type: 'text', text: 'You won the battle!' });
      }
    }
    return;
  }
  if (p.hp <= 0) {
    const next = firstAlive(battle.player.party);
    if (next) {
      battle.playerActive = battle.player.party.indexOf(next);
      steps.push({ type: 'text', text: `Go, ${SPECIES[next.speciesId].name}!` });
      steps.push({ type: 'sendout', side: 'player', name: SPECIES[next.speciesId].name, level: next.level, hp: next.hp, maxHp: next.maxHp });
    } else {
      battle.finished = true;
      battle.outcome = 'lose';
      steps.push({ type: 'text', text: 'All your Pokémon have fainted...' });
    }
  }
}

export function switchActive(battle, partyIndex) {
  if (battle.player.party[partyIndex].hp <= 0) return false;
  battle.playerActive = partyIndex;
  return true;
}

export function attemptFlee(battle) {
  const p = activePlayerMon(battle), e = activeEnemyMon(battle);
  const chance = Math.min(0.9, 0.5 + (p.spd - e.spd) / (e.spd * 2 + 1));
  if (Math.random() < Math.max(0.25, chance)) {
    battle.finished = true;
    battle.outcome = 'ran';
    return true;
  }
  return false;
}

export function attemptCatch(battle, ballType) {
  const e = activeEnemyMon(battle);
  const sp = SPECIES[e.speciesId];
  const ballBonus = ballType === 'greatball' ? 1.6 : 1;
  const hpFactor = (3 * e.maxHp - 2 * e.hp) / (3 * e.maxHp);
  let chance = (sp.catchRate / 255) * hpFactor * ballBonus;
  chance = Math.max(0.02, Math.min(0.95, chance));
  const shakes = Math.random() < chance ? 3 : Math.floor(Math.random() * 3);
  const success = shakes >= 3;
  if (success) {
    battle.finished = true;
    battle.outcome = 'caught';
  }
  return { success, shakes, pokemon: e };
}

// Enemy takes a free turn — used when the player uses an item, switches, or fails to flee/catch.
export function enemyFreeTurn(battle) {
  const steps = [];
  if (battle.finished) return steps;
  const e = activeEnemyMon(battle);
  if (e.hp <= 0) return steps;
  const moveId = enemyPickMove(e);
  useMove(battle, false, moveId, steps);
  resolveFaintCheck(battle, steps);
  return steps;
}

export function usePotion(battle, isPlayer = true) {
  const p = activePlayerMon(battle);
  if (battle.player.items.potion <= 0 || p.hp <= 0) return false;
  battle.player.items.potion -= 1;
  p.hp = Math.min(p.maxHp, p.hp + Math.floor(p.maxHp * 0.5));
  return true;
}
