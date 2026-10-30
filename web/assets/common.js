"use strict";
// Shared by the leaderboard, chart and position pages: plain status wording + tooltip.
// Mirrored in tools/prerender.py (static HTML) and the browser tests.
// Each position is scored 1, 7 and 30 days after the post.
const PFPS = (() => {
  const HZ = ["1", "7", "30"];
  const day = iso => iso.slice(0, 10);
  const plus = (iso, d) => new Date(Date.parse(iso) + d * 864e5).toISOString().slice(0, 10);
  function statusLabel(p) {
    if (p.status === "resolved") return "all horizons in";
    if (p.status === "pending") return "no price yet";
    if (p.status === "no_entry") return "no price at post time";
    const open = HZ.filter(h => p.unresolved && p.unresolved[h]);
    return open.length ? open.map(h => h + "d").join(", ") + " pending" : p.status;
  }
  function statusTip(p) {
    if (p.status === "resolved") return "The 1d, 7d and 30d results after the post are all in.";
    if (p.status === "pending") return "No hourly price after the post yet; the entry fills in on the next daily refresh.";
    if (p.status === "no_entry") return "No price within the allowed delay after the post (market closed too long or a data gap), so it cannot be scored.";
    const open = HZ.filter(h => p.unresolved && p.unresolved[h]);
    return open.map(h => `The ${h}d result comes in on ${plus(p.post.posted_at, Number(h))} (${p.unresolved[h]}).`).join(" ");
  }
  // one fixed colour per author for initial avatars: no greens or reds (those mean long / short)
  const AUTHOR_COLORS = ["#2a78d6", "#eb6834", "#4a3aa7", "#d55181", "#5b6475", "#8a5a2b"];
  function authorColor(handle) {
    let h = 0;
    for (const ch of handle.toLowerCase()) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return AUTHOR_COLORS[h % AUTHOR_COLORS.length];
  }
  // file name of a position's static page (tools/prerender.py writes pos-<slug>.html)
  const slug = (id, asset) => `${id.replace(/[^A-Za-z0-9_-]/g, "-")}_${asset.replace(/[^A-Za-z0-9_-]/g, "-")}`;
  const positionUrl = (id, asset) => `pos-${slug(id, asset)}.html`;
  return { statusLabel, statusTip, day, authorColor, slug, positionUrl };
})();
