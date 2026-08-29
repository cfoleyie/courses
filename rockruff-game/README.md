# Rockruff

A cute, browser-based Pokémon-inspired adventure. No build step, no dependencies — just HTML5 Canvas and vanilla JavaScript.

## The story

Arceus appears to you in a dream and names you its chosen Trainer: only someone who has
bonded closely with many Pokémon may ever stand before it as an equal. You wake in Hearth
Town with your starter, **Rockruff**, curled up beside you, and set out to explore, catch,
train, battle, and one day find — and catch — Arceus itself.

## How to run it

Because the game is split into ES modules, open it through a local web server rather than
double-clicking `index.html` (browsers block `file://` module imports):

```bash
cd rockruff-game
python3 -m http.server 8000
# then open http://localhost:8000/ in your browser
```

## How to play

- **Move**: Arrow keys / WASD (touch devices get an on-screen D-pad)
- **Interact**: `E` / `Enter` / `Space` — talk to trainers & the Elder, read signs, shop, heal
- **Pause menu**: `Esc` — Party, Pokédex, Bag
- Wild Pokémon actually roam each biome as visible sprites — walk into one to battle it.
  Defeated/caught ones respawn elsewhere after a short while. Battle trainers by interacting
  with them. Defeat them for cash, catch wild Pokémon with Poké/Great Balls, level up, and
  evolve.
- Bond with enough Pokémon and the Elder guarding the **Sacred Hollow** will let you through
  to find Arceus.

Progress autosaves to `localStorage` in your browser.

## Structure

- `js/pokedex-data.js`, `js/moves-data.js` — species, evolutions, moves, type chart
- `js/render.js` — all procedural canvas art (creatures, tiles, player/trainer sprites)
- `js/world.js` — the generated overworld map, biomes, trainers, signs
- `js/wild.js` — wild Pokémon that spawn, wander, and respawn on the map
- `js/player.js` — party/XP/leveling/evolution
- `js/battle.js` — turn-based battle engine, catching
- `js/ui.js` — DOM overlay (dialogue, menus, Pokédex/Party/Shop screens)
- `js/main.js` — game loop, input, state machine
