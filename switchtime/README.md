# Switch Time

Finish a lesson on IXL, get time on the Switch. The console's daily play-time
limit is driven from a minute ledger, so the reward lands without anyone
unlocking anything by hand.

It runs on a machine at home and serves a small web app that works on a
Chromebook and an Android tablet — both are Chrome, so it installs to the home
screen as a PWA.

## How it works

```
IXL (headless browser, every 3 min)  ──►  ledger (SQLite)  ──►  Switch daily limit
        ▲                                      ▲
        └─ "Check IXL now" button              └─ parent approvals and adjustments
```

Every sync does three things in order: credit newly finished skills, charge for
what the console says was played, then write the resulting balance back.

The limit written is always **`minutes played today + minutes still owed`**.
Nintendo enforces a daily *total*, not a countdown, so computing that absolute
number each time makes every write idempotent — a retried or duplicated sync
lands on the same value instead of stacking bonuses. Consequences worth knowing:

- Earning more mid-session raises the limit immediately.
- A zero balance sets the limit to exactly what has been played, so the console
  locks where it stands.
- Unused minutes roll over to tomorrow by default, because the balance persists
  while the console's counter resets.

## Setting it up

### 1. Install

```bash
git clone <this repo> && cd switchtime
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
cp config.example.toml config.toml
```

### 2. Link the Nintendo account

```bash
switchtime nintendo-login
```

It prints a Nintendo sign-in URL. Sign in as the **parent** account, then on the
final page right-click the *Link account* button, copy the link address (it
starts with `npf`), and paste it back. You get a long-lived session token:

```bash
export NINTENDO_SESSION_TOKEN='...'
```

Then find each console's id and paste it into `config.toml`:

```bash
switchtime devices
```

### 3. Add IXL credentials

IXL has no API, so the service signs in as each child and reads their Analytics
pages the way you would. Put each password in the environment variable named by
`ixl_password_env`:

```bash
export IXL_PASSWORD_OLIVER='...'
```

### 4. Check the wiring, then run

```bash
switchtime check-config     # what is configured and what is missing
switchtime sync oliver      # one pass, with dry_run still on
switchtime serve            # http://<this machine>:8777
```

Leave `dry_run = true` until a couple of syncs report a sensible target limit.
Then set it to `false` and the console starts following the ledger.

### On the Chromebook and the tablet

Open `http://<machine>:8777` in Chrome, then **⋮ → Install page as app** (or
*Add to Home screen*). It runs full-screen with its own icon. Both devices need
to be on the same network as the machine running the service.

## Tuning the IXL side

**Expect one round of tuning here.** IXL publishes no API, so the scraper reads
whatever JSON the analytics pages load and keeps objects that look like a
practised skill: something carrying a name plus a score or a date. That
heuristic survives IXL renaming its keys, which pinned selectors would not — but
it has never been run against your actual account, and the first run is the one
that tells you whether it matches.

```bash
switchtime probe oliver --out data/probe
```

That signs in, saves every JSON payload it saw, and prints what it matched. If
nothing matched, open the dumped JSON, find the objects describing finished
skills, and widen the key lists at the top of
`switchtime/providers/ixl_extract.py`. The extraction logic is pure and covered
by tests, so you can iterate on it without a browser.

If IXL sign-in stops working entirely, the app still works: kids tap **Ask a
parent for time** and you approve from your phone.

## Known limits

- **One child per console.** Nintendo enforces play-time limits per *console*,
  not per user account. With two kids sharing a Switch, whatever one earns is
  available to both. The app reports play time per console for the same reason.
- **The Nintendo API is unofficial.** It broke in March 2026 when Nintendo
  changed it, and it will break again. When it does, the ledger keeps working
  and only the console write fails; the parent view shows the error.
- **Minutes are only charged when a sync runs.** Between polls the console can
  run past a balance that just hit zero. Nothing is lost — the overshoot is
  charged on the next pass and comes off tomorrow.
- The first sync of a day never charges for play time already on the clock, to
  avoid double-billing after a restart.

## Running it as a service

```bash
cp .env.example .env      # fill in the tokens
docker compose up -d
```

Or run `switchtime serve` under systemd. Data lives in `data/`, which is the
only directory worth backing up.

## Layout

| Path | What it holds |
| --- | --- |
| `switchtime/ledger.py` | Pure domain logic: balances, caps, limit arithmetic |
| `switchtime/sync.py` | One sync pass, and the background poller |
| `switchtime/providers/ixl.py` | Headless-browser IXL reader |
| `switchtime/providers/ixl_extract.py` | The heuristic that finds skills in IXL's JSON |
| `switchtime/switch.py` | Nintendo parental-controls client |
| `switchtime/app.py` | HTTP API |
| `switchtime/static/` | The web app |

```bash
pytest        # 107 tests, no network or credentials needed
```
