# Trolley

Two Tesco deliveries a week, every week, and the same question each time: what
has quietly run out since the last one? Trolley watches what you actually buy
and, the evening before each order, asks about the things that will not last
until the delivery after this one.

It runs on a machine at home and serves a small web app that works on a phone —
it installs to the home screen as a PWA — with a command line for everything
else.

## How it works

```
your mailbox (IMAP, every 15 min)  ──►  purchase history  ──►  suggestions
        ▲                                      ▲                    │
        └─ or a file, a paste, a CSV,          └─ your yes/no        ▼
           or "I ordered these"                   on each      reminder the
                                                               evening before
```

### The question it asks

Not "is this due today". With deliveries on Monday and Friday, skipping the
Monday order means going without until Friday, so the test that matters is
whether an item lasts until **the delivery after the one you are planning**. An
item due on Wednesday is not urgent today, but it is the thing you will be
annoyed about on Tuesday, so it goes on the Monday list.

That is why the app always shows two dates in the header: the order it is
helping you build, and the one after it that sets the deadline.

### What it learns

For each item it keeps the gaps between purchases and takes a **recency-weighted
median** of them, which matters more than it sounds:

- **Median, not mean.** One holiday, one stock-up, one week with guests, and an
  average is wrong for months afterwards. A median steps over those.
- **Recency-weighted.** A gap from four months ago counts half as much as last
  week's, so the estimate follows a real change in habits without being yanked
  around by a single odd week.
- **Per unit, not per purchase.** Gaps are divided by the quantity that had to
  cover them, so buying two packs of toilet roll pushes the next reminder out
  twice as far instead of making it look like you get through them at double
  speed.

An item needs about three purchases before the history stands on its own. Below
that the estimate is pulled towards a built-in guess for that staple — the
catalogue knows toilet roll is roughly a fortnightly thing — so something bought
once can still be suggested, marked as a low-confidence guess. Something bought
once that *isn't* a known staple is never suggested at all; it sits under "not
enough history to call", because one purchase of birthday candles is not a habit.

### Brands

This is the part that quietly breaks the naive version. The receipt says *Tesco
Toilet Tissue 9 Roll* one week and *Andrex Classic Clean 12 Rolls* the next, and
treated literally those are two products bought once each, which predicts
nothing. Trolley strips brand names, pack sizes and packaging words, then maps
what is left onto a canonical item.

It is deliberately cautious about it. *Cadbury Dairy Milk* is not milk, *peanut
butter* is not butter, and *garlic bread* is not bread, so those stay as their
own items rather than poisoning a staple's history. When it does get something
wrong, one command fixes it for good, including the purchases already recorded:

```bash
trolley link "Oatly Oat Drink Whole 1L" milk
```

## Getting your history in

### The short version

One command. It asks for the mailbox your order emails arrive in, tries it
before writing anything down, and shows you the orders it found so you can see
it reading your own shopping:

```bash
trolley setup-mail
```

```
Your email address: you@gmail.com
IMAP host [imap.gmail.com]:
App password (not shown as you type):
Folder [INBOX]:
IMAP search for grocery mail [FROM "tesco"]:

Trying it...
  connected to imap.gmail.com as you@gmail.com; folder 'INBOX' has 96 message(s)
  matching 'FROM "tesco"' in the last 730 days

Reading a sample: 20 messages checked, 20 orders, 74 lines would be recorded
    Tesco British Semi Skimmed Milk 2.272L/4 Pints   -> Milk
    Tesco Toilet Tissue 9 Roll                       -> Toilet roll
    Andrex Classic Clean Toilet Tissue 12 Rolls      -> Toilet roll
    ...

Save this to the config? [Y/n]:
```

Then read the back catalogue once and start the server:

```bash
trolley mail --all     # everything already in the mailbox
trolley serve          # from here it keeps itself up to date
```

From that point there is nothing to do. An order is placed, the email arrives,
the next check folds it into the history, and the list for the following
delivery already knows about it.

### Gmail, specifically

The host is `imap.gmail.com` and the setup command fills that in from your
address. Two things trip people up, and both are handled:

- **The password must be an app password**, not your Google password. Turn on
  2-Step Verification, then make one at
  [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
  Google shows it as four groups of four; paste it exactly as shown, spaces and
  all, because the spaces are presentation only and get stripped for you.
  If Google refuses it, the error says which of these to check rather than just
  "invalid credentials".
- **A Gmail folder is a label.** `INBOX` reads everything. If you filter Tesco
  mail into a label, name that label instead and Trolley never sees anything
  else. Nested labels use a slash, and a label with a space in it is fine.

IMAP also has to be on: Gmail, Settings, See all settings, Forwarding and
POP/IMAP.

The password is written to a `.env` file beside the config, readable only by
you, and never into the config file itself.

### If you would rather not hand over your main mailbox

This is where forwarding earns its keep. Make a Gmail filter that auto-forwards
Tesco mail to a separate free mail account, and point Trolley at that instead.
It then only ever sees grocery email. The label approach above is a lighter
version of the same idea.

Either way the connection is outbound only: nothing has to be exposed to the
internet, no port forwarding, no webhook, no third party holding your mail.

Progress is tracked by message ID rather than read/unread, so Trolley never
touches your inbox to keep its place, and reading mail on your phone does not
hide it from the importer. Set `mark_seen = true` if you would rather it did
mark them read.

### Which email it believes

Tesco sends more than one email per order: a confirmation when you book, a
notice if you amend it, and a receipt after the van has been. Only the last one
knows what actually turned up, substitutions and all.

Trolley reads all of them, keyed by order number, and a later email **replaces**
the earlier one rather than being skipped or double-counted. If the toilet roll
was out of stock, the confirmation's claim that you bought it is thrown away
when the receipt arrives. That matters: an item you did not actually get should
not reset its clock.

### The other ways in

You do not have to use the mailbox at all.

**Files.** Save emails out of your mail client (in Gmail: open one, ⋮ →
*Download message*) and point Trolley at the folder:

```bash
trolley import ~/Downloads/tesco --dry-run   # see what it makes of them
trolley import ~/Downloads/tesco             # keep it
```

**Paste one in.** The **Import** tab in the web app takes a single email, with
the same preview.

**CSV.** If your emails defeat the parser, any file with a date column and an
item column will do:

```csv
date,item,qty
2026-09-14,Tesco Toilet Tissue 9 Roll,1
2026-09-14,Tesco Semi Skimmed Milk,2
```

**Just using it.** Tick things onto the list and press *I ordered these*, and
that is recorded as a purchase. Start from nothing and after three or four
weeks it is useful on the staples you buy most.

### About the parser

It does not depend on Tesco's markup, which changes: it looks for the shape
every receipt has, a description with a quantity and a price, and ignores the
delivery charges, Clubcard lines and totals around them. Marketing email is
skipped rather than mangled.

That is still a heuristic, so **check it once** with `trolley mail --dry-run`
or `trolley import --dry-run`, which print every line found and what each was
matched to. `trolley import --show-text` prints an email as the parser sees it
if something is being missed.

## Why not read it from the Tesco app?

That was the first thing worth checking, and the answer is no, for reasons
worth knowing.

Tesco's public grocery API was retired years ago. The phone app talks to a
private one that is not documented or supported for this, and using it would
mean lifting the app's credentials and pretending to be it. Scraping the
website while logged in as you is the other version of the same idea. Both
would work for a while. Both break without warning whenever Tesco changes
something, both are against the terms you agreed to, and a scraper that logs
into your account is a password sitting on a machine at home waiting to be
worth stealing.

The confirmation emails carry the same information — what you bought, how much,
when — and they are yours, already sitting in your mailbox, in a format nobody
is going to change without also breaking their own customers' receipts. Reading
them needs no account access and cannot touch your order.

One thing the app is genuinely good for: if you want the full back catalogue
rather than whatever is still in your mail, Tesco will give you your Clubcard
purchase history on request, and that export can be fed in as CSV.

## Setting it up

```bash
git clone <this repo> && cd trolley
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp config.example.toml config.toml
```

Edit the `[[slots]]` entries to match your delivery days, then:

```bash
trolley demo        # a year of invented history, to see what it does
trolley suggest     # the list for the next delivery
trolley serve       # the web app on http://localhost:8815
```

`trolley demo` writes into the same database as everything else, so use a
throwaway `config.toml` for it or delete the database afterwards.

With Docker:

```bash
cp .env.example .env && mkdir -p data inbox
docker compose up -d
docker compose exec trolley trolley import /app/inbox
```

## Reminders

The server checks the clock and sends one notification per delivery, by default
14 hours before the slot, which for an 8am delivery is the evening before while
there is still time to change the order. Set `notify.enabled` and a channel:

- **`ntfy`** — install the ntfy app, pick a topic nobody would guess, put it in
  `notify.ntfy_topic`. This is the least fuss for getting it onto a phone.
- **`smtp`** — an email with the list. The password goes in
  `TROLLEY_SMTP_PASSWORD`, never in the config file.
- **`console`** — prints it, which is what you want if you would rather drive it
  from cron: `trolley notify` sends the list and says nothing when nothing is due.

A restart inside the reminder window will not send the same list twice.

## Using it

The web app has four tabs.

**Suggested** is the list for the next delivery, most urgent first. Each item
says why it is there — *"Due 3 weeks ago. Usually every 3 weeks; last bought 7
weeks ago"* — with three answers:

- **Add** puts it on the list, and confirms the estimate was right.
- **Not now** skips it for this delivery only. It is back for the next one.
- **✕** stops suggesting it entirely, until you turn it back on under *Items*.

Turning a suggestion down without saying *not now* stretches that item's
estimate a little, so an item you keep dismissing asks less often instead of
nagging every delivery. The stretch is capped, and accepting a suggestion
clears it.

**List** is what you have ticked on, with a *Copy list* button for pasting into
Tesco, and *I ordered these* to record them as bought.

**Items** is everything it knows, when each is next due, and a confidence bar.
This is where you un-pause something, or pin an item to a fixed interval if you
know better than the history does.

**Import** takes a pasted order email.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

## What it does not do

- **It does not touch your Tesco account.** It cannot read your orders, add
  anything to your basket, or place an order. Everything it knows, you gave it,
  and the list is something you copy across yourself.
- **It does not predict things you buy irregularly.** Anything bought once,
  or with no rhythm to it, stays in "not enough history to call". That is the
  intended behaviour: a list that suggests everything is a list you stop reading.
- **It does not know what is in your cupboards**, only what you bought and when.
  A month where you eat out constantly will make it early, and telling it *not
  now* is how you say so.
