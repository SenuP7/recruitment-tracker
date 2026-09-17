(function () {
  if (window.lucide) window.lucide.createIcons();

  // Collapse the table of contents on narrow screens, where it sits above the text.
  var toc = document.querySelector(".doc-toc-inner");
  if (toc && window.matchMedia("(max-width: 960px)").matches) toc.removeAttribute("open");

  // Highlight the section currently being read.
  var links = document.querySelectorAll(".doc-toc a[href^='#']");
  if (!links.length || !("IntersectionObserver" in window)) return;

  var byId = {};
  links.forEach(function (link) { byId[link.getAttribute("href").slice(1)] = link; });

  var visible = {};
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) { visible[entry.target.id] = entry.isIntersecting; });
    var current = null;
    document.querySelectorAll(".prose section[id]").forEach(function (section) {
      if (!current && visible[section.id]) current = section.id;
    });
    if (!current) return;
    links.forEach(function (link) { link.removeAttribute("aria-current"); });
    if (byId[current]) byId[current].setAttribute("aria-current", "true");
  }, { rootMargin: "-90px 0px -55% 0px" });

  document.querySelectorAll(".prose section[id]").forEach(function (section) { observer.observe(section); });
})();
