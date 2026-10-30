// Frame busting: a meta CSP cannot set frame-ancestors, so a page shown inside someone else's
// frame tries to take over the top window, and hides itself when the frame blocks that.
(function () {
  "use strict";
  if (window.top === window.self) return;
  document.documentElement.setAttribute("data-framed", "1");
  try { window.top.location.replace(window.self.location.href); } catch (e) { /* sandboxed frame: stay hidden */ }
})();
