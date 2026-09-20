/* Quality-of-life layer for the app shell.
 *
 * Command palette, keyboard shortcuts, click-to-copy, table density, and a
 * recently-viewed list. All progressive: nothing here is the only way to do
 * anything, so with JavaScript off the app behaves exactly as before.
 *
 * The palette's "Go to" list is read from the sidebar rather than hardcoded,
 * which means it inherits permission gating for free -- a link the context
 * processor hid is not in the DOM, so the palette cannot offer it either.
 */
(function () {
  "use strict";

  var RECENT_KEY = "candidflow-recent";
  var DENSITY_KEY = "candidflow-density";
  var RECENT_LIMIT = 6;
  var SEARCH_URL = "/accounts/search/quick/";

  function readJSON(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      return fallback;
    }
  }

  function writeJSON(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      /* Private window, or storage disabled. The feature simply stops
         remembering; nothing else depends on it. */
    }
  }

  function isTypingTarget(el) {
    if (!el) return false;
    var tag = (el.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
  }

  /* ---- recently viewed ------------------------------------------------ */

  function rememberCurrentRecord() {
    var heading = document.querySelector(".record-header h1");
    if (!heading) return;
    var title = heading.textContent.trim();
    if (!title) return;

    var entries = readJSON(RECENT_KEY, []).filter(function (e) {
      return e && e.url !== window.location.pathname;
    });
    entries.unshift({ title: title, url: window.location.pathname });
    writeJSON(RECENT_KEY, entries.slice(0, RECENT_LIMIT));
  }

  /* ---- click to copy -------------------------------------------------- */

  function copyText(text, button) {
    function done(ok) {
      var icon = button.querySelector("i");
      button.setAttribute("data-copied", ok ? "yes" : "no");
      if (icon) icon.setAttribute("data-lucide", ok ? "check" : "x");
      if (window.lucide) lucide.createIcons({ nameAttr: "data-lucide" });
      button.setAttribute("aria-label", ok ? "Copied" : "Copy failed");
      setTimeout(function () {
        button.removeAttribute("data-copied");
        if (icon) icon.setAttribute("data-lucide", "copy");
        if (window.lucide) lucide.createIcons({ nameAttr: "data-lucide" });
        button.setAttribute("aria-label", "Copy");
      }, 1400);
    }

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
      return;
    }
    // Older browsers, and anything served over plain HTTP.
    var field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "absolute";
    field.style.left = "-9999px";
    document.body.appendChild(field);
    field.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(field);
    done(ok);
  }

  function addCopyButton(target, text) {
    if (!text || target.dataset.copyReady) return;
    target.dataset.copyReady = "1";

    var button = document.createElement("button");
    button.type = "button";
    button.className = "copy-btn";
    button.setAttribute("aria-label", "Copy");
    button.title = "Copy";
    button.innerHTML = '<i data-lucide="copy"></i>';
    button.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      copyText(text, button);
    });
    target.insertAdjacentElement("afterend", button);
  }

  function enhanceCopy(root) {
    (root || document).querySelectorAll('a[href^="mailto:"]').forEach(function (link) {
      addCopyButton(link, link.getAttribute("href").replace(/^mailto:/, "").trim());
    });
    (root || document).querySelectorAll("[data-copy]").forEach(function (el) {
      var text = el.getAttribute("data-copy") || el.textContent.trim();
      if (text && text !== "—") addCopyButton(el, text);
    });
  }

  /* ---- table density -------------------------------------------------- */

  function applyDensity(value) {
    document.body.setAttribute("data-density", value === "compact" ? "compact" : "comfortable");
    var button = document.getElementById("density-toggle");
    if (button) {
      var compact = value === "compact";
      button.setAttribute("aria-pressed", compact ? "true" : "false");
      button.title = compact ? "Comfortable rows" : "Compact rows";
      var icon = button.querySelector("i");
      if (icon) {
        icon.setAttribute("data-lucide", compact ? "rows-3" : "rows-2");
        if (window.lucide) lucide.createIcons({ nameAttr: "data-lucide" });
      }
    }
  }

  /* ---- command palette ------------------------------------------------ */

  var palette = null;
  var paletteInput = null;
  var paletteList = null;
  var activeIndex = 0;
  var currentItems = [];
  var searchTimer = null;

  function navTargets() {
    var seen = {};
    var items = [];
    document.querySelectorAll(".sidebar a[href]").forEach(function (link) {
      var href = link.getAttribute("href");
      var label = link.textContent.trim();
      if (!href || href === "#" || !label || seen[href]) return;
      seen[href] = true;
      items.push({ kind: "Go to", icon: "corner-down-right", label: label, detail: "", url: href });
    });
    return items;
  }

  function buildPalette() {
    palette = document.createElement("div");
    palette.className = "palette";
    palette.setAttribute("hidden", "");
    palette.innerHTML =
      '<div class="palette-backdrop" data-palette-close></div>' +
      '<div class="palette-panel" role="dialog" aria-modal="true" aria-label="Command palette">' +
      '  <div class="palette-search">' +
      '    <i data-lucide="search"></i>' +
      '    <input type="text" autocomplete="off" spellcheck="false" placeholder="Search candidates, applications and roles…" aria-label="Search">' +
      '    <kbd>Esc</kbd>' +
      "  </div>" +
      '  <div class="palette-results" role="listbox"></div>' +
      '  <div class="palette-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>?</kbd> shortcuts</span></div>' +
      "</div>";
    document.body.appendChild(palette);

    paletteInput = palette.querySelector("input");
    paletteList = palette.querySelector(".palette-results");

    palette.addEventListener("click", function (event) {
      if (event.target.hasAttribute("data-palette-close")) closePalette();
    });
    paletteInput.addEventListener("input", function () {
      clearTimeout(searchTimer);
      var query = paletteInput.value.trim();
      if (!query) return renderDefault();
      searchTimer = setTimeout(function () { runSearch(query); }, 160);
    });
    paletteInput.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") { event.preventDefault(); move(1); }
      else if (event.key === "ArrowUp") { event.preventDefault(); move(-1); }
      else if (event.key === "Enter") {
        event.preventDefault();
        var item = currentItems[activeIndex];
        if (item) window.location.href = item.url;
      } else if (event.key === "Escape") {
        event.preventDefault();
        closePalette();
      }
    });
  }

  function renderItems(items, emptyMessage) {
    currentItems = items;
    activeIndex = 0;
    if (!items.length) {
      paletteList.innerHTML = '<p class="palette-empty">' + emptyMessage + "</p>";
      return;
    }
    paletteList.innerHTML = items
      .map(function (item, index) {
        return (
          '<a class="palette-item" role="option" href="' + item.url + '" data-index="' + index + '"' +
          (index === 0 ? ' data-active="1" aria-selected="true"' : "") + ">" +
          '<i data-lucide="' + (item.icon || "circle") + '"></i>' +
          '<span class="palette-label">' + item.label + "</span>" +
          (item.detail ? '<span class="palette-detail">' + item.detail + "</span>" : "") +
          '<span class="palette-kind">' + item.kind + "</span>" +
          "</a>"
        );
      })
      .join("");
    if (window.lucide) lucide.createIcons({ nameAttr: "data-lucide" });
    paletteList.querySelectorAll(".palette-item").forEach(function (el) {
      el.addEventListener("mouseenter", function () { setActive(Number(el.dataset.index)); });
    });
  }

  function setActive(index) {
    activeIndex = index;
    paletteList.querySelectorAll(".palette-item").forEach(function (el, i) {
      if (i === index) { el.setAttribute("data-active", "1"); el.setAttribute("aria-selected", "true"); }
      else { el.removeAttribute("data-active"); el.setAttribute("aria-selected", "false"); }
    });
  }

  function move(delta) {
    if (!currentItems.length) return;
    var next = (activeIndex + delta + currentItems.length) % currentItems.length;
    setActive(next);
    var el = paletteList.querySelector('[data-index="' + next + '"]');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
  }

  function renderDefault() {
    var recent = readJSON(RECENT_KEY, []).map(function (e) {
      return { kind: "Recent", icon: "clock", label: e.title, detail: "", url: e.url };
    });
    renderItems(recent.concat(navTargets()), "Start typing to search.");
  }

  function runSearch(query) {
    paletteList.setAttribute("data-loading", "1");
    fetch(SEARCH_URL + "?q=" + encodeURIComponent(query), {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    })
      .then(function (response) { return response.ok ? response.json() : { results: [] }; })
      .then(function (data) {
        paletteList.removeAttribute("data-loading");
        if (paletteInput.value.trim() !== query) return; // a newer keystroke won
        renderItems(data.results || [], "Nothing matched “" + query + "”.");
      })
      .catch(function () {
        paletteList.removeAttribute("data-loading");
        renderItems([], "Search is unavailable right now.");
      });
  }

  function openPalette() {
    if (!palette) buildPalette();
    palette.removeAttribute("hidden");
    document.body.classList.add("palette-open");
    paletteInput.value = "";
    renderDefault();
    if (window.lucide) lucide.createIcons({ nameAttr: "data-lucide" });
    paletteInput.focus();
  }

  function closePalette() {
    if (!palette) return;
    palette.setAttribute("hidden", "");
    document.body.classList.remove("palette-open");
  }

  /* ---- shortcuts overlay ---------------------------------------------- */

  var SHORTCUTS = [
    ["Ctrl K", "Open the command palette"],
    ["/", "Focus the search box"],
    ["g then d", "Dashboard"],
    ["g then c", "Candidates"],
    ["g then a", "Applications"],
    ["g then i", "Interviews"],
    ["g then p", "Positions"],
    ["?", "Show this list"],
    ["Esc", "Close whatever is open"],
  ];

  var helpPanel = null;

  function toggleHelp() {
    if (!helpPanel) {
      helpPanel = document.createElement("div");
      helpPanel.className = "palette";
      helpPanel.innerHTML =
        '<div class="palette-backdrop" data-palette-close></div>' +
        '<div class="palette-panel shortcuts-panel" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts">' +
        '  <div class="palette-search"><i data-lucide="keyboard"></i><strong>Keyboard shortcuts</strong><kbd>Esc</kbd></div>' +
        '  <dl class="shortcut-list">' +
        SHORTCUTS.map(function (s) {
          return "<div><dt>" + s[0].split(" ").map(function (k) { return "<kbd>" + k + "</kbd>"; }).join(" ") + "</dt><dd>" + s[1] + "</dd></div>";
        }).join("") +
        "  </dl>" +
        "</div>";
      document.body.appendChild(helpPanel);
      helpPanel.addEventListener("click", function (event) {
        if (event.target.hasAttribute("data-palette-close")) helpPanel.setAttribute("hidden", "");
      });
      if (window.lucide) lucide.createIcons({ nameAttr: "data-lucide" });
      return;
    }
    if (helpPanel.hasAttribute("hidden")) helpPanel.removeAttribute("hidden");
    else helpPanel.setAttribute("hidden", "");
  }

  /* ---- "g then x" jumps ----------------------------------------------- */

  var GO_TARGETS = { d: "/dashboard/", c: "/candidates/", a: "/candidates/applications/", i: "/interviews/", p: "/positions/" };
  var goArmed = false;
  var goTimer = null;

  /* ---- wiring --------------------------------------------------------- */

  document.addEventListener("DOMContentLoaded", function () {
    applyDensity(readJSON(DENSITY_KEY, "comfortable"));
    rememberCurrentRecord();
    enhanceCopy(document);

    var densityBtn = document.getElementById("density-toggle");
    if (densityBtn) {
      densityBtn.addEventListener("click", function () {
        var next = document.body.getAttribute("data-density") === "compact" ? "comfortable" : "compact";
        writeJSON(DENSITY_KEY, next);
        applyDensity(next);
      });
    }

    var paletteBtn = document.getElementById("palette-open");
    if (paletteBtn) paletteBtn.addEventListener("click", openPalette);
  });

  document.addEventListener("keydown", function (event) {
    var typing = isTypingTarget(event.target);

    if ((event.ctrlKey || event.metaKey) && (event.key === "k" || event.key === "K")) {
      event.preventDefault();
      openPalette();
      return;
    }

    if (event.key === "Escape") {
      closePalette();
      if (helpPanel) helpPanel.setAttribute("hidden", "");
      return;
    }

    if (typing || event.ctrlKey || event.metaKey || event.altKey) return;

    if (event.key === "?") {
      event.preventDefault();
      toggleHelp();
      return;
    }

    if (goArmed && GO_TARGETS[event.key]) {
      event.preventDefault();
      goArmed = false;
      clearTimeout(goTimer);
      window.location.href = GO_TARGETS[event.key];
      return;
    }

    if (event.key === "g") {
      goArmed = true;
      clearTimeout(goTimer);
      // A lone "g" shouldn't arm the next keystroke forever.
      goTimer = setTimeout(function () { goArmed = false; }, 1200);
    } else {
      goArmed = false;
    }
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    enhanceCopy(event.target);
  });
})();
