(function () {
  var THEME_KEY = "candidflow-theme";
  var SIDEBAR_KEY = "candidflow-sidebar-collapsed";
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function setTheme(theme) {
    if (theme === "light") {
      document.documentElement.setAttribute("data-theme", "light");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }

  // Animates [data-countup] numbers from 0. The final value is already the
  // element's text, so without JS (or with reduced motion) nothing changes.
  function countUp(root) {
    // Background tabs pause requestAnimationFrame, which would leave a
    // half-counted (wrong) number on screen -- only animate when visible.
    if (reduceMotion || document.visibilityState !== "visible") return;
    root.querySelectorAll("[data-countup]").forEach(function (el) {
      if (el.dataset.counted) return;
      el.dataset.counted = "1";
      var original = el.textContent;
      var target = parseFloat(original.replace(/[^0-9.]/g, ""));
      if (!isFinite(target) || target === 0) return;
      var decimals = (original.split(".")[1] || "").replace(/[^0-9]/g, "").length;
      var duration = 650;
      var start = performance.now();
      var done = false;
      function finish() {
        if (done) return;
        done = true;
        el.textContent = original;
      }
      function frame(now) {
        if (done) return;
        var p = Math.min((now - start) / duration, 1);
        el.textContent = (target * (1 - Math.pow(1 - p, 3))).toFixed(decimals);
        if (p < 1) requestAnimationFrame(frame);
        else finish();
      }
      el.textContent = (0).toFixed(decimals);
      requestAnimationFrame(frame);
      // Guarantees the true value even if frames stop (tab hidden mid-count).
      setTimeout(finish, duration + 150);
    });
  }

  function enhance(root) {
    if (window.lucide) lucide.createIcons();
    countUp(root);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var themeBtn = document.getElementById("theme-toggle");
    if (themeBtn) {
      themeBtn.addEventListener("click", function () {
        var next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
        try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
        setTheme(next);
      });
    }

    var sidebarToggle = document.getElementById("sidebar-toggle");
    if (sidebarToggle) {
      sidebarToggle.addEventListener("click", function () {
        var collapsed = !document.body.classList.contains("sidebar-collapsed");
        document.body.classList.toggle("sidebar-collapsed", collapsed);
        try { localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0"); } catch (e) {}
      });
    }

    // Whole table rows navigate, except when the click lands on a real control.
    document.addEventListener("click", function (event) {
      var row = event.target.closest("tr[data-href]");
      if (row && !event.target.closest("a, button, input, select, textarea, label")) {
        if (event.metaKey || event.ctrlKey) window.open(row.dataset.href, "_blank");
        else window.location.href = row.dataset.href;
      }
      document.querySelectorAll("details.menu[open]").forEach(function (menu) {
        if (!menu.contains(event.target)) menu.removeAttribute("open");
      });
    });

    // "/" focuses search from anywhere that isn't already a text field.
    document.addEventListener("keydown", function (event) {
      if (event.key !== "/" || event.metaKey || event.ctrlKey) return;
      var tag = (event.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select" || event.target.isContentEditable) return;
      var search = document.querySelector(".topbar-search input");
      if (search) {
        event.preventDefault();
        search.focus();
      }
    });

    enhance(document);
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    enhance(event.target);
  });
})();
