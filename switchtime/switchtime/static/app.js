/* Switch Time — kid and parent views over the /api endpoints.
   Vanilla on purpose: this runs on a Chromebook and a tablet on the house
   wi-fi, and a build step would be one more thing to keep working. */
(function () {
  "use strict";

  var state = { kids: [], parent: false, pending: [], rules: {} };
  var ui = { screen: "home", kidId: null, history: [], report: null, busy: false, pinOpen: false };
  var POLL_MS = 20000;
  var timer = null;

  // ---------- tiny DOM helper ----------
  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k === "html") n.innerHTML = v;
      else if (k.indexOf("on") === 0 && typeof v === "function") n.addEventListener(k.slice(2), v);
      else if (v === true) n.setAttribute(k, "");
      else n.setAttribute(k, v);
    });
    (children || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return n;
  }

  function fmt(mins) {
    mins = Math.round(mins || 0);
    var sign = mins < 0 ? "-" : "";
    mins = Math.abs(mins);
    var h = Math.floor(mins / 60), m = mins % 60;
    if (!h) return sign + m + "m";
    if (!m) return sign + h + "h";
    return sign + h + "h " + m + "m";
  }

  function timeAgo(iso) {
    if (!iso) return "never";
    var secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (secs < 90) return "just now";
    if (secs < 3600) return Math.round(secs / 60) + " min ago";
    if (secs < 86400) return Math.round(secs / 3600) + "h ago";
    return Math.round(secs / 86400) + "d ago";
  }

  // ---------- api ----------
  function api(path, options) {
    options = options || {};
    return fetch(path, {
      method: options.method || "GET",
      headers: options.body ? { "Content-Type": "application/json" } : undefined,
      body: options.body ? JSON.stringify(options.body) : undefined,
      credentials: "same-origin"
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) {
          var err = new Error(data.detail || res.statusText || "Something went wrong");
          err.status = res.status;
          throw err;
        }
        return data;
      });
    });
  }

  var toastTimer = null;
  function toast(message, bad) {
    var existing = document.querySelector(".toast");
    if (existing) existing.remove();
    var node = el("div", { class: "toast" + (bad ? " bad" : ""), text: message });
    document.body.appendChild(node);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { node.remove(); }, 4000);
  }

  function refresh() {
    return api("/api/state").then(function (data) {
      state = data;
      render();
    }).catch(function () { /* a dropped poll is not worth shouting about */ });
  }

  function kidById(id) {
    return state.kids.filter(function (k) { return k.id === id; })[0];
  }

  // ---------- screens ----------
  function render() {
    var root = document.getElementById("app");
    root.innerHTML = "";
    root.appendChild(topbar());
    if (ui.screen === "kid" && kidById(ui.kidId)) root.appendChild(kidScreen(kidById(ui.kidId)));
    else if (ui.screen === "parent") root.appendChild(parentScreen());
    else root.appendChild(homeScreen());
    if (ui.pinOpen) root.appendChild(pinModal());
  }

  function topbar() {
    return el("header", { class: "topbar" }, [
      el("div", { class: "topbar-inner" }, [
        el("div", {
          class: "brand",
          onclick: function () { ui.screen = "home"; ui.kidId = null; render(); }
        }, [
          el("span", { class: "title", text: "Switch Time" }),
          el("span", { class: "sub", text: "IXL in, play time out" })
        ]),
        el("div", { class: "topbar-actions" }, [
          state.parent && state.pending.length
            ? el("button", {
                class: "btn warn small",
                onclick: function () { ui.screen = "parent"; render(); },
                text: "Requests (" + state.pending.length + ")"
              })
            : null,
          state.parent
            ? el("button", {
                class: "btn small",
                onclick: function () {
                  api("/api/parent/lock", { method: "POST" }).then(function () {
                    ui.screen = "home"; refresh();
                  });
                },
                text: "Lock"
              })
            : el("button", {
                class: "btn ghost small",
                onclick: function () { ui.pinOpen = true; render(); },
                text: "Parent"
              })
        ])
      ])
    ]);
  }

  function homeScreen() {
    if (!state.kids.length) {
      return el("div", { class: "card pad empty" }, ["No kids configured yet — check config.toml."]);
    }
    return el("div", { class: "stack" }, [
      el("div", { class: "kid-grid" }, state.kids.map(function (kid) {
        return el("button", {
          class: "kid-card",
          style: "--kid-color:" + kid.color,
          onclick: function () { openKid(kid.id); }
        }, [
          statusChip(kid),
          el("div", { class: "name", text: kid.name }),
          el("div", { class: "label", text: "play time banked" }),
          el("div", { class: "balance num", text: fmt(kid.balance) })
        ]);
      })),
      el("div", { class: "card pad" }, [
        el("div", { class: "section-title" }, [el("h2", { text: "How this works" })]),
        el("p", {
          class: "hint",
          style: "margin:0",
          text:
            "Finish a lesson on IXL and it turns into " +
            fmt(state.rules.minutes_per_lesson || 30) +
            " on the Switch. The console's daily limit updates by itself, usually within a couple of minutes. " +
            "Up to " + fmt(state.rules.daily_cap || 180) + " can be earned in a day" +
            (state.rules.rollover ? ", and anything unused carries over to tomorrow." : ". Unused time expires overnight.")
        })
      ])
    ]);
  }

  function statusChip(kid) {
    if (!kid.switch_ready) return el("span", { class: "chip", text: "no console linked" });
    if (kid.pending) return el("span", { class: "chip warn", text: kid.pending + " waiting on a parent" });
    if (!kid.last_sync_ok) return el("span", { class: "chip bad", text: "sync problem" });
    if (kid.balance > 0) return el("span", { class: "chip ok", text: "ready to play" });
    return el("span", { class: "chip", text: "nothing banked" });
  }

  function openKid(kidId) {
    ui.kidId = kidId;
    ui.screen = "kid";
    ui.history = [];
    render();
    api("/api/kids/" + kidId + "/history").then(function (data) {
      ui.history = data.events || [];
      if (ui.screen === "kid") render();
    }).catch(function () {});
  }

  function kidScreen(kid) {
    var capUsed = kid.daily_cap ? Math.min(1, kid.earned_today / kid.daily_cap) : 0;
    var wrap = el("div", { class: "stack" }, [
      el("div", { class: "card pad hero" }, [
        el("div", {}, [
          el("div", { class: "label", text: kid.name + " · play time banked" }),
          el("div", { class: "num", text: fmt(kid.balance) }),
          el("div", {
            class: "sub",
            text: kid.played_today
              ? "Played " + fmt(kid.played_today) + " today"
              : "Nothing played yet today"
          })
        ]),
        el("div", {}, [statusChip(kid)])
      ]),

      el("div", { class: "card pad stack" }, [
        el("button", {
          class: "btn primary big",
          disabled: ui.busy || !kid.ixl_ready,
          onclick: function () { checkIXL(kid); },
          text: ui.busy ? "Checking IXL…" : "Check IXL now"
        }),
        el("p", {
          class: "hint",
          style: "margin:0",
          text: kid.ixl_ready
            ? "Finished a lesson? Tap this and it lands on the Switch in a few seconds. It also checks by itself every few minutes."
            : "Automatic IXL checking is off for you, so ask a parent instead."
        }),
        el("button", {
          class: "btn",
          onclick: function () { askParent(kid); },
          text: "Ask a parent for time"
        })
      ]),

      el("div", { class: "card pad" }, [
        el("div", { class: "section-title" }, [
          el("h2", { text: "Earned today" }),
          el("span", { class: "hint", text: fmt(kid.earned_today) + " of " + fmt(kid.daily_cap) })
        ]),
        el("div", { class: "bar" }, [el("span", { style: "width:" + (capUsed * 100).toFixed(0) + "%" })]),
        el("p", {
          class: "hint",
          style: "margin:10px 0 0",
          text: "Last checked " + timeAgo(kid.last_sync) +
                (kid.target_limit !== null && kid.target_limit !== undefined
                  ? " · console limit set to " + fmt(kid.target_limit) + " for today"
                  : "")
        })
      ]),

      historyCard(),
      el("div", { class: "btn-row" }, [
        el("button", {
          class: "btn ghost",
          onclick: function () { ui.screen = "home"; render(); },
          text: "‹ Back"
        })
      ])
    ]);
    return wrap;
  }

  function historyCard() {
    if (!ui.history.length) {
      return el("div", { class: "card pad empty" }, ["Nothing here yet."]);
    }
    return el("div", { class: "card pad" }, [
      el("div", { class: "section-title" }, [el("h2", { text: "Recent" })]),
      el("div", { class: "stack", style: "gap:8px" }, ui.history.slice(0, 15).map(function (e) {
        return el("div", { class: "row" }, [
          el("div", { class: "info" }, [
            el("div", { class: "line1", text: e.note || e.label }),
            el("div", { class: "line2", text: e.label + " · " + e.day + (e.pending ? " · waiting on a parent" : "") })
          ]),
          el("div", {
            class: "amount " + (e.minutes >= 0 ? "plus" : "minus"),
            text: (e.minutes > 0 ? "+" : "") + fmt(e.minutes)
          })
        ]);
      }))
    ]);
  }

  function checkIXL(kid) {
    ui.busy = true;
    render();
    api("/api/kids/" + kid.id + "/sync", { method: "POST" })
      .then(function (report) {
        if (report.new_lessons > 0) {
          toast("Nice — " + report.new_lessons + " lesson" + (report.new_lessons > 1 ? "s" : "") +
                " found, +" + fmt(report.minutes_earned));
        } else if (!report.provider_ok) {
          toast("Could not reach IXL just now. Ask a parent.", true);
        } else {
          toast("Nothing new on IXL yet.");
        }
        return refresh();
      })
      .catch(function (err) { toast(err.message, true); })
      .then(function () {
        ui.busy = false;
        if (ui.kidId) openKid(ui.kidId); else render();
      });
  }

  function askParent(kid) {
    var note = window.prompt("What did you finish?", "An IXL lesson");
    if (note === null) return;
    api("/api/kids/" + kid.id + "/claim", { method: "POST", body: { note: note } })
      .then(function () {
        toast("Sent — a parent needs to say yes.");
        return refresh();
      })
      .catch(function (err) { toast(err.message, true); });
  }

  // ---------- parent ----------
  function parentScreen() {
    if (!state.parent) {
      ui.pinOpen = true;
      return el("div", { class: "card pad empty" }, ["Parent PIN needed."]);
    }
    var pending = state.pending || [];
    return el("div", { class: "stack" }, [
      el("div", { class: "card pad" }, [
        el("div", { class: "section-title" }, [
          el("h2", { text: "Requests" }),
          el("span", { class: "hint", text: pending.length + " waiting" })
        ]),
        pending.length
          ? el("div", { class: "stack", style: "gap:8px" }, pending.map(function (e) {
              return el("div", { class: "row" }, [
                el("div", { class: "info" }, [
                  el("div", { class: "line1", text: e.kid_name + " · " + e.note }),
                  el("div", { class: "line2", text: e.day + " · worth " + fmt(e.minutes) })
                ]),
                el("div", { class: "btn-row" }, [
                  el("button", {
                    class: "btn good small",
                    onclick: function () { decide(e.id, "approve"); },
                    text: "Yes"
                  }),
                  el("button", {
                    class: "btn danger small",
                    onclick: function () { decide(e.id, "reject"); },
                    text: "No"
                  })
                ])
              ]);
            }))
          : el("div", { class: "empty" }, ["Nothing waiting."])
      ]),
      adjustCard(),
      el("div", { class: "card pad stack" }, [
        el("div", { class: "section-title" }, [el("h2", { text: "Maintenance" })]),
        el("button", {
          class: "btn",
          onclick: function () {
            toast("Syncing everyone…");
            api("/api/sync-all", { method: "POST" })
              .then(function (data) {
                var bad = (data.reports || []).filter(function (r) { return !r.ok; });
                toast(bad.length ? bad.length + " kid(s) had sync trouble" : "All synced.", bad.length > 0);
                return refresh();
              })
              .catch(function (err) { toast(err.message, true); });
          },
          text: "Sync everyone now"
        })
      ])
    ]);
  }

  function adjustCard() {
    var select, minutes, note;
    return el("div", { class: "card pad stack" }, [
      el("div", { class: "section-title" }, [el("h2", { text: "Add or take away time" })]),
      el("label", { class: "field" }, [
        "Who",
        (select = el("select", {
          style: "font:inherit;padding:11px 13px;border-radius:10px;border:1px solid var(--border-strong);background:var(--bg-elevated);color:var(--ink);width:100%"
        }, state.kids.map(function (k) {
          return el("option", { value: k.id, text: k.name });
        })))
      ]),
      el("label", { class: "field" }, [
        "Minutes (negative takes time away)",
        (minutes = el("input", { type: "number", value: "30", step: "5", min: "-360", max: "360" }))
      ]),
      el("label", { class: "field" }, [
        "Why",
        (note = el("input", { type: "text", placeholder: "e.g. finished a workbook page" }))
      ]),
      el("button", {
        class: "btn primary",
        onclick: function () {
          var value = parseInt(minutes.value, 10);
          if (!value) { toast("Enter some minutes.", true); return; }
          api("/api/kids/" + select.value + "/adjust", {
            method: "POST",
            body: { minutes: value, note: note.value || "Parent adjustment" }
          }).then(function () {
            toast("Done — " + fmt(value) + " for " + select.options[select.selectedIndex].text);
            note.value = "";
            return refresh();
          }).catch(function (err) { toast(err.message, true); });
        },
        text: "Apply"
      })
    ]);
  }

  function decide(eventId, verb) {
    api("/api/events/" + eventId + "/" + verb, { method: "POST" })
      .then(function () { return refresh(); })
      .catch(function (err) { toast(err.message, true); });
  }

  function pinModal() {
    var input = el("input", { type: "password", inputmode: "numeric", placeholder: "••••" });
    var error = el("div", { style: "color:var(--danger);font-size:.8rem;min-height:1.1em" });
    function submit() {
      api("/api/parent/unlock", { method: "POST", body: { pin: input.value } })
        .then(function () {
          ui.pinOpen = false;
          ui.screen = "parent";
          return refresh();
        })
        .catch(function () {
          error.textContent = "Wrong PIN — try again";
          input.value = "";
          input.focus();
        });
    }
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") submit(); });
    setTimeout(function () { input.focus(); }, 30);
    return el("div", {
      class: "modal-backdrop",
      onclick: function (e) {
        if (e.target === e.currentTarget) {
          ui.pinOpen = false;
          if (ui.screen === "parent") ui.screen = "home";
          render();
        }
      }
    }, [
      el("div", { class: "modal" }, [
        el("h3", { style: "margin:0 0 4px", text: "Parent PIN" }),
        el("p", { class: "hint", style: "margin:0 0 14px", text: "Needed to approve requests and change minutes." }),
        input,
        error,
        el("div", { class: "btn-row", style: "margin-top:14px;justify-content:flex-end" }, [
          el("button", {
            class: "btn ghost small",
            onclick: function () {
              ui.pinOpen = false;
              if (ui.screen === "parent") ui.screen = "home";
              render();
            },
            text: "Cancel"
          }),
          el("button", { class: "btn primary small", onclick: submit, text: "Unlock" })
        ])
      ])
    ]);
  }

  // ---------- boot ----------
  function startPolling() {
    clearInterval(timer);
    timer = setInterval(function () {
      // Pause while a modal is open so a refresh cannot yank it away mid-typing.
      if (!ui.pinOpen && !ui.busy && document.visibilityState === "visible") refresh();
    }, POLL_MS);
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") refresh();
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function () {});
    });
  }

  render();
  refresh();
  startPolling();
})();
