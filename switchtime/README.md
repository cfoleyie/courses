# Switch Time

Finish a lesson on IXL, get time on the Switch. The console's daily play-time
limit is driven from a minute ledger, so the reward lands without anyone
unlocking anything by hand.

It runs on a machine at home and serves a small web app for a Chromebook, a
tablet or a phone. Served over HTTPS it installs to the home screen as a proper
app; see step 5, which is the one part that needs more than a LAN address.

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
git clone https://github.com/cfoleyie/courses && cd courses/switchtime
bash tools/setup.sh
```

That creates the virtualenv, installs everything including the headless browser,
copies `config.example.toml` to `config.toml`, runs the tests, and prints what is
still missing. It is safe to re-run.

Doing it by hand instead:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
cp config.example.toml config.toml
```

### 2. Link the Nintendo account

```bash
switchtime nintendo-login
```

It prints a Nintendo sign-in URL. Sign in as the **parent** account and you land
on a *Link an account* page with a red **Select this account** button.

**Right-click that button and choose *Copy link address*** — a two-finger tap or
Alt+click on a Chromebook — then paste it back. Left-clicking navigates to
`npf...://auth`, which the browser cannot open, and takes the code with it. If
the menu has no *Copy link address*, press Ctrl+Shift+J and run
`document.querySelector('a[href^="npf"]').href`.

Close any leftover Nintendo tab before you start: every run generates its own
secret, and only the URL from the current run can complete the exchange.

The token is written straight into `.env.local` (mode 600) rather than printed.
It is valid for **years** — treat it like a password, and do not paste it into a
chat, an issue or a screenshot. `--print-token` puts it on screen instead, for
Docker or a password manager.

If one does leak: change your Nintendo Account password and use
*Sign-in and security settings → Sign-in history → Sign out from all devices*,
then run this command again for a fresh one. The scopes are limited to parental
controls, so a leaked token cannot buy anything or take over the account, but it
can read play summaries and change your children's limits.

Then find each console's id and paste it into `config.toml`:

```bash
switchtime devices
```

### 3. Add IXL credentials

IXL has no API, so the service signs in and reads the Analytics pages the way
you would.

**On a family subscription this is two steps**, and both need configuring: you
sign in with one account, then each child taps their name and enters what IXL
calls their **secret word**. `ixl_username` is the *family* account, not the
child, and `ixl_profile_password_env` holds the secret word:

```toml
ixl_username = "family-account-username"
ixl_password_env = "IXL_FAMILY_PASSWORD"
ixl_profile = "Oliver"                   # the name he taps on the chooser
ixl_profile_password_env = "IXL_PROFILE_OLIVER"
```

Note that `ixl_password_env` is the **name of an environment variable**, not the
password. The passwords themselves go in `.env.local`, and this fills them in
without echoing them or putting them in your shell history:

```bash
switchtime set-secret            # prompts for every missing one
switchtime set-secret NAME       # or just the one
```

Leave the two `profile` lines out if your child signs in directly with their own
username.

Every command reads `.env.local` from beside `config.toml`, and so does the
background service, so the secrets are configured once. A real environment
variable still takes precedence if you would rather export one.

### 4. Check the wiring, then run

```bash
switchtime check-config     # what is configured and what is missing
switchtime sync oliver      # one pass, with dry_run still on
switchtime grant oliver 30  # add minutes by hand, to watch the loop work
switchtime status           # balances
switchtime serve            # http://<this machine>:8777
```

Leave `dry_run = true` until a couple of syncs report a sensible target limit.
Then set it to `false` and the console starts following the ledger.

### 5. Put it on the Chromebook and your phone

**Installing needs HTTPS.** A plain `http://192.168.x.x:8777` is not a secure
origin, and Chrome then hides `navigator.serviceWorker` entirely and will not
offer to install the page — verified, not assumed. Over plain HTTP you can still
use the app as an ordinary bookmark; you just do not get the icon, the
full-screen window, or the cached shell.

The tidiest fix is [Tailscale](https://tailscale.com), which is free for
personal use and gets you a real certificate plus access from outside the house
— which matters for the phone, since approving a request is exactly the thing
you want to do while not at home.

On the machine running the service:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg 8777        # HTTPS in front of the app
tailscale serve status                # prints the https://... name to use
```

Install Tailscale on the Chromebook and the phone, sign in with the same
account, and both can reach that `https://` name from anywhere.

**Chromebook:** open the URL in Chrome → **⋮** → *Cast, save and share* →
**Install page as app** → *Install*. It lands in the launcher and opens in its
own window.

**Android phone:** open the URL in Chrome → **⋮** → **Add to Home screen** →
*Install*. Chrome builds a real app from the manifest, so it gets the icon and
opens full-screen. Note that *Install* and *Create shortcut* are different: only
the former makes a standalone app.

**iPhone:** open the URL in Safari (not Chrome — only Safari can install on iOS)
→ Share → **Add to Home Screen**.

If you would rather not use Tailscale, any HTTPS route works: a reverse proxy
such as Caddy with a real domain, or Cloudflare Tunnel.

## Tuning the IXL side

**Set your country first.** IXL runs a separate site per country and an account
only works on its own, so signing in on the wrong one fails in a way that looks
exactly like a wrong password. Check the address bar while your child is signed
in and set it in `config.toml`:

```toml
[ixl]
base_url = "https://ie.ixl.com"   # uk.ixl.com, ca.ixl.com, au.ixl.com, www.ixl.com
```

The sign-in and report URLs are derived from it.

**Expect one round of tuning here.** IXL publishes no API, so the scraper reads
whatever JSON the analytics pages load and keeps objects that look like a
practised skill: something carrying a name plus a score or a date. That
heuristic survives IXL renaming its keys, which pinned selectors would not — but
it has never been run against your actual account, and the first run is the one
that tells you whether it matches.

```bash
switchtime probe oliver --out data/probe
```

That signs in and saves, per page: a full-page screenshot, the rendered HTML,
and every JSON payload it saw. It then prints what it matched and, when nothing
did, a checklist working outwards from the most likely cause.

The screenshots are the useful part. `*-1-after-signin.png` shows whether the
sign-in worked at all; `*-report.png` shows whether `report_urls` point at the
right pages. Only once those look right is it worth reading the JSON, and then
the job is to find a skill name you can see in the screenshot and add the keys
around it to `switchtime/providers/ixl_extract.py`. That logic is pure and
covered by tests, so it can be iterated on without a browser.

Set `headless = false` in `config.toml` to watch the browser do it, which is
often faster than reading the artefacts.

### School accounts

If your child's IXL comes through their school, they may sign in with Google,
Clever, Microsoft or ClassLink rather than an IXL password. There is then no
password for this to use, and the probe will report being stuck on the sign-in
page while naming the provider it saw.

Options, roughly in order of hassle:

- **A family IXL account.** A separate subscription the app can sign into with a
  real password. Cleanest, but it is a second account and a second cost, and the
  school work would not count.
- **Sign in once by hand.** Set `headless = false`, run
  `switchtime probe <kid>`, complete the SSO in the window that opens. The
  session is saved to `data/ixl-sessions/` and reused, so the poller works until
  it expires — weeks, typically, then you repeat it. No code changes needed.
- **Skip IXL sync.** Set `enabled = false` under `[ixl]`. Kids tap **Ask a parent
  for time**, you approve from your phone, and everything else works unchanged.

The second option is the usual answer: one manual sign-in, then it runs itself.

If IXL sign-in stops working entirely, the app still works the same way: kids
tap **Ask a parent for time** and you approve from your phone.

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
- The very first sync for a kid never charges for play time already on the
  clock, so a fresh install cannot open with a large debt. After that a new day
  starts counting from zero, so play that happened before the day's first sync
  — overnight, or while the machine was asleep — is still charged.

## Running it as a service

```bash
bash tools/install-service.sh
```

Installs a systemd user service where one exists, and falls back to a `@reboot`
cron entry where it does not. Either way it creates `.env.local` (mode 600,
gitignored) for the Nintendo token and the IXL passwords — a background service
inherits nothing from your shell, so `export` is not enough; the secrets have to
live in that file.

```bash
systemctl --user status switchtime      # is it running
systemctl --user restart switchtime     # after editing config.toml or .env.local
journalctl --user -u switchtime -f      # follow the logs
```

Docker instead:

```bash
cp .env.example .env      # fill in the tokens
docker compose up -d
```

Data lives in `data/`, which is the only directory worth backing up.

### Hosting it on a Chromebook

Workable, with two caveats worth knowing before you rely on it.

Enable **Settings → Advanced → Developers → Linux development environment**,
then run `tools/setup.sh` and `tools/install-service.sh` in the Terminal app.

**It stops when the Chromebook sleeps.** The Linux container is suspended with
the rest of the device, so polling halts when the lid closes. Set
**Settings → Device → Power → While charging → Keep display on** and leave it
plugged in. Nothing is lost when it does sleep: the console keeps its own count,
and the next sync after waking charges whatever was played meanwhile.

**Whoever holds the Chromebook can stop the service.** If this is the same
machine a child uses, they can quit the container that enforces their own
limits. A Pi or any always-on box avoids both problems.

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
| `tools/setup.sh` | One-shot install on a fresh machine |
| `tools/install-service.sh` | Runs it in the background, surviving reboots |
| `tools/make_icons.py` | Regenerates the PWA icons |

```bash
pytest        # 160 tests, no network or credentials needed
```
