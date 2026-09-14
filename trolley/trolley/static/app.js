/* Trolley — what to add to the next Tesco order.
   Vanilla on purpose: this runs on a phone on the house wi-fi, and a build
   step would be one more thing to keep working. */
(function () {
  "use strict";

  var state = { slot: null, horizon: null, suggestions: [], unsure: [], list: [], items: [], mailbox: null };
  var ui = { tab: "suggest", busy: false, paste: "", matches: null, dry: true };
  var REFRESH_MS = 120000;

  // ---------- tiny DOM helper ----------
  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
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

  function api(path, options) {
    return fetch(path, options).then(function (response) {
      if (!response.ok) {
        return response.json().then(
          function (body) { throw new Error(body.detail || response.statusText); },
          function () { throw new Error(response.statusText); }
        );
      }
      return response.status === 204 ? null : response.json();
    });
  }

  var toastTimer = null;
  function toast(message, bad) {
    var existing = document.querySelector(".toast");
    if (existing) existing.remove();
    var node = el("div", { class: bad ? "toast bad" : "toast", text: message });
    document.body.appendChild(node);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { node.remove(); }, 2800);
  }

  // ---------- formatting ----------
  function dayName(iso) {
    var d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  }

  function shortDay(iso) {
    if (!iso) return "—";
    var d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }

  function daysUntil(iso) {
    var target = new Date(iso + "T00:00:00");
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.round((target - today) / 86400000);
  }

  function relativeDays(iso) {
    if (!iso) return "";
    var days = daysUntil(iso);
    if (days === 0) return "today";
    if (days === 1) return "tomorrow";
    if (days === -1) return "yesterday";
    return days < 0 ? Math.abs(days) + " days ago" : "in " + days + " days";
  }

  /* "runs out 31 days ago" is not a sentence, so the verb follows the date. */
  function runsOut(iso) {
    if (!iso) return "";
    var days = daysUntil(iso);
    return (days < 0 ? "ran out " : "runs out ") + relativeDays(iso);
  }

  // ---------- data ----------
  function load() {
    return api("/api/suggestions").then(function (data) {
      state.slot = data.slot;
      state.horizon = data.horizon;
      state.suggestions = data.suggestions;
      state.unsure = data.unsure;
      state.list = data.list;
      render();
    }).catch(function (error) { toast(error.message, true); });
  }

  function loadMailbox() {
    return api("/api/mailbox").then(function (data) {
      state.mailbox = data;
      render();
    }).catch(function () { /* the panel is optional */ });
  }

  function loadItems() {
    return api("/api/items").then(function (data) {
      state.items = data.items;
      render();
    }).catch(function (error) { toast(error.message, true); });
  }

  function decide(itemId, action, quantity) {
    ui.busy = true;
    render();
    return api("/api/items/" + itemId + "/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: action, quantity: quantity || 1 })
    }).then(function (result) {
      toast(result.message);
      ui.busy = false;
      return load();
    }).catch(function (error) {
      ui.busy = false;
      toast(error.message, true);
      render();
    });
  }

  // ---------- views ----------
  function header() {
    if (!state.slot) return el("div", { class: "head" }, [el("h1", { text: "Trolley" })]);
    var after = state.horizon ? "Next one after that: " + dayName(state.horizon.day) : "";
    return el("div", { class: "head" }, [
      el("div", { class: "eyebrow", text: "Planning" }),
      el("h1", { text: state.slot.label }),
      el("div", { class: "sub", text: dayName(state.slot.day) + (after ? " · " + after : "") })
    ]);
  }

  function tabs() {
    var defs = [
      ["suggest", "Suggested", state.suggestions.length],
      ["list", "List", state.list.length],
      ["items", "Items", 0],
      ["import", "Import", 0]
    ];
    return el("div", { class: "tabs" }, defs.map(function (def) {
      return el("button", {
        class: ui.tab === def[0] ? "on" : "",
        onclick: function () {
          ui.tab = def[0];
          if (def[0] === "items" && !state.items.length) loadItems();
          else if (def[0] === "import" && !state.mailbox) loadMailbox();
          else render();
        }
      }, [
        el("span", { text: def[1] }),
        def[2] ? el("span", { class: "count", text: String(def[2]) }) : null
      ]);
    }));
  }

  function suggestionCard(suggestion) {
    var quantity = suggestion.quantity > 1 ? " ×" + suggestion.quantity : "";
    return el("div", { class: "card" }, [
      el("div", { class: "name" }, [
        el("span", { text: suggestion.name + quantity }),
        el("span", { class: "pill " + suggestion.status, text: suggestion.status })
      ]),
      el("div", { class: "reason", text: suggestion.reason }),
      el("div", {
        class: "meta",
        text: "Bought " + suggestion.purchases + " times, last on " + shortDay(suggestion.last_bought) +
              " · " + runsOut(suggestion.due_on)
      }),
      el("div", { class: "actions" }, [
        el("button", {
          class: "btn primary", text: "Add", disabled: ui.busy,
          onclick: function () { decide(suggestion.item_id, "add", suggestion.quantity); }
        }),
        el("button", {
          class: "btn", text: "Not now", disabled: ui.busy,
          onclick: function () { decide(suggestion.item_id, "snooze"); }
        }),
        el("button", {
          class: "btn ghost", text: "✕", title: "Stop suggesting this", disabled: ui.busy,
          onclick: function () {
            if (confirm("Stop suggesting " + suggestion.name + "?")) decide(suggestion.item_id, "pause");
          }
        })
      ])
    ]);
  }

  function suggestView() {
    var nodes = [];
    if (!state.suggestions.length) {
      nodes.push(el("div", { class: "empty" }, [
        el("strong", { text: "Nothing looks due" }),
        el("span", { text: "Everything you buy regularly should last past the next delivery." })
      ]));
    } else {
      nodes = state.suggestions.map(suggestionCard);
    }

    if (state.unsure.length) {
      nodes.push(el("div", { class: "section-title", text: "Not enough history to call" }));
      nodes.push(el("div", { class: "card tight" }, state.unsure.slice(0, 12).map(function (est) {
        return el("div", { class: "item-row" }, [
          el("div", { class: "grow" }, [
            el("div", { class: "name", text: est.name }),
            el("div", { class: "meta", text: est.purchases + " purchase(s), last " + shortDay(est.last_bought) })
          ]),
          el("button", {
            class: "btn", text: "Add", disabled: ui.busy,
            onclick: function () { decide(est.item_id, "add", 1); }
          })
        ]);
      })));
    }
    return nodes;
  }

  function listView() {
    if (!state.list.length) {
      return [el("div", { class: "empty" }, [
        el("strong", { text: "The list is empty" }),
        el("span", { text: "Add things from the Suggested tab and they collect here." })
      ])];
    }
    var rows = state.list.map(function (entry) {
      return el("div", { class: "item-row" }, [
        el("div", { class: "grow" }, [
          el("div", { class: "name", text: entry.name + (entry.quantity > 1 ? " ×" + entry.quantity : "") }),
          el("div", { class: "meta", text: entry.category })
        ]),
        el("button", {
          class: "btn ghost", text: "✕", title: "Remove", disabled: ui.busy,
          onclick: function () { decide(entry.item_id, "remove"); }
        })
      ]);
    });

    return [
      el("div", { class: "card" }, rows),
      el("div", { class: "bar" }, [
        el("button", {
          class: "btn", text: "Copy list",
          onclick: function () {
            var text = state.list.map(function (e) {
              return e.name + (e.quantity > 1 ? " x" + e.quantity : "");
            }).join("\n");
            if (navigator.clipboard) {
              navigator.clipboard.writeText(text).then(
                function () { toast("Copied " + state.list.length + " items"); },
                function () { toast("Could not copy", true); }
              );
            } else {
              toast("Clipboard not available here", true);
            }
          }
        }),
        el("button", {
          class: "btn primary", text: "I ordered these",
          onclick: function () {
            if (!confirm("Record these " + state.list.length + " items as bought?")) return;
            api("/api/list/ordered", { method: "POST" }).then(function (result) {
              toast("Recorded " + result.recorded + " purchases");
              load();
            }).catch(function (error) { toast(error.message, true); });
          }
        })
      ]),
      el("div", { class: "meta", text: "“I ordered these” records them as bought today, which is what the next suggestion is based on." })
    ];
  }

  function itemsView() {
    if (!state.items.length) {
      return [el("div", { class: "empty" }, [
        el("strong", { text: "No history yet" }),
        el("span", { text: "Import an order confirmation email, or paste one on the Import tab." })
      ])];
    }
    var sorted = state.items.slice().sort(function (a, b) {
      return (a.due_on || "9999") < (b.due_on || "9999") ? -1 : 1;
    });
    return [el("div", { class: "card" }, sorted.map(function (item) {
      return el("div", { class: "item-row" }, [
        el("div", { class: "grow" }, [
          el("div", { class: "name" }, [
            el("span", { text: item.name }),
            item.paused ? el("span", { class: "pill quiet", text: "off" }) : null
          ]),
          el("div", {
            class: "meta",
            text: (item.interval ? "every " + Math.round(item.interval) + " days" : "no pattern yet") +
                  " · " + item.purchases + " purchases · last " + shortDay(item.last_bought)
          }),
          el("div", { class: "bars" }, [
            el("i", { style: "width:" + Math.round(item.confidence * 100) + "%" })
          ])
        ]),
        el("div", { class: "when", text: item.due_on ? relativeDays(item.due_on) : "—" }),
        el("button", {
          class: "btn ghost", text: item.paused ? "↺" : "✕",
          title: item.paused ? "Suggest again" : "Stop suggesting",
          onclick: function () {
            decide(item.item_id, item.paused ? "resume" : "pause").then(loadItems);
          }
        })
      ]);
    }))];
  }

  function importView() {
    var area = el("textarea", {
      placeholder: "Paste a Tesco order confirmation email here — the whole thing, text or HTML.",
      oninput: function (event) { ui.paste = event.target.value; }
    });
    area.value = ui.paste;

    function send(dry) {
      if (ui.paste.trim().length < 10) { toast("Paste an order email first", true); return; }
      ui.busy = true; ui.dry = dry; render();
      api("/api/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: ui.paste, dry_run: dry })
      }).then(function (result) {
        ui.busy = false;
        ui.matches = result;
        toast(result.summary);
        if (!dry) { ui.paste = ""; state.items = []; load(); }
        render();
      }).catch(function (error) {
        ui.busy = false;
        toast(error.message, true);
        render();
      });
    }

    var nodes = [];
    if (state.mailbox && state.mailbox.enabled) {
      nodes.push(el("div", { class: "section-title", text: "Watching your mailbox" }));
      nodes.push(el("div", { class: "card" }, [
        el("div", { class: "name" }, [
          el("span", { text: state.mailbox.host }),
          el("span", {
            class: "pill " + (state.mailbox.last_error ? "overdue" : "soon"),
            text: state.mailbox.last_error ? "problem" : "on"
          })
        ]),
        el("div", {
          class: "reason",
          text: state.mailbox.last_error ||
                (state.mailbox.last_result || "Waiting for the first check.")
        }),
        el("div", {
          class: "meta",
          text: state.mailbox.folder + " · " + state.mailbox.search +
                " · every " + Math.round(state.mailbox.poll_seconds / 60) + " min" +
                (state.mailbox.last_run ? " · last checked " + state.mailbox.last_run.replace("T", " ") : "")
        }),
        el("div", { class: "actions" }, [
          el("button", {
            class: "btn", text: "Check now", disabled: ui.busy,
            onclick: function () {
              ui.busy = true; render();
              api("/api/mailbox/check", { method: "POST" }).then(function (result) {
                ui.busy = false;
                toast(result.summary);
                state.items = [];
                loadMailbox();
                load();
              }).catch(function (error) {
                ui.busy = false;
                toast(error.message, true);
                loadMailbox();
              });
            }
          })
        ])
      ]));
      nodes.push(el("div", { class: "section-title", text: "Or paste one in" }));
    }

    nodes.push(
      el("div", { class: "card" }, [
        area,
        el("div", { class: "bar" }, [
          el("button", { class: "btn", text: "Preview", disabled: ui.busy, onclick: function () { send(true); } }),
          el("button", { class: "btn primary", text: "Import", disabled: ui.busy, onclick: function () { send(false); } })
        ]),
        el("div", { class: "meta", text: "Preview shows what each line was matched to without saving anything." })
      ])
    );

    if (ui.matches) {
      nodes.push(el("div", { class: "section-title", text: (ui.matches.dry_run ? "Preview" : "Imported") + " · " + dayName(ui.matches.bought_on) }));
      nodes.push(el("div", { class: "card tight" }, ui.matches.matches.map(function (match) {
        return el("div", { class: "match" }, [
          el("span", { class: "raw", text: (match.quantity > 1 ? match.quantity + "× " : "") + match.raw_name }),
          el("span", { class: "to", text: "→ " + match.item }),
          el("span", { class: "how", text: match.how })
        ]);
      })));
    }
    return nodes;
  }

  function render() {
    var root = document.getElementById("app");
    root.textContent = "";
    root.appendChild(header());
    root.appendChild(tabs());
    var views = { suggest: suggestView, list: listView, items: itemsView, import: importView };
    (views[ui.tab] || suggestView)().forEach(function (node) { root.appendChild(node); });
  }

  render();
  load();
  setInterval(function () { if (ui.tab === "suggest") load(); }, REFRESH_MS);

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(function () { /* offline shell is optional */ });
  }
})();
