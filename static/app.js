// Dynasty Trade Helper UI — plain JS, hash routing, no build step.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = n => (n == null || isNaN(n) ? "–" : Math.round(n).toLocaleString());
const pct = (n, d = 1) => (n == null ? "–" : `${n > 0 ? "+" : ""}${Number(n).toFixed(d)}%`);
const signCls = n => (n > 0.5 ? "delta-pos" : n < -0.5 ? "delta-neg" : "");
const SRC = { fantasycalc: "FC", ktc: "KTC", dynastyprocess: "DP" };
const WINDOW_LABEL = { contend: "Contender", middle: "Middle", rebuild: "Rebuilder" };

// Record uncaught errors on <body data-js-error> so smoke tests (and you) can spot them.
window.addEventListener("error", e => { document.body.dataset.jsError = e.message; });
window.addEventListener("unhandledrejection", e => { document.body.dataset.jsError = String(e.reason && e.reason.message || e.reason); });

const state = { ov: null, trade: { a: null, b: null, aGives: [], bGives: [] }, teamCache: {}, cache: {} };

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2200);
}
async function overview(force) {
  if (!state.ov || force) state.ov = await api("/api/overview");
  return state.ov;
}
async function teamData(rid, force) {
  if (!state.teamCache[rid] || force) state.teamCache[rid] = await api(`/api/team/${rid}`);
  return state.teamCache[rid];
}
function invalidate() {
  state.ov = null; state.teamCache = {}; state.draftsData = null; state.waiversData = null; state.rankingsData = null;
  state.pickupsData = null; state.breakoutsData = null; state.reviewData = null; state.recordsData = null; state.backtestData = null; state.seasonData = null; state.draftPrepData = null;
  state.cache = {};
}

// ---------------------------------------------------------------- help tooltips
// Any element with data-tip shows an explanation on hover and on keyboard focus.
const tipAttr = (text, focusable = true) => `data-tip="${esc(text)}"${focusable ? ' tabindex="0"' : ""}`;
const hint = (labelHtml, text) => `<span class="has-tip" ${tipAttr(text)}>${labelHtml}</span>`;
(function initHelpTips() {
  const el = document.createElement("div");
  el.className = "help-tip"; el.setAttribute("role", "tooltip"); el.hidden = true;
  document.body.append(el);
  let cur = null;
  const show = t => {
    cur = t; el.textContent = t.dataset.tip; el.hidden = false;
    const r = t.getBoundingClientRect(), w = el.offsetWidth, h = el.offsetHeight;
    const left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    const top = r.bottom + 8 + h > window.innerHeight ? r.top - h - 8 : r.bottom + 8;
    el.style.left = left + "px"; el.style.top = top + "px";
  };
  const hide = () => { cur = null; el.hidden = true; };
  document.addEventListener("pointerover", e => { const t = e.target.closest("[data-tip]"); if (t && t !== cur) show(t); });
  document.addEventListener("pointerout", e => { const t = e.target.closest("[data-tip]"); if (t && !t.contains(e.relatedTarget)) hide(); });
  document.addEventListener("focusin", e => { const t = e.target.closest("[data-tip]"); if (t) show(t); });
  document.addEventListener("focusout", hide);
  document.addEventListener("keydown", e => { if (e.key === "Escape") hide(); });
  window.addEventListener("scroll", hide, { passive: true });
})();

const WINDOW_HELP = {
  contend: "Contender (contend score 60+): a strong starting lineup and/or record. Values production now over the future.",
  middle: "Middle (contend score 41–59): not clearly contending or rebuilding.",
  rebuild: "Rebuilder (contend score 40 or less): values youth and draft picks over current production.",
};
const TAG_HELP = {
  "Very active": "Averages 5+ trades per season.",
  "Rarely trades": "Averages 1.5 or fewer trades per season. Expect to work harder to get a deal done.",
  "Consolidator": "Usually gets back fewer, better pieces than they send. Offer one strong player for several of theirs.",
  "Depth seeker": "Usually takes back more pieces than they send. Will split a stud into several assets.",
  "Pick buyer": "Net acquirer of rookie draft picks in trades. Picks are good currency with them.",
  "Pick seller": "Net seller of rookie draft picks in trades. Ask for their picks.",
  "Buys youth": "The players they acquire are younger (value-weighted) than the ones they give up.",
  "Buys veterans": "The players they acquire are older than the ones they give up: a win-now mindset.",
  "Shark": "Has come out ahead by 8%+ per trade on average. Judged at today's values, so includes hindsight.",
  "Generous": "Has given up 8%+ more value than they got per trade on average. Judged at today's values, so includes hindsight. Room to ask for more.",
  "No trade history": "Hasn't made a trade yet, so tendencies can't be estimated.",
};
const tagHelp = t => TAG_HELP[t] || (t.startsWith("Targets ") ? `Has added ${t.slice(8)} value through trades. Players at that position are good currency with them.` : "");
const NEED_HELP = {
  "Big need": "1+ standard deviations below the league average at this position.",
  "Need": "0.5–1 standard deviations below the league average.",
  "Avg": "Within half a standard deviation of the league average.",
  "Solid": "0.5–1 standard deviations above the league average.",
  "Strength": "1+ standard deviations above the league average.",
};

const HELP = {
  contend: "0–100. Blends starting-lineup strength (win-now values), record and points scored (record counts more as the season goes on), plus trade behavior. 60+ = contender, 40 or less = rebuilder.",
  window: "Each team's competitive window, based on its contend score. Hover a badge for details. You can override any team's window on its Teams page.",
  winnow: "Where your best possible starting lineup ranks by win-now (redraft) value. 1 = strongest lineup in the league.",
  winnowTotal: "Total win-now (redraft) value of the team's best possible starting lineup. Higher = stronger this season.",
  dynasty: "Where the total dynasty value of your rostered players ranks (draft picks not included). 1 = most valuable roster.",
  dynastyTotal: "Total blended dynasty value of every rostered player (0–10,000 scale per player), draft picks not included.",
  picks: "Where the total value of the rookie picks you own for the next 3 drafts ranks. 1 = most pick capital.",
  pickTotal: "Total value of the rookie draft picks the team owns for the next 3 drafts.",
  age: "Average roster age weighted by dynasty value, so stars count more than bench players. Lower = younger core.",
  needs: "Positions where the team is clearly below league average: starters for contenders, long-term value for rebuilders. Good targets for selling to them.",
  tendencies: "Habits detected from this manager's trade history. Hover a tag for details. With only a few trades, these are applied lightly.",
  sell: "Players worth 1,000+ who are within 6 months of their position's age cliff (QB 32, RB 26, WR 28, TE 29), or whose win-now value is 25%+ above their dynasty value. Contenders pay the most for them now.",
  outlook: "How your roster compares with the league at each position, as a z-score: 0 = league average, ±1 = one standard deviation.",
  now: "Starters' win-now value at this position vs. the rest of the league.",
  future: "Dynasty value of your top players at this position vs. the rest of the league.",
  depth: "Value of backups beyond the starters. Surplus = spare trade chips; Thin = one injury from a hole.",
  market: "How the deal looks on trade calculators: the blended market value you get vs. give, with a premium for the single best piece. Positive = you get more.",
  teamValue: "How the deal looks for your team specifically: values adjusted for your window (rebuilders favor youth and picks) and your positional needs, minus anyone you'd have to cut.",
  fit: "0–100. Combines how opposite your windows are (contender vs. rebuilder trade best), the quality of the best package found, and how often they trade.",
  // waivers
  pickups: "Players added from waivers or free agency. Each add counts once, even if the same player is added again later.",
  faab: "Total free-agent budget ($) spent on winning waiver claims.",
  hits: "Pickups that are now worth 1,000+, or were traded away while worth 1,000+. In other words, they became real dynasty assets.",
  atPickup: "Dynasty value of the players on the day they were picked up. 0 = not yet on DynastyProcess's ranked list.",
  captured: "What the pickups are worth to the team today: current value if still rostered, value on the trade date if flipped in a trade, 0 if dropped.",
  startPts: "Fantasy points these players scored in this team's starting lineup while it held them. The in-season payoff that dynasty values miss.",
  stillRostered: "Pickups the team still holds today.",
  peak: "Highest weekly value while this team held him.",
  // franchise
  franchise: "Overall team state. The total value of every rostered player plus every rookie pick the team owns (next 3 drafts), relative to the league average. 100 = average; 120 = 20% more total assets than average.",
  franchiseValue: "Total dynasty value of all rostered players plus all owned rookie picks, on the same 0–10,000-per-asset scale.",
  core: "Value of the team's 10 most valuable players: the part of the roster that wins games and anchors trades.",
  depthValue: "Value of every rostered player outside the top 10.",
  pickValue: "Value of the rookie picks the team owns for the next 3 drafts (next year's picks are tiered early/mid/late by projected finish).",
  leagueMap: "Each team's starting-lineup strength this season (across) against its total franchise value (up). The lines mark league averages and split teams into four situations.",
  heat: "Each team's strength at each position vs. the league, in standard deviations. Blue = above average, red = below. 'Now' uses starters' win-now value; 'Long-term' uses dynasty value of the top players.",
};

// ---------------------------------------------------------------- components
const windowBadge = (w, src) => `<span class="badge w-${w}" ${tipAttr(WINDOW_HELP[w] + (src === "you" ? " ✎ = set by you, not auto-detected." : " Auto-detected; change it on the team's page."))}>${WINDOW_LABEL[w] || w}${src === "you" ? " ✎" : ""}</span>`;
const posBadge = p => `<span class="pos pos-${esc(p)}">${esc(p)}</span>`;
const tags = ts => (ts || []).map(t => `<span class="badge tag" ${tipAttr(tagHelp(t))}>${esc(t)}</span>`).join("");
const accBadge = s => `<span class="badge acc-${s.acceptance_label}" ${tipAttr(`Model estimate of how likely they are to accept, 0–100: their team-context gain (with their trade tendencies) blended 50/50 with market value. 60+ Likely, 35–59 Possible, under 35 Unlikely. Calibrated on real completed trades: a fair deal is about a coin flip.`)}>${s.acceptance_label} (${s.acceptance})</span>`;

function assetMeta(a) {
  if (a.kind === "pick") return a.tier ? `${a.tier} projected` : "";
  const bits = [];
  if (a.age != null) bits.push(`${a.age}y`);
  if (a.nfl_team) bits.push(a.nfl_team);
  if (a.injury) bits.push(`<span class="delta-neg">${esc(a.injury)}</span>`);
  if (a.taxi) bits.push("taxi");
  return bits.join(" · ");
}
function assetLine(a, opts = {}) {
  const notes = opts.notes && a.notes && a.notes.length ? `<ul class="notes">${a.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : "";
  return `<div class="asset ${opts.cls || ""}" data-kind="${a.kind}" data-id="${esc(a.id)}">
    ${posBadge(a.pos)}
    <div class="name">${esc(a.name)} <span class="muted small">${assetMeta(a)}</span>${notes}</div>
    <span class="val" ${tipAttr(sourceTitle(a), false)}>${fmt(a.value)}</span>
  </div>`;
}
function sourceTitle(a) {
  const parts = Object.entries(a.sources || {}).map(([k, v]) => `${SRC[k]} ${fmt(v)}`);
  if (a.redraft) parts.push(`win-now ${fmt(a.redraft)}`);
  if (a.override != null) parts.push(`override applied`);
  return `Blended dynasty value (0–10,000 scale). ${parts.join(" · ")}`;
}
function centerBar(p, max = 30) {
  const v = Math.max(-max, Math.min(max, p)) / max * 50;
  const color = p >= 0 ? "var(--good)" : "var(--bad)";
  const style = v >= 0 ? `left:50%;width:${v}%` : `left:${50 + v}%;width:${-v}%`;
  return `<div class="center-bar"><span style="${style};background:${color}"></span></div>`;
}
function needCell(z) {
  const cls = z >= 0.5 ? "pos-bad" : z <= -0.5 ? "pos-good" : "";
  const label = z >= 1 ? "Big need" : z >= 0.5 ? "Need" : z <= -1 ? "Strength" : z <= -0.5 ? "Solid" : "Avg";
  // z is a need score: positive = below league average at this position.
  const exact = Math.abs(z) < 0.05 ? "right at the league average" : `${Math.abs(z).toFixed(2)} standard deviations ${z > 0 ? "below" : "above"} the league average`;
  return `<span class="${cls}" ${tipAttr(`${label}: ${NEED_HELP[label]} This team is ${exact}.`, false)}>${label}</span>`;
}

// ---------------------------------------------------------------- views
async function viewDashboard() {
  const ov = await overview();
  const me = ov.teams.find(t => t.is_me);
  const meT = me ? await teamData(me.roster_id) : null;
  const rank = (key) => me ? [...ov.teams].sort((a, b) => b[key] - a[key]).findIndex(t => t.is_me) + 1 : "–";
  const sells = meT ? meT.players.filter(p => meT.sell_candidates.includes(p.id)) : [];
  const errs = Object.entries(ov.source_errors || {});
  if (me) setTimeout(() => { dashFeed(); dashOpportunity(me.roster_id); }, 0);
  return `
    ${errs.length ? `<div class="warnbox">Some value sources failed and were skipped: ${errs.map(([k, v]) => `${k} (${esc(v)})`).join("; ")}</div>` : ""}
    ${me ? `<div class="card" id="dash-feed"><h2>Since your last visit</h2><p class="muted">Checking for changes…</p></div>` : ""}
    ${me ? `<div class="card">
      <div class="row spread">
        <div><h1>${esc(me.manager)} ${windowBadge(me.window, me.window_source)}</h1>
          <div class="muted">${ov.league.season} · ${me.wins}-${me.losses}${me.ties ? "-" + me.ties : ""} · ${fmt(me.fpts)} pts for · <a href="#/season">playoff odds</a> · <a href="#/team/${me.roster_id}">your team</a></div></div>
        <div class="row">
          <div class="stat"><div class="k">${hint("Franchise score", HELP.franchise)}</div><div class="v">${me.franchise_score}</div><div class="muted small">#${me.franchise_rank} of ${ov.teams.length} · <a href="#/rankings">rankings</a></div></div>
          <div class="stat"><div class="k">${hint("Contend score", HELP.contend)}</div><div class="v">${me.contend_score}</div></div>
          <div class="stat"><div class="k">${hint("Win-now rank", HELP.winnow)}</div><div class="v">${rank("starter_redraft")}/${ov.teams.length}</div></div>
          <div class="stat"><div class="k">${hint("Dynasty rank", HELP.dynasty)}</div><div class="v">${rank("dynasty_total")}/${ov.teams.length}</div></div>
          <div class="stat"><div class="k">${hint("Pick capital rank", HELP.picks)}</div><div class="v">${rank("pick_total")}/${ov.teams.length}</div></div>
          <div class="stat"><div class="k">${hint("Roster age (value-wtd)", HELP.age)}</div><div class="v">${me.avg_age_weighted}</div></div>
        </div>
      </div>
      <div class="grid g2" style="margin-top:10px">
        <div>
          <h3>${hint("Sell candidates", HELP.sell)} (aging or producing above their dynasty price)</h3>
          <p class="small"><a href="#/deadline">Deadline sell list →</a> · <a href="#/future">Your rebuild timeline →</a> · <a href="#/calendar">Your calendar →</a></p>
          ${sells.length ? sells.map(a => assetLine(a, { notes: true })).join("") : `<p class="muted">None flagged.</p>`}
        </div>
        <div>
          <h3>${hint("Positional outlook", HELP.outlook)}</h3>
          ${posTable(meT)}
          <p class="muted small">Now = starters' win-now value vs. league. Future = dynasty value of your top players at each position.</p>
          <p><a href="#/partners">Find trades →</a></p>
        </div>
      </div>
    </div>` : `<div class="warnbox">Couldn't find "${esc(ov.config.username)}" in this league. Check Settings.</div>`}
    ${me ? `<div class="card" id="dash-opp"><h2>Free agents &amp; breakout targets</h2><p class="muted">Loading…</p></div>` : ""}
    <div class="card">
      <div class="row spread"><h2>League landscape</h2><a class="small" href="#/rankings">Rankings →</a></div>
      <div class="scroll"><table>
        <thead><tr><th>Team</th><th>${hint("Window", HELP.window)}</th><th class="num">${hint("Contend", HELP.contend)}</th>
          <th class="num">${hint("Franchise", HELP.franchise)}</th><th>Record</th>
          <th class="num">${hint("Win-now", HELP.winnowTotal)}</th><th class="num">${hint("Dynasty", HELP.dynastyTotal)}</th>
          <th class="num">${hint("Picks", HELP.pickTotal)}</th><th class="num">${hint("Age", HELP.age)}</th>
          <th>${hint("Needs", HELP.needs)}</th><th>${hint("Trade tendencies", HELP.tendencies)}</th></tr></thead>
        <tbody>${ov.teams.map(t => `<tr class="click ${t.is_me ? "me" : ""}" onclick="location.hash='#/team/${t.roster_id}'">
          <td><b>${esc(t.manager)}</b><div class="muted small">${esc(t.team_name)}</div></td>
          <td data-sort="${t.contend_score}">${windowBadge(t.window, t.window_source)}</td>
          <td class="num">${t.contend_score}</td>
          <td class="num">${t.franchise_score}</td>
          <td data-sort="${t.wins + 0.5 * t.ties - t.losses / 100}">${t.wins}-${t.losses}</td>
          <td class="num">${fmt(t.starter_redraft)}</td>
          <td class="num">${fmt(t.dynasty_total)}</td>
          <td class="num">${fmt(t.pick_total)}</td>
          <td class="num">${t.avg_age_weighted}</td>
          <td>${t.needs.map(p => `<span class="pos pos-${p}">${p}</span>`).join(" ") || '<span class="muted">–</span>'}</td>
          <td>${tags(t.tags)}</td></tr>`).join("")}</tbody>
      </table></div>
      <p class="muted small">Contend score blends starting-lineup strength (win-now values), record and points scored, plus trade behavior. Values are on a 0–10,000 blended scale.</p>
    </div>`;
}

const FEED_GROUPS = [["injury", "Injuries on your roster"], ["value", "Value moves on your roster"], ["trade", "Trades"],
  ["available", "Newly available"], ["breakout", "New breakout flags"], ["move", "Notable adds elsewhere"]];
async function dashFeed() {
  const host = $("#dash-feed");
  let F;
  try { F = await api("/api/feed"); } catch (e) { if (host) host.innerHTML = `<h2>Since your last visit</h2><div class="warnbox">${esc(e.message)}</div>`; return; }
  if (!$("#dash-feed")) return;
  const head = `<div class="row spread"><h2>Since your last visit${F.since ? ` <span class="muted small">(${esc(F.since.replace("T", " "))})</span>` : ""}</h2>
    ${!F.baseline ? `<button id="feed-seen">Mark all as seen</button>` : ""}</div>`;
  let body;
  if (F.baseline) body = `<p class="muted">Saved a starting point. From now on, changes show up here: value moves and injuries on your roster, trades, newly available players and new breakout flags.</p>`;
  else if (!F.items.length) body = `<p class="muted">Nothing notable has changed.</p>`;
  else body = `<div class="grid g3">${FEED_GROUPS.map(([k, label]) => {
      const xs = F.items.filter(x => x.kind === k);
      if (!xs.length) return "";
      return `<div><h3>${label} <span class="muted small">${xs.length}</span></h3><ul class="feed">${xs.slice(0, 8).map(x => `<li class="${x.mine ? "mine" : ""}">
        ${x.pos ? posBadge(x.pos) + " " : ""}${x.name ? `<b>${esc(x.name)}</b> ` : ""}<span class="${x.delta > 0 ? "delta-pos" : x.delta < 0 ? "delta-neg" : "muted"}">${x.date ? esc(x.date) + " · " : ""}${esc(x.text)}</span></li>`).join("")}
        ${xs.length > 8 ? `<li class="muted">+${xs.length - 8} more</li>` : ""}</ul></div>`;
    }).join("")}</div>`;
  host.innerHTML = head + body;
  const btn = $("#feed-seen");
  if (btn) btn.onclick = async () => { btn.disabled = true; await api("/api/feed/seen", { method: "POST" }); dashFeed(); toast("Marked as seen"); };
}

// Header: when the data was last rebuilt, and a prompt when the server has newer data.
(function watchUpdates() {
  let seen = null;
  const ago = s => { const m = Math.round((Date.now() / 1000 - s) / 60); return m < 1 ? "just now" : m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`; };
  async function tick() {
    try {
      const s = await api("/api/status");
      const el = $("#updated");
      if (!el || !s.built) return;
      if (seen === null) seen = s.built;
      el.innerHTML = s.built > seen
        ? `· <button class="chip on" id="new-data">New data · refresh</button>`
        : `· updated ${ago(s.built)}`;
      const b = $("#new-data");
      if (b) b.onclick = () => { seen = s.built; invalidate(); route(); tick(); };
    } catch {}
  }
  tick();
  setInterval(tick, 60000);
})();

async function dashOpportunity(me) {
  const host = $("#dash-opp");
  let W, B;
  try { [W, B] = await Promise.all([pickupsData(), breakoutsData()]); }
  catch (e) { if (host) host.innerHTML = `<h2>Free agents &amp; breakout targets</h2><div class="warnbox">${esc(e.message)}</div>`; return; }
  if (!$("#dash-opp")) return;
  const targets = B.players.filter(r => r.owner_rid != null && r.owner_rid !== me && r.value < 4000).slice(0, 4);
  const line = (a, right) => `<div class="asset">${posBadge(a.pos)}<div class="name">${esc(a.name)} <span class="muted small">${assetMeta(a)}</span>
    <div>${sigChips(a)}</div></div><span class="val small">${right}</span></div>`;
  $("#dash-opp").innerHTML = `<h2>Free agents &amp; breakout targets</h2><div class="grid g2">
    <div><h3>${hint("Best adds for you", HELP.pickupScore)}</h3>
      ${W.suggestions.slice(0, 4).map(s => line(s.asset, `${hint("score", HELP.pickupScore)} ${fmt(s.score)}<br><span class="muted">bid ~$${s.bid.mid}</span>`)).join("") || '<p class="muted">Nobody beats your weakest player right now.</p>'}
      <p><a href="#/pickups">All free agents →</a></p></div>
    <div><h3>${hint("Buy before the breakout", "Players on other rosters (worth under 4,000) with the highest breakout scores.")}</h3>
      ${targets.map(r => line(r, `${hint("breakout", HELP.breakout)} ${r.breakout}<br><span class="muted">${esc(r.owner)}</span>`)).join("") || '<p class="muted">None flagged.</p>'}
      <p><a href="#/breakouts">All breakouts →</a></p></div>
  </div>`;
}

function posTable(t) {
  if (!t) return "";
  return `<table data-nosort><thead><tr><th>Pos</th><th>${hint("Now", HELP.now)}</th><th>${hint("Future", HELP.future)}</th><th>${hint("Depth", HELP.depth)}</th></tr></thead><tbody>
    ${["QB", "RB", "WR", "TE"].map(p => `<tr><td>${posBadge(p)}</td><td>${needCell(t.need_now[p])}</td><td>${needCell(t.need_future[p])}</td>
      <td>${t.depth_z[p] >= 0.8 ? '<span class="pos-good">Surplus</span>' : t.depth_z[p] <= -0.8 ? '<span class="pos-bad">Thin</span>' : '<span class="muted">Avg</span>'}</td></tr>`).join("")}
  </tbody></table>`;
}

function suggestionCard(s, partnerRid) {
  const me = s.eval.sides[0], them = s.eval.sides[1];
  return `<div class="sugg">
    <div class="sides">
      <div><div class="side-h">You give</div>${s.give.map(a => assetLine(a)).join("")}</div>
      <div><div class="side-h">You get</div>${s.get.map(a => assetLine(a)).join("")}</div>
    </div>
    <div class="row spread small" style="margin-top:6px">
      <span>${hint("Market", HELP.market)}: <b class="${signCls(s.eval.market.pct)}">${pct(s.eval.market.pct)}</b> for you</span>
      <span>${hint("Your team value", HELP.teamValue)}: <b class="${signCls(me.gain_pct)}">${pct(me.gain_pct)}</b></span>
      <span>Their acceptance: ${accBadge(them)}</span>
      <button onclick='openInEvaluator(${JSON.stringify({ b: partnerRid, aGives: s.give.map(a => ({ kind: a.kind, id: a.id })), bGives: s.get.map(a => ({ kind: a.kind, id: a.id })) })})'>Open in evaluator</button>
    </div>
    ${s.why.length || them.acceptance_reasons.length ? `<ul class="notes">${[...s.why, ...them.acceptance_reasons].map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
  </div>`;
}

async function viewPartners() {
  const [ov, partners] = await Promise.all([overview(), api("/api/suggestions")]);
  const me = ov.teams.find(t => t.is_me);
  return `<div class="card"><h1>Find trades</h1>
    <p class="muted">You're set as a <b>${WINDOW_LABEL[me.window]}</b>. Suggestions look for value arbitrage: assets worth more to them than to you
      (e.g. aging producers to contenders) for assets worth more to you (youth, picks). They're tuned by each manager's trade history.
      Acceptance is a model estimate, not a guarantee.</p></div>
    ${partners.map((p, i) => `<div class="card">
      <div class="row spread">
        <div><h2>${i + 1}. <a href="#/team/${p.roster_id}">${esc(p.manager)}</a> ${windowBadge(p.window)} <span class="muted small">contend ${p.contend_score}</span></h2></div>
        <div class="stat"><div class="k">${hint("Partner fit", HELP.fit)}</div><div class="v">${p.fit}</div></div>
      </div>
      <ul class="notes">${p.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>
      ${p.suggestions.length ? p.suggestions.map(s => suggestionCard(s, p.roster_id)).join("") : `<p class="muted">No packages found that help you and that they'd plausibly accept.</p>`}
    </div>`).join("")}`;
}

// ---------------------------------------------------------------- evaluator
function openInEvaluator(x) {
  state.trade = { a: state.ov.me, b: x.b, aGives: x.aGives, bGives: x.bGives };
  location.hash = "#/trade";
}
window.openInEvaluator = openInEvaluator;

async function viewTrade() {
  const ov = await overview();
  const tr = state.trade;
  if (tr.a == null) tr.a = ov.me ?? ov.teams[0].roster_id;
  if (tr.b == null || tr.b === tr.a) tr.b = ov.teams.find(t => t.roster_id !== tr.a).roster_id;
  const [ta, tb] = await Promise.all([teamData(tr.a), teamData(tr.b)]);
  const opts = sel => ov.teams.map(t => `<option value="${t.roster_id}" ${t.roster_id === sel ? "selected" : ""}>${esc(t.manager)}${t.is_me ? " (you)" : ""}</option>`).join("");
  const picker = (t, side) => {
    const chosen = new Set(tr[side].map(x => x.kind + ":" + x.id));
    const all = [...t.players, ...t.picks];
    return `<input class="filter" data-side="${side}" placeholder="Filter…" style="width:100%;margin-bottom:6px">
      <div class="picker" data-side="${side}">${all.map(a => assetLine(a, { cls: chosen.has(a.kind + ":" + a.id) ? "sel" : "" })).join("")}</div>`;
  };
  setTimeout(() => wireTrade(), 0);
  return `<div class="grid g2">
    <div class="card"><div class="row spread"><h2>Team A gives</h2><select id="team-a">${opts(tr.a)}</select></div>${picker(ta, "aGives")}</div>
    <div class="card"><div class="row spread"><h2>Team B gives</h2><select id="team-b">${opts(tr.b)}</select></div>${picker(tb, "bGives")}</div>
  </div>
  <div class="row" style="margin-bottom:12px">
    <button id="clear-trade">Clear</button>
    <button id="suggest-b" class="primary" ${tr.a !== ov.me ? "disabled title='Suggestions are generated for your team as Team A'" : ""}>Suggest trades with Team B</button>
  </div>
  <div id="trade-result"></div><div id="trade-sugg"></div>`;
}

function wireTrade() {
  const tr = state.trade;
  $("#team-a").onchange = e => { tr.a = +e.target.value; tr.aGives = []; if (tr.a === tr.b) tr.b = null; route(); };
  $("#team-b").onchange = e => { tr.b = +e.target.value; tr.bGives = []; if (tr.a === tr.b) tr.a = null; route(); };
  $("#clear-trade").onclick = () => { tr.aGives = []; tr.bGives = []; route(); };
  $$(".filter").forEach(inp => inp.oninput = () => {
    const q = inp.value.toLowerCase();
    $$(`.picker[data-side="${inp.dataset.side}"] .asset`).forEach(el => el.hidden = q && !el.textContent.toLowerCase().includes(q));
  });
  $$(".picker").forEach(p => p.onclick = e => {
    const el = e.target.closest(".asset"); if (!el) return;
    const list = tr[p.dataset.side];
    const i = list.findIndex(x => x.kind === el.dataset.kind && x.id === el.dataset.id);
    if (i >= 0) list.splice(i, 1); else list.push({ kind: el.dataset.kind, id: el.dataset.id });
    el.classList.toggle("sel", i < 0);
    runEval();
  });
  const sb = $("#suggest-b");
  if (sb) sb.onclick = async () => {
    $("#trade-sugg").innerHTML = `<p class="muted">Generating…</p>`;
    const list = await api(`/api/suggestions?partner=${tr.b}&limit=6`);
    $("#trade-sugg").innerHTML = `<div class="card"><h2>Suggested packages</h2>${list.length ? list.map(s => suggestionCard(s, tr.b)).join("") : '<p class="muted">Nothing found.</p>'}</div>`;
  };
  runEval();
}

async function runEval() {
  const tr = state.trade, out = $("#trade-result");
  if (!out) return;
  if (!tr.aGives.length && !tr.bGives.length) { out.innerHTML = `<p class="muted">Click players or picks on either side to build a trade.</p>`; return; }
  const tok = state.evalTok = (state.evalTok || 0) + 1;  // later async cards check they're still for this trade
  let r;
  try { r = await api("/api/evaluate", { method: "POST", body: { a_rid: tr.a, a_gives: tr.aGives, b_rid: tr.b, b_gives: tr.bGives } }); }
  catch (e) { out.innerHTML = `<div class="warnbox">${esc(e.message)}</div>`; return; }
  if (tok !== state.evalTok) return;
  const [A, B] = r.sides;
  const side = (s, gets) => `<div class="card">
    <div class="row spread"><h2>${esc(s.manager)} ${windowBadge(s.window)}</h2>${accBadge(s)}</div>
    <div class="muted small">Receives</div>${gets.map(a => assetLine(a, { notes: true })).join("") || '<p class="muted">Nothing</p>'}
    <table style="margin-top:8px"><tbody>
      <tr><td>Value to this team (team context)</td><td class="num">${fmt(s.gets_value)} vs ${fmt(s.gives_value)}</td><td class="num ${signCls(s.gain_pct)}">${pct(s.gain_pct)}</td></tr>
      <tr><td>Starting lineup (win-now)</td><td class="num">${fmt(s.impact.lineup_before)} → ${fmt(s.impact.lineup_after)}</td><td class="num ${signCls(s.impact.lineup_delta_pct)}">${pct(s.impact.lineup_delta_pct)}</td></tr>
      <tr><td>Roster age (value-weighted)</td><td class="num">${s.impact.age_before} → ${s.impact.age_after}</td><td></td></tr>
      <tr><td>Pick capital change</td><td></td><td class="num ${signCls(s.impact.pick_value_delta)}">${s.impact.pick_value_delta > 0 ? "+" : ""}${fmt(s.impact.pick_value_delta)}</td></tr>
    </tbody></table>
    <div class="small" style="margin-top:6px"><b>${esc(s.verdict)}</b></div>
    ${s.acceptance_reasons.length ? `<ul class="notes">${s.acceptance_reasons.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
  </div>`;
  out.innerHTML = `<div class="card">
      <div class="row spread">
        <div><div class="muted small">Market verdict (blended values, consolidation-adjusted)</div>
          <div class="verdict">${esc(r.market.verdict)}</div>
          <div class="muted">${esc(A.manager)} gets ${fmt(r.market.a_gets)} · ${esc(B.manager)} gets ${fmt(r.market.b_gets)} · <span class="${signCls(r.market.pct)}">${pct(r.market.pct)}</span> for ${esc(A.manager)}</div></div>
        <div style="min-width:320px">
          ${Object.entries(r.by_source).map(([k, v]) => `<div class="row" style="gap:8px;margin:3px 0"><span style="width:36px" class="small">${SRC[k]}</span>
            <div style="flex:1">${centerBar(v.pct)}</div><span class="small ${signCls(v.pct)}" style="width:52px;text-align:right">${pct(v.pct, 0)}</span></div>`).join("")}
          <div class="muted small">Per-source result for ${esc(A.manager)}</div>
        </div>
      </div>
      ${r.notes.length ? `<ul class="notes">${r.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    </div>
    ${tr.a === state.ov.me && (tr.aGives.length || tr.bGives.length) ? `<div class="row" style="margin:0 0 12px"><button id="plan-add">Add to trade plan</button>
      <span class="muted small">Line up several trades and see what they do together on <a href="#/plan">Plan</a>${loadPlan().length ? ` (${loadPlan().length} in your plan)` : ""}.</span></div>` : ""}
    <div class="grid g2">${side(A, r.b_gives)}${side(B, r.a_gives)}</div>
    ${tr.aGives.length && tr.bGives.length ? `<div class="card"><div class="row spread"><div><h2>Counter-offer</h2>
      <p class="muted small">The smallest changes that make this work for both sides: ${esc(A.manager)} gains at least 3% in team-context value, and ${esc(B.manager)} would accept about 45%+ of the time.</p></div>
      <button id="counter-btn" class="primary">Make it work for both sides</button></div><div id="counter-out"></div></div>` : ""}
    <div class="card" id="impact-out"><h2>Season impact</h2><p class="muted small">Simulating the rest of the season with and without the trade…</p></div>
    ${tr.aGives.length && tr.bGives.length ? `<div class="card"><div class="row spread"><div><h2>Message to send</h2>
      <p class="muted small">A short note for ${esc(B.manager)} on why the deal helps them: their needs, lineup and playoff odds, and the calculator that has them ahead. Only points in their favor; nothing about your gain.</p></div>
      <button id="pitch-btn">Write a message</button></div><div id="pitch-out"></div></div>` : ""}`;
  const cb = $("#counter-btn");
  if (cb) cb.onclick = runCounter;
  const pb = $("#pitch-btn");
  if (pb) pb.onclick = runPitch;
  const pa = $("#plan-add");
  if (pa) pa.onclick = () => {
    const plan = loadPlan();
    plan.push({ b: tr.b, aGives: [...tr.aGives], bGives: [...tr.bGives] });
    savePlan(plan);
    toast(`Added to your trade plan (${plan.length} trade${plan.length === 1 ? "" : "s"})`);
    runEval();
  };
  loadImpact(tok);
}

// ---------------------------------------------------------------- team
async function viewTeam(rid) {
  const ov = await overview();
  rid = rid ? +rid : ov.me ?? ov.teams[0].roster_id;
  const t = await teamData(rid);
  const td = t.tendencies || {};
  const aff = (label, v, hint) => `<tr><td>${label}</td><td style="width:45%">${centerBar(v * 100, 100)}</td><td class="num small">${v > 0 ? "+" : ""}${(v ?? 0).toFixed(2)}</td><td class="muted small">${hint}</td></tr>`;
  setTimeout(() => wireTeam(t), 0);
  return `<div class="card">
    <div class="row spread">
      <div><h1>${esc(t.manager)} ${windowBadge(t.window, t.window_source)}</h1>
        <div class="muted">${esc(t.team_name)} · ${t.wins}-${t.losses} · ${fmt(t.fpts)} pts · contend score ${t.contend_score}</div>
        <div style="margin-top:4px">${tags(t.tags)}</div></div>
      <div class="row">
        <select id="team-switch">${ov.teams.map(x => `<option value="${x.roster_id}" ${x.roster_id === rid ? "selected" : ""}>${esc(x.manager)}</option>`).join("")}</select>
        <label class="field">Window
          <select id="window-set">
            <option value="">Auto (${t.window_source === "auto" ? WINDOW_LABEL[t.window] : "model"})</option>
            ${["contend", "middle", "rebuild"].map(w => `<option value="${w}" ${t.window_source === "you" && t.window === w ? "selected" : ""}>${WINDOW_LABEL[w]}</option>`).join("")}
          </select></label>
        <a class="btn" href="#/drafts/${rid}">Draft report</a>
        <a class="btn" href="#/waivers/${rid}">Pickup report</a>
        ${t.is_me ? "" : `<button class="primary" onclick='openInEvaluator({b:${rid},aGives:[],bGives:[]})'>Trade with ${esc(t.manager)}</button>`}
      </div>
    </div>
  </div>
  <div class="grid g2">
    <div class="card"><h2>Roster</h2><div class="scroll"><table>
      <thead><tr><th></th><th>Player</th><th class="num">Value</th><th class="num">Win-now</th><th class="num">FC</th><th class="num">KTC</th><th class="num">DP</th></tr></thead>
      <tbody>${t.players.map(a => `<tr>
        <td>${posBadge(a.pos)}</td>
        <td><b>${playerLink(a.id, a.name)}</b> ${a.starter ? '<span class="badge tag">starter</span>' : ""}${t.sell_candidates.includes(a.id) ? ' <span class="badge w-rebuild">sell?</span>' : ""}${a.breakout >= 35 ? ` <span class="badge tag" ${tipAttr(HELP.breakout)}>breakout ${a.breakout}</span>` : ""}
          <div class="muted small">${assetMeta(a)}</div>
          ${a.notes.length || a.user_note ? `<ul class="notes">${a.user_note ? `<li><b>You:</b> ${esc(a.user_note)}</li>` : ""}${a.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}</td>
        <td class="num"><b>${fmt(a.value)}</b></td><td class="num">${fmt(a.redraft)}</td>
        <td class="num">${fmt(a.sources.fantasycalc)}</td><td class="num">${fmt(a.sources.ktc)}</td><td class="num">${fmt(a.sources.dynastyprocess)}</td></tr>`).join("")}</tbody>
    </table></div>
    <h3>Draft picks</h3>${t.picks.map(a => assetLine(a)).join("") || '<p class="muted">None</p>'}
    </div>
    <div>
      <div class="card"><h2>Needs</h2>${posTable(t)}</div>
      <div class="card"><h2>Manager profile</h2>
        <ul class="notes" style="color:var(--text);font-size:13px">${(td.notes || []).map(n => `<li>${esc(n)}</li>`).join("")}</ul>
        ${td.n_trades ? `<table style="margin-top:8px"><tbody>
          ${aff("Consolidation", td.consolidation, "+ gets fewer, better pieces")}
          ${aff("Pick appetite", td.pick_affinity, "+ buys picks")}
          ${aff("Youth appetite", td.youth_affinity, "+ gets younger")}
          ${["QB", "RB", "WR", "TE"].map(p => aff(`${p} appetite`, td.pos_affinity[p], `+ adds ${p} value`)).join("")}
          ${aff("Trade edge", Math.max(-1, Math.min(1, td.value_edge * 4)), "+ wins trades (by today's values)")}
        </tbody></table>
        <p class="muted small">Confidence ${Math.round(td.confidence * 100)}%, based on ${td.n_trades} trade(s). Trades are valued at today's prices, so the trade edge includes hindsight.</p>` : ""}
        <h3>Your notes on this manager</h3>
        <textarea id="mgr-note" placeholder="e.g. Loves Bills players, slow to respond, always counters…">${esc(t.manager_note)}</textarea>
        <button id="save-mgr-note" style="margin-top:6px">Save note</button>
      </div>
      <div class="card"><h2>Trade history</h2>${t.trades.length ? t.trades.slice().reverse().map(tradeBlock).join("") : '<p class="muted">No trades.</p>'}</div>
    </div>
  </div>`;
}

function wireTeam(t) {
  $("#team-switch").onchange = e => (location.hash = `#/team/${e.target.value}`);
  $("#window-set").onchange = async e => {
    await api("/api/window", { method: "POST", body: { user_id: t.owner_id, window: e.target.value || null } });
    invalidate(); toast("Window updated"); route();
  };
  $("#save-mgr-note").onclick = async () => {
    await api("/api/notes", { method: "POST", body: { kind: "manager", key: t.owner_id, text: $("#mgr-note").value } });
    invalidate(); toast("Note saved");
  };
}

function tradeBlock(tx) {
  return `<div class="sugg">
    <div class="row spread small"><b>${esc(tx.date)}</b><span class="muted">${tx.season} wk ${tx.week ?? "?"}${tx.winner ? ` · edge today: <b>${esc(tx.winner)}</b>` : ""}</span></div>
    <div class="sides" style="grid-template-columns:repeat(${tx.sides.length},1fr)">
      ${tx.sides.map(s => `<div><div class="side-h">${esc(s.manager)} gets · ${fmt(s.recv_value)}</div>
        ${s.received.map(a => `<div class="asset">${posBadge(a.pos)}<div class="name">${esc(a.name)}${a.age ? ` <span class="muted small">${a.age.toFixed(1)}y then</span>` : ""}</div><span class="val">${fmt(a.value)}</span></div>`).join("") || '<span class="muted">–</span>'}
        ${s.faab ? `<div class="small muted">+ $${s.faab} FAAB</div>` : ""}</div>`).join("")}
    </div></div>`;
}

// ---------------------------------------------------------------- players
async function viewPlayers() {
  const rows = await api("/api/players");
  state.players = rows;
  setTimeout(wirePlayers, 0);
  return `<div class="card">
    <div class="row spread"><h1>Rostered players</h1>
      <div class="row"><input id="p-q" placeholder="Search name / team / owner"><select id="p-pos"><option value="">All positions</option>${["QB", "RB", "WR", "TE"].map(p => `<option>${p}</option>`).join("")}</select>
      <label class="small"><input type="checkbox" id="p-disagree"> Sources disagree</label></div></div>
    <p class="muted small">Values are blended FantasyCalc / KeepTradeCut / DynastyProcess on a common 0–10,000 curve. Set an override to use your own value everywhere (trade evaluation, suggestions). Clear the field to remove it.</p>
    <div class="scroll"><table id="p-table"><thead><tr><th></th><th>Player</th><th>Owner</th><th class="num">Value</th><th class="num">Win-now</th><th class="num">FC</th><th class="num">KTC</th><th class="num">DP</th><th class="num">30d</th><th class="num">${hint("Breakout", HELP.breakout)}</th><th>${hint("Age outlook", HELP.ageOutlook)}</th><th>Your override</th><th>Your note</th></tr></thead><tbody></tbody></table></div>
  </div>`;
}
function wirePlayers() {
  const draw = () => {
    const q = $("#p-q").value.toLowerCase(), pos = $("#p-pos").value, dis = $("#p-disagree").checked;
    const rows = state.players.filter(a => (!pos || a.pos === pos)
      && (!q || `${a.name} ${a.nfl_team} ${a.owner}`.toLowerCase().includes(q))
      && (!dis || a.notes.some(n => n.startsWith("Sources disagree")))).slice(0, 400);
    $("#p-table tbody").innerHTML = rows.map(a => `<tr>
      <td>${posBadge(a.pos)}</td>
      <td><b>${playerLink(a.id, a.name)}</b> <span class="muted small">${assetMeta(a)}</span>${a.notes.length ? `<ul class="notes">${a.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}</td>
      <td><a href="#/team/${a.owner_rid}">${esc(a.owner)}</a></td>
      <td class="num"><b>${fmt(a.value)}</b>${a.override != null ? `<div class="muted small">mkt ${fmt(a.market)}</div>` : ""}</td>
      <td class="num">${fmt(a.redraft)}</td>
      <td class="num">${fmt(a.sources.fantasycalc)}</td><td class="num">${fmt(a.sources.ktc)}</td><td class="num">${fmt(a.sources.dynastyprocess)}</td>
      <td class="num ${signCls(a.trend)}">${a.trend ? (a.trend > 0 ? "+" : "") + fmt(a.trend) : ""}</td>
      <td class="num" data-sort="${a.breakout ?? 0}">${a.breakout ? `<span class="${a.breakout >= 40 ? "bo-hi" : ""}">${a.breakout}</span>` : '<span class="muted">0</span>'}</td>
      <td data-sort="${a.age_outlook ? a.age_outlook.y1_pct : ""}">${a.age_outlook ? `${verdictBadge(a.age_outlook)} <span class="small muted">${a.age_outlook.y1_pct > 0 ? "+" : ""}${a.age_outlook.y1_pct.toFixed(0)}%</span>` : ""}</td>
      <td><input type="number" class="ov" data-id="${a.id}" value="${a.override ?? ""}" placeholder="${Math.round(a.market)}"></td>
      <td><input class="pn" data-id="${a.id}" value="${esc(a.user_note)}" placeholder="Add note…" style="width:200px"></td></tr>`).join("");
    $$(".ov").forEach(inp => inp.onchange = async () => {
      await api("/api/override", { method: "POST", body: { kind: "player", key: inp.dataset.id, value: inp.value === "" ? null : +inp.value } });
      invalidate(); toast("Override saved"); state.players = await api("/api/players"); draw();
    });
    $$(".pn").forEach(inp => inp.onchange = async () => {
      await api("/api/notes", { method: "POST", body: { kind: "player", key: inp.dataset.id, text: inp.value } });
      invalidate(); toast("Note saved");
      const p = state.players.find(x => x.id === inp.dataset.id); if (p) p.user_note = inp.value;
    });
    makeSortable($("#p-table").parentElement);  // re-apply the remembered sort after filtering
  };
  ["#p-q", "#p-pos", "#p-disagree"].forEach(s => $(s).addEventListener("input", draw));
  draw();
}

// ---------------------------------------------------------------- trade review
Object.assign(HELP, {
  atTime: "Value gap on the day of the trade: what each side received minus what it sent, both valued as packages (with the stud premium) at the weekly snapshot on or before the trade date.",
  peakGap: "The most lopsided this trade has been at any weekly snapshot since it was made, and who was ahead then.",
  today: "Value gap at the latest weekly snapshot. This decides who 'won': a trade is even when the gap is under 250 or under 8% of the bigger side.",
  netThen: "Sum of this manager's value gaps on trade day, across all their trades. Positive = they usually got more value at the time.",
  netNow: "Sum of this manager's value gaps today, across all their trades. Positive = what they traded for is worth more now than what they gave up.",
  ptsGained: "Fantasy points the players they traded for scored in their starting lineup while they held them. Picks count once the player drafted with them plays for that team.",
  ptsGiven: "Fantasy points the players they traded away scored in the other team's starting lineup.",
  record: "Trades won, lost and even, judged by today's value gap.",
});
state.tr = { season: "all", mgr: "", all: false };
function setTr(k, v) { state.tr[k] = v; if (k !== "all") state.tr.all = false; route(); }
window.setTr = setTr;
async function reviewData() {
  if (!state.reviewData) state.reviewData = await api("/api/trade-review");
  return state.reviewData;
}
const gapTxt = m => m.leader ? `<b>${esc(m.leader)}</b> +${fmt(m.gap)} <span class="muted small">(${m.pct.toFixed(0)}%)</span>` : `<span class="muted">Even</span> <span class="muted small">(${fmt(Math.abs(m.gap))} gap)</span>`;
const resBadge = r => `<span class="badge res-${r}">${{ won: "Won", lost: "Lost", even: "Even" }[r]}</span>`;
const signed = n => `<span class="${signCls(n)}">${n > 0 ? "+" : ""}${fmt(n)}</span>`;

function reviewCard(t, me) {
  const mine = t.sides.some(s => s.user_id === me);
  return `<div class="card${mine ? " me-card" : ""}">
    <div class="row spread"><div><b>${esc(t.date)}</b> <span class="muted small">${t.season}${t.week ? ` wk ${t.week}` : ""}</span>
      ${t.before_history ? ` <span class="badge res-even" ${tipAttr("Made before value history starts, so 'at the time' uses the first available snapshot.")}>early</span>` : ""}</div>
      <div>${t.now.leader ? `${esc(t.now.leader)} won` : "Even so far"}</div></div>
    <div class="moments">
      <div><div class="k">${hint("At the time", HELP.atTime)}</div><div class="v">${gapTxt(t.then)}</div></div>
      <div><div class="k">${hint("Peak gap", HELP.peakGap)} · ${esc(t.peak.date)}</div><div class="v">${gapTxt(t.peak)}</div></div>
      <div><div class="k">${hint("Today", HELP.today)}</div><div class="v">${gapTxt(t.now)}</div></div>
    </div>
    <div class="tsides" style="grid-template-columns:repeat(${t.sides.length},minmax(0,1fr))">
      ${t.sides.map(s => `<div><div class="side-h">${esc(s.manager)} ${resBadge(s.result)} <span class="muted small">gets</span></div>
        <table data-nosort class="small"><tbody>${s.received.map(a => `<tr><td>${posBadge(a.pos)}</td><td>${esc(a.name)}</td>
          <td class="num muted">${fmt(a.then)} →</td><td class="num"><b>${fmt(a.now)}</b></td><td class="num muted">${a.points ? a.points.toFixed(0) + " pts" : ""}</td></tr>`).join("")
          || '<tr><td class="muted">Nothing</td></tr>'}</tbody></table>
        ${s.faab ? `<div class="small muted">+ $${s.faab} FAAB</div>` : ""}
        <div class="small" style="margin-top:4px">Gap: ${signed(s.net_then)} then → ${signed(s.net_now)} now · ${hint(`${s.points.toFixed(0)} start pts`, HELP.ptsGained)}</div></div>`).join("")}
    </div>
    <details class="tableview" data-trade="${esc(t.id)}"><summary>Value over time</summary><div class="tr-chart"></div></details>
  </div>`;
}

async function viewHistory() {
  const R = await reviewData();
  const tr = state.tr, me = R.me;
  const seasons = [...new Set(R.trades.map(t => String(t.season)))].sort();
  const shown = R.trades.filter(t => (tr.season === "all" || String(t.season) === tr.season) && (!tr.mgr || t.sides.some(s => s.user_id === tr.mgr)));
  const decided = shown.filter(t => t.now.leader).length;
  const biggest = [...shown].sort((a, b) => b.now.gap - a.now.gap)[0];
  const flipped = shown.filter(t => t.then.leader && t.now.leader && t.then.leader !== t.now.leader).length;
  setTimeout(() => drawReview(R, shown), 0);
  const limit = tr.all ? shown.length : 40;
  return `<div class="card"><h1>Trade history</h1>
    <p class="muted">Who won each trade: the value gap ${hint("at the time", HELP.atTime)}, the ${hint("peak gap", HELP.peakGap)} since, and the gap ${hint("today", HELP.today)}.
      Values come from ${esc(R.source)}, so then and now are on one scale (they can differ a little from the blended values elsewhere). Rookie picks count at today's generic value for their round until used, then as the player drafted.
      Points are what the acquired players scored in that team's starting lineup.</p>
    <div class="tiles">
      <div class="tile"><div class="k">Trades</div><div class="v">${shown.length}</div><div class="d muted">${decided} decided · ${shown.length - decided} even so far</div></div>
      <div class="tile"><div class="k">Flipped since</div><div class="v">${flipped}</div><div class="d muted">the side ahead at the time is behind today</div></div>
      ${biggest ? `<div class="tile"><div class="k">Most lopsided today</div><div class="v">+${fmt(biggest.now.gap)}</div><div class="d muted">${esc(biggest.now.leader || "–")} · ${esc(biggest.date)}</div></div>` : ""}
    </div></div>
  <div class="filters">
    <div><span class="flabel">Season</span><span class="seg">${[["all", "All"], ...seasons.map(s => [s, s])].map(([v, l]) =>
      `<button class="${tr.season === v ? "on" : ""}" onclick='setTr("season", ${JSON.stringify(v)})'>${l}</button>`).join("")}</span></div>
    <div><span class="flabel">Manager</span><select onchange="setTr('mgr', this.value)"><option value="">Everyone</option>
      ${R.managers.map(m => `<option value="${esc(m.user_id || "")}" ${tr.mgr === m.user_id ? "selected" : ""}>${esc(m.manager)}</option>`).join("")}</select></div>
  </div>
  <div class="grid g2">
    <div class="card"><h2>Who wins trades</h2><div class="scroll"><table>
      <thead><tr><th>Manager</th><th class="num">Trades</th><th>${hint("Record", HELP.record)}</th><th class="num">${hint("Gap then", HELP.netThen)}</th>
        <th class="num">${hint("Gap today", HELP.netNow)}</th><th class="num">${hint("Pts gained", HELP.ptsGained)}</th><th class="num">${hint("Pts given", HELP.ptsGiven)}</th></tr></thead>
      <tbody>${R.managers.map(m => `<tr class="click ${m.user_id === me ? "me" : ""}" onclick='setTr("mgr", ${JSON.stringify(m.user_id || "")})'>
        <td><b>${esc(m.manager)}</b></td><td class="num">${m.trades}</td><td data-sort="${m.won - m.lost}">${m.won}–${m.lost}–${m.even}</td>
        <td class="num" data-sort="${m.net_then}">${signed(m.net_then)}</td><td class="num" data-sort="${m.net_now}"><b>${signed(m.net_now)}</b></td>
        <td class="num">${fmt(m.points)}</td><td class="num">${fmt(m.points_sent)}</td></tr>`).join("")}</tbody>
    </table></div><p class="muted small">All seasons. Click a manager to see only their trades. Gaps are summed across trades.</p></div>
    <div class="card"><h2>Won at the time vs. won in hindsight</h2>
      ${legendHTML([{ label: "You", color: "var(--series-1)" }, { label: "Other managers", color: "var(--series-2)" }])}
      <div id="tr-map"></div>
      <p class="muted small">Each manager's summed value gap on trade day (across) against today (up). Right of the line = they usually got more at the time; above it = they're ahead today.</p>
      <details class="tableview"><summary>View as table</summary><table data-nosort><thead><tr><th>Manager</th><th class="num">Then</th><th class="num">Today</th></tr></thead>
        <tbody>${R.managers.map(m => `<tr><td>${esc(m.manager)}</td><td class="num">${fmt(m.net_then)}</td><td class="num">${fmt(m.net_now)}</td></tr>`).join("")}</tbody></table></details>
    </div>
  </div>
  ${shown.slice(0, limit).map(t => reviewCard(t, me)).join("") || '<div class="card muted">No trades match.</div>'}
  ${shown.length > limit ? `<p><button onclick='setTr("all", true)'>Show all ${shown.length} trades</button></p>` : ""}`;
}

function drawReview(R, shown) {
  const host = $("#tr-map");
  if (!host) return;
  const pts = R.managers.map(m => ({ id: m.user_id, label: m.manager, x: m.net_then, y: m.net_now, highlight: m.user_id === R.me,
    color: m.user_id === R.me ? "var(--series-1)" : "var(--series-2)",
    tip: [["Gap at the time", fmt(m.net_then)], ["Gap today", fmt(m.net_now)], ["Record", `${m.won}–${m.lost}–${m.even}`], ["Trades", String(m.trades)]] }));
  const draw = () => scatter(host, { points: pts, refX: 0, refY: 0, xLabel: "Value gap at the time →", yLabel: "Value gap today →",
    quadrants: { tr: "Won then and now", tl: "Lost then, won in hindsight", br: "Won then, faded", bl: "Lost then and now" }, title: "Trade results by manager", height: 360 });
  draw();
  onResize(draw);
  $$("details[data-trade]").forEach(d => d.addEventListener("toggle", () => {
    if (!d.open || d.dataset.drawn) return;
    d.dataset.drawn = "1";
    const t = shown.find(x => x.id === d.dataset.trade);
    const dates = R.dates.slice(t.start);
    lineChart($(".tr-chart", d), {
      dates, format: compact, height: 240, title: "Value received by each side",
      markers: [{ date: dates[0], label: "Trade" }],
      series: t.sides.map((s, i) => ({ id: s.roster_id, label: s.manager, values: s.recv_series.slice(t.start), highlight: true, color: `var(--series-${i + 1})` })),
    });
  }));
}

// ---------------------------------------------------------------- settings
async function viewSettings() {
  const ov = await overview(true);
  const c = ov.config;
  const ovr = await api("/api/overrides");
  setTimeout(wireSettings, 0);
  return `<div class="grid g2">
    <div class="card"><h2>League</h2>
      <div class="row">
        ${Object.keys(c.profiles || {}).length > 1 ? `<label class="field">Saved leagues<select id="s-profile">
          ${Object.entries(c.profiles).map(([id, p]) => `<option value="${esc(id)}" ${id === String(c.league_id) ? "selected" : ""}>${esc(p.name || id)}${p.username ? ` · ${esc(p.username)}` : ""}</option>`).join("")}
        </select></label>` : ""}
        <label class="field">Sleeper league ID<input id="s-league" value="${esc(c.league_id)}" style="width:220px"></label>
        <label class="field">Your Sleeper username<input id="s-user" value="${esc(c.username)}"></label>
        <label class="field">Your strategy<select id="s-strat">${["auto", "rebuild", "contend"].map(s => `<option ${c.my_strategy === s ? "selected" : ""}>${s}</option>`).join("")}</select></label>
      </div>
      <label class="field" style="margin-top:8px">Linked older league IDs (optional)
        <input id="s-linked" value="${esc((c.linked_league_ids || []).join(", "))}" placeholder="e.g. 1389739787392385024" style="width:100%"></label>
      <p class="muted small">If your league was restarted (for example, to add teams) and Sleeper doesn't connect the seasons, add the old league's ID here.
        Its seasons become history: trades, drafts and pickups follow each manager to their current team, and old-league activity after the new league started is ignored.</p>
      <p class="muted small">History: ${(ov.league.history || []).map(h => `${h.season} ${esc(h.name)} (${h.teams})${h.linked ? " · linked" : ""}`).join(" ← ")}</p>
      <p class="muted small">${esc(ov.league.name)} · ${ov.league.season} · ${ov.league.teams} teams · ${ov.league.superflex ? "Superflex" : "1QB"} · ${ov.league.ppr} PPR · starters: ${ov.league.slots.join(", ")}</p>
      <div class="row"><button class="primary" id="s-save-league">Save</button><button id="s-refresh">Refresh all data from Sleeper & value sources</button></div>
      <div id="s-league-status" class="small" role="status" aria-live="polite"></div>
      <p class="muted small">Data is cached: rosters 15 min, values 12 h, player DB 24 h. Last build: ${new Date(ov.built * 1000).toLocaleString()}.</p>
    </div>
    <div class="card"><h2>Valuation</h2>
      <h3>Source weights</h3>
      ${Object.entries(c.source_weights).map(([k, v]) => `<div class="row" style="margin:4px 0"><span style="width:130px">${esc(ov.sources[k]?.label || k)}</span>
        <input type="range" min="0" max="2" step="0.1" value="${v}" class="s-w" data-k="${k}" style="flex:1"><span class="small" style="width:30px">${v}</span>
        <span class="muted small" style="width:140px">${ov.sources[k] ? ov.sources[k].players + " players" : '<span class="delta-neg">unavailable</span>'}</span></div>`).join("")}
      <div class="row" style="margin-top:10px">
        <label class="field">Stud premium (consolidation exponent)<input type="number" step="0.05" min="1" max="2" id="s-exp" value="${c.consolidation_exponent}"></label>
        <label class="field">Min asset value for suggestions<input type="number" step="100" id="s-min" value="${c.suggestion_min_value}"></label>
      </div>
      <p class="muted small">Package value = (Σ value^p)^(1/p). At p = 1 values simply add; higher p means two good players are worth less than one great one.</p>
      <h3>Rookie pick multipliers</h3>
      <div class="row">${[1, 2, 3].map(r => `<label class="field">Round ${r}<input type="number" step="0.05" class="s-pm" data-k="${r}" value="${ovr.pick_multipliers[r] ?? ""}" placeholder="1.00"></label>`).join("")}</div>
      <p class="muted small">Scale all pick values in a round to match how your league values picks (e.g. 1.2 = 20% higher than market).</p>
      <button class="primary" id="s-save-val">Save valuation settings</button>
    </div>
    <div class="card" id="s-phone"><h2>Open on your phone</h2><p class="muted small">Checking…</p></div>
    <div class="card" id="s-health"><h2>Data health</h2><p class="muted small">Checking…</p></div>
  </div>`;
}
async function loadPhone() {
  const host = $("#s-phone");
  const p = await api("/api/phone").catch(() => null);
  if (!host) return;
  const body = !p || !p.url
    ? `<p class="muted small">This computer doesn't seem to be on a network right now.</p>`
    : !p.reachable
      ? `<p class="small">The server is only listening on this computer. Restart it with <code>.\\run.ps1</code> (without <code>-LocalOnly</code>) to open it from a phone on the same Wi-Fi.</p>`
      : `<div class="row" style="align-items:center;gap:16px"><div class="qr">${p.svg}</div>
          <div><p>Scan with your phone's camera, or type<br><b><a href="${esc(p.url)}">${esc(p.url)}</a></b></p>
          <p class="muted small">Your phone needs to be on the same Wi-Fi, and this computer needs to be awake with the app running.
            The address can change when your router hands out a new one; this card always shows the current one.</p></div></div>`;
  host.innerHTML = `<h2>Open on your phone</h2>${body}`;
}

async function loadHealth() {
  const host = $("#s-health");
  let H;
  try { H = await api("/api/health"); } catch (e) { if (host) host.innerHTML = `<h2>Data health</h2><div class="warnbox">${esc(e.message)}</div>`; return; }
  if (!$("#s-health")) return;
  const ago = t => t ? shortAgo(t) : "–";
  host.innerHTML = `<div class="row spread"><h2>Data health</h2><span class="badge ${H.ok === H.total ? "acc-Likely" : "acc-Possible"}">${H.ok} of ${H.total} OK</span></div>
    <p class="muted small">Every data source the app uses. Extras that fail don't stop the app, but the pages they power lose those features until the next refresh.</p>
    <div class="scroll"><table data-nosort><thead><tr><th>Source</th><th>Status</th><th>Loaded</th><th>Details</th></tr></thead><tbody>
      ${H.rows.map(r => `<tr><td><b>${esc(r.name)}</b><div class="muted small">${esc(r.powers)}</div></td>
        <td><span class="badge ${r.ok ? "acc-Likely" : "acc-Unlikely"}">${r.ok ? "OK" : "Problem"}</span></td>
        <td class="small">${ago(r.loaded)}</td><td class="small">${esc(r.detail || "")}</td></tr>`).join("")}</tbody></table></div>
    <p class="muted small">League last built ${ago(H.built)}. <b>Refresh</b> above re-downloads everything.</p>`;
}
const shortAgo = t => {
  const m = Math.round((Date.now() / 1000 - t) / 60);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 48 * 60 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`;
};

function wireSettings() {
  loadPhone();
  loadHealth();
  $$(".s-w").forEach(r => r.oninput = () => (r.nextElementSibling.textContent = r.value));
  // Picking a saved league fills in its remembered settings; Save switches to it.
  const prof = $("#s-profile");
  if (prof) prof.onchange = () => {
    const p = (state.ov.config.profiles || {})[prof.value] || {};
    $("#s-league").value = prof.value;
    if (p.username) $("#s-user").value = p.username;
    if (p.my_strategy) $("#s-strat").value = p.my_strategy;
    $("#s-linked").value = (p.linked_league_ids || []).join(", ");
    $("#s-league-status").className = "small muted";
    $("#s-league-status").textContent = `Click Save to switch to ${p.name || prof.value}.`;
  };
  $("#s-save-league").onclick = async e => {
    const btn = e.target, status = $("#s-league-status");
    const linked = $("#s-linked").value.split(/[\s,]+/).map(s => s.trim()).filter(Boolean);
    btn.disabled = true; btn.textContent = "Saving…";
    status.className = "small muted";
    status.textContent = "Loading the league… A league you haven't opened before can take a minute while every season downloads.";
    let r;
    try {
      r = await api("/api/config", { method: "POST", body: { league_id: $("#s-league").value.trim(), username: $("#s-user").value.trim(), my_strategy: $("#s-strat").value, linked_league_ids: linked } });
    } catch (err) {
      btn.disabled = false; btn.textContent = "Save";
      status.className = "small delta-neg"; status.textContent = err.message;
      return;
    }
    invalidate();
    await route();
    const msg = `✓ Saved. Now showing ${r.league} (${r.season}, ${r.teams} teams).`;
    toast(r.warning ? "Saved, with a warning" : "Saved");
    const s2 = $("#s-league-status");
    if (s2) { s2.className = r.warning ? "small delta-neg" : "small delta-pos"; s2.textContent = r.warning ? `${msg} ${r.warning}` : msg; }
  };
  $("#s-refresh").onclick = async e => {
    e.target.disabled = true; e.target.textContent = "Refreshing…";
    try { await api("/api/refresh", { method: "POST" }); toast("Data refreshed"); } catch (err) { toast("Refresh failed: " + err.message); }
    invalidate(); route();
  };
  $("#s-save-val").onclick = async e => {
    e.target.disabled = true; e.target.textContent = "Saving…";
    const w = {}; $$(".s-w").forEach(r => (w[r.dataset.k] = +r.value));
    await api("/api/config", { method: "POST", body: { source_weights: w, consolidation_exponent: +$("#s-exp").value, suggestion_min_value: +$("#s-min").value } });
    for (const inp of $$(".s-pm")) await api("/api/override", { method: "POST", body: { kind: "pick", key: inp.dataset.k, value: inp.value === "" ? null : +inp.value } });
    invalidate(); toast("Valuation settings saved"); route();
  };
}

// ---------------------------------------------------------------- drafts
const SRC_KEYS = ["startup", "rookie", "trade", "waiver"];
const SRC_LABELS = { startup: "Startup draft", rookie: "Rookie draft", trade: "Trade", waiver: "Waivers / FA" };
const MAX_HL = 4;
state.dr = { draft: "all", measure: "series", hl: null, slots: {} };

async function draftsData() {
  if (!state.draftsData) state.draftsData = await api("/api/drafts");
  return state.draftsData;
}
// Color follows the team: a highlighted team keeps its slot until un-highlighted.
function slotOf(rid) {
  const dr = state.dr;
  if (!dr.slots[rid]) {
    const used = new Set(dr.hl.filter(r => r !== rid).map(r => dr.slots[r]));
    dr.slots[rid] = [1, 2, 3, 4].find(s => !used.has(s));
  }
  return dr.slots[rid];
}
function toggleHL(rid) {
  const dr = state.dr;
  if (dr.hl.includes(rid)) { dr.hl = dr.hl.filter(r => r !== rid); delete dr.slots[rid]; }
  else if (dr.hl.length >= MAX_HL) { toast(`Highlight up to ${MAX_HL} teams at a time`); return; }
  else { dr.hl.push(rid); slotOf(rid); }
  route();
}
window.toggleHL = toggleHL;
function setDr(k, v) { state.dr[k] = v; route(); }
window.setDr = setDr;

const segCtl = (label, key, options) => `<div><span class="flabel">${label}</span><span class="seg">${options.map(([v, l]) =>
  `<button class="${state.dr[key] === v ? "on" : ""}" onclick='setDr("${key}", ${JSON.stringify(v)})'>${esc(l)}</button>`).join("")}</span></div>`;
// Pick within its round, e.g. 3.07 (works for snake and linear drafts).
const pickLabel = (p, n) => `${p.round}.${String(p.pick_no - (p.round - 1) * n).padStart(2, "0")}`;
const pctTxt = n => `<span class="${signCls(n)}">${pct(n)}</span>`;
const measureFmt = () => state.dr.measure === "index" ? (v => v == null ? "–" : Math.round(v).toString()) : compact;

// Trim leading dates where no series has data (e.g. rookie-draft-only view).
function trimDates(dates, seriesList) {
  let first = dates.findIndex((_, i) => seriesList.some(v => v[i] != null));
  if (first < 0) first = 0;
  first = Math.max(0, first - 1);
  return { dates: dates.slice(first), cut: arr => arr.slice(first) };
}
function median(nums) {
  const a = nums.filter(v => v != null).sort((x, y) => x - y);
  if (!a.length) return null;
  const k = Math.floor(a.length / 2);
  return a.length % 2 ? a[k] : (a[k - 1] + a[k]) / 2;
}
function draftMarkers(D) {
  return D.drafts.filter(d => state.dr.draft === "all" || d.id === state.dr.draft)
    .map(d => ({ date: d.start, label: d.kind === "startup" ? "Startup draft" : `${d.season} rookie draft` }));
}

async function viewDrafts() {
  const D = await draftsData();
  const dr = state.dr;
  if (!dr.hl) { dr.hl = D.me ? [D.me] : []; dr.hl.forEach(slotOf); }
  const key = dr.draft;
  const teams = D.teams.filter(t => t.drafts[key]);
  const picks = D.picks.filter(p => key === "all" || p.draft_id === key);
  const byChange = [...picks].sort((a, b) => b.change - a.change);
  setTimeout(() => drawDraftsCharts(D), 0);
  const rows = [...teams].sort((a, b) => b.drafts[key].change_pct - a.drafts[key].change_pct);
  const pickHead = `<thead><tr><th></th><th>Player</th><th>Drafted by</th><th class="num">Draft day</th><th class="num">Now</th><th class="num">Change</th><th>Trend</th></tr></thead>`;
  const pickLine = p => `<tr><td>${posBadge(p.pos)}</td><td><b>${esc(p.name)}</b><div class="muted small">${esc(p.draft)} · ${pickLabel(p, D.teams.length)} (#${p.pick_no})</div></td>
    <td><a href="#/drafts/${p.roster_id}">${esc(p.manager)}</a></td><td class="num">${fmt(p.draft_value)}</td><td class="num">${fmt(p.now_value)}</td>
    <td class="num ${signCls(p.change)}">${p.change > 0 ? "+" : ""}${fmt(p.change)}</td><td>${sparkline(p.history)}</td></tr>`;
  return `<div class="card"><h1>Past drafts</h1>
    <p class="muted">Every pick from the startup and rookie drafts, credited to the team that made it, valued on the day it was made and every week since.
      History comes from ${esc(D.source)} (the only free source with weekly history), so "now" can differ slightly from the blended values elsewhere in the app.
      Slow drafts: each pick's date is estimated from its position between the draft's first and last pick.</p>
    ${D.early_drafts && D.early_drafts.length ? `<div class="warnbox">Value history starts ${esc(D.history_start)}. For ${esc(D.early_drafts.join(", "))},
      "draft day" values are really values as of ${esc(D.history_start)}, so changes for those drafts cover only the period since then.</div>` : ""}</div>
  <div class="filters">
    ${segCtl("Draft", "draft", [["all", "All drafts"], ...D.drafts.map(d => [d.id, d.label])])}
    ${segCtl("Measure", "measure", [["series", "Total value"], ["index", "Index (draft day = 100)"]])}
  </div>
  <div class="card">
    <div class="row spread"><h2>Draft class value over time</h2></div>
    <div class="row" style="gap:6px;margin-bottom:6px"><span class="flabel">Highlight (up to ${MAX_HL})</span>
      ${D.teams.map(t => { const on = dr.hl.includes(t.roster_id);
        return `<button class="chip ${on ? "on" : ""}" onclick="toggleHL(${t.roster_id})" aria-pressed="${on}"><i class="lk" style="background:${on ? `var(--series-${slotOf(t.roster_id)})` : "var(--context-line)"}"></i>${esc(t.manager)}</button>`; }).join("")}
    </div>
    <div id="dr-legend"></div>
    <div id="dr-line"></div>
    <p class="muted small">${dr.measure === "index" ? "Index = current value of the players drafted so far ÷ their value on draft day × 100. Above 100 means the class has gained value." : "Sum of the value of every player the team drafted (whether or not they still roster him)."} Lines step up while a draft is in progress as picks are added. Hover or focus the chart and use ← → to read values.</p>
    <details class="tableview"><summary>View as table</summary><div class="scroll"><table>
      <thead><tr><th>Team</th><th class="num">Draft day</th><th class="num">Peak</th><th class="num">Now</th><th class="num">Change</th></tr></thead>
      <tbody>${rows.map(t => { const d = t.drafts[key]; const s = d.series.filter(v => v != null);
        return `<tr><td>${esc(t.manager)}</td><td class="num">${fmt(d.draft_value)}</td><td class="num">${fmt(Math.max(...s))}</td><td class="num">${fmt(d.now_value)}</td><td class="num">${pctTxt(d.change_pct)}</td></tr>`; }).join("")}</tbody>
    </table></div></details>
  </div>
  <div class="card"><h2>Draft scorecard</h2><div class="scroll"><table>
    <thead><tr><th>Team</th><th class="num">Picks</th><th class="num">Draft-day value</th><th class="num">Value now</th><th class="num">Change</th>
      <th class="num">Still on roster</th><th class="num">Still in league</th><th class="num">Value still on roster</th><th>Best riser</th><th>Biggest faller</th></tr></thead>
    <tbody>${rows.map(t => { const d = t.drafts[key];
      return `<tr class="click ${t.roster_id === D.me ? "me" : ""}" onclick="location.hash='#/drafts/${t.roster_id}'">
        <td><b>${esc(t.manager)}</b></td><td class="num">${d.n}</td><td class="num">${fmt(d.draft_value)}</td><td class="num">${fmt(d.now_value)}</td>
        <td class="num">${pctTxt(d.change_pct)}</td><td class="num">${d.retained_pct}% <span class="muted small">(${d.retained}/${d.n})</span></td>
        <td class="num">${Math.round(d.in_league / d.n * 100)}%</td><td class="num">${fmt(d.retained_value)}</td>
        <td>${posBadge(d.best.pos)} ${esc(d.best.name)} <span class="delta-pos small">+${fmt(d.best.change)}</span></td>
        <td>${posBadge(d.worst.pos)} ${esc(d.worst.name)} <span class="delta-neg small">${fmt(d.worst.change)}</span></td></tr>`; }).join("")}</tbody>
  </table></div>
  <p class="muted small">Still on roster = drafted players the drafting team still owns. Still in league = rostered by anyone.</p></div>
  <div class="grid g2">
    <div class="card"><h2>Biggest risers</h2><table>${pickHead}<tbody>${byChange.slice(0, 10).map(pickLine).join("")}</tbody></table></div>
    <div class="card"><h2>Biggest fallers</h2><table>${pickHead}<tbody>${byChange.slice(-10).reverse().map(pickLine).join("")}</tbody></table></div>
  </div>
  <div class="card"><h2>Roster construction</h2>
    <p class="muted small">How each team's <b>current</b> roster was acquired, as a share of current roster value (blended values). Each player counts under his most recent move onto that team. Not affected by the draft filter.</p>
    ${legendHTML(SRC_KEYS.map((k, i) => ({ label: SRC_LABELS[k], color: `var(--series-${i + 1})`, rect: true })))}
    <div id="dr-cons"></div>
    <details class="tableview"><summary>View as table</summary><div class="scroll"><table>
      <thead><tr><th>Team</th>${SRC_KEYS.map(k => `<th class="num">${SRC_LABELS[k]}</th>`).join("")}</tr></thead>
      <tbody>${D.construction.map(c => `<tr><td>${esc(c.manager)}</td>${SRC_KEYS.map(k => `<td class="num">${c.value_pct[k]}% <span class="muted small">(${c.counts[k]} pl.)</span></td>`).join("")}</tr>`).join("")}</tbody>
    </table></div></details>
  </div>`;
}

function drawDraftsCharts(D) {
  const dr = state.dr, key = dr.draft;
  const host = $("#dr-line");
  if (!host) return;
  const raw = D.teams.map(t => ({ t, v: t.drafts[key] ? t.drafts[key][dr.measure] : D.dates.map(() => null) }));
  const { dates, cut } = trimDates(D.dates, raw.map(r => r.v));
  const series = raw.map(({ t, v }) => {
    const hl = dr.hl.includes(t.roster_id);
    return { id: t.roster_id, label: t.manager, values: cut(v), highlight: hl, color: hl ? `var(--series-${slotOf(t.roster_id)})` : null };
  });
  $("#dr-legend").innerHTML = legendHTML([
    ...dr.hl.map(rid => ({ label: D.teams.find(t => t.roster_id === rid).manager, color: `var(--series-${slotOf(rid)})` })),
    { label: "Other teams", color: "var(--context-line)" },
  ]);
  const draw = () => lineChart(host, { dates, series, format: measureFmt(), markers: draftMarkers(D), title: "Draft class value over time" });
  draw();
  onResize(draw, () => drawCons(D));
  drawCons(D);
}
function drawCons(D, only) {
  const host = $("#dr-cons");
  if (!host) return;
  const rows = D.construction.filter(c => !only || c.roster_id === only)
    .sort((a, b) => b.value_pct.startup - a.value_pct.startup)
    .map(c => ({ label: c.manager, parts: c.value_pct,
      tip: Object.fromEntries(SRC_KEYS.map(k => [k, `${c.counts[k]} players · ${fmt(c.values[k])} value`])) }));
  stackedBars(host, { rows, keys: SRC_KEYS, labels: SRC_LABELS, max: 100, title: "Roster construction by acquisition source" });
}
let _resize;
function onResize(...fns) {
  window.removeEventListener("resize", _resize);
  let t;
  _resize = () => { clearTimeout(t); t = setTimeout(() => fns.forEach(f => f()), 150); };
  window.addEventListener("resize", _resize);
}

async function viewDraftTeam(rid) {
  const D = await draftsData();
  rid = +rid;
  const team = D.teams.find(t => t.roster_id === rid);
  if (!team) return `<div class="warnbox">No such team.</div>`;
  const key = team.drafts[state.dr.draft] ? state.dr.draft : "all";
  const d = team.drafts[key];
  const picks = D.picks.filter(p => p.roster_id === rid && (key === "all" || p.draft_id === key)).sort((a, b) => a.pick_no - b.pick_no || a.draft.localeCompare(b.draft));
  const rank = [...D.teams.filter(t => t.drafts[key])].sort((a, b) => b.drafts[key].change_pct - a.drafts[key].change_pct).findIndex(t => t.roster_id === rid) + 1;
  const cons = D.construction.find(c => c.roster_id === rid);
  setTimeout(() => drawDraftTeam(D, team, key), 0);
  const draftTiles = D.drafts.filter(x => team.drafts[x.id]).map(x => { const s = team.drafts[x.id];
    return `<div class="tile"><div class="k">${esc(x.label)}</div><div class="v">${compact(s.now_value)}</div>
      <div class="d">from ${compact(s.draft_value)} on draft day · ${pctTxt(s.change_pct)}</div></div>`; }).join("");
  return `<div class="card"><div class="row spread">
      <div><h1>${esc(team.manager)} · drafts</h1><div class="muted"><a href="#/drafts">← Past drafts</a> · <a href="#/waivers/${rid}">Pickup report</a> · <a href="#/team/${rid}">Team page</a></div></div>
      <select onchange="location.hash='#/drafts/'+this.value">${D.teams.map(t => `<option value="${t.roster_id}" ${t.roster_id === rid ? "selected" : ""}>${esc(t.manager)}</option>`).join("")}</select>
    </div></div>
  <div class="filters">
    ${segCtl("Draft", "draft", [["all", "All drafts"], ...D.drafts.filter(x => team.drafts[x.id]).map(x => [x.id, x.label])])}
    ${segCtl("Measure", "measure", [["series", "Total value"], ["index", "Index (draft day = 100)"]])}
  </div>
  <div class="card"><div class="tiles">
    ${draftTiles}
    <div class="tile"><div class="k">Still on roster</div><div class="v">${d.retained_pct}%</div><div class="d muted">${d.retained} of ${d.n} picks · ${Math.round(d.in_league / d.n * 100)}% still in the league</div></div>
    <div class="tile"><div class="k">Value still on roster</div><div class="v">${compact(d.retained_value)}</div><div class="d muted">of ${compact(d.now_value)} drafted value</div></div>
    <div class="tile"><div class="k">League rank (value change)</div><div class="v">${rank} of ${D.teams.filter(t => t.drafts[key]).length}</div><div class="d muted">${esc(key === "all" ? "all drafts" : D.drafts.find(x => x.id === key).label)}</div></div>
  </div></div>
  <div class="card"><h2>Draft class value over time</h2>
    <div id="dt-legend"></div><div id="dt-line"></div>
    <p class="muted small">${state.dr.measure === "index" ? "Index = current value of the players drafted so far ÷ their draft-day value × 100." : "Sum of the value of every player this team drafted, whether or not still rostered."} The league median is the middle team at each date.</p>
  </div>
  <div class="card"><h2>Picks</h2><div class="scroll"><table>
    <thead><tr><th>Pick</th><th></th><th>Player</th><th>Drafted</th><th class="num">Draft-day value</th><th class="num">Now</th><th class="num">Change</th><th>Value over time</th><th>Status</th></tr></thead>
    <tbody>${picks.map(p => `<tr>
      <td class="num">${pickLabel(p, D.teams.length)}<div class="muted small">#${p.pick_no}${key === "all" ? " · " + (p.kind === "startup" ? "SU" : p.draft.slice(0, 4)) : ""}</div></td>
      <td>${posBadge(p.pos)}</td><td><b>${esc(p.name)}</b></td><td class="small">${p.date}</td>
      <td class="num">${fmt(p.draft_value)}</td><td class="num">${fmt(p.now_value)}</td>
      <td class="num ${signCls(p.change)}">${p.change > 0 ? "+" : ""}${fmt(p.change)}</td>
      <td>${sparkline(p.history)}</td>
      <td class="small">${p.on_roster ? '<span class="badge w-contend">On roster</span>' : esc(p.status)}</td></tr>`).join("")}</tbody>
  </table></div></div>
  <div class="card"><h2>Roster construction</h2>
    <p class="muted small">How the current roster was acquired (share of current roster value). Not affected by the draft filter.</p>
    ${legendHTML(SRC_KEYS.map((k, i) => ({ label: SRC_LABELS[k], color: `var(--series-${i + 1})`, rect: true })))}
    <div id="dr-cons"></div>
    <div class="grid g2" style="margin-top:10px">${SRC_KEYS.map(k => { const ps = cons.players.filter(p => p.source === k);
      return `<div><h3>${SRC_LABELS[k]} · ${ps.length} players · ${cons.value_pct[k]}% of value</h3>${ps.map(p =>
        `<div class="asset">${posBadge(p.pos)}<div class="name">${esc(p.name)} <span class="muted small">${p.date || ""}</span></div><span class="val">${fmt(p.value)}</span></div>`).join("") || '<p class="muted small">None</p>'}</div>`; }).join("")}</div>
  </div>`;
}

function drawDraftTeam(D, team, key) {
  const host = $("#dt-line");
  if (!host) return;
  const m = state.dr.measure;
  const mine = team.drafts[key][m];
  const med = D.dates.map((_, i) => median(D.teams.filter(t => t.drafts[key]).map(t => t.drafts[key][m][i])));
  const { dates, cut } = trimDates(D.dates, [mine]);
  const series = [
    { id: "median", label: "League median", values: cut(med), highlight: true, color: "var(--chart-muted)" },
    { id: team.roster_id, label: team.manager, values: cut(mine), highlight: true, color: "var(--series-1)" },
  ];
  $("#dt-legend").innerHTML = legendHTML([{ label: team.manager, color: "var(--series-1)" }, { label: "League median", color: "var(--chart-muted)" }]);
  const draw = () => lineChart(host, { dates, series, format: measureFmt(), markers: draftMarkers(D), title: `${team.manager} draft class value` });
  draw();
  onResize(draw, () => drawCons(D, team.roster_id));
  drawCons(D, team.roster_id);
}

// ---------------------------------------------------------------- waivers
state.wv = { season: "all" };
async function waiversData() {
  if (!state.waiversData) state.waiversData = await api("/api/waivers");
  return state.waiversData;
}
function setWv(k, v) { state.wv[k] = v; route(); }
window.setWv = setWv;
const wvSeg = (W, teamPage) => `<div><span class="flabel">Season</span><span class="seg">${[["all", "All seasons"], ...W.seasons.map(s => [String(s), String(s)])].map(([v, l]) =>
  `<button class="${state.wv.season === v ? "on" : ""}" onclick='setWv("season", ${JSON.stringify(v)})'>${l}</button>`).join("")}</span></div>`;
const howCell = p => p.type === "claim" ? `Claim${p.bid ? ` · $${p.bid}` : ""}` : "Free agent";
const outcomeCell = p => p.on_roster ? '<span class="badge w-contend">On roster</span>' : esc(p.outcome);

async function viewWaivers() {
  const W = await waiversData();
  const dr = state.dr;
  if (!dr.hl) { dr.hl = W.me ? [W.me] : []; dr.hl.forEach(slotOf); }
  const key = state.wv.season;
  const ps = W.pickups.filter(p => key === "all" || String(p.season) === key);
  const rows = [...W.teams].sort((a, b) => b.stats[key].captured - a.stats[key].captured);
  const pkHead = (metric) => `<thead><tr><th></th><th>Player</th><th>Picked up by</th><th class="num">${hint("At pickup", HELP.atPickup)}</th><th class="num">${metric}</th><th>Trend</th></tr></thead>`;
  const pkRow = (p, field) => `<tr><td>${posBadge(p.pos)}</td><td><b>${esc(p.name)}</b><div class="muted small">${p.date} · ${howCell(p)} · ${esc(p.outcome)}</div></td>
    <td><a href="#/waivers/${p.roster_id}">${esc(p.manager)}</a></td><td class="num">${fmt(p.value_at_pickup)}</td>
    <td class="num"><b>${field === "start_points" ? p.start_points.toFixed(1) : fmt(p[field])}</b>${field === "start_points" ? `<div class="muted small">${p.starts} starts</div>` : ""}</td><td>${sparkline(p.history)}</td></tr>`;
  setTimeout(() => drawWaivers(W), 0);
  const best = b => b ? `${posBadge(b.pos)} ${esc(b.name)}` : '<span class="muted">–</span>';
  return `<div class="card"><h1>Pickup history</h1>
    <p class="muted">Every player added from waivers or free agency, held until that team dropped or traded him. Two ways to judge a pickup:
      <b>${hint("value captured", HELP.captured)}</b> (what he's worth to the team today, in dynasty value) and
      <b>${hint("start points", HELP.startPts)}</b> (fantasy points he scored in their starting lineup). Values come from ${esc(W.source)}.</p></div>
  <div class="filters">${wvSeg(W)}</div>
  <div class="card"><h2>Who picks up the most players</h2>
    ${legendHTML([{ label: "Waiver claims", color: "var(--series-1)", rect: true }, { label: "Free-agent adds", color: "var(--series-2)", rect: true }])}
    <div id="wv-count"></div>
    <details class="tableview"><summary>View as table</summary><table>
      <thead><tr><th>Team</th><th class="num">Claims</th><th class="num">Free agents</th><th class="num">Total</th><th class="num">FAAB spent</th></tr></thead>
      <tbody>${[...W.teams].sort((a, b) => b.stats[key].n - a.stats[key].n).map(t => { const s = t.stats[key];
        return `<tr><td>${esc(t.manager)}</td><td class="num">${s.claims}</td><td class="num">${s.fa}</td><td class="num">${s.n}</td><td class="num">$${s.faab}</td></tr>`; }).join("")}</tbody>
    </table></details>
  </div>
  <div class="card"><h2>Value of pickups on roster over time</h2>
    <div class="row" style="gap:6px;margin-bottom:6px"><span class="flabel">Highlight (up to ${MAX_HL})</span>
      ${W.teams.map(t => { const on = dr.hl.includes(t.roster_id);
        return `<button class="chip ${on ? "on" : ""}" onclick="toggleHL(${t.roster_id})" aria-pressed="${on}"><i class="lk" style="background:${on ? `var(--series-${slotOf(t.roster_id)})` : "var(--context-line)"}"></i>${esc(t.manager)}</button>`; }).join("")}
    </div>
    <div id="wv-legend"></div><div id="wv-line"></div>
    <p class="muted small">Total dynasty value of the waiver/FA pickups each team was holding at each date. Falls when a team drops or trades a pickup. Hover or focus the chart and use ← → to read values.</p>
  </div>
  <div class="card"><h2>Waiver scorecard</h2><div class="scroll"><table>
    <thead><tr><th>Team</th><th class="num">${hint("Pickups", HELP.pickups)}</th><th class="num">${hint("FAAB", HELP.faab)}</th>
      <th class="num">${hint("Still rostered", HELP.stillRostered)}</th><th class="num">${hint("Hits", HELP.hits)}</th>
      <th class="num">${hint("Value at pickup", HELP.atPickup)}</th><th class="num">${hint("Value captured", HELP.captured)}</th>
      <th class="num">${hint("Start points", HELP.startPts)}</th><th>Best pickup (value)</th><th>Best pickup (points)</th></tr></thead>
    <tbody>${rows.map(t => { const s = t.stats[key];
      return `<tr class="click ${t.roster_id === W.me ? "me" : ""}" onclick="location.hash='#/waivers/${t.roster_id}'">
        <td><b>${esc(t.manager)}</b></td><td class="num">${s.n}</td><td class="num">$${s.faab}</td><td class="num">${s.on_roster}</td><td class="num">${s.hits}</td>
        <td class="num">${fmt(s.value_at_pickup)}</td><td class="num"><b>${fmt(s.captured)}</b></td>
        <td class="num">${s.start_points.toFixed(1)} <span class="muted small">(${s.starts})</span></td>
        <td>${best(s.best_value)}${s.best_value ? ` <span class="small muted">${fmt(s.best_value.value)}</span>` : ""}</td>
        <td>${best(s.best_points)}${s.best_points ? ` <span class="small muted">${s.best_points.value.toFixed(1)} pts</span>` : ""}</td></tr>`; }).join("")}</tbody>
  </table></div>
  <p class="muted small">Sorted by value captured. Start points show the number of starts in parentheses.</p></div>
  <div class="grid g2">
    <div class="card"><h2>Best pickups by value captured</h2><table>${pkHead(hint("Captured", HELP.captured))}<tbody>${[...ps].sort((a, b) => b.captured - a.captured).slice(0, 10).map(p => pkRow(p, "captured")).join("")}</tbody></table></div>
    <div class="card"><h2>Best pickups by start points</h2><table>${pkHead(hint("Start pts", HELP.startPts))}<tbody>${[...ps].sort((a, b) => b.start_points - a.start_points).slice(0, 10).map(p => pkRow(p, "start_points")).join("")}</tbody></table></div>
  </div>`;
}

function drawWaivers(W) {
  const key = state.wv.season, dr = state.dr;
  const countHost = $("#wv-count");
  if (!countHost) return;
  const sorted = [...W.teams].sort((a, b) => b.stats[key].n - a.stats[key].n);
  const max = Math.max(1, ...sorted.map(t => t.stats[key].n));
  const drawCount = () => stackedBars(countHost, {
    rows: sorted.map(t => ({ label: t.manager, parts: { claim: t.stats[key].claims, fa: t.stats[key].fa },
      tip: { claim: `$${t.stats[key].faab} FAAB spent`, fa: "no FAAB cost" } })),
    keys: ["claim", "fa"], labels: { claim: "Waiver claims", fa: "Free-agent adds" }, max, text: v => String(v),
    title: "Pickups per team",
  });
  const raw = W.teams.map(t => ({ t, v: t.stats[key].series }));
  const { dates, cut } = trimDates(W.dates, raw.map(r => r.v));
  const series = raw.map(({ t, v }) => {
    const hl = dr.hl.includes(t.roster_id);
    return { id: t.roster_id, label: t.manager, values: cut(v), highlight: hl, color: hl ? `var(--series-${slotOf(t.roster_id)})` : null };
  });
  $("#wv-legend").innerHTML = legendHTML([
    ...dr.hl.map(rid => ({ label: W.teams.find(t => t.roster_id === rid).manager, color: `var(--series-${slotOf(rid)})` })),
    { label: "Other teams", color: "var(--context-line)" },
  ]);
  const drawLine = () => lineChart($("#wv-line"), { dates, series, format: compact, title: "Value of pickups on roster" });
  drawCount(); drawLine();
  onResize(drawCount, drawLine);
}

async function viewWaiverTeam(rid) {
  const W = await waiversData();
  rid = +rid;
  const team = W.teams.find(t => t.roster_id === rid);
  if (!team) return `<div class="warnbox">No such team.</div>`;
  const key = state.wv.season, s = team.stats[key];
  const rank = f => [...W.teams].sort((a, b) => b.stats[key][f] - a.stats[key][f]).findIndex(t => t.roster_id === rid) + 1;
  const ps = W.pickups.filter(p => p.roster_id === rid && (key === "all" || String(p.season) === key)).sort((a, b) => b.date.localeCompare(a.date));
  setTimeout(() => drawWaiverTeam(W, team), 0);
  const n = W.teams.length;
  return `<div class="card"><div class="row spread">
      <div><h1>${esc(team.manager)} · pickups</h1><div class="muted"><a href="#/waivers">← Pickup history</a> · <a href="#/drafts/${rid}">Draft report</a> · <a href="#/team/${rid}">Team page</a></div></div>
      <select onchange="location.hash='#/waivers/'+this.value">${W.teams.map(t => `<option value="${t.roster_id}" ${t.roster_id === rid ? "selected" : ""}>${esc(t.manager)}</option>`).join("")}</select>
    </div></div>
  <div class="filters">${wvSeg(W)}</div>
  <div class="card"><div class="tiles">
    <div class="tile"><div class="k">${hint("Pickups", HELP.pickups)}</div><div class="v">${s.n}</div><div class="d muted">${s.claims} claims · ${s.fa} free agents · #${rank("n")} of ${n}</div></div>
    <div class="tile"><div class="k">${hint("FAAB spent", HELP.faab)}</div><div class="v">$${s.faab}</div><div class="d muted">${s.claims ? `$${(s.faab / s.claims).toFixed(0)} per claim` : "–"}</div></div>
    <div class="tile"><div class="k">${hint("Hits", HELP.hits)}</div><div class="v">${s.hits}</div><div class="d muted">${s.n ? Math.round(s.hits / s.n * 100) : 0}% of pickups · ${s.on_roster} still rostered</div></div>
    <div class="tile"><div class="k">${hint("Value captured", HELP.captured)}</div><div class="v">${compact(s.captured)}</div><div class="d muted">#${rank("captured")} of ${n} · from ${compact(s.value_at_pickup)} at pickup</div></div>
    <div class="tile"><div class="k">${hint("Start points", HELP.startPts)}</div><div class="v">${s.start_points.toFixed(0)}</div><div class="d muted">#${rank("start_points")} of ${n} · ${s.starts} starts</div></div>
  </div></div>
  <div class="card"><h2>Value of pickups on roster over time</h2><div id="wt-legend"></div><div id="wt-line"></div>
    <p class="muted small">Total dynasty value of the pickups this team was holding at each date, vs. the league median.</p></div>
  <div class="card"><h2>All pickups</h2><div class="scroll"><table>
    <thead><tr><th>Date</th><th></th><th>Player</th><th>How</th><th class="num">${hint("At pickup", HELP.atPickup)}</th><th class="num">${hint("Peak held", HELP.peak)}</th>
      <th class="num">Now</th><th class="num">${hint("Captured", HELP.captured)}</th><th class="num">${hint("Start pts", HELP.startPts)}</th><th>Value since pickup</th><th>Outcome</th></tr></thead>
    <tbody>${ps.map(p => `<tr><td class="small">${p.date}<div class="muted">${p.week == null ? `${p.season} offseason` : `${p.season} wk ${p.week}`}</div></td><td>${posBadge(p.pos)}</td><td><b>${esc(p.name)}</b></td>
      <td class="small">${howCell(p)}</td><td class="num">${fmt(p.value_at_pickup)}</td><td class="num">${fmt(p.peak)}</td><td class="num">${fmt(p.now_value)}</td>
      <td class="num"><b>${fmt(p.captured)}</b></td><td class="num">${p.start_points.toFixed(1)}<div class="muted small">${p.starts} starts</div></td>
      <td>${sparkline(p.history)}</td><td class="small">${outcomeCell(p)}</td></tr>`).join("") || '<tr><td colspan="11" class="muted">No pickups.</td></tr>'}</tbody>
  </table></div></div>`;
}

function drawWaiverTeam(W, team) {
  const host = $("#wt-line");
  if (!host) return;
  const key = state.wv.season;
  const mine = team.stats[key].series;
  const med = W.dates.map((_, i) => median(W.teams.map(t => t.stats[key].series[i])));
  const { dates, cut } = trimDates(W.dates, [mine]);
  const series = [
    { id: "median", label: "League median", values: cut(med), highlight: true, color: "var(--chart-muted)" },
    { id: team.roster_id, label: team.manager, values: cut(mine), highlight: true, color: "var(--series-1)" },
  ];
  $("#wt-legend").innerHTML = legendHTML([{ label: team.manager, color: "var(--series-1)" }, { label: "League median", color: "var(--chart-muted)" }]);
  const draw = () => lineChart(host, { dates, series, format: compact, title: `${team.manager} pickup value` });
  draw();
  onResize(draw);
}

// ---------------------------------------------------------------- sortable tables
// Every table with a <thead> sorts by clicking a header (or Enter/Space on it). A cell's
// data-sort overrides its text. The last sort per page + table is remembered.
const sortMemory = {};
function sortKeyOf(td) {
  if (!td) return null;
  const raw = (td.dataset.sort ?? td.textContent).trim();
  if (raw === "" || raw === "–" || raw === "-") return null;
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw;  // ISO dates sort as text
  const m = raw.replace(/−/g, "-").match(/^[+-]?\$?\d[\d,]*(\.\d+)?/);
  return m ? parseFloat(m[0].replace(/[$,+]/g, "")) : raw.toLowerCase();
}
function sortTable(table, col, dir) {
  const body = table.tBodies[0];
  const keyed = [...body.rows].map((r, i) => ({ r, i, k: sortKeyOf(r.cells[col]) }));
  keyed.sort((a, b) => {
    if (a.k === null || b.k === null) return (a.k === null) - (b.k === null) || a.i - b.i;  // blanks last
    const c = typeof a.k === typeof b.k ? (a.k < b.k ? -1 : a.k > b.k ? 1 : 0) : (typeof a.k === "number" ? -1 : 1);
    return (dir === "asc" ? c : -c) || a.i - b.i;
  });
  keyed.forEach(x => body.append(x.r));
  const hdr = table.tHead.rows[table.tHead.rows.length - 1];
  [...hdr.cells].forEach((th, i) => th.classList.contains("sort") && th.setAttribute("aria-sort", i === col ? (dir === "asc" ? "ascending" : "descending") : "none"));
}
function makeSortable(root) {
  $$("table", root).forEach((table, ti) => {
    if (table.hasAttribute("data-nosort") || !table.tHead || !table.tBodies[0]) return;
    const key = `${(location.hash || "#/").split("?")[0]}|${table.id || ti}`;
    const hdr = table.tHead.rows[table.tHead.rows.length - 1];
    [...hdr.cells].forEach((th, ci) => {
      if (!th.textContent.trim() || th.classList.contains("sort")) return;
      th.classList.add("sort"); th.tabIndex = 0; th.setAttribute("aria-sort", "none");
      const go = () => {
        const prev = sortMemory[key];
        const first = [...table.tBodies[0].rows].map(r => sortKeyOf(r.cells[ci])).find(k => k !== null);
        const dir = prev && prev.col === ci ? (prev.dir === "asc" ? "desc" : "asc") : (typeof first === "number" ? "desc" : "asc");
        sortMemory[key] = { col: ci, dir };
        sortTable(table, ci, dir);
      };
      th.addEventListener("click", e => { if (!e.target.closest("a,button,input,select")) go(); });
      th.addEventListener("keydown", e => { if ((e.key === "Enter" || e.key === " ") && e.target === th) { e.preventDefault(); go(); } });
    });
    const mem = sortMemory[key];
    if (mem) sortTable(table, mem.col, mem.dir);
  });
}

// ---------------------------------------------------------------- rankings
const WINDOW_SLOT = { contend: 1, middle: 2, rebuild: 3 };
async function rankingsData() {
  if (!state.rankingsData) state.rankingsData = await api("/api/rankings");
  return state.rankingsData;
}
const mean = a => a.reduce((s, v) => s + v, 0) / (a.length || 1);
function heatCell(team, pos, need, kind) {
  const s = -need;  // strength: + = above league average
  const bin = s >= 1.25 ? ["s3", "strong"] : s >= 0.75 ? ["s2", "mid"] : s >= 0.25 ? ["s1", "weak"] : s > -0.25 ? ["mid", "weak"]
    : s > -0.75 ? ["n1", "weak"] : s > -1.25 ? ["n2", "mid"] : ["n3", "strong"];
  const words = Math.abs(s) < 0.05 ? "right at the league average" : `${Math.abs(s).toFixed(2)} standard deviations ${s > 0 ? "above" : "below"} the league average`;
  return `<td class="hc" data-sort="${s.toFixed(2)}" style="background:var(--div-${bin[0]});color:var(--on-div-${bin[1]})"
    ${tipAttr(`${team} · ${pos} ${kind}: ${words}.`, false)}>${s > 0 ? "+" : ""}${s.toFixed(1)}</td>`;
}

async function viewRankings() {
  const R = await rankingsData();
  const dr = state.dr;
  if (!dr.hl) { dr.hl = R.me ? [R.me] : []; dr.hl.forEach(slotOf); }
  setTimeout(() => drawRankings(R), 0);
  const P = R.positions;
  return `<div class="card"><h1>Franchise rankings</h1>
    <p class="muted">${hint("Franchise score", HELP.franchise)} rates each team's overall state: everything it owns (rostered players plus rookie picks for the next 3 drafts),
      on one value scale, relative to the league average. 100 = average. It measures assets, not this season's strength; see the league map for both together.
      Click any column header to sort.</p></div>
  <div class="card"><h2>Rankings</h2><div class="scroll"><table id="rank-table">
    <thead><tr><th class="num">#</th><th>Team</th><th>${hint("Window", HELP.window)}</th><th class="num">${hint("Franchise score", HELP.franchise)}</th>
      <th class="num">${hint("Total value", HELP.franchiseValue)}</th><th class="num">${hint("Top-10 players", HELP.core)}</th><th class="num">${hint("Depth", HELP.depthValue)}</th>
      <th class="num">${hint("Picks", HELP.pickValue)}</th>${R.pick_seasons.map(s => `<th class="num">${s} picks</th>`).join("")}
      <th class="num">${hint("Win-now", HELP.winnowTotal)}</th><th class="num">${hint("Age", HELP.age)}</th><th>Top players</th></tr></thead>
    <tbody>${R.teams.map(t => `<tr class="click ${t.roster_id === R.me ? "me" : ""}" onclick="location.hash='#/team/${t.roster_id}'">
      <td class="num">${t.franchise_rank}</td><td><b>${esc(t.manager)}</b><div class="muted small">${esc(t.team_name)}</div></td>
      <td data-sort="${t.contend_score}">${windowBadge(t.window)}</td><td class="num"><b>${t.franchise_score}</b></td>
      <td class="num">${fmt(t.franchise_value)}</td><td class="num">${fmt(t.core)}</td><td class="num">${fmt(t.depth)}</td><td class="num">${fmt(t.pick_value)}</td>
      ${R.pick_seasons.map(s => `<td class="num">${fmt(t.pick_seasons[s])}</td>`).join("")}
      <td class="num">${fmt(t.win_now)}</td><td class="num">${t.age}</td>
      <td class="small">${t.top_players.map(p => `${posBadge(p.pos)} ${esc(p.name)}`).join("<br>")}</td></tr>`).join("")}</tbody>
  </table></div></div>
  <div class="grid g2">
    <div class="card"><h2>${hint("League map", HELP.leagueMap)}</h2>
      ${legendHTML([...Object.entries(WINDOW_SLOT).map(([w, s]) => ({ label: WINDOW_LABEL[w], color: `var(--series-${s})`, rect: true }))])}
      <div id="rk-map"></div>
      <p class="muted small">Circled = you. Hover or tab to a dot for details.</p>
      <details class="tableview"><summary>View as table</summary><table>
        <thead><tr><th>Team</th><th>Window</th><th class="num">Win-now</th><th class="num">Franchise value</th></tr></thead>
        <tbody>${R.teams.map(t => `<tr><td>${esc(t.manager)}</td><td>${WINDOW_LABEL[t.window]}</td><td class="num">${fmt(t.win_now)}</td><td class="num">${fmt(t.franchise_value)}</td></tr>`).join("")}</tbody>
      </table></details>
    </div>
    <div class="card"><h2>What each franchise is made of</h2>
      ${legendHTML([{ label: "Top-10 players", color: "var(--series-1)", rect: true }, { label: "Depth", color: "var(--series-2)", rect: true }, { label: "Draft picks", color: "var(--series-3)", rect: true }])}
      <div id="rk-comp"></div>
      <p class="muted small">Total franchise value split into the 10 most valuable players, the rest of the roster, and owned rookie picks.</p>
    </div>
  </div>
  <div class="card"><h2>Roster value over time</h2>
    <div class="row" style="gap:6px;margin-bottom:6px"><span class="flabel">Highlight (up to ${MAX_HL})</span>
      ${R.teams.map(t => { const on = dr.hl.includes(t.roster_id);
        return `<button class="chip ${on ? "on" : ""}" onclick="toggleHL(${t.roster_id})" aria-pressed="${on}"><i class="lk" style="background:${on ? `var(--series-${slotOf(t.roster_id)})` : "var(--context-line)"}"></i>${esc(t.manager)}</button>`; }).join("")}
    </div>
    <div id="rk-legend"></div><div id="rk-line"></div>
    <p class="muted small">Each team's roster at every weekly snapshot, rebuilt by replaying every draft pick, trade and waiver move, valued with DynastyProcess weekly values.
      Players only (there's no history of pick values). Climbs during the startup draft as rosters fill. Hover or focus and use ← → to read values.</p>
  </div>
  <div class="card"><h2>${hint("Positional strength heatmap", HELP.heat)}</h2>
    <div class="row spread"><span class="scale">Need ${["n3", "n2", "n1", "mid", "s1", "s2", "s3"].map(b => `<i style="background:var(--div-${b})"></i>`).join("")} Strength</span>
      <span class="muted small">Numbers = standard deviations from league average. Click a column to sort.</span></div>
    <div class="scroll"><table class="heat" id="rk-heat" style="margin-top:8px">
      <thead><tr><th></th><th class="grp" colspan="${P.length}">Now (starters)</th><th class="grp" colspan="${P.length}">Long-term (dynasty)</th></tr>
        <tr><th>Team</th>${P.map(p => `<th class="num">${p}</th>`).join("")}${P.map(p => `<th class="num">${p}</th>`).join("")}</tr></thead>
      <tbody>${R.teams.map(t => `<tr class="${t.roster_id === R.me ? "me" : ""}"><td><b>${esc(t.manager)}</b></td>
        ${P.map(p => heatCell(t.manager, p, t.need_now[p], "now")).join("")}${P.map(p => heatCell(t.manager, p, t.need_future[p], "long-term")).join("")}</tr>`).join("")}</tbody>
    </table></div>
  </div>
  <div class="card"><h2>Age structure</h2>
    ${legendHTML(R.age_buckets.map((b, i) => ({ label: b.label, color: `var(--age-${i + 1})`, rect: true })))}
    <div id="rk-age"></div>
    <p class="muted small">Share of each team's player value by age (youngest teams first). Rebuilders want value on the left; contenders' value tends to sit older.</p>
    <details class="tableview"><summary>View as table</summary><table>
      <thead><tr><th>Team</th>${R.age_buckets.map(b => `<th class="num">${b.label}</th>`).join("")}<th class="num">Avg age</th></tr></thead>
      <tbody>${R.teams.map(t => `<tr><td>${esc(t.manager)}</td>${R.age_buckets.map(b => `<td class="num">${fmt(t.age_value[b.key])}</td>`).join("")}<td class="num">${t.age}</td></tr>`).join("")}</tbody>
    </table></details>
  </div>`;
}

function drawRankings(R) {
  if (!$("#rk-map")) return;
  const dr = state.dr;
  const drawMap = () => scatter($("#rk-map"), {
    points: R.teams.map(t => ({ id: t.roster_id, label: t.manager, x: t.win_now, y: t.franchise_value, color: `var(--series-${WINDOW_SLOT[t.window]})`,
      highlight: t.roster_id === R.me,
      tip: [["Franchise value", fmt(t.franchise_value)], ["Win-now lineup", fmt(t.win_now)], ["Franchise score", String(t.franchise_score)], ["Window", WINDOW_LABEL[t.window]]] })),
    xLabel: "Win-now strength (starting lineup) →", yLabel: "Franchise value →", refX: mean(R.teams.map(t => t.win_now)), refY: mean(R.teams.map(t => t.franchise_value)),
    quadrants: { tr: "Loaded: strong now and later", tl: "Rebuilding with assets", br: "Win-now, thinner future", bl: "Weak now and later" },
    title: "League map", height: 400,
  });
  const byValue = [...R.teams].sort((a, b) => b.franchise_value - a.franchise_value);
  const drawComp = () => stackedBars($("#rk-comp"), {
    rows: byValue.map(t => ({ label: t.manager, parts: { core: t.core, depth: t.depth, picks: t.pick_value },
      tip: { core: `${fmt(t.core)} value`, depth: `${fmt(t.depth)} value`, picks: `${t.n_picks} picks · ${fmt(t.pick_value)} value` } })),
    keys: ["core", "depth", "picks"], labels: { core: "Top-10 players", depth: "Depth", picks: "Draft picks" },
    max: Math.max(...R.teams.map(t => t.franchise_value)), text: v => compact(v), title: "Franchise value composition",
  });
  const series = R.teams.map(t => {
    const hl = dr.hl.includes(t.roster_id);
    return { id: t.roster_id, label: t.manager, values: t.history, highlight: hl, color: hl ? `var(--series-${slotOf(t.roster_id)})` : null };
  });
  const { dates, cut } = trimDates(R.dates, series.map(s => s.values));
  series.forEach(s => (s.values = cut(s.values)));
  $("#rk-legend").innerHTML = legendHTML([
    ...dr.hl.map(rid => ({ label: R.teams.find(t => t.roster_id === rid).manager, color: `var(--series-${slotOf(rid)})` })),
    { label: "Other teams", color: "var(--context-line)" },
  ]);
  const drawLine = () => lineChart($("#rk-line"), { dates, series, format: compact, title: "Roster value over time" });
  const keys = R.age_buckets.map(b => b.key);
  const drawAge = () => stackedBars($("#rk-age"), {
    rows: [...R.teams].sort((a, b) => a.age - b.age).map(t => {
      const tot = keys.reduce((s, k) => s + t.age_value[k], 0) || 1;
      return { label: t.manager, parts: Object.fromEntries(keys.map(k => [k, t.age_value[k] / tot * 100])),
        tip: Object.fromEntries(keys.map(k => [k, `${fmt(t.age_value[k])} value`])) };
    }),
    keys, labels: Object.fromEntries(R.age_buckets.map(b => [b.key, b.label])), max: 100,
    colors: keys.map((_, i) => `var(--age-${i + 1})`), onColors: keys.map((_, i) => `var(--on-age-${i + 1})`), title: "Age structure",
  });
  drawMap(); drawComp(); drawLine(); drawAge();
  onResize(drawMap, drawComp, drawLine, drawAge);
}

// ---------------------------------------------------------------- opportunity: waiver wire + breakouts
const SIGNAL_LABEL = { rising: "Rising role", efficient: "Efficient", vacancy_now: "Opening now", vacancy_next: "Path opening", fa_move: "Contract-year backup", injured: "Injured stash" };
const SIGNAL_HELP = {
  rising: "His share of snaps, or of his team's opportunities at his position, is up over the last 3 games.",
  efficient: "Scores more fantasy points per opportunity (carries + 1.5× targets; dropbacks for QBs) than the median regular at his position, so a bigger role should pay off. The strongest signal in backtests: it predicted value gains in every season tested.",
  vacancy_now: "A player ahead of him on the depth chart is out right now. Full credit when that player is on IR or PUP, half for a likely short absence (Out, Doubtful, suspended). No credit if he's on IR himself, since the starter will probably be back first.",
  injured: "He's on IR or PUP himself. Any breakout case is about next season, not now. Injuries ahead of him don't count toward his score.",
  vacancy_next: "A player ahead of him may not be back next season: contract ending, or the team can cut him cheaply. Shown for context only, and not counted in the score: in backtests these players did worse than average every season, because teams usually bring in a replacement.",
  fa_move: "His contract ends this season while he's stuck behind a starter, so he may sign somewhere with a bigger role. This is the Isaiah Likely path. It predicted value gains in every season tested.",
};
Object.assign(HELP, {
  breakout: "0–100. How strongly usage, depth-chart and contract signals point to a bigger role ahead. It's discounted for players who already have a full role, who are already valued as stars, or who are past age 25. Hover a player's signal tags for the specifics.",
  oppScore: "0–100. His current role: share of his team's opportunities at his position (carries + 1.5× targets, or dropbacks for QBs), blended with snap share over the last 3 games.",
  pickupScore: "His value to your team (dynasty value adjusted for your window and positional needs, the same as in trades), plus a breakout allowance of up to 750 at a breakout score of 100.",
  snaps: "Share of his team's offensive snaps over his last 3 games (whole season below).",
  share: "His share of his team's weighted opportunities at his position over the last 3 games: carries + 1.5× targets, or dropbacks for QBs.",
  eff: "Fantasy points per opportunity vs. the median regular at his position, pooling this season and half of last season. 1.00× = median.",
  depthChart: "His place on his NFL team's depth chart, ranked by opportunities per game (recent games weighted up), with Sleeper's depth chart as the tiebreaker.",
  contract: "Final season of his current contract (OverTheCap via nflverse) and its average annual value. Hover for whether he's likely to be back.",
  bid: "Suggested FAAB bid: the median winning bid on the 8 most similar-value claims in this league over the last two seasons, with the middle half of those bids as the range.",
  gain: "Pickup score of the player minus the pickup score of the player you'd drop.",
  drops: "Your lowest pickup scores among active (non-taxi, non-IR) players: the cheapest roster spots to open.",
  backtest: "The model run as it would have looked at the end of each past season (that season's usage, contracts in force then and values then), compared with values a year later. Players already worth 4,000+ are excluded. A hit gained 500+ value.",
  shakeup: "Starters who may not be on their team next season (contract ending, or cheap to cut) or who are out now, and the next players in line behind them.",
});
const pctCell = v => (v == null ? "–" : `${Math.round(v * 100)}%`);
const sigChips = a => ((a.opp || {}).notes || []).map(n => `<span class="badge tag sig" ${tipAttr(`${n.text}. ${SIGNAL_HELP[n.key]}`)}>${SIGNAL_LABEL[n.key]}</span>`).join(" ");
const boCell = a => `<td class="num" data-sort="${a.breakout}"><b class="${a.breakout >= 40 ? "bo-hi" : ""}">${a.breakout}</b></td>`;
function roleCells(a) {
  const r = (a.opp || {}).role;
  if (!r) return `<td class="num">–</td>`.repeat(4);
  return `<td class="num" data-sort="${r.snap_l3}">${pctCell(r.snap_l3)}<div class="muted small">${pctCell(r.snap)} season</div></td>
    <td class="num" data-sort="${r.share_l3}">${pctCell(r.share_l3)}</td><td class="num">${r.ppg.toFixed(1)}</td>
    <td class="num" data-sort="${r.eff ?? ""}">${r.eff == null ? "–" : r.eff.toFixed(2) + "×"}</td>`;
}
function depthCell(a) {
  const d = (a.opp || {}).depth;
  if (!d || !d.label) return `<td class="muted">–</td>`;
  const ahead = d.ahead.map(q => `${esc(q.name)}${q.injury ? ` <span class="delta-neg">${esc(q.injury)}</span>` : ""}`).join(", ");
  return `<td data-sort="${d.rank}">${esc(a.nfl_team)} ${esc(d.label)}${ahead ? `<div class="muted small">behind ${ahead}</div>` : ""}</td>`;
}
function contractCell(a, season) {
  const c = (a.opp || {}).contract;
  if (!c || c.end == null) return `<td class="muted" data-sort="">–</td>`;
  const tip = c.leave_why || `Under contract through ${c.end}.`;
  return `<td data-sort="${c.end}"><span class="has-tip ${c.end <= season ? "delta-neg" : ""}" ${tipAttr(tip)}>${c.end}</span>${c.apy ? `<div class="muted small">$${c.apy.toFixed(1)}M/yr</div>` : ""}</td>`;
}
const metaLine = a => `<div class="muted small">${assetMeta(a)}${a.years_exp != null ? ` · yr ${a.years_exp + 1}` : ""}</div>`;
const playerCell = a => `<td><b>${playerLink(a.id, a.name)}</b>${metaLine(a)}</td>`;
const usageNote = W => W.weeks ? `usage from weeks 1–${W.weeks} of ${W.role_season}` : "no usage data yet";

async function pickupsData() {
  if (!state.pickupsData) state.pickupsData = await api("/api/pickups");
  return state.pickupsData;
}
async function breakoutsData() {
  if (!state.breakoutsData) state.breakoutsData = await api("/api/breakouts");
  return state.breakoutsData;
}

state.wire = { pos: "", q: "" };
async function viewPickups() {
  const [W, ov] = await Promise.all([pickupsData(), overview()]);
  const season = ov.league.season;
  setTimeout(() => wirePickups(W, season), 0);
  const dropTxt = s => s.taxi_ok ? '<span class="pos-good">Taxi slot open</span>' : s.drop ? `${posBadge(s.drop.asset.pos)} ${esc(s.drop.asset.name)} <span class="muted small">${fmt(s.drop.score)}</span>` : '<span class="pos-good">Open roster spot</span>';
  return `${W.error ? `<div class="warnbox">Usage/contract data failed to load (${esc(W.error)}); suggestions use values only.</div>` : ""}
  <div class="card"><h1>Free agents</h1>
    <p class="muted">Every available QB/RB/WR/TE on an NFL roster, scored for your team. ${hint("Pickup score", HELP.pickupScore)} = what he's worth to you now
      plus a ${hint("breakout", HELP.breakout)} allowance for role growth (rising usage, efficiency, openings on his depth chart and contract situations).
      Based on ${usageNote(W)}, OverTheCap contracts, and your league's past claims for bids.</p>
    <div class="tiles">
      <div class="tile"><div class="k">Active roster</div><div class="v">${W.active}/${W.roster_limit}</div><div class="d muted">${W.open_spots ? `${W.open_spots} open spot(s)` : "Full: every add needs a drop"}</div></div>
      <div class="tile"><div class="k">Open taxi slots</div><div class="v">${W.open_taxi}</div><div class="d muted">for players in their first ${W.taxi_years} seasons</div></div>
      <div class="tile"><div class="k">${hint("FAAB left", HELP.faab)}</div><div class="v">$${W.faab_left}</div><div class="d muted">of $${W.budget}</div></div>
      <div class="tile"><div class="k">Past claims used for bids</div><div class="v">${W.n_claims}</div><div class="d muted">winning claims, last 2 seasons</div></div>
    </div></div>
  <div class="card"><h2>Suggested adds for you</h2>
    <div class="scroll"><table id="wire-sugg">
      <thead><tr><th></th><th>Player</th><th class="num">Value</th><th class="num">${hint("Breakout", HELP.breakout)}</th><th class="num">${hint("Pickup score", HELP.pickupScore)}</th>
        <th>Why</th><th>${hint("Drop", HELP.drops)}</th><th class="num">${hint("Gain", HELP.gain)}</th><th class="num">${hint("Bid", HELP.bid)}</th></tr></thead>
      <tbody>${W.suggestions.map(s => { const a = s.asset;
        return `<tr><td>${posBadge(a.pos)}</td>${playerCell(a)}<td class="num">${fmt(a.value)}</td>${boCell(a)}<td class="num"><b>${fmt(s.score)}</b></td>
          <td class="small">${s.why.length ? `<ul class="notes" style="margin:0">${s.why.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : '<span class="muted">Best value available</span>'}</td>
          <td class="small">${dropTxt(s)}</td><td class="num delta-pos">+${fmt(s.gain)}</td>
          <td class="num" data-sort="${s.bid.mid}"><b>$${s.bid.mid}</b><div class="muted small">$${s.bid.lo}–$${s.bid.hi}</div></td></tr>`; }).join("")
        || '<tr><td colspan="9" class="muted">Nobody available beats the weakest player on your roster right now.</td></tr>'}</tbody>
    </table></div>
    <p class="muted small">Only players who beat your weakest active player by 50+ points are shown. Bids assume he's on waivers; once he clears, he's free.</p>
  </div>
  <div class="grid g2">
    <div class="card"><h2>Available players: upside vs. value to you</h2>
      ${legendHTML([{ label: "Suggested adds", color: "var(--series-1)" }, { label: "Other available players", color: "var(--context-line)" }])}
      <div id="wire-map"></div>
      <p class="muted small">Top 120 available players by pickup score. The vertical line is a breakout score of 40; the horizontal line is your weakest active player. Hover or tab to a dot for details.</p>
    </div>
    <div class="card"><h2>${hint("Drop candidates", HELP.drops)}</h2><table>
      <thead><tr><th></th><th>Player</th><th class="num">Value</th><th class="num">${hint("Breakout", HELP.breakout)}</th><th class="num">${hint("Pickup score", HELP.pickupScore)}</th></tr></thead>
      <tbody>${W.drops.map(d => `<tr><td>${posBadge(d.asset.pos)}</td>${playerCell(d.asset)}<td class="num">${fmt(d.asset.value)}</td>${boCell(d.asset)}<td class="num"><b>${fmt(d.score)}</b></td></tr>`).join("")}</tbody>
    </table></div>
  </div>
  <div class="card"><div class="row spread"><h2>All available players</h2>
      <div class="row"><input id="w-q" placeholder="Search name / NFL team" value="${esc(state.wire.q)}">
        <select id="w-pos"><option value="">All positions</option>${["QB", "RB", "WR", "TE"].map(p => `<option ${state.wire.pos === p ? "selected" : ""}>${p}</option>`).join("")}</select></div></div>
    <div class="scroll"><table id="w-table"><thead><tr><th></th><th>Player</th><th class="num">Value</th><th class="num">Win-now</th>
      <th class="num">${hint("Breakout", HELP.breakout)}</th><th class="num">${hint("Opp.", HELP.oppScore)}</th><th class="num">${hint("Snaps", HELP.snaps)}</th>
      <th class="num">${hint("Share", HELP.share)}</th><th class="num">PPG</th><th class="num">${hint("Eff.", HELP.eff)}</th><th>${hint("Depth", HELP.depthChart)}</th>
      <th>${hint("Contract", HELP.contract)}</th><th>Signals</th><th class="num">${hint("Pickup score", HELP.pickupScore)}</th></tr></thead><tbody></tbody></table></div>
  </div>`;
}
function wirePickups(W, season) {
  if (!$("#w-table")) return;
  const draw = () => {
    state.wire.q = $("#w-q").value; state.wire.pos = $("#w-pos").value;
    const q = state.wire.q.toLowerCase(), pos = state.wire.pos;
    const rows = W.available.filter(r => (!pos || r.asset.pos === pos) && (!q || `${r.asset.name} ${r.asset.nfl_team}`.toLowerCase().includes(q))).slice(0, 200);
    $("#w-table tbody").innerHTML = rows.map(({ asset: a, score }) => `<tr><td>${posBadge(a.pos)}</td>${playerCell(a)}
      <td class="num">${fmt(a.value)}</td><td class="num">${fmt(a.redraft)}</td>${boCell(a)}<td class="num">${a.opp_score ?? "–"}</td>${roleCells(a)}
      ${depthCell(a)}${contractCell(a, season)}<td>${sigChips(a)}</td><td class="num"><b>${fmt(score)}</b></td></tr>`).join("")
      || '<tr><td colspan="14" class="muted">No matches.</td></tr>';
    makeSortable($("#w-table").parentElement);
  };
  ["#w-q", "#w-pos"].forEach(s => $(s).addEventListener("input", draw));
  draw();
  const sugg = new Set(W.suggestions.map(s => s.asset.id));
  const pts = W.available.slice(0, 120).map(r => ({
    id: r.asset.id, label: r.asset.name, x: r.asset.breakout, y: r.score, labeled: sugg.has(r.asset.id), highlight: false,
    color: sugg.has(r.asset.id) ? "var(--series-1)" : "var(--context-line)",
    tip: [["Pickup score", fmt(r.score)], ["Breakout", String(r.asset.breakout)], ["Value", fmt(r.asset.value)], ["Team", `${r.asset.pos} · ${r.asset.nfl_team}`]],
  }));
  if (!pts.length) return;
  const drawMap = () => scatter($("#wire-map"), {
    points: pts, xDomain: [0, 100], xLabel: "Breakout score →", yLabel: "Pickup score →", xFormat: v => String(Math.round(v)),
    refX: 40, refY: W.drops.length ? W.drops[0].score : null, hitRadius: 9, title: "Available players", height: 360,
  });
  drawMap();
  onResize(drawMap);
}

state.bo = { avail: "all", pos: "" };
function setBo(k, v) { state.bo[k] = v; route(); }
window.setBo = setBo;
const boSeg = (label, key, options) => `<div><span class="flabel">${label}</span><span class="seg">${options.map(([v, l]) =>
  `<button class="${state.bo[key] === v ? "on" : ""}" onclick='setBo("${key}", ${JSON.stringify(v)})'>${esc(l)}</button>`).join("")}</span></div>`;
const AVAIL = { mine: ["You", 1], other: ["Other teams", 2], fa: ["Free agents", 3] };
const availOf = (r, me) => r.owner_rid == null ? "fa" : r.owner_rid === me ? "mine" : "other";
function ownerCell(r, me) {
  if (r.owner_rid == null) return `<td data-sort="free agent"><a href="#/pickups">Free agent</a></td>`;
  if (r.owner_rid === me) return `<td data-sort="you"><b>You</b></td>`;
  return `<td><a href="#/team/${r.owner_rid}">${esc(r.owner)}</a>${r.owner_window ? `<div class="small">${windowBadge(r.owner_window)}</div>` : ""}</td>`;
}
const tradeBtn = (r, me) => r.owner_rid != null && r.owner_rid !== me
  ? `<button onclick='openInEvaluator(${JSON.stringify({ b: r.owner_rid, aGives: [], bGives: [{ kind: "player", id: r.id }] })})'>Trade for</button>` : "";

async function viewBreakouts() {
  const [B, ov] = await Promise.all([breakoutsData(), overview()]);
  const season = ov.league.season, me = B.me, bo = state.bo;
  const rows = B.players.filter(r => (bo.avail === "all" || availOf(r, me) === bo.avail) && (!bo.pos || r.pos === bo.pos));
  const faMovers = rows.filter(r => (r.opp?.signals?.fa_move || 0) > 0).slice(0, 25);
  setTimeout(() => { drawBreakouts(B, rows); loadBacktest(); }, 0);
  const nextTxt = n => `<b>${esc(n.name)}</b> <span class="small muted">${esc(n.depth || "")}${n.age ? ` · ${n.age}y` : ""} · ${fmt(n.value)} · breakout ${n.breakout} · ${n.owner_rid == null ? "free agent" : n.owner_rid === me ? "<b>yours</b>" : esc(n.owner)}</span>`;
  return `${B.error ? `<div class="warnbox">Usage/contract data failed to load (${esc(B.error)}).</div>` : ""}
  <div class="card"><h1>Breakout watch</h1>
    <p class="muted">Players whose role is likely to grow before the market prices it in: ${Object.keys(SIGNAL_LABEL).filter(k => k !== "injured").map(k => `<span class="badge tag" ${tipAttr(SIGNAL_HELP[k])}>${SIGNAL_LABEL[k]}</span>`).join(" ")}.
      Free agents are pickup targets; players on other teams are buy-low ${hint("trade targets", "In trade suggestions, rebuilding teams value breakout upside up to 15% more, and suggestions flag players to buy before a breakout.")}. Based on ${usageNote(B)} and OverTheCap contracts.</p>
    <div id="bo-bt-tiles"><p class="muted small">Running the backtest… The first time, this downloads several seasons of history and can take a minute.</p></div></div>
  <div class="filters">${boSeg("Show", "avail", [["all", "Everyone"], ["fa", "Free agents"], ["other", "Trade targets"], ["mine", "My roster"]])}
    ${boSeg("Position", "pos", [["", "All"], ["QB", "QB"], ["RB", "RB"], ["WR", "WR"], ["TE", "TE"]])}</div>
  <div class="card"><h2>Breakout score vs. dynasty value</h2>
    ${legendHTML(Object.values(AVAIL).map(([l, s]) => ({ label: l, color: `var(--series-${s})` })))}
    <div id="bo-map"></div>
    <p class="muted small">The ${Math.min(150, rows.length)} highest breakout scores in this view; the top 12 are labeled. Lower right = upside the market hasn't priced in yet. Hover or tab to a dot for details.</p>
  </div>
  <div class="card"><h2>Breakout board</h2><div class="scroll"><table id="bo-table">
    <thead><tr><th></th><th>Player</th><th>Owner</th><th class="num">Value</th><th class="num">30d</th><th class="num">${hint("Breakout", HELP.breakout)}</th>
      <th class="num">${hint("Opp.", HELP.oppScore)}</th><th class="num">${hint("Snaps", HELP.snaps)}</th><th class="num">${hint("Share", HELP.share)}</th><th class="num">PPG</th>
      <th class="num">${hint("Eff.", HELP.eff)}</th><th>${hint("Depth", HELP.depthChart)}</th><th>${hint("Contract", HELP.contract)}</th><th>Signals</th><th></th></tr></thead>
    <tbody>${rows.slice(0, 150).map(r => `<tr class="${r.owner_rid === me ? "me" : ""}"><td>${posBadge(r.pos)}</td>${playerCell(r)}${ownerCell(r, me)}
      <td class="num">${fmt(r.value)}</td><td class="num ${signCls(r.trend)}">${r.trend ? (r.trend > 0 ? "+" : "") + fmt(r.trend) : ""}</td>${boCell(r)}<td class="num">${r.opp_score ?? "–"}</td>
      ${roleCells(r)}${depthCell(r)}${contractCell(r, season)}<td>${sigChips(r)}</td><td>${tradeBtn(r, me)}</td></tr>`).join("") || '<tr><td colspan="15" class="muted">No players.</td></tr>'}</tbody>
  </table></div></div>
  <div class="card"><h2>Contract-year backups <span class="muted small">(the Isaiah Likely watchlist)</span></h2>
    <p class="muted small">${SIGNAL_HELP.fa_move}</p>
    <div class="scroll"><table><thead><tr><th></th><th>Player</th><th>Owner</th><th class="num">Value</th><th class="num">${hint("Breakout", HELP.breakout)}</th><th>${hint("Depth", HELP.depthChart)}</th>
      <th class="num">${hint("Eff.", HELP.eff)}</th><th>${hint("Contract", HELP.contract)}</th><th></th></tr></thead>
      <tbody>${faMovers.map(r => `<tr class="${r.owner_rid === me ? "me" : ""}"><td>${posBadge(r.pos)}</td>${playerCell(r)}${ownerCell(r, me)}<td class="num">${fmt(r.value)}</td>${boCell(r)}
        ${depthCell(r)}<td class="num">${r.opp?.role?.eff == null ? "–" : r.opp.role.eff.toFixed(2) + "×"}</td>${contractCell(r, season)}<td>${tradeBtn(r, me)}</td></tr>`).join("") || '<tr><td colspan="9" class="muted">None in this view.</td></tr>'}</tbody>
    </table></div></div>
  <div class="card"><h2>${hint("Depth-chart shake-ups", HELP.shakeup)}</h2>
    <p class="muted small">If the starter leaves, these are the players who move up. Sorted by the best breakout score behind each starter.</p>
    <div class="scroll"><table><thead><tr><th>NFL team</th><th>Starter</th><th>Why he may not be there</th><th class="num">Leave risk</th><th>Next in line</th></tr></thead>
      <tbody>${B.shakeups.filter(s => !bo.pos || s.pos === bo.pos).slice(0, 40).map(s => `<tr>
        <td><b>${esc(s.team)}</b> ${posBadge(s.pos)}</td>
        <td><b>${esc(s.starter.name)}</b><div class="muted small">${s.starter.age ?? "?"}y · ${fmt(s.starter.value)}${s.starter.owner ? ` · ${esc(s.starter.owner)}` : ""}</div></td>
        <td class="small">${s.out_now ? `<span class="delta-neg">${esc(s.starter.injury)} now.</span> ` : ""}${esc(s.starter.leave_why || "")}</td>
        <td class="num" data-sort="${s.starter.leave_p ?? 0}">${s.starter.leave_p != null ? Math.round(s.starter.leave_p * 100) + "%" : "–"}</td>
        <td class="small">${s.next.map(nextTxt).join("<br>")}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">None.</td></tr>'}</tbody>
    </table></div>
    <p class="muted small">Leave risk is a rough rule of thumb, not a forecast: about 55% for an expiring deal, 70% if he's also past the age cliff, 25% for a productive starter (usually extended or tagged), and 30–45% for an aging player the team can cut cheaply.</p>
  </div>
  <div id="bo-bt-card"></div>`;
}
async function loadBacktest() {
  const tiles = $("#bo-bt-tiles");
  if (!tiles) return;
  let R;
  try { R = state.backtestData || (state.backtestData = await api("/api/backtest")); }
  catch (e) { tiles.innerHTML = `<p class="small delta-neg">Backtest unavailable: ${esc(e.message)}</p>`; return; }
  if (!$("#bo-bt-tiles")) return;
  if (!R.pooled) { tiles.innerHTML = ""; return; }
  const P = R.pooled, L = R.latest, S = R.spotlight;
  const yrs = P.seasons.length > 1 ? `${P.seasons[0]}–${P.seasons[P.seasons.length - 1]}` : String(P.seasons[0]);
  tiles.innerHTML = `<div class="tiles">
    <div class="tile"><div class="k">${hint(`Backtest: top ${P.top} hit rate`, HELP.backtest)}</div><div class="v">${Math.round(P.top_hit_rate * 100)}%</div>
      <div class="d muted">gained ${fmt(P.hit)}+ value within a year · vs ${(P.base_hit_rate * 100).toFixed(1)}% of all players · ${yrs} seasons</div></div>
    <div class="tile"><div class="k">${hint("Backtest: value vs. similar players", HELP.backtest)}</div><div class="v">${P.top_excess > 0 ? "+" : ""}${fmt(P.top_excess)}</div>
      <div class="d muted">average for the top ${P.top} each season, over the next year</div></div>
    ${S ? `<div class="tile"><div class="k">Isaiah Likely, end of ${S.as_of}</div><div class="v">#${S.rank}</div>
      <div class="d muted">of ${S.n} · score ${S.breakout}${S.notes.length ? ` · ${S.notes.map(n => SIGNAL_LABEL[n.key]).join(", ").toLowerCase()}` : ""} · ${fmt(S.then)} → ${fmt(S.now)}</div></div>` : ""}
  </div>`;
  const btRow = r => `<tr><td class="num">${r.rank}</td><td>${posBadge(r.pos)}</td><td><b>${esc(r.name)}</b><div class="muted small">${esc(r.team)}${r.now_team && r.now_team !== r.team ? ` → ${esc(r.now_team)}` : ""}</div></td>
    <td class="num">${r.breakout}</td><td class="num">${fmt(r.then)}</td><td class="num">${fmt(r.now)}</td><td class="num ${signCls(r.change)}">${r.change > 0 ? "+" : ""}${fmt(r.change)}</td>
    <td>${(r.notes || []).map(n => `<span class="badge tag" ${tipAttr(n.text + ".")}>${SIGNAL_LABEL[n.key]}</span>`).join(" ")}</td></tr>`;
  const btHead = `<thead><tr><th class="num">Rank</th><th></th><th>Player</th><th class="num">Score then</th><th class="num">Value then</th><th class="num">Later</th><th class="num">Change</th><th>Signals then</th></tr></thead>`;
  $("#bo-bt-card").innerHTML = `<div class="card"><h2>${hint("Model check: how past flags did", HELP.backtest)}</h2>
    <p class="muted small">The model as it would have looked at the end of each season, compared with values about a year later (the latest season: up to now).
      Injuries aren't known historically, so the "opening now" signal is off in backtests.</p>
    <div class="scroll"><table><thead><tr><th>Season</th><th>Judged</th><th class="num">Players</th><th class="num">Top ${P.top} hits</th><th class="num">Hit rate</th><th class="num">Base rate</th><th class="num">Vs. similar players</th></tr></thead>
      <tbody>${R.by_season.map(x => `<tr><td>${x.as_of}</td><td class="small">${esc(x.then_date)} → ${esc(x.now_date)}</td><td class="num">${x.n}</td><td class="num">${x.top_hits}</td>
        <td class="num"><b>${Math.round(x.top_hit_rate * 100)}%</b></td><td class="num">${(x.base_hit_rate * 100).toFixed(1)}%</td><td class="num">${signed(x.top_excess)}</td></tr>`).join("")}</tbody></table></div>
    <div class="grid g2" style="margin-top:10px">
      <div><h3>Top ${L.top} breakout scores, end of ${L.as_of}</h3><div class="scroll"><table>${btHead}<tbody>${L.picks.map(btRow).join("")}</tbody></table></div></div>
      <div><h3>Biggest risers since ${L.as_of}, and where the model ranked them</h3><div class="scroll"><table>${btHead}<tbody>${L.risers.map(btRow).join("")}</tbody></table></div></div>
    </div></div>`;
  makeSortable($("#bo-bt-card"));
}
function drawBreakouts(B, rows) {
  const host = $("#bo-map");
  if (!host || !rows.length) return;
  const top = rows.slice(0, 150), labeled = new Set(top.slice(0, 12).map(r => r.id));
  const pts = top.map(r => { const [lab, s] = AVAIL[availOf(r, B.me)];
    return { id: r.id, label: r.name, x: r.breakout, y: r.value, labeled: labeled.has(r.id), highlight: false, color: `var(--series-${s})`,
      tip: [["Breakout", String(r.breakout)], ["Value", fmt(r.value)], ["Owner", r.owner_rid == null ? "Free agent" : r.owner_rid === B.me ? "You" : r.owner], ["Role", `${r.pos} · ${r.nfl_team} ${(r.opp?.depth?.label) || ""}`]] }; });
  const draw = () => scatter(host, {
    points: pts, xDomain: [0, 100], xLabel: "Breakout score →", yLabel: "Dynasty value →", xFormat: v => String(Math.round(v)), refX: 40, hitRadius: 9,
    quadrants: { br: "Cheap upside: add or buy", tr: "Valued and still rising", tl: "Priced in" }, title: "Breakout score vs. dynasty value", height: 400,
  });
  draw();
  onResize(draw);
}

// ---------------------------------------------------------------- record book
async function recordsData() {
  if (!state.recordsData) state.recordsData = await api("/api/records");
  return state.recordsData;
}
const pts2 = n => Number(n).toFixed(2);
const wk = x => `${x.season} wk ${x.week}${x.playoffs ? " (playoffs)" : ""}`;
// One record: the holder big, runners-up below. row(x) -> [holderHtml, valueHtml, detailHtml].
// expand(x), if given, returns details HTML shown when an entry is expanded.
function recordCard(title, help, rows, row, me, expand) {
  if (!rows || !rows.length) return "";
  const [top, ...rest] = rows;
  const [h, v, d] = row(top);
  const mine = x => x.manager === me || x.winner === me || x.loser === me || x.champion === me;
  const more = x => expand ? `<details class="rec-more"><summary>Show trade</summary>${expand(x)}</details>` : "";
  return `<div class="card record">
    <div class="k">${help ? hint(esc(title), help) : esc(title)}</div>
    <div class="row spread"><div class="holder ${mine(top) ? "mine" : ""}">${h}</div><div class="v">${v}</div></div>
    <div class="muted small">${d}</div>${more(top)}
    ${rest.length ? `<ol class="runners" start="2">${rest.map(x => { const [rh, rv, rd] = row(x);
      return `<li class="${mine(x) ? "mine" : ""}"><span>${rh} <span class="muted">${rd}</span></span><span class="num">${rv}</span>${more(x)}</li>`; }).join("")}</ol>` : ""}
  </div>`;
}
// One side of a trade: what that manager received, valued then and now. Picks show who they became.
function tradeAssetsHTML(x) {
  const asset = a => {
    const p = a.pick;
    const label = p ? `${esc(p.label)}${p.orig ? ` <span class="muted">(${esc(p.orig)}'s)</span>` : ""}${p.became ? `<div class="became">→ ${posBadge(p.became_pos)} ${esc(p.became)}</div>` : '<div class="became muted">not used yet</div>'}` : esc(a.name);
    return `<tr><td>${posBadge(p ? "PICK" : a.pos)}</td><td>${label}</td><td class="num muted">${fmt(a.then)} →</td><td class="num"><b>${fmt(a.now)}</b></td></tr>`;
  };
  return `<div class="rec-trade">${x.sides.map(s => `<div><div class="side-h">${esc(s.manager)} got</div>
    <table data-nosort class="small"><tbody>${s.received.map(asset).join("") || '<tr><td class="muted">Nothing</td></tr>'}</tbody></table>
    ${s.faab ? `<div class="small muted">+ $${s.faab} FAAB</div>` : ""}<div class="small muted">${fmt(s.points)} start points from these players</div></div>`).join("")}
    <div class="small muted rec-gaps">At the time: ${x.then_gap.leader ? `${esc(x.then_gap.leader)} +${fmt(x.then_gap.gap)}` : "even"} · Today: ${x.now_gap.leader ? `${esc(x.now_gap.leader)} +${fmt(x.now_gap.gap)}` : "even"} · <a href="#/history">Trade history</a></div></div>`;
}
Object.assign(HELP, {
  titles: "Championships: winners of the final in Sleeper's playoff bracket.",
  finals: "Appearances in the championship game.",
  allTimeRecord: "Regular-season games only, across every season in the league's history (including linked leagues before a restart).",
  franchisePlayer: "Most fantasy points one player scored in one manager's starting lineup, summed across every season.",
  classChange: "Value now of every player the team drafted in that class vs. their value on draft day, in %. Startup and rookie drafts are ranked separately.",
  swing: "How far the trade moved: the gap for the side ahead at the time plus the gap for the side ahead today.",
});

async function viewRecords() {
  const [R, ov] = await Promise.all([recordsData(), overview()]);
  const me = (ov.teams.find(t => t.is_me) || {}).manager;
  const G = R.games, S = R.season_records, P = R.players, T = R.trades, D = R.drafts, W = R.pickups;
  const early = c => c.early ? ` <span class="badge res-even" ${tipAttr(`Value history starts ${R.value_history_start}, so this class is measured from then, not from draft day.`)}>since ${esc(R.value_history_start)}</span>` : "";
  const tradeRow = x => [`<b>${esc(x.winner)}</b> over ${esc(x.loser || "")}`, `+${fmt(x.gap)}`,
    `${esc(x.date)} · ${x.pct.toFixed(0)}% of the deal`];
  const classRow = x => [`<b>${esc(x.manager)}</b>${early(x)}`, `${x.change_pct > 0 ? "+" : ""}${x.change_pct.toFixed(1)}%`,
    `${esc(x.draft)} · ${x.n} picks · ${fmt(x.draft_value)} → ${fmt(x.now_value)}${x.best ? ` · best: ${esc(x.best.name)}` : ""}`];
  const pickRow = x => [`${posBadge(x.pos)} <b>${esc(x.name)}</b>`, signed(x.change), `${esc(x.manager)} · ${esc(x.draft)} ${esc(x.pick)} · ${fmt(x.draft_value)} → ${fmt(x.now_value)}`];
  const wvRow = (x, v) => [`${posBadge(x.pos)} <b>${esc(x.name)}</b>`, v, `${esc(x.manager)} · ${esc(x.date)} · ${x.type === "claim" ? `claim $${x.bid}` : "free agent"} · ${esc(x.outcome)}`];
  const section = (title, cards) => { const body = cards.join(""); return body ? `<h2 class="sec">${title}</h2><div class="grid g3">${body}</div>` : ""; };
  return `<div class="card"><h1>Record book</h1>
    <p class="muted">All-time records across ${R.seasons.length} season${R.seasons.length === 1 ? "" : "s"} (${[...R.seasons].sort().join(", ")}) and ${fmt(R.n_games)} games.
      Each team is credited to whoever managed it that season. Your entries are highlighted.
      Trade, draft and pickup records use the weekly value history, which starts ${esc(R.value_history_start || "–")}.</p>
    ${R.champions.length ? `<div class="tiles">${R.champions.map(c => `<div class="tile ${c.champion === me ? "mine" : ""}"><div class="k">${c.season} champion</div>
      <div class="v">🏆 ${esc(c.champion)}</div><div class="d muted">runner-up ${esc(c.runner_up)}</div></div>`).join("")}</div>` : '<p class="muted">No completed seasons yet.</p>'}
  </div>
  <div class="card"><h2>All-time standings</h2><div class="scroll"><table>
    <thead><tr><th>Manager</th><th class="num">Seasons</th><th class="num">${hint("Titles", HELP.titles)}</th><th class="num">${hint("Finals", HELP.finals)}</th>
      <th>${hint("Record", HELP.allTimeRecord)}</th><th class="num">Win %</th><th class="num">Points</th><th class="num">PPG</th><th class="num">Best game</th></tr></thead>
    <tbody>${R.standings.map(s => `<tr class="${s.manager === me ? "me" : ""}"><td><b>${esc(s.manager)}</b></td><td class="num">${s.seasons}</td>
      <td class="num">${s.titles ? "🏆".repeat(s.titles) : "0"}</td><td class="num">${s.finals}</td>
      <td data-sort="${s.w - s.l}">${s.w}–${s.l}${s.t ? "–" + s.t : ""}</td><td class="num">${(s.win_pct * 100).toFixed(1)}%</td>
      <td class="num">${fmt(s.pf)}</td><td class="num">${s.ppg.toFixed(1)}</td><td class="num">${pts2(s.high)}</td></tr>`).join("")}</tbody>
  </table></div><p class="muted small">Sorted by titles, then win %. Click a column to sort.</p></div>
  ${section("Games", [
    recordCard("Highest score", "", G.high, x => [`<b>${esc(x.manager)}</b>`, pts2(x.points), `${wk(x)} · vs ${esc(x.opp)} (${pts2(x.opp_points)})`], me),
    recordCard("Lowest score", "Regular season only.", G.low, x => [`<b>${esc(x.manager)}</b>`, pts2(x.points), `${wk(x)} · vs ${esc(x.opp)} (${pts2(x.opp_points)})`], me),
    recordCard("Biggest blowout", "", G.blowouts, x => [`<b>${esc(x.manager)}</b> over ${esc(x.opp)}`, `+${pts2(x.margin)}`, `${wk(x)} · ${pts2(x.points)}–${pts2(x.opp_points)}`], me),
    recordCard("Closest game", "", G.close, x => [`<b>${esc(x.manager)}</b> over ${esc(x.opp)}`, `+${pts2(x.margin)}`, `${wk(x)} · ${pts2(x.points)}–${pts2(x.opp_points)}`], me),
  ])}
  ${section("Seasons", [
    recordCard("Most points in a season", "Regular season.", S.points, x => [`<b>${esc(x.manager)}</b>`, fmt(x.pf), `${x.season} · ${x.w}–${x.l} · ${x.ppg.toFixed(1)} per game`], me),
    recordCard("Best regular-season record", "", S.record, x => [`<b>${esc(x.manager)}</b>`, `${x.w}–${x.l}${x.t ? "–" + x.t : ""}`, `${x.season} · ${fmt(x.pf)} points`], me),
  ])}
  ${section("Players", [
    recordCard("Best single game", "Fantasy points by one player in a starting lineup.", P.games, x => [`${posBadge(x.pos)} <b>${esc(x.name)}</b>`, pts2(x.points), `${esc(x.manager)} · ${x.season} wk ${x.week}`], me),
    recordCard("Franchise player", HELP.franchisePlayer, P.franchise, x => [`${posBadge(x.pos)} <b>${esc(x.name)}</b>`, fmt(x.points), `for ${esc(x.manager)} · ${x.starts} starts`], me),
  ])}
  ${section("Trades", [
    recordCard("Biggest fleece (today)", HELP.today, T.now, tradeRow, me, tradeAssetsHTML),
    recordCard("Biggest fleece (at the time)", HELP.atTime, T.then, tradeRow, me, tradeAssetsHTML),
    recordCard("Biggest reversal", HELP.swing, T.flips, x => [`<b>${esc(x.winner)}</b> over ${esc(x.loser || "")}`, fmt(x.swing),
      `${esc(x.date)} · ${esc(x.then_leader)} was ahead at the time; ${esc(x.winner)} leads by ${fmt(x.gap)} today`], me, tradeAssetsHTML),
  ])}
  ${section("Drafts", [
    recordCard("Best rookie draft class", HELP.classChange, D.best_rookie, classRow, me),
    recordCard("Worst rookie draft class", HELP.classChange, D.worst_rookie, classRow, me),
    recordCard("Best startup draft", HELP.classChange, D.best_startup, classRow, me),
    recordCard("Worst startup draft", HELP.classChange, D.worst_startup, classRow, me),
    recordCard("Biggest draft steal", "Largest value gain since the pick was made.", D.steals, pickRow, me),
    recordCard("Biggest draft bust", "Largest value loss since the pick was made.", D.busts, pickRow, me),
  ])}
  ${section("Pickups", [
    recordCard("Best pickup (value)", HELP.captured, W.value, x => wvRow(x, fmt(x.captured)), me),
    recordCard("Best pickup (points)", HELP.startPts, W.points, x => wvRow(x, `${x.start_points.toFixed(1)} pts`), me),
    recordCard("Best free pickup", "Most start points from a player added for $0 or as a free agent.", W.free, x => wvRow(x, `${x.start_points.toFixed(1)} pts`), me),
    recordCard("Biggest FAAB bid", "", W.bids, x => wvRow(x, `$${x.bid}`), me),
  ])}`;
}

// ---------------------------------------------------------------- season: playoff odds
Object.assign(HELP, {
  playoffOdds: "Share of simulated seasons in which the team makes the playoffs. Each sim plays out the remaining schedule using every team's best projected lineup each week (Sleeper projections), with the league's own week-to-week spread.",
  byeOdds: "Share of sims finishing as a top-2 seed (first-round bye).",
  titleOdds: "Share of sims ending in a championship, playing the playoffs with each team's projected strength in the playoff weeks.",
  projWins: "Average final regular-season wins across the sims.",
  weeklyProj: "Average projected points of the team's best lineup over the remaining regular-season weeks.",
  sosLeft: "Average projected score of remaining opponents minus the league average. Positive = a harder schedule ahead.",
  sosPast: "Average points scored against the team so far minus the league average. Positive = they've faced tougher opponents (or unlucky weeks).",
  projSlot: "Average rookie-draft slot across the sims, using the draft-order rule this league used last year.",
});
async function seasonData() {
  if (!state.seasonData) state.seasonData = await api("/api/season");
  return state.seasonData;
}
// Normal CDF, for single-game win chances.
const ncdf = z => 0.5 * (1 + Math.sign(z) * Math.sqrt(1 - Math.exp(-2 * z * z / Math.PI)));
const pctCellNum = v => `<td class="num" data-sort="${v}">${v >= 99.95 ? "100" : v < 0.05 ? "0" : v.toFixed(1)}%</td>`;
// Schedule strength is neither good nor bad news by sign, so it isn't colored.
const sosTxt = v => v == null ? "–" : Math.abs(v) < 0.05 ? "0.0" : `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}`;
const ruleTxt = r => r === "record" ? "worst record first" : "lowest max points (potential points) first";

async function viewSeason() {
  const S = await seasonData();
  const me = S.teams.find(t => t.roster_id === S.me);
  setTimeout(() => drawSeason(S), 0);
  const rec = t => `${t.wins}-${t.losses}${t.ties ? "-" + t.ties : ""}`;
  return `<div class="card"><h1>Playoff odds</h1>
    <p class="muted">${fmt(S.sims)} simulations of the remaining ${S.weeks_left.length} regular-season week${S.weeks_left.length === 1 ? "" : "s"}${S.weeks_left.length ? ` (weeks ${S.weeks_left[0]}–${S.weeks_left[S.weeks_left.length - 1]})` : ""} and the playoffs.
      Each team scores around its best projected lineup that week (Sleeper projections), give or take this league's typical swing of ${S.sd} points. Top ${S.playoff_teams} make the playoffs.</p>
    ${me ? `<div class="tiles">
      <div class="tile"><div class="k">Your record</div><div class="v">${rec(me)}</div><div class="d muted">projected ${me.proj_wins} wins</div></div>
      <div class="tile"><div class="k">${hint("Playoff odds", HELP.playoffOdds)}</div><div class="v">${me.playoff_pct.toFixed(1)}%</div><div class="d muted">bye ${me.bye_pct.toFixed(1)}% · title ${me.title_pct.toFixed(1)}%</div></div>
      <div class="tile"><div class="k">${hint("Schedule ahead", HELP.sosLeft)}</div><div class="v">${me.sos_left == null ? "–" : (me.sos_left > 0 ? "+" : "") + me.sos_left.toFixed(1)}</div><div class="d muted">${me.sos_left == null ? "" : me.sos_left > 2 ? "harder than average" : me.sos_left < -2 ? "easier than average" : "about average"}</div></div>
      <div class="tile"><div class="k">${hint("Projected draft slot", HELP.projSlot)}</div><div class="v">${me.avg_slot.toFixed(1)}</div><div class="d muted">${S.draft_season} rookie draft · <a href="#/draftprep">upcoming draft</a></div></div>
    </div>` : ""}</div>
  <div class="grid g2">
    <div class="card"><h2>Playoff chances</h2>
      ${legendHTML([{ label: "Bye (top 2)", color: "var(--series-1)", rect: true }, { label: "Playoffs, no bye", color: "var(--series-2)", rect: true }])}
      <div id="ss-bars"></div>
    </div>
    ${me ? `<div class="card"><h2>Your remaining schedule</h2><table>
      <thead><tr><th>Week</th><th>Opponent</th><th class="num">You</th><th class="num">Them</th><th class="num">Win chance</th></tr></thead>
      <tbody>${me.remaining.map(g => { const p = ncdf((g.proj - (g.opp_proj ?? 0)) / (S.sd * Math.SQRT2)) * 100;
        return `<tr><td>${g.week}</td><td>${esc(g.opp_manager || "–")}</td><td class="num">${g.proj.toFixed(1)}</td><td class="num">${g.opp_proj == null ? "–" : g.opp_proj.toFixed(1)}</td>
          <td class="num ${p >= 55 ? "delta-pos" : p <= 45 ? "delta-neg" : ""}" data-sort="${p.toFixed(1)}">${p.toFixed(0)}%</td></tr>`; }).join("") || '<tr><td colspan="5" class="muted">Regular season is over.</td></tr>'}</tbody>
    </table><p class="muted small">Projected points are each lineup's best possible starters this week. Win chance assumes the league's typical ${S.sd}-point swing.</p></div>` : ""}
  </div>
  <div class="card"><h2>All teams</h2><div class="scroll"><table>
    <thead><tr><th>Team</th><th>Record</th><th class="num">Points</th><th class="num">${hint("Proj. wins", HELP.projWins)}</th><th class="num">${hint("Playoffs", HELP.playoffOdds)}</th>
      <th class="num">${hint("Bye", HELP.byeOdds)}</th><th class="num">${hint("Title", HELP.titleOdds)}</th><th class="num">Last place</th><th class="num">${hint("Weekly proj.", HELP.weeklyProj)}</th>
      <th class="num">${hint("Schedule ahead", HELP.sosLeft)}</th><th class="num">${hint("Schedule so far", HELP.sosPast)}</th><th class="num">${hint("Draft slot", HELP.projSlot)}</th></tr></thead>
    <tbody>${S.teams.map(t => `<tr class="${t.roster_id === S.me ? "me" : ""}"><td><b>${esc(t.manager)}</b></td><td data-sort="${t.wins + 0.5 * t.ties}">${rec(t)}</td>
      <td class="num">${fmt(t.fpts)}</td><td class="num">${t.proj_wins.toFixed(1)}</td>${pctCellNum(t.playoff_pct)}${pctCellNum(t.bye_pct)}${pctCellNum(t.title_pct)}${pctCellNum(t.last_pct)}
      <td class="num">${t.weekly_proj == null ? "–" : t.weekly_proj.toFixed(1)}</td>
      <td class="num" data-sort="${t.sos_left ?? ""}">${sosTxt(t.sos_left)}</td><td class="num" data-sort="${t.sos_past ?? ""}">${sosTxt(t.sos_past)}</td>
      <td class="num">${t.avg_slot.toFixed(1)}</td></tr>`).join("")}</tbody>
  </table></div>
  <p class="muted small">Draft slots use this league's rule from last year: non-playoff teams by ${ruleTxt(S.draft_rule)}, then playoff teams by the round they went out in, champion last.</p></div>`;
}
function drawSeason(S) {
  const host = $("#ss-bars");
  if (!host) return;
  const rows = [...S.teams].sort((a, b) => b.playoff_pct - a.playoff_pct).map(t => ({ label: t.manager,
    parts: { bye: t.bye_pct, rest: Math.max(0, t.playoff_pct - t.bye_pct) },
    tip: { bye: `${t.bye_pct.toFixed(1)}% bye`, rest: `${t.playoff_pct.toFixed(1)}% playoffs in total` } }));
  const draw = () => stackedBars(host, { rows, keys: ["bye", "rest"], labels: { bye: "Bye (top 2)", rest: "Playoffs, no bye" }, max: 100,
    text: v => v >= 8 ? `${Math.round(v)}%` : "", title: "Playoff chances" });
  draw();
  onResize(draw);
}

// ---------------------------------------------------------------- draft prep
Object.assign(HELP, {
  pickRange: "The middle 80% of simulated outcomes for this pick's slot.",
  bpaRate: "How often this manager took the most valuable player still on the board (by draft-day value).",
  avgRank: "Average value rank of their pick among players still available. 1 = always the best available; higher = they reach for need or preference.",
  posLean: "Positions they draft more than the league does (startup and rookie drafts).",
  mockAvail: "Share of mock drafts in which this player is still on the board at your pick.",
  mockTaken: "Share of mock drafts in which you'd take him there (best value × your needs, with some randomness).",
  replay: "Last year's rookie draft replayed pick by pick: given who was already gone, how often the model's first choice (or top 3) was the actual pick, vs. simply taking the best available player.",
});
async function draftPrepData() {
  if (!state.draftPrepData) state.draftPrepData = await api("/api/draft-prep");
  return state.draftPrepData;
}
function slotHeat(p) {
  const b = p >= 0.6 ? 4 : p >= 0.3 ? 3 : p >= 0.1 ? 2 : p >= 0.02 ? 1 : 0;
  return b ? `style="background:var(--age-${b});color:var(--on-age-${b})"` : "";
}
async function viewDraftPrep() {
  const D = await draftPrepData();
  const me = D.me;
  const mine = D.picks.filter(p => p.owner_rid === me);
  const firstRound = D.picks.filter(p => p.round === 1 && p.slot_probs).sort((a, b) => a.exp_slot - b.exp_slot);
  const myCap = D.capital.find(c => c.roster_id === me);
  const capRank = D.capital.findIndex(c => c.roster_id === me) + 1;
  const R = D.replay;
  setTimeout(() => drawDraftPrep(D), 0);
  const lean = h => ["QB", "RB", "WR", "TE"].filter(k => h.pos_bias[k] >= 0.15).map(k => posBadge(k)).join(" ") || '<span class="muted">balanced</span>';
  return `<div class="card"><h1>Upcoming draft <span class="muted">· ${D.season} rookie draft</span></h1>
    <p class="muted">${D.projected ? `Pick slots come from the <a href="#/season">season simulation</a>: non-playoff teams pick by ${ruleTxt(D.draft_rule)} (the rule this league used last year), then playoff teams, champion last.` : "Slots for this draft aren't projected yet."}
      ${D.snake ? "Snake draft." : "Linear draft: the same slot every round."} Each pick is valued at the market price for every slot it could land in, weighted by the chance it lands there.</p>
    <div class="tiles">
      <div class="tile"><div class="k">Your picks</div><div class="v">${mine.length}</div><div class="d muted">${mine.filter(p => p.round === 1).length} first-rounder(s)</div></div>
      <div class="tile"><div class="k">Pick capital</div><div class="v">${myCap ? compact(myCap.value) : "0"}</div><div class="d muted">${capRank ? `#${capRank} of ${D.capital.length} for this draft` : "no picks"}</div></div>
      <div class="tile"><div class="k">Your first pick</div><div class="v">${mine.length ? esc(mine[0].label) : "–"}</div><div class="d muted">${mine.length && mine[0].range ? `likely ${mine[0].range[0] === mine[0].range[1] ? `slot ${mine[0].range[0]}` : `slots ${mine[0].range[0]}–${mine[0].range[1]}`}` : ""}</div></div>
      ${R ? `<div class="tile"><div class="k">${hint("Mock accuracy (last draft)", HELP.replay)}</div><div class="v">${Math.round(R.top1 * 100)}%</div><div class="d muted">exact pick · ${Math.round(R.top3 * 100)}% in top 3 · best-available alone ${Math.round(R.bpa_top1 * 100)}%</div></div>` : ""}
    </div></div>
  <div class="grid g2">
    <div class="card"><h2>Your picks</h2><table>
      <thead><tr><th>Projected</th><th>Original team</th><th class="num">${hint("Likely slots", HELP.pickRange)}</th><th class="num">Value</th><th class="num">${hint("Hit / bust", HELP.hitDef)}</th><th class="num">${hint("Value kept", HELP.valueKept)}</th></tr></thead>
      <tbody>${mine.map(p => `<tr><td><b>${esc(p.label)}</b></td><td>${esc(p.orig || "")}${p.orig_rid === me ? ' <span class="muted small">(own)</span>' : ""}</td>
        <td class="num">${p.range ? (p.range[0] === p.range[1] ? p.range[0] : `${p.range[0]}–${p.range[1]}`) : "–"}</td><td class="num">${fmt(p.value)}</td>
        <td class="num">${p.hit != null ? `${p.hit}% <span class="muted small">/ ${p.bust}%</span>` : "–"}</td>
        <td class="num ${p.kept == null ? "" : p.kept >= 115 ? "delta-pos" : p.kept <= 85 ? "delta-neg" : ""}">${p.kept != null ? p.kept + "%" : "–"}</td></tr>`).join("") || '<tr><td colspan="6" class="muted">You have no picks in this draft.</td></tr>'}</tbody>
    </table><p class="muted small">Values are priced across every slot the season simulation says a pick can land in. Hit / bust: how often picks there became a starter, or never even a flex player, in past classes.
      Value kept: what those players were worth three years later vs. draft day; above 100% means picks there have been underpriced. <a href="#/hitrates">Hit rates →</a></p></div>
    <div class="card"><h2>Pick capital for this draft</h2><div id="dp-cap"></div>
      <p class="muted small">Total value of each team's picks in the ${D.season} draft, at their projected slots.</p></div>
  </div>
  <div class="card" id="dp-timing"><h2>When to sell picks</h2><p class="muted small">Loading pick history… The first time, this downloads about 300 weekly snapshots and can take a minute.</p></div>
  ${firstRound.length ? `<div class="card"><h2>Projected first round</h2>
    <div class="row spread"><span class="scale">Chance ${[1, 2, 3, 4].map(b => `<i style="background:var(--age-${b})"></i>`).join("")} higher</span><span class="muted small">Each row is a team's own first-round pick; cells are the chance it lands in that slot.</span></div>
    <div class="scroll"><table class="heat" style="margin-top:8px"><thead><tr><th>Pick (owner)</th>${firstRound[0].slot_probs.map((_, i) => `<th class="num">${i + 1}</th>`).join("")}<th class="num">Avg</th></tr></thead>
      <tbody>${firstRound.map(p => `<tr class="${p.owner_rid === me ? "me" : ""}"><td><b>${esc(p.orig)}</b>${p.owner_rid !== p.orig_rid ? ` <span class="muted small">→ ${esc(p.owner)}</span>` : ""}</td>
        ${p.slot_probs.map((x, i) => `<td class="hc" ${slotHeat(x)} ${tipAttr(`${p.orig}'s 1st: ${(x * 100).toFixed(1)}% to be pick ${i + 1}`, false)}>${x >= 0.005 ? Math.round(x * 100) : ""}</td>`).join("")}
        <td class="num">${p.exp_slot.toFixed(1)}</td></tr>`).join("")}</tbody></table></div></div>` : ""}
  ${D.board.length ? `<div class="grid g2">
    <div class="card"><h2>Big board</h2><div class="scroll"><table><thead><tr><th class="num">#</th><th></th><th>Player</th><th class="num">Value</th><th class="num">NFL pick</th><th class="num">${hint("Hit / bust", HELP.capitalOdds)}</th></tr></thead>
      <tbody>${D.board.map((b, i) => `<tr><td class="num">${i + 1}</td><td>${posBadge(b.pos)}</td><td><b>${esc(b.name)}</b> <span class="muted small">${esc(b.nfl_team || "")}</span></td><td class="num">${fmt(b.value)}</td>
        <td class="num">${b.nfl_pick || '<span class="muted small">UDFA</span>'}</td><td class="num">${b.hit != null ? `${Math.round(b.hit)}% <span class="muted small">/ ${Math.round(b.bust)}%</span>` : "–"}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="card"><h2>Mock drafts: who's there at your picks</h2>
      ${D.mock.map(m => `<h3>${esc(m.label)}</h3><table><thead><tr><th></th><th>Player</th><th class="num">${hint("Available", HELP.mockAvail)}</th><th class="num">${hint("You take him", HELP.mockTaken)}</th></tr></thead>
        <tbody>${m.candidates.map(c => `<tr><td>${posBadge(c.pos)}</td><td>${esc(c.name)}</td><td class="num">${Math.round(c.available * 100)}%</td><td class="num">${Math.round(c.taken * 100)}%</td></tr>`).join("")}</tbody></table>`).join("")}
    </div></div>` : `<div class="card"><h2>Big board and mock drafts</h2>
    <p class="muted">The ${D.season} rookie class isn't in the value sources yet. Players get dynasty values after the NFL draft in late April.
      Once they do, this page shows a big board and mock drafts: who's likely to be on the board at each of your picks, simulated with every manager's draft habits and needs (below).</p></div>`}
  <div class="card"><h2>How each manager drafts</h2><div class="scroll"><table>
    <thead><tr><th>Manager</th><th class="num">Picks</th><th class="num">QB</th><th class="num">RB</th><th class="num">WR</th><th class="num">TE</th><th>${hint("Leans", HELP.posLean)}</th>
      <th class="num">${hint("Best available", HELP.bpaRate)}</th><th class="num">${hint("Avg rank taken", HELP.avgRank)}</th><th>Needs now</th></tr></thead>
    <tbody>${D.habits.map(h => `<tr class="${h.roster_id === me ? "me" : ""}"><td><b>${esc(h.manager)}</b></td><td class="num">${h.n}</td>
      ${["QB", "RB", "WR", "TE"].map(k => `<td class="num">${Math.round(h.pos_share[k] * 100)}%</td>`).join("")}<td>${lean(h)}</td>
      <td class="num">${h.bpa_rate == null ? "–" : Math.round(h.bpa_rate * 100) + "%"}</td><td class="num">${h.avg_rank ?? "–"}</td>
      <td>${h.needs.map(posBadge).join(" ") || '<span class="muted">–</span>'}</td></tr>`).join("")}</tbody>
  </table></div><p class="muted small">From every startup and rookie draft in the league's history. Needs are long-term positional needs (dynasty value vs. the league).</p></div>`;
}
function drawDraftPrep(D) {
  const host = $("#dp-cap");
  const rows = D.capital.map(c => ({ label: c.manager, parts: { v: c.value }, tip: { v: `${c.n} pick(s), ${c.firsts} first(s) · ${fmt(c.value)} value` } }));
  const draw = () => host && D.capital.length && stackedBars(host, { rows, keys: ["v"], labels: { v: "Pick value" }, max: Math.max(...D.capital.map(c => c.value)),
    text: v => compact(v), title: "Pick capital" });
  draw();
  onResize(draw);
  loadPickTiming([draw]);
}

// ---------------------------------------------------------------- player page
const VERDICT = {
  sell: ["Sell now", "acc-Unlikely"], soon: ["Sell within a year", "acc-Possible"],
  hold: ["Hold", "res-even"], rising: ["Rising with age", "acc-Likely"],
};
Object.assign(HELP, {
  ageOutlook: "How a player's value typically changes over the next year at his age, compared with other players at his position and value level. From about four years of weekly value history. Negative = his age is working against him.",
  vsPeers: "His value over time if only his age mattered: compared with other players at his position and value level. This is what the sell verdict uses.",
  likelyValue: "His expected actual value: the age effect plus the average change for players at his position and value level over that many years (new rookie classes push everyone down, and many lower-value players fade out entirely).",
  ageCurve: "Typical one-year change in value at each age, compared with players at the same position and value level. Bars below zero are ages where value usually falls faster than for peers. His current age is outlined.",
});
const verdictBadge = o => o ? `<span class="badge ${VERDICT[o.verdict][1]}" ${tipAttr(HELP.ageOutlook)}>${VERDICT[o.verdict][0]}</span>` : "";
const playerLink = (id, name) => `<a href="#/player/${esc(id)}">${esc(name)}</a>`;

async function viewPlayer(pid) {
  const P = await api(`/api/player/${encodeURIComponent(pid)}`);
  const a = P.player, o = P.outlook;
  setTimeout(() => drawPlayer(P), 0);
  return `<div class="card"><div class="row spread">
      <div><h1>${posBadge(a.pos)} ${esc(a.name)} ${verdictBadge(o)}</h1>
        <div class="muted">${assetMeta(a)}${a.years_exp != null ? ` · year ${a.years_exp + 1}` : ""} · ${P.owner ? (P.is_mine ? "<b>your roster</b>" : `on <a href="#/team/${P.owner_rid}">${esc(P.owner)}</a>`) : "free agent"}</div></div>
      <div class="row">
        <div class="stat"><div class="k">Dynasty value</div><div class="v">${fmt(a.value)}</div></div>
        <div class="stat"><div class="k">Win-now</div><div class="v">${fmt(a.redraft)}</div></div>
        ${a.breakout ? `<div class="stat"><div class="k">${hint("Breakout", HELP.breakout)}</div><div class="v">${a.breakout}</div></div>` : ""}
        ${P.owner && !P.is_mine ? `<button class="primary" onclick='openInEvaluator(${JSON.stringify({ b: P.owner_rid, aGives: [], bGives: [{ kind: "player", id: a.id }] })})'>Trade for him</button>` : ""}
      </div></div>
    ${a.notes && a.notes.length ? `<ul class="notes">${a.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
  </div>
  <div class="grid g2">
    <div class="card"><h2>Value history</h2><div id="pl-line"></div>
      <p class="muted small">Weekly DynastyProcess values on the app's scale, so they can differ a little from the blended value above.</p></div>
    <div class="card"><h2>Sell timing</h2>
      ${o ? `<p><b>${VERDICT[o.verdict][0]}.</b> ${esc(o.why)}</p>
        <table data-nosort><thead><tr><th>In</th><th class="num">Age</th><th class="num">${hint("Vs. peers", HELP.vsPeers)}</th><th class="num">${hint("Expected value", HELP.likelyValue)}</th></tr></thead>
        <tbody><tr><td>Now</td><td class="num">${a.age}</td><td class="num">${fmt(a.value)}</td><td class="num">${fmt(a.value)}</td></tr>
          ${o.path.map(p => `<tr><td>${p.years} year${p.years > 1 ? "s" : ""}</td><td class="num">${p.age}</td>
            <td class="num">${fmt(p.value)} <span class="small ${signCls(p.change_pct)}">${pct(p.change_pct, 0)}</span></td>
            <td class="num">${p.typical != null ? `${fmt(p.typical)} <span class="small ${signCls(p.typical_pct)}">${pct(p.typical_pct, 0)}</span>` : "–"}</td></tr>`).join("")}</tbody></table>
        <p class="muted small">"Vs. peers" is the age effect alone: how he does against other ${a.pos}s at his value. The verdict is based on this. "Expected value" also includes the average drop for ${a.pos}s at his value as new rookie classes arrive, so it's usually lower even for a Hold. Both assume he performs like a typical player his age, so injuries, role changes and breakouts aren't included.</p>` : '<p class="muted">Not enough age data for this player.</p>'}
      <h3>${hint(`Typical ${a.pos} value change by age`, HELP.ageCurve)}</h3><div id="pl-curve"></div>
    </div>
  </div>`;
}
function drawPlayer(P) {
  const line = $("#pl-line");
  if (!line) return;
  const first = P.history.findIndex(v => v != null);
  const drawLine = () => first < 0 ? (line.innerHTML = '<p class="muted">No value history for this player.</p>') : lineChart(line, {
    dates: P.dates.slice(first), series: [{ id: P.player.id, label: P.player.name, values: P.history.slice(first), highlight: true, color: "var(--series-1)" }],
    format: compact, height: 260, title: `${P.player.name} value history` });
  const age = P.player.age != null ? Math.floor(P.player.age) : null;
  const items = P.curve.filter(c => c.age >= 20 && c.age <= 36).map(c => ({ label: String(c.age), value: (c.ratio - 1) * 100, highlight: c.age === age,
    tip: [{ color: c.ratio >= 1 ? "var(--div-s2)" : "var(--div-n2)", value: `${c.ratio >= 1 ? "+" : ""}${((c.ratio - 1) * 100).toFixed(0)}%`, label: `vs. peers · ${c.n} samples` }] }));
  const drawCurve = () => divergingColumns($("#pl-curve"), { items, xLabel: "Age", title: `Typical ${P.player.pos} value change by age` });
  drawLine(); drawCurve();
  onResize(drawLine, drawCurve);
}

// ---------------------------------------------------------------- deadline, buy low, timeline, league prices
const cachedApi = (key, url) => (state.cache[key] ||= api(url).catch(e => { delete state.cache[key]; throw e; }));
const shortDate = d => { const x = new Date(d + "T00:00"); return `${MONTHS[x.getMonth()]} ${x.getDate()}`; };
Object.assign(HELP, {
  sellScore: "Buyer premium plus half the value he's expected to lose over the next year, in value points. Higher = more reason to sell now.",
  premium: "How much more the buyer's team values him than yours does (team context: their window, needs and trade tendencies).",
  ask: "The best package of theirs that works for both sides: you gain at least 3% in team-context value, they'd accept about 45%+ of the time, and (when possible) it doesn't weaken their lineup for the rest of the season.",
  dropPct: "Today's DynastyProcess value vs. his highest value in the last 4 months.",
  roleShare: "Share of his team's opportunities at his position (targets and carries; pass attempts and runs for QBs) over his last 3 games vs. the season.",
  strength: "Projected value of each team's best starting lineup that year, if nobody trades. Players age along the age curves; picks become rookies after their draft.",
  priceIndex: "How much more (or less) market value managers got back when they traded this kind of asset away, at trade-day values. Positive = this league pays above market for it.",
  pickIndex: "A pick's value that month compared with its own average over its last 11 months before the draft, averaged over past draft classes. Values are what the pick would buy in players.",
});

async function viewDeadline() {
  const D = await cachedApi("deadline", "/api/deadline");
  setTimeout(() => { loadChecks("sell"); loadSeasonal(); }, 0);
  const dl = D.deadline;
  const when = !dl.week ? "Your league has no trade deadline set."
    : dl.weeks_left == null ? `Trade deadline: week ${dl.week}.`
    : dl.weeks_left < 0 ? `The week ${dl.week} trade deadline has passed, so this list is for the offseason market.`
    : `Trade deadline: week ${dl.week}${dl.dates ? ` (${shortDate(dl.dates[0])}–${shortDate(dl.dates[1])})` : ""}, ${dl.weeks_left === 0 ? "this week" : `${dl.weeks_left} week${dl.weeks_left === 1 ? "" : "s"} away`}.`;
  const ask = (r, b) => {
    const x = (b.asks || [])[0];
    if (!x) return '<span class="muted small">No package found that works for both sides.</span>';
    const deal = { b: b.roster_id, aGives: [{ kind: "player", id: r.id }], bGives: x.get.map(g => ({ kind: g.kind, id: g.id })) };
    return `${x.get.map(g => `${g.kind === "player" ? posBadge(g.pos) + " " : ""}${esc(g.name)} <span class="muted small">${fmt(g.value)}</span>`).join("<br>")}
      <div class="small muted">you ${pct(x.gain_pct, 0)} · they accept ~${x.acceptance}%${x.their_weekly != null ? ` · their lineup <span class="${x.their_weekly < -0.5 ? "delta-neg" : x.their_weekly > 0.5 ? "delta-pos" : ""}">${x.their_weekly > 0 ? "+" : ""}${x.their_weekly} pts/week</span>` : ""}</div>
      ${x.their_weekly != null && x.their_weekly < -0.5 ? '<div class="small delta-neg">Weakens their lineup this season: a contender is unlikely to take it at the deadline.</div>' : ""}
      <button class="small" onclick='openInEvaluator(${JSON.stringify(deal)})'>Open in evaluator</button>`;
  };
  return `<div class="card"><h1>Deadline sell list</h1>
    <p class="muted">${when} Contenders pay the most for win-now help before the deadline. After it, these players are worth what the offseason market says, a year older.
      Buyers are teams with a ${D.buyer_odds}%+ chance to make the playoffs. Ranked by ${hint("sell score", HELP.sellScore)}.</p>
    <div class="tiles">
      <div class="tile"><div class="k">Weeks to the deadline</div><div class="v">${dl.weeks_left == null ? "–" : Math.max(0, dl.weeks_left)}</div><div class="d muted">${dl.week ? `week ${dl.week}` : "no deadline"}</div></div>
      <div class="tile"><div class="k">Buyers</div><div class="v">${D.buyers.length}</div><div class="d muted">teams ${D.buyer_odds}%+ to make the playoffs</div></div>
      <div class="tile"><div class="k">Players worth selling</div><div class="v">${D.players.length}</div><div class="d muted">${D.players.length ? esc(D.players[0].name) + " first" : "none right now"}</div></div>
    </div>
    ${D.buyers.length ? `<h3>Buyers</h3><div class="row">${D.buyers.map(b => `<span class="badge tag">${esc(b.manager)} · ${b.playoff_pct.toFixed(0)}%${b.needs.length ? " · needs " + b.needs.join(", ") : ""}</span>`).join(" ")}</div>` : ""}
  </div>
  ${D.players.map(r => `<div class="card">
    <div class="row spread"><div><h2>${posBadge(r.pos)} ${playerLink(r.id, r.name)} ${verdictBadge(r.verdict ? { verdict: r.verdict } : null)}</h2>
      <div class="muted small">${r.age ? r.age + "y · " : ""}${esc(r.nfl_team || "")}${r.injury ? ` · <span class="delta-neg">${esc(r.injury)}</span>` : ""}</div></div>
      <div class="row">
        <div class="stat"><div class="k">Value</div><div class="v">${fmt(r.value)}</div></div>
        <div class="stat"><div class="k">Win-now</div><div class="v">${fmt(r.redraft)}</div></div>
        <div class="stat"><div class="k">${hint("Expected in a year", HELP.likelyValue)}</div><div class="v">${fmt(r.expected_next_year)}</div></div>
        <div class="stat"><div class="k">${hint("Sell score", HELP.sellScore)}</div><div class="v">${fmt(r.score)}</div></div>
      </div></div>
    <ul class="notes">${r.reasons.map(x => `<li>${esc(x)}</li>`).join("")}</ul>
    <div class="scroll"><table data-nosort><thead><tr><th>Buyer</th><th class="num">Playoff odds</th><th class="num">${hint("Values him at", HELP.premium)}</th><th>${hint("What to ask for", HELP.ask)}</th></tr></thead>
      <tbody>${r.buyers.filter(b => b.asks).map(b => `<tr><td><a href="#/team/${b.roster_id}">${esc(b.manager)}</a>${b.need >= 0.5 ? ` <span class="badge tag">needs ${r.pos}</span>` : ""}</td>
        <td class="num">${b.playoff_pct.toFixed(0)}%</td>
        <td class="num">${fmt(b.their_value)} <span class="small ${signCls(b.premium)}">${b.premium > 0 ? "+" : ""}${fmt(b.premium)}</span></td>
        <td>${b.asks ? ask(r, b) : '<span class="muted small">–</span>'}</td></tr>`).join("")}</tbody></table></div>
  </div>`).join("") || `<div class="card"><p class="muted">Nobody on your roster is worth more to a likely playoff team than to you, and nobody is aging out fast. Nothing to sell for deadline reasons.</p></div>`}
  <div class="card" id="dl-season"><h2>When players are worth the most</h2><p class="muted small">Loading…</p></div>
  <div class="card" id="dl-check"><h2>How reliable are the sell verdicts?</h2><p class="muted small">Loading…</p></div>`;
}

async function viewBuyLow() {
  const B = await cachedApi("buylow", "/api/buylow");
  setTimeout(() => loadChecks("buy"), 0);
  const others = B.players.filter(r => r.owner_rid != null && !r.mine), mine = B.players.filter(r => r.mine), fa = B.players.filter(r => r.owner_rid == null);
  const kind = { injury: ["Injury dip", "acc-Possible"], slump: ["Slump", "res-even"], dip: ["Price dip", "res-even"] };
  const table = (rows, action) => `<div class="scroll"><table><thead><tr><th>Player</th><th class="num">Value</th><th class="num">${hint("Drop", HELP.dropPct)}</th>
      <th class="num">${hint("Role", HELP.roleShare)}</th><th>4 months</th><th>Why</th><th></th></tr></thead>
    <tbody>${rows.map(r => `<tr><td><b>${posBadge(r.pos)} ${playerLink(r.id, r.name)}</b><div class="muted small">${r.age ? r.age + "y · " : ""}${esc(r.nfl_team || "")}${r.owner ? " · " + esc(r.owner) : ""}</div>
        <span class="badge ${kind[r.kind][1]}">${kind[r.kind][0]}</span></td>
      <td class="num">${fmt(r.value)}</td>
      <td class="num" data-sort="${r.drop_pct}"><b class="delta-neg">−${r.drop_pct.toFixed(0)}%</b><div class="muted small">${fmt(r.high)} → ${fmt(r.now_dp)}</div></td>
      <td class="num" data-sort="${r.share_l3}">${Math.round(r.share_l3 * 100)}%<div class="muted small">season ${Math.round(r.share * 100)}%</div></td>
      <td>${sparkline(r.spark)}</td>
      <td class="small"><ul class="notes" style="margin:0">${r.reasons.slice(1).map(x => `<li>${esc(x)}</li>`).join("")}</ul></td>
      <td>${action(r)}</td></tr>`).join("") || `<tr><td colspan="7" class="muted">None right now.</td></tr>`}</tbody></table></div>`;
  return `<div class="card"><h1>Buy low</h1>
    <p class="muted">Players whose market value has dropped at least ${B.min_drop_pct}% from their high in the last 4 months while their role hasn't: a few quiet games, a minor injury or a crowded headline.
      Those are the cheapest times to buy, and the worst times to sell your own. Injury dips are labeled; judge how serious the injury is. Players whose age says "sell" are left out. Values as of ${esc(B.as_of || "–")}.</p>
    <div class="tiles">
      <div class="tile"><div class="k">On other teams</div><div class="v">${others.length}</div><div class="d muted">trade targets</div></div>
      <div class="tile"><div class="k">On your roster</div><div class="v">${mine.length}</div><div class="d muted">don't sell these low</div></div>
      <div class="tile"><div class="k">Free agents</div><div class="v">${fa.length}</div><div class="d muted">see Free agents</div></div>
    </div></div>
  <div class="card"><h2>Trade targets</h2>${table(others, r => `<button onclick='openInEvaluator(${JSON.stringify({ b: r.owner_rid, aGives: [], bGives: [{ kind: "player", id: r.id }] })})'>Trade for</button>`)}</div>
  ${mine.length ? `<div class="card"><h2>Yours: hold, don't sell low</h2>${table(mine, () => "")}</div>` : ""}
  ${fa.length ? `<div class="card"><h2>Free agents</h2>${table(fa, () => `<a href="#/pickups">Free agents →</a>`)}</div>` : ""}
  <div class="card" id="bl-check"><h2>Does buying the dip work?</h2><p class="muted small">Loading…</p></div>`;
}

async function viewFuture() {
  const F = await cachedApi("future", "/api/future");
  const me = F.teams.find(t => t.is_me), S = F.me;
  setTimeout(() => {
    drawFuture(F);
    // Default target: the later year where you're closest to (or furthest above) the playoff line.
    const best = S ? F.years.slice(1).reduce((b, y, i) => (S.gap[i + 1] > S.gap[b + 1] ? i : b), 0) : 0;
    loadTarget(F, state.targetYear || F.years[best + 1]);
  }, 0);
  const n = F.years.length, y2 = Math.min(2, n - 1);
  let headline = "";
  if (S) {
    let closest = 1;
    for (let i = 1; i < n; i++) if (S.gap[i] > S.gap[closest]) closest = i;
    headline = S.first_playoff_year === "Now" ? "Your lineup is already above the playoff line."
      : S.first_playoff_year ? `If nothing changes, you reach the playoff line in <b>${esc(S.first_playoff_year)}</b>.`
      : `If nothing changes, you don't reach the playoff line within ${n - 1} years. Closest: <b>${esc(F.years[closest])}</b>, ${fmt(-S.gap[closest])} of lineup value short.`;
  }
  return `<div class="card"><h1>Rebuild timeline</h1>
    <p class="muted">Every team's projected ${hint("lineup strength", HELP.strength)} over the next ${n - 1} years if nobody trades. Players follow the age curves (expected value, including falling out of the league).
      Draft picks become rookies after their draft. The playoff line is the ${F.playoff_teams}th-best team that year. Dynasty values price in the future, so treat ranks as a guide to who will be good when, not as exact standings.</p>
    ${S ? `<p>${headline}</p><div class="tiles">${F.years.map((y, i) => `<div class="tile ${me.rank[i] <= F.playoff_teams ? "mine" : ""}"><div class="k">${esc(y)}</div><div class="v">#${me.rank[i]}</div>
      <div class="d muted">${S.gap[i] >= 0 ? `${fmt(S.gap[i])} above` : `${fmt(-S.gap[i])} below`} the playoff line</div></div>`).join("")}</div>` : ""}
  </div>
  <div class="card" id="fu-target"></div>
  <div class="card"><h2>Lineup strength by year</h2><div id="fu-legend"></div><div id="fu-line"></div><p class="muted small">Highlighted: you, the playoff line, and the teams projected on top in ${esc(F.years[y2])}.</p></div>
  <div class="card"><h2>All teams</h2><div class="scroll"><table>
    <thead><tr><th>Team</th>${F.years.map(y => `<th class="num">${esc(y)}</th>`).join("")}<th class="num">Franchise value ${esc(F.years[y2])}</th></tr></thead>
    <tbody>${F.teams.map(t => `<tr class="${t.is_me ? "me" : ""}"><td><b>${esc(t.manager)}</b> ${windowBadge(t.window)}</td>
      ${t.strength.map((v, i) => `<td class="num" data-sort="${-t.rank[i]}"><b>#${t.rank[i]}</b> <span class="muted small">${compact(v)}</span></td>`).join("")}
      <td class="num">${compact(t.franchise[y2])}</td></tr>`).join("")}</tbody></table></div></div>
  ${me ? `<div class="grid g2">
    <div class="card"><h2>Your core in ${esc(F.years[y2])}</h2><table data-nosort><thead><tr><th>Player</th>${F.years.map(y => `<th class="num">${esc(y)}</th>`).join("")}</tr></thead>
      <tbody>${me.core.map(c => `<tr><td>${posBadge(c.pos)} ${playerLink(c.id, c.name)} <span class="muted small">${c.age ?? ""}</span></td>${c.path.map(v => `<td class="num">${fmt(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
    <div class="card"><h2>Your picks</h2><table data-nosort><thead><tr><th>Pick</th>${F.years.map(y => `<th class="num">${esc(y)}</th>`).join("")}</tr></thead>
      <tbody>${me.picks.map(p => `<tr><td>${esc(p.name)}</td>${p.path.map(v => `<td class="num">${fmt(v)}</td>`).join("")}</tr>`).join("") || `<tr><td colspan="${n + 1}" class="muted">No picks.</td></tr>`}</tbody></table>
      <p class="muted small">A pick keeps its value until its draft, then ages like a typical rookie.</p></div>
  </div>` : ""}`;
}
function drawFuture(F) {
  const host = $("#fu-line");
  if (!host) return;
  const today = new Date();
  const dates = F.years.map((_, i) => new Date(today.getFullYear() + i, today.getMonth(), today.getDate()).toISOString().slice(0, 10));
  const y2 = Math.min(2, F.years.length - 1);
  const top = [...F.teams].sort((a, b) => a.rank[y2] - b.rank[y2]).filter(t => !t.is_me).slice(0, 2).map(t => t.roster_id);
  let k = 1;
  const series = F.teams.map(t => {
    const hl = t.is_me || top.includes(t.roster_id);
    return { id: t.roster_id, label: t.manager + (t.is_me ? " (you)" : ""), values: t.strength, highlight: hl, color: hl ? `var(--series-${t.is_me ? 1 : ++k})` : undefined };
  });
  series.push({ id: "line", label: "Playoff line", values: F.playoff_line, highlight: true, color: "var(--series-4)" });
  $("#fu-legend").innerHTML = legendHTML([...series.filter(s => s.highlight).map(s => ({ label: s.label, color: s.color })), { label: "Other teams", color: "var(--context-line)" }]);
  const markers = dates.map((d, i) => ({ date: d, label: F.years[i] }));
  const draw = () => lineChart(host, { dates, series, markers, hideMonths: true, format: compact, height: 300, title: "Projected lineup strength" });
  draw();
  onResize(draw);
}

async function viewPrices() {
  const M = await cachedApi("prices", "/api/league-prices");
  setTimeout(() => { drawPrices(M); loadCalculators(); }, 0);
  const VERD = { over: ["Pays above market", "Sell these here; they're pricey to buy."], under: ["Pays below market", "Buy these here; selling them gets less."], market: ["About market", ""] };
  return `<div class="card"><h1>League prices</h1>
    <p class="muted">How this league has priced assets in its ${M.trades} completed trades${M.since ? ` since ${esc(M.since)}` : ""}, compared with the market on each trade day.
      A ${hint("price index", HELP.priceIndex)} of +15% for 1sts means managers who traded a 1st away got 15% more market value back than they gave: this league pays extra for 1sts.
      Small samples are pulled toward 0%, so with few trades most kinds read close to market. ${M.pick_history ? "Picks are valued with DynastyProcess's pick rankings from the week of the trade." : "Pick history was unavailable, so picks use today's values."}</p></div>
  ${M.groups.map((g, gi) => `<div class="card"><h2>By ${g.title.toLowerCase()}</h2><div id="pr-chart-${gi}"></div>
    <div class="scroll"><table data-nosort><thead><tr><th>Kind</th><th class="num">${hint("Price index", HELP.priceIndex)}</th><th class="num">Trades</th><th>Reading</th><th>Biggest examples</th></tr></thead>
      <tbody>${g.rows.map(r => `<tr><td><b>${esc(r.label)}</b></td><td class="num">${pct(r.pct, 0)}</td><td class="num">${r.n}</td>
        <td>${VERD[r.verdict][0]}${VERD[r.verdict][1] ? `<div class="muted small">${VERD[r.verdict][1]}</div>` : ""}${r.n < 4 ? '<div class="muted small">Too few trades to say.</div>' : ""}</td>
        <td class="small">${r.examples.length ? `<details><summary>${r.examples.length} trade${r.examples.length === 1 ? "" : "s"}</summary>${r.examples.map(x => `<div style="margin:4px 0"><b>${esc(x.date)}</b> ${esc(x.manager)} sent ${esc(x.sent)}<br>for ${esc(x.recv)} <span class="${signCls(x.pct)}">(${pct(x.pct, 0)})</span></div>`).join("")}</details>` : ""}</td></tr>`).join("")}</tbody></table></div>
  </div>`).join("")}
  <div class="card" id="pr-calc"><h2>Which calculator each manager trusts</h2><p class="muted">Loading KeepTradeCut history… The first time, this downloads each traded player's KTC page and can take a minute.</p></div>`;
}
const PRICE_SHORT = { QB: "QB", RB: "RB", WR: "WR", TE: "TE", R1: "1st", R2: "2nd", R3: "3rd+", young: "≤24", prime: "25–27", vet: "28+" };
function drawPrices(M) {
  const draws = M.groups.map((g, gi) => () => {
    const host = $(`#pr-chart-${gi}`);
    if (!host) return;
    divergingColumns(host, { height: 200, xLabel: g.title, title: `League price index by ${g.title.toLowerCase()}`,
      items: g.rows.map(r => ({ label: PRICE_SHORT[r.key], value: r.pct,
        tip: [{ color: r.pct >= 0 ? "var(--div-s2)" : "var(--div-n2)", value: pct(r.pct, 0), label: `${r.label} · ${r.n} trades` }] })) });
  });
  draws.forEach(f => f());
  onResize(...draws);
}

// "When to sell picks" card on the Upcoming draft page.
async function loadPickTiming(draws) {
  const host = $("#dp-timing");
  if (!host) return;
  let T;
  try { T = await cachedApi("picktiming", "/api/pick-timing"); }
  catch (e) { host.innerHTML = `<h2>When to sell picks</h2><div class="warnbox">Couldn't load pick history: ${esc(e.message)}</div>`; return; }
  if (!$("#dp-timing")) return;
  const tracks = T.tracks.filter(t => t.months.some(m => m.index));
  if (!tracks.length) { host.innerHTML = `<h2>When to sell picks</h2><p class="muted">Not enough pick history yet.</p>`; return; }
  const sel = Math.min(state.pickTrack ?? 0, tracks.length - 1);
  const t = tracks[sel], o = t.outlook;
  host.innerHTML = `<div class="row spread"><h2>When to sell picks</h2>
      <select id="dp-track" aria-label="Pick">${tracks.map((x, i) => `<option value="${i}" ${i === sel ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select></div>
    <p class="muted small">Typical value of next year's picks by month, vs. each draft class's own average (${t.classes.join(", ")} classes; DynastyProcess pick rankings since ${esc(T.since || "")}, turned into what the pick would buy in players).
      ${hint("How it's measured", HELP.pickIndex)}</p>
    <div id="dp-timing-chart"></div>
    ${o ? `<p>For ${/^e/i.test(t.label) ? "an" : "a"} ${esc(t.label.toLowerCase())}, the typical high point from here is <b>${o.best}</b> (${pct(o.best_pct, 0)} vs. ${o.now}).
      ${o.worst === o.now ? `${o.now} is already the typical low point, so selling now means selling near the bottom.` : `The low point ahead is ${o.worst} (${pct(o.worst_pct, 0)}).`}${o.draft_pct != null ? ` Holding to April: ${pct(o.draft_pct, 0)}.` : ""}</p>` : ""}
    <table data-nosort><thead><tr><th>Pick</th><th class="num">Typical best month</th><th class="num">${T.month} → best month</th><th class="num">${T.month} → April</th></tr></thead>
      <tbody>${tracks.map(x => x.outlook ? `<tr><td>${esc(x.label)}</td><td class="num">${x.outlook.best}</td><td class="num">${pct(x.outlook.best_pct, 0)}</td>
        <td class="num">${x.outlook.draft_pct == null ? "–" : pct(x.outlook.draft_pct, 0)}</td></tr>` : "").join("")}</tbody></table>
    <p class="muted small">February is missing: DynastyProcess's pick rankings are off-scale for a few weeks most Februaries, so those snapshots are skipped.</p>`;
  $("#dp-track").onchange = e => { state.pickTrack = +e.target.value; loadPickTiming(draws); };
  const draw = () => {
    const ch = $("#dp-timing-chart");
    if (!ch) return;
    divergingColumns(ch, { height: 200, xLabel: "Month", title: `${t.label} value by month`,
      items: t.months.map(m => ({ label: m.label, value: m.index ? (m.index - 1) * 100 : 0, highlight: m.label === T.month,
        tip: [{ color: (m.index || 1) >= 1 ? "var(--div-s2)" : "var(--div-n2)", value: m.index ? pct((m.index - 1) * 100, 0) : "no data", label: `vs. average · ${m.n} classes` }] })) });
  };
  draw();
  onResize(...draws, draw);
}

// Counter-offer section under the evaluator.
async function runCounter() {
  const tr = state.trade, out = $("#counter-out");
  if (!out) return;
  out.innerHTML = `<p class="muted">Looking for changes…</p>`;
  let r;
  try { r = await api("/api/counter", { method: "POST", body: { a_rid: tr.a, a_gives: tr.aGives, b_rid: tr.b, b_gives: tr.bGives } }); }
  catch (e) { out.innerHTML = `<div class="warnbox">${esc(e.message)}</div>`; return; }
  if (r.status === "works") { out.innerHTML = `<p>This deal already works for both sides: ${pct(r.current.gain_pct, 0)} in team-context value for Team A, and Team B would accept about ${r.current.acceptance}% of the time.</p>`; return; }
  out.innerHTML = `${r.why.length ? `<ul class="notes">${r.why.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    ${r.options.length ? `<table data-nosort><thead><tr><th>Change</th><th class="num">Team A gain</th><th class="num">Team B accepts</th><th></th></tr></thead><tbody>
      ${r.options.map((o, i) => `<tr><td><b>${esc(o.label)}</b><div class="muted small">${esc(o.a_gives.map(a => a.name).join(", "))} for ${esc(o.b_gives.map(a => a.name).join(", "))}</div></td>
        <td class="num ${signCls(o.gain_pct)}">${pct(o.gain_pct, 0)}</td><td class="num">~${o.acceptance}%</td><td><button data-opt="${i}">Use this</button></td></tr>`).join("")}</tbody></table>`
      : `<p class="muted">No small change makes this work for both sides. Try a different centerpiece, or use "Suggest trades with Team B".</p>`}`;
  $$("#counter-out button[data-opt]").forEach(b => b.onclick = () => {
    const o = r.options[+b.dataset.opt];
    tr.aGives = o.a_gives.map(a => ({ kind: a.kind, id: a.id }));
    tr.bGives = o.b_gives.map(a => ({ kind: a.kind, id: a.id }));
    route();
  });
}

// ---------------------------------------------------------------- target year, calculators, checks, impact, message, recap, roster room
Object.assign(HELP, {
  yearGain: "How much your best starting lineup's projected value goes up in that year (players along their expected value, picks as rookies after their draft).",
  todayCost: "Your gain or loss in team-context value today. Building for a later year usually costs a little now; deals here cost at most 10%.",
  calcLean: "Average of (your side's result on KeepTradeCut − result on DynastyProcess) over a manager's trades, at trade-day values. A manager who trusts one calculator accepts deals that look fine on it, so their trades look better on that one.",
  vsPeersBack: "Change in value over the period divided by the median change of players at the same position and value level on the same date. +5% = did 5% better than similar players.",
  draftSlot: "Average projected spot of the team's own 1st in the next rookie draft, across the simulated seasons (1 = first pick).",
  keepValue: "Expected value a year from now (age curve), or the pick's value for an incoming rookie. Lowest goes first.",
});

// Copy text, with a fallback for http:// pages on a phone (the clipboard API needs a secure page).
async function copyText(text, el) {
  try { await navigator.clipboard.writeText(text); }
  catch { if (el) { el.select(); document.execCommand("copy"); } }
  toast("Copied");
}

// "Build toward a year" card on the Timeline page.
async function loadTarget(F, year) {
  const host = $("#fu-target");
  if (!host) return;
  const years = F.years.slice(1);
  year = year || state.targetYear || years[Math.min(1, years.length - 1)];
  const head = `<div class="row spread"><div><h2>Build toward a year</h2>
      <p class="muted small">Trades that raise your projected starting lineup most in the year you pick, that the other manager would accept about 45%+ of the time, and that cost you at most 10% in value today.</p></div>
    <label class="field">Target year<select id="fu-year">${years.map(y => `<option ${+y === +year ? "selected" : ""}>${esc(y)}</option>`).join("")}</select></label></div>`;
  host.innerHTML = head + `<p class="muted">Searching every team's roster…</p>`;
  $("#fu-year").onchange = e => { state.targetYear = e.target.value; loadTarget(F, e.target.value); };
  let T;
  try { T = await cachedApi(`target:${year}`, `/api/target?year=${year}`); }
  catch (e) { host.innerHTML = head + `<div class="warnbox">${esc(e.message)}</div>`; return; }
  if (!$("#fu-target")) return;
  const line = n => `${n >= 0 ? `${fmt(n)} above` : `${fmt(-n)} below`} the line`;
  const assets = (xs, show) => xs.map(a => `${a.kind === "player" ? posBadge(a.pos) + " " : ""}${esc(a.name)} <span class="muted small">${fmt(a.value)}${show ? ` → ${fmt(a.then)} in ${T.year}` : ""}</span>`).join("<br>");
  host.innerHTML = head + `<p>In <b>${T.year}</b> you're projected <b>#${T.rank}</b>, ${line(T.gap)} (the ${T.playoff_teams}th-best lineup).</p>
    ${T.deals.length ? `<div class="scroll"><table data-nosort><thead><tr><th>Partner</th><th>You give</th><th>You get</th>
      <th class="num">${hint(`Lineup ${T.year}`, HELP.yearGain)}</th><th class="num">Rank after</th><th class="num">${hint("Today", HELP.todayCost)}</th><th class="num">They accept</th><th></th></tr></thead>
      <tbody>${T.deals.map(d => `<tr><td><a href="#/team/${d.roster_id}">${esc(d.manager)}</a> ${windowBadge(d.window)}</td>
        <td>${assets(d.give, true)}</td><td>${assets(d.get, true)}</td>
        <td class="num delta-pos">+${fmt(d.gain)}</td>
        <td class="num"><b>#${d.rank_after}</b><div class="muted small">${line(d.gap_after)}</div></td>
        <td class="num ${signCls(d.gain_pct)}">${pct(d.gain_pct, 0)}</td><td class="num">~${d.acceptance}%</td>
        <td><button onclick='openInEvaluator(${JSON.stringify({ b: d.roster_id, aGives: d.give.map(a => ({ kind: a.kind, id: a.id })), bGives: d.get.map(a => ({ kind: a.kind, id: a.id })) })})'>Open in evaluator</button></td></tr>`).join("")}</tbody></table></div>`
      : `<p class="muted">No trade raises your ${T.year} lineup at an acceptable price.</p>`}`;
  $("#fu-year").onchange = e => { state.targetYear = e.target.value; loadTarget(F, e.target.value); };
}

// "Which calculator each manager trusts" on the League prices page.
async function loadCalculators() {
  const host = $("#pr-calc");
  if (!host) return;
  let C;
  try { C = await cachedApi("calc", "/api/calculators"); }
  catch (e) { host.innerHTML = `<h2>Which calculator each manager trusts</h2><div class="warnbox">${esc(e.message)}</div>`; return; }
  if (!$("#pr-calc")) return;
  const name = { ktc: "KeepTradeCut", dynastyprocess: "DynastyProcess" };
  const lean = m => m.lean ? `<span class="badge ${m.strength >= 0.5 ? "acc-Likely" : "acc-Possible"}">${name[m.lean]}</span> <span class="muted small">${m.strength >= 0.5 ? "clear" : "likely"}</span>`
    : `<span class="muted small">${m.n < C.min_trades ? "Too few trades" : "No clear lean"}</span>`;
  const res = v => v == null ? "–" : `<span class="${signCls(v)}">${pct(v, 0)}</span>`;
  host.innerHTML = `<h2>Which calculator each manager trusts</h2>
    <p class="muted small">Each of the ${C.trades} trades is valued on its trade date in KeepTradeCut's and DynastyProcess's own numbers (KTC's daily history, DP's weekly history; picks at the same rank in both).
      A manager who trusts one calculator accepts deals that look fine on it, so their side looks better on that one: that's the ${hint("lean", HELP.calcLean)}. FantasyCalc publishes no history, so it can't be checked.
      A clear lean (${C.min_trades}+ trades) tilts that manager's acceptance odds toward their calculator, and Find trades lists what it rates above and below the consensus.
      DynastyProcess's values fall off faster from stars to depth than KTC's, so a DynastyProcess lean also means valuing studs more.</p>
    ${C.error ? `<div class="warnbox">KTC history unavailable: ${esc(C.error)}</div>` : ""}
    <div class="scroll"><table><thead><tr><th>Manager</th><th class="num">Trades</th><th class="num">Avg. result on KTC</th><th class="num">Avg. result on DP</th><th>${hint("Lean", HELP.calcLean)}</th><th>Trades</th></tr></thead>
      <tbody>${C.managers.map(m => `<tr class="${m.is_me ? "me" : ""}"><td><a href="#/team/${m.roster_id}">${esc(m.manager)}</a></td><td class="num">${m.n}</td>
        <td class="num">${res(m.avg_gain.ktc)}</td><td class="num">${res(m.avg_gain.dynastyprocess)}</td><td data-sort="${m.lean ? m.strength : -1}">${lean(m)}</td>
        <td class="small">${m.trades.length ? `<details><summary>${m.trades.length} trade${m.trades.length === 1 ? "" : "s"}</summary>${m.trades.map(t => `<div style="margin:4px 0"><b>${esc(t.date)}</b> got ${esc(t.recv.map(a => a.name).join(", "))}<br>for ${esc(t.sent.map(a => a.name).join(", "))}
          <div class="muted">KTC ${pct(t.gain.ktc, 0)} · DP ${pct(t.gain.dynastyprocess, 0)}</div></div>`).join("")}</details>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
  makeSortable(host);
}

// Model checks on the Deadline and Buy low pages.
async function loadChecks(which) {
  const host = $(which === "sell" ? "#dl-check" : "#bl-check");
  if (!host) return;
  let K;
  try { K = await cachedApi("checks", "/api/checks"); }
  catch (e) { host.innerHTML = `<div class="warnbox">${esc(e.message)}</div>`; return; }
  if (!$(which === "sell" ? "#dl-check" : "#bl-check")) return;
  const row = (label, s) => `<tr><td>${label}</td><td class="num">${s.n ? fmt(s.n) : "–"}</td><td class="num ${signCls(s.median_pct)}">${s.n ? pct(s.median_pct, 0) : "–"}</td><td class="num">${s.n ? s.beat_pct + "%" : "–"}</td></tr>`;
  const head = `<thead><tr><th></th><th class="num">Player-dates</th><th class="num">${hint("Vs. similar players", HELP.vsPeersBack)}</th><th class="num">Beat them</th></tr></thead>`;
  if (which === "sell") {
    const S = K.sell_timing;
    if (!S.ok) { host.innerHTML = `<h2>How reliable are the sell verdicts?</h2><p class="muted">Not enough value history to check.</p>`; return; }
    const lab = { rising: "Rising", hold: "Hold for now", soon: "Sell within a year", sell: "Sell now" };
    host.innerHTML = `<h2>How reliable are the sell verdicts?</h2>
      <p class="muted small">Checked on data the model didn't see: the age curve was refit using only results known by ${esc(S.train_until)}, then each player's verdict every 4 weeks from ${esc(S.test_from)} to ${esc(S.test_to)} was compared with his value a year later.</p>
      <table data-nosort>${head}<tbody>${Object.entries(S.verdicts).map(([k, s]) => row(lab[k], s)).join("")}</tbody></table>
      <p class="small">"Sell" players did worse than similar players a year later and "rising" ones did better, so the verdicts sort players the right way. Expected value a year out:
        actual values averaged <b>${S.expected.mean_ratio_pct}%</b> of the expectation (median ${S.expected.median_ratio_pct}%), with a typical miss of ${S.expected.median_error_pct}% of the player's value. Treat it as a center, not a promise.</p>`;
  } else {
    const B = K.buy_low;
    if (!B.ok) { host.innerHTML = `<h2>Does buying the dip work?</h2><p class="muted">Not enough value history to check.</p>`; return; }
    host.innerHTML = `<h2>Does buying the dip work?</h2>
      <p class="muted small">Every 4 weeks from ${esc(B.since)} to ${esc(B.until)}: players down 15%+ from their 4-month high (high 800+, below their position's sell age), compared with similar players 6 and 12 months later.
        Weekly usage isn't available for past seasons, so this tests the price drop alone, not the "role held" filter this page also uses.</p>
      <div class="grid g2">${Object.entries(B.horizons).map(([h, x]) => `<div><h3>${esc(h)} later</h3><table data-nosort>${head}<tbody>${row("All dips", x.dipped)}${x.depth.map(d => row(d.label, d)).join("")}</tbody></table></div>`).join("")}</div>
      <p class="small">A dip alone isn't a strong signal. Moderate dips have come back a little better than similar players over a year, but deeper drops did no better: those players usually lost value for a reason.
        So the list ranks drops past 25% no higher than a 25% drop, and leans on the role check to separate scares from real declines.</p>`;
  }
}

// "When players are worth the most" on the Deadline page.
async function loadSeasonal() {
  const host = $("#dl-season");
  if (!host) return;
  let S;
  try { S = await cachedApi("seasonal", "/api/seasonal"); } catch (e) { host.innerHTML = `<h2>When players are worth the most</h2><div class="warnbox">${esc(e.message)}</div>`; return; }
  if (!$("#dl-season") || !S.groups.length) return;
  const cell = v => v == null ? '<td class="num muted">–</td>'
    : `<td class="num ${v - 100 >= 3 ? "delta-pos" : v - 100 <= -3 ? "delta-neg" : "muted"}">${v - 100 > 0 ? "+" : ""}${Math.round(v - 100)}</td>`;
  host.innerHTML = `<h2>When players are worth the most</h2>
    <p class="muted small">Typical dynasty value by month vs. the player's normal level that year (DynastyProcess, ${esc(S.since)} to ${esc(S.until)}, players worth ${fmt(S.min_value)}+; each player's long-run trend is removed, so aging and breakouts don't count).
      Most groups dip in May, when the new rookie class arrives, and run high from late in the season through winter. Swings under about 5% are within the noise.</p>
    ${S.mine.length ? `<h3>Your players</h3><table data-nosort><thead><tr><th>Player</th><th>Group</th><th class="num">Best month ahead</th><th class="num">Worst month ahead</th></tr></thead><tbody>
      ${S.mine.slice(0, 10).map(m => `<tr><td>${posBadge(m.pos)} ${playerLink(m.id, m.name)}</td><td class="small">${esc(m.group)}</td>
        <td class="num">${m.best} <span class="small ${signCls(m.best_pct)}">${pct(m.best_pct, 0)}</span></td><td class="num">${m.worst} <span class="small ${signCls(m.worst_pct)}">${pct(m.worst_pct, 0)}</span></td></tr>`).join("")}</tbody></table>` : ""}
    <h3>By position and age (% vs. normal)</h3>
    <div class="scroll"><table data-nosort><thead><tr><th>Group</th>${S.months.map((m, i) => `<th class="num ${i === S.month ? "me" : ""}">${m}</th>`).join("")}</tr></thead>
      <tbody>${S.groups.map(g => `<tr><td><b>${esc(g.label)}</b></td>${g.index.map(cell).join("")}</tr>`).join("")}</tbody></table></div>`;
}

// Season impact and offer message under the evaluator.
async function loadImpact(tok) {
  const tr = state.trade, host = $("#impact-out");
  if (!host) return;
  let r;
  try { r = await api("/api/trade-impact", { method: "POST", body: { a_rid: tr.a, a_gives: tr.aGives, b_rid: tr.b, b_gives: tr.bGives } }); }
  catch (e) { host.innerHTML = `<h2>Season impact</h2><div class="warnbox">${esc(e.message)}</div>`; return; }
  if (tok !== state.evalTok || !$("#impact-out")) return;
  if (!r.teams.length) { host.remove(); return; }
  const arrow = (b, a, f, better) => `${f(b)} → <b>${f(a)}</b> <span class="small ${Math.abs(a - b) < 0.05 ? "muted" : (better(a, b) ? "delta-pos" : "delta-neg")}">${a - b > 0 ? "+" : ""}${f(a - b)}</span>`;
  const p0 = v => v.toFixed(0) + "%", s1 = v => v.toFixed(1);
  host.innerHTML = `<h2>Season impact</h2>
    <p class="muted small">The rest of this season simulated with and without the trade (same simulated games both times, ${r.weeks_left} weeks left), from Sleeper's weekly projections.
      Your league orders its rookie draft by ${r.draft_rule === "max_pf" ? "max points for non-playoff teams" : "record for non-playoff teams"}, so weakening a lineup can move a pick up.</p>
    <table data-nosort><thead><tr><th>Team</th><th class="num">Playoff odds</th><th class="num">Title odds</th><th class="num">${hint(`Own ${r.draft_season} 1st`, HELP.draftSlot)}</th></tr></thead>
      <tbody>${r.teams.map(t => `<tr><td><b>${esc(t.manager)}</b></td>
        <td class="num">${arrow(t.playoff_pct[0], t.playoff_pct[1], p0, (a, b) => a > b)}</td>
        <td class="num">${arrow(t.title_pct[0], t.title_pct[1], p0, (a, b) => a > b)}</td>
        <td class="num">#${arrow(t.avg_slot[0], t.avg_slot[1], s1, (a, b) => a < b)}${t.pick_owner_after && t.pick_owner_after !== t.manager ? `<div class="muted small">owned by ${esc(t.pick_owner_after)}</div>` : ""}</td></tr>`).join("")}</tbody></table>`;
}

async function runPitch() {
  const tr = state.trade, out = $("#pitch-out");
  if (!out) return;
  out.innerHTML = `<p class="muted">Writing…</p>`;
  let r;
  try { r = await api("/api/pitch", { method: "POST", body: { a_rid: tr.a, a_gives: tr.aGives, b_rid: tr.b, b_gives: tr.bGives } }); }
  catch (e) { out.innerHTML = `<div class="warnbox">${esc(e.message)}</div>`; return; }
  out.innerHTML = `<textarea id="pitch-text" rows="${r.text.split("\n").length + 1}" style="width:100%">${esc(r.text)}</textarea>
    <div class="row"><button class="primary" id="pitch-copy">Copy</button><span class="muted small">Edit it however you like before sending.${r.points.length ? "" : " (No strong selling points found for their side.)"}</span></div>`;
  $("#pitch-copy").onclick = () => copyText($("#pitch-text").value, $("#pitch-text"));
}

// ---------------------------------------------------------------- weekly recap
async function viewRecap(week) {
  const R = await api(`/api/recap${week ? `?week=${week}` : ""}`);
  if (!R.weeks.length) return `<div class="card"><h1>Weekly recap</h1><p class="muted">No completed weeks this season yet.</p></div>`;
  setTimeout(() => {
    const sel = $("#rc-week");
    if (sel) sel.onchange = e => { location.hash = `#/recap/${e.target.value}`; };
    const cp = $("#rc-copy");
    if (cp) cp.onclick = () => copyText($("#rc-text").value, $("#rc-text"));
  }, 0);
  return `<div class="card"><div class="row spread"><h1>Weekly recap</h1>
      <label class="field">Week<select id="rc-week">${R.weeks.map(w => `<option ${w === R.week ? "selected" : ""}>${w}</option>`).join("")}</select></label></div>
    <p class="muted">A recap of week ${R.week} to paste into your league chat. Upsets use Sleeper's projections for each team's starters that week; trades are judged at today's values; value movers are DynastyProcess's weekly changes for rostered players.</p></div>
  <div class="grid g2">${R.sections.map(s => `<div class="card"><h2>${esc(s.title)}</h2>${s.numbered
    ? `<ol class="small" style="margin:0;padding-left:20px">${s.lines.map(x => `<li>${esc(x.replace(/^\d+\.\s*/, ""))}</li>`).join("")}</ol>`
    : `<ul class="notes">${s.lines.map(x => `<li>${esc(x)}</li>`).join("")}</ul>`}</div>`).join("")}</div>
  <div class="card"><div class="row spread"><h2>For the league chat</h2><button class="primary" id="rc-copy">Copy</button></div>
    <textarea id="rc-text" rows="14" style="width:100%">${esc(R.text)}</textarea></div>`;
}

// ---------------------------------------------------------------- roster room
async function viewRoster() {
  const R = await cachedApi("roster", "/api/roster-room");
  const st = R.settings, me = R.me;
  const list = xs => xs.length ? xs.map(a => `${a.kind === "player" ? posBadge(a.pos) + " " + playerLink(a.id, a.name) : esc(a.name)} <span class="muted small">${fmt(a.value)}</span>`).join("<br>") : '<span class="muted small">None</span>';
  const taxiRule = `Players can stay on taxi through their first ${st.taxi_years} NFL season${st.taxi_years === 1 ? "" : "s"}${st.allow_vets ? "; veterans in that window can be moved there too" : "; only rookies can be added"}.`;
  if (!me) return `<div class="card"><h1>Roster room</h1><p class="muted">Your username wasn't found in the league; check Settings.</p></div>`;
  const over = Math.max(0, me.over);
  return `<div class="card"><h1>Roster room · ${R.season}</h1>
    <p class="muted">Next offseason, your picks become rookies and taxi players who've aged out need active spots. This plans the taxi squad and shows who to cut (or trade first) if the roster overflows.
      Roster limit: ${st.limit} QB/RB/WR/TE spots${st.other_slots ? ` (after ${st.other_slots} kicker/defense spot${st.other_slots === 1 ? "" : "s"})` : ""}, plus ${st.taxi_slots} taxi and ${st.ir_slots} IR. ${taxiRule}</p>
    <div class="tiles">
      <div class="tile ${over ? "" : "mine"}"><div class="k">Cuts needed</div><div class="v">${over}</div><div class="d muted">${me.active} for ${st.limit} spots</div></div>
      <div class="tile"><div class="k">Incoming rookies</div><div class="v">${me.rookies.length}</div><div class="d muted">${R.season} picks you own</div></div>
      <div class="tile"><div class="k">Taxi next season</div><div class="v">${me.taxi_stay.length + me.to_taxi.length}/${st.taxi_slots}</div><div class="d muted">${me.promoted.length} coming off</div></div>
    </div></div>
  <div class="grid g2">
    <div class="card"><h2>Taxi plan</h2><table data-nosort><tbody>
      <tr><td>Staying on taxi</td><td>${list(me.taxi_stay)}</td></tr>
      <tr><td>Moving to taxi</td><td>${list(me.to_taxi)}</td></tr>
      <tr><td>Aging off taxi (need an active spot)</td><td>${list(me.promoted)}</td></tr>
      <tr><td>Incoming rookies</td><td>${list(me.rookies)}</td></tr>
      <tr><td>On IR now (need a spot if healthy)</td><td>${list(me.ir)}</td></tr></tbody></table>
      ${me.taxi_stay.length >= st.taxi_slots && me.rookies.length ? `<p class="muted small">Your taxi squad is full with players who can stay, so the rookies need active spots, unless you cut or promote a taxi player (the cut order includes them).</p>` : ""}</div>
    <div class="card"><h2>${over ? `Cut order (${over})` : "No cuts needed"}</h2>
      ${me.cuts.length ? `<table data-nosort><thead><tr><th>Player</th><th class="num">Value</th><th class="num">${hint("Next year", HELP.keepValue)}</th><th></th></tr></thead>
        <tbody>${me.cuts.map(c => `<tr><td>${c.kind === "player" ? posBadge(c.pos) + " " + playerLink(c.id, c.name) : esc(c.name)} <span class="muted small">${c.age ?? ""}</span></td>
          <td class="num">${fmt(c.value)}</td><td class="num">${fmt(c.keep)}</td><td class="small">${c.taxi ? '<span class="badge tag">on taxi: a rookie takes his spot</span> ' : ""}${c.value >= 500 ? '<span class="badge tag">trade first</span>' : ""}</td></tr>`).join("")}</tbody></table>
        ${me.trade_first.length ? `<p class="small">${me.trade_first.length} of these still have trade value. Package two for one better player before the draft instead of cutting them for nothing.</p>` : ""}` : `<p class="muted">Everyone fits.</p>`}
      ${me.next_cuts.length ? `<p class="muted small">Next in line: ${me.next_cuts.map(c => esc(c.name)).join(", ")}.</p>` : ""}</div>
  </div>
  <div class="card"><h2>Around the league</h2>
    <p class="muted small">Teams that will have to cut players next offseason. Their cut candidates are cheap to trade for now, and some will reach waivers.</p>
    <div class="scroll"><table><thead><tr><th>Team</th><th class="num">Cuts needed</th><th>Likely cuts</th></tr></thead>
      <tbody>${R.teams.map(t => `<tr><td><a href="#/team/${t.roster_id}">${esc(t.manager)}</a></td><td class="num" data-sort="${t.over}">${Math.max(0, t.over)}</td>
        <td class="small">${t.cuts.map(c => `${esc(c.name)} <span class="muted">${fmt(c.value)}</span>`).join(", ") || '<span class="muted">None</span>'}</td></tr>`).join("")}</tbody></table></div>
    ${R.likely_cuts.some(c => c.kind === "player" && c.value >= 500) ? `<h3>Best players likely to be cut</h3><table data-nosort><tbody>${R.likely_cuts.filter(c => c.kind === "player" && c.value >= 500).map(c => `<tr>
      <td>${posBadge(c.pos)} ${playerLink(c.id, c.name)} <span class="muted small">${esc(c.manager)}</span></td><td class="num">${fmt(c.value)}</td>
      <td><button onclick='openInEvaluator(${JSON.stringify({ b: c.roster_id, aGives: [], bGives: [{ kind: "player", id: c.id }] })})'>Trade for</button></td></tr>`).join("")}</tbody></table>` : ""}
  </div>`;
}

// ---------------------------------------------------------------- rookie hit rates
const OUTCOME = {
  elite: { label: "Elite", cls: "acc-Likely" }, starter: { label: "Starter", cls: "acc-Likely" },
  flex: { label: "Flex", cls: "acc-Possible" }, bust: { label: "Bust", cls: "acc-Unlikely" },
};
const OUTCOME_KEYS = ["elite", "starter", "flex", "bust"];
const POS_SERIES = { QB: 1, RB: 2, WR: 3, TE: 4 };
const ord = n => `${n}${["th", "st", "nd", "rd"][(n % 100 > 10 && n % 100 < 14) ? 0 : n % 10] || "th"}`;
Object.assign(HELP, {
  hitDef: "Hit = at least one starter season (elite or starter) in his first 3 NFL seasons, by PPR points per game with at least 7 games. Bust = not even one flex-level season.",
  valueHeld: "Total dynasty value of all of a position's rookie picks, k years after their draft, as a % of their total on draft day. Above 100 = the picks as a group gained value (the hits gained more than the busts lost).",
  stillStarting: "Of players at that position who had at least one starter season, the share who had a starter season in that year of their career.",
  capitalOdds: "Of QB/RB/WR/TE drafted into the NFL around the same overall pick at the same position (2000 on), the share with a starter season in their first 3 years / the share without even a flex season.",
  valueKept: "What the players taken at those slots were worth three years later, as a % of what they were worth on draft day (both DynastyProcess). Above 100% = the market priced those picks too low.",
});

// Plain-language takeaways from the slot data (computed, so they follow the data).
function slotTakeaways(H) {
  const c = H.curves, n = H.teams, t = H.slot_tiers;
  const avg = (xs) => xs.reduce((s, x) => s + x, 0) / xs.length;
  const top = avg(c.hit.slice(0, 3)), rest1 = avg(c.hit.slice(3, n));
  const out = [`The biggest divide is the top of the 1st round: picks 1.01–1.03 have hit ${Math.round(top)}% of the time, the rest of the 1st ${Math.round(rest1)}%.`];
  for (let r = 1; r <= H.rounds; r++) {
    const e = t.find(x => x.round === r && x.tier === "early"), l = t.find(x => x.round === r && x.tier === "late");
    if (!e || !l) continue;
    const ek = Math.round(e.payoff * 100), lk = Math.round(l.payoff * 100), name = `${ord(r)}s`;
    const odds = `${Math.round(l.hit)}% hit vs. ${Math.round(e.hit)}% for early ${name}`;
    if (Math.abs(lk - ek) < 20 && Math.abs(e.hit - l.hit) < 12) out.push(`In the ${ord(r)} round the slot barely matters (${odds}; ${lk}% vs. ${ek}% of value kept).`);
    else if (lk > ek) out.push(`Late ${name} have been the better value for the price: ${l.hit < e.hit - 5 ? "less likely to hit" : "about as likely to hit"} (${odds}), but they kept ${lk}% of their value vs. ${ek}%${l.price_now < e.price_now ? ` and cost less (${fmt(l.price_now)} vs. ${fmt(e.price_now)} today)` : ""}.`);
    else out.push(`Early ${name} have held up better than late ones: ${ek}% of value kept vs. ${lk}% (${Math.round(e.hit)}% vs. ${Math.round(l.hit)}% hit).`);
  }
  return out.join(" ");
}

function hitThresholds(H) {
  const t = H.thresholds;
  const f = k => ["QB", "RB", "WR", "TE"].map(p => `${p}${t[k][p]}`).join(", ");
  return `Elite: top ${f("elite")}. Starter: ${f("starter")}. Flex: ${f("flex")} (positional rank by PPR points per game, ${H.min_games}+ games).`;
}

async function viewHitRates() {
  const H = await cachedApi("hits", "/api/rookie-hits");
  setTimeout(() => drawHitRates(H), 0);
  const rows = x => `<td class="num">${x.n}</td>${OUTCOME_KEYS.map(k => `<td class="num">${x.n ? Math.round(x[k]) + "%" : "–"}</td>`).join("")}<td class="num"><b>${x.n ? Math.round(x.hit) + "%" : "–"}</b></td>`;
  const head = `<th class="num">Picks</th>${OUTCOME_KEYS.map(k => `<th class="num">${OUTCOME[k].label}</th>`).join("")}<th class="num">${hint("Hit", HELP.hitDef)}</th>`;
  const nm = r => `${ord(r)} round`;
  const L = H.longevity.positions;
  const byClass = {};
  for (const p of H.picks) (byClass[p.cls] ||= []).push(p);
  const finish = p => p.best ? `${p.pos}${p.best} in ${p.best_season}` : "–";
  return `<div class="card"><h1>Rookie pick hit rates</h1>
    <p class="muted">How often rookie picks turn into starters, from the ${H.complete_classes[0]}–${H.complete_classes[H.complete_classes.length - 1]} rookie classes (the ones with ${H.window} full NFL seasons to judge).
      Each class is ranked by DynastyProcess's ${H.superflex ? "superflex" : "1QB"} values just before rookie-draft season, and the top ${H.teams * H.rounds} become picks 1.01–${H.rounds}.${String(H.teams).padStart(2, "0")} for a ${H.teams}-team league:
      a stand-in for where they actually went. Outcomes are judged over each player's first ${H.window} seasons. ${hint("Definitions", hitThresholds(H))}</p>
    <div class="tiles">${H.by_round.map(r => `<div class="tile"><div class="k">${nm(r.round)} pick</div><div class="v">${Math.round(r.hit)}% hit</div>
      <div class="d muted">${Math.round(r.bust)}% bust · ${Math.round(r.elite)}% elite · ${r.n} picks</div></div>`).join("")}</div>
    <p class="muted small">About ${H.by_round[0].n} picks per round, so each rate is good to roughly ±12 points.</p></div>
  <div class="grid g2">
    <div class="card"><h2>By round and slot</h2><div class="hr-legend-o"></div><div id="hr-round"></div>
      <table data-nosort><thead><tr><th>Picks</th>${head}</tr></thead><tbody>
        ${H.by_round.map(r => `<tr><td><b>${nm(r.round)}</b></td>${rows(r)}</tr>${r.tiers.map(t => `<tr><td class="muted">&nbsp;&nbsp;${t.label}</td>${rows(t)}</tr>`).join("")}`).join("")}
      </tbody></table></div>
    <div class="card"><h2>By position</h2><div class="hr-legend-o"></div><div id="hr-pos"></div>
      <table data-nosort><thead><tr><th>Position</th><th class="num">Picks</th>${H.by_round.map(r => `<th class="num">${nm(r.round)} hit</th>`).join("")}<th class="num">All: hit</th><th class="num">All: bust</th></tr></thead><tbody>
        ${H.by_pos.map(p => `<tr><td>${posBadge(p.pos)}</td><td class="num">${p.n}</td>
          ${p.rounds.map(r => `<td class="num">${r.n ? `${Math.round(r.hit)}% <span class="muted small">of ${r.n}</span>` : "–"}</td>`).join("")}
          <td class="num"><b>${Math.round(p.hit)}%</b></td><td class="num">${Math.round(p.bust)}%</td></tr>`).join("")}
      </tbody></table>
      <p class="muted small">Position samples are small (tight ends especially), so read across rounds rather than at single cells.</p></div>
  </div>
  <div class="card"><h2>Early or late: does the slot matter?</h2>
    <p>${slotTakeaways(H)}</p>
    <div class="grid g2">
      <div><h3>Hit and bust rate by slot</h3><div id="hr-slot-legend"></div><div id="hr-slot"></div>
        <p class="muted small">Smoothed across neighboring slots (each slot alone has only ${H.complete_classes.length} picks).</p></div>
      <div><h3>${hint("Value kept after 3 years", HELP.valueKept)}</h3><div id="hr-kept"></div>
        <p class="muted small">Above 0: picks there have been underpriced on draft day (buy). Below: overpriced (sell before the draft).</p></div>
    </div>
    <div class="scroll"><table data-nosort><thead><tr><th>Picks</th><th class="num">Hit</th><th class="num">Bust</th><th class="num">Draft day</th><th class="num">3 years later (avg.)</th>
      <th class="num">${hint("Value kept", HELP.valueKept)}</th><th class="num">Price today</th></tr></thead>
      <tbody>${H.slot_tiers.map(t => `<tr><td><b>${t.label}</b></td><td class="num">${Math.round(t.hit)}%</td><td class="num">${Math.round(t.bust)}%</td>
        <td class="num">${fmt(t.draft_day)}</td><td class="num">${fmt(t.mean_later)}</td>
        <td class="num ${t.payoff >= 1.15 ? "delta-pos" : t.payoff <= 0.85 ? "delta-neg" : ""}">${Math.round(t.payoff * 100)}%</td><td class="num">${fmt(t.price_now)}</td></tr>`).join("")}</tbody></table></div>
    <p class="muted small">Draft day and 3 years later are what the players taken there were worth (average), in the app's value scale. Price today is the market's current price for a next-year pick in that range.
      Your own picks are priced from the season simulation's odds of landing in each slot; see <a href="#/draftprep">Upcoming draft</a>.</p></div>
  <div class="card"><h2>By NFL draft capital</h2>
    <p class="muted small">Where a player went in the NFL draft is the strongest single predictor of a hit. Every QB/RB/WR/TE drafted ${H.capital.from}–${H.capital.to} (${Object.values(H.capital.positions).reduce((a, p) => a + p.n, 0).toLocaleString()} players), same definitions, first ${H.capital.window} seasons.
      Rookies in their first three seasons get these odds in their player notes, and the draft board shows them once a class is drafted.</p>
    <div class="grid g2">
      <div><h3>Hit rate by overall NFL pick</h3><div id="hr-cap-legend"></div><div id="hr-cap"></div></div>
      <div><table data-nosort><thead><tr><th>Overall pick</th>${["QB", "RB", "WR", "TE"].map(p => `<th class="num">${posBadge(p)}</th>`).join("")}</tr></thead>
        <tbody>${H.capital.positions.QB.ranges.map((r, i) => `<tr><td>${r.label}</td>${["QB", "RB", "WR", "TE"].map(p => {
          const x = H.capital.positions[p].ranges[i];
          return `<td class="num">${x.n ? `<b>${Math.round(x.hit)}%</b> <span class="muted small">/ ${Math.round(x.bust)}% · ${x.n}</span>` : "–"}</td>`;
        }).join("")}</tr>`).join("")}</tbody></table>
        <p class="muted small">Hit % / bust % · players. Running backs keep decent odds into the 2nd round; receivers are the least sure thing even in the top 10, and fall off fast after the 1st.</p></div>
    </div></div>
  <div class="card"><h2>How long value lasts</h2>
    <div class="grid g2">
      <div><h3>${hint("Still a starter", HELP.stillStarting)}, by year of career</h3><div id="hr-legend-a"></div><div id="hr-long"></div>
        <p class="muted small">NFL draft picks ${H.longevity.from}–${H.longevity.to} who had at least one starter season, followed for ${H.longevity.years} seasons.</p></div>
      <div><h3>${hint("Dynasty value kept", HELP.valueHeld)}, years after the draft</h3><div id="hr-legend-b"></div><div id="hr-value"></div>
        <p class="muted small">Rookie picks from the ${H.classes[0]}+ classes; later years rest on fewer classes (${H.value_curve.reduce((s, p) => s + p.n[H.value_years], 0)} picks reach year ${H.value_years}).</p></div>
    </div>
    <table data-nosort><thead><tr><th>Position</th><th class="num">Players who hit</th><th class="num">Starter seasons (typical)</th><th class="num">Average</th><th class="num">Best year</th><th class="num">Half as many starting by</th></tr></thead>
      <tbody>${L.map(p => `<tr><td>${posBadge(p.pos)}</td><td class="num">${p.n}</td><td class="num">${p.median_seasons}</td><td class="num">${p.mean_seasons}</td>
        <td class="num">year ${p.peak_year}</td><td class="num">${p.half_life ? `year ${p.half_life}` : `after year ${H.longevity.years}`}</td></tr>`).join("")}</tbody></table>
    <p class="small">Running backs start fast and fade fast; receivers and quarterbacks keep producing for years. For a rebuild, a rookie RB's best seasons may come before your window opens, while a WR or QB's are still ahead.</p></div>
  <div class="card"><h2>Every pick</h2><p class="muted small">Ranked by draft-day value within each class. Classes with fewer than ${H.window} seasons are "so far".</p>
    ${H.classes.slice().reverse().map(c => {
      const ps = byClass[c] || [], done = ps[0]?.complete;
      const seasons = ps[0]?.seasons || 0;
      const tally = OUTCOME_KEYS.filter(k => done || k !== "bust").map(k => `${ps.filter(p => p.outcome === k).length} ${OUTCOME[k].label.toLowerCase()}`).join(" · ");
      return `<details><summary><b>${c}</b> <span class="muted small">${done ? tally : seasons ? `${seasons} season${seasons === 1 ? "" : "s"} so far · ${tally}` : "no NFL seasons yet"}</span></summary>
        <div class="scroll"><table data-nosort><thead><tr><th>Pick</th><th>Player</th><th>Outcome</th><th>Best finish</th><th class="num">Value now</th></tr></thead><tbody>
        ${ps.map(p => `<tr><td>${p.label}</td><td>${posBadge(p.pos)} ${p.sleeper_id ? playerLink(p.sleeper_id, p.name) : esc(p.name)}</td>
          <td>${p.seasons ? `<span class="badge ${OUTCOME[p.outcome].cls}">${OUTCOME[p.outcome].label}</span>${done ? "" : ' <span class="muted small">so far</span>'}` : '<span class="muted small">no seasons yet</span>'}</td>
          <td class="small">${finish(p)}</td><td class="num">${p.value_now ? fmt(p.value_now) : "–"}</td></tr>`).join("")}</tbody></table></div></details>`;
    }).join("")}</div>`;
}

function drawHitRates(H) {
  const colors = OUTCOME_KEYS.map((_, i) => `var(--age-${4 - i})`), onColors = OUTCOME_KEYS.map((_, i) => `var(--on-age-${4 - i})`);
  const labels = Object.fromEntries(OUTCOME_KEYS.map(k => [k, OUTCOME[k].label]));
  const bar = x => ({ parts: Object.fromEntries(OUTCOME_KEYS.map(k => [k, x[k] || 0])), tip: Object.fromEntries(OUTCOME_KEYS.map(k => [k, `${x.counts[k]} of ${x.n} picks`])) });
  const drawRound = () => $("#hr-round") && stackedBars($("#hr-round"), {
    rows: H.by_round.flatMap(r => [{ label: `${ord(r.round)} round`, ...bar(r) }, ...r.tiers.map(t => ({ label: t.label, ...bar(t) }))]),
    keys: OUTCOME_KEYS, labels, max: 100, colors, onColors, title: "Rookie pick outcomes by round and slot" });
  const drawPos = () => $("#hr-pos") && stackedBars($("#hr-pos"), {
    rows: H.by_pos.map(p => ({ label: p.pos, ...bar(p) })), keys: OUTCOME_KEYS, labels, max: 100, colors, onColors, title: "Rookie pick outcomes by position" });
  const line = (id, values, n, xl, title) => {
    const host = $(id);
    if (!host) return;
    const dates = Array.from({ length: n }, (_, k) => `${2000 + k}-01-01`);
    lineChart(host, { dates, xLabels: xl, title, height: 240, format: v => Math.round(v) + "%",
      series: values.map(v => ({ id: v.pos, label: v.pos, values: v.vals, highlight: true, color: `var(--series-${POS_SERIES[v.pos]})` })) });
  };
  const leg = H.by_pos.map(p => ({ label: p.pos, color: `var(--series-${POS_SERIES[p.pos]})` }));
  ["#hr-legend-a", "#hr-legend-b"].forEach(id => { if ($(id)) $(id).innerHTML = legendHTML(leg); });
  $$(".hr-legend-o").forEach(el => (el.innerHTML = legendHTML(OUTCOME_KEYS.map((k, i) => ({ label: OUTCOME[k].label, color: colors[i], rect: true })))));
  const drawLong = () => line("#hr-long", H.longevity.positions.map(p => ({ pos: p.pos, vals: p.share })), H.longevity.years,
    Array.from({ length: H.longevity.years }, (_, k) => `Yr ${k + 1}`), "Share still starting by year of career");
  const drawValue = () => line("#hr-value", H.value_curve.map(p => ({ pos: p.pos, vals: p.held })), H.value_years + 1,
    Array.from({ length: H.value_years + 1 }, (_, k) => k ? `Yr ${k}` : "Draft"), "Dynasty value kept by years after the draft");
  const slots = c => Array.from({ length: c.hit.length }, (_, i) => `${Math.floor(i / H.teams) + 1}.${String(i % H.teams + 1).padStart(2, "0")}`);
  if ($("#hr-slot-legend")) $("#hr-slot-legend").innerHTML = legendHTML([{ label: "Hit", color: "var(--series-1)" }, { label: "Bust", color: "var(--series-2)" }]);
  const drawSlot = () => {
    const host = $("#hr-slot");
    if (!host) return;
    const xl = slots(H.curves);
    lineChart(host, { dates: xl.map((_, k) => `${2000 + k}-01-01`), xLabels: xl, height: 240, format: v => Math.round(v) + "%", title: "Hit and bust rate by draft slot",
      series: [{ id: "hit", label: "Hit", values: H.curves.hit, highlight: true, color: "var(--series-1)" },
               { id: "bust", label: "Bust", values: H.curves.bust, highlight: true, color: "var(--series-2)" }] });
  };
  const drawKept = () => $("#hr-kept") && divergingColumns($("#hr-kept"), { height: 220, xLabel: "Picks", title: "Value kept after 3 years by slot range",
    items: H.slot_tiers.map(t => ({ label: t.label.replace(/–\d\./, "–"), value: Math.round((t.payoff - 1) * 100),
      tip: [{ color: t.payoff >= 1 ? "var(--div-s2)" : "var(--div-n2)", value: `${Math.round(t.payoff * 100)}% kept`, label: `${t.label} · ${t.n_value} picks` }] })) });
  if ($("#hr-cap-legend")) $("#hr-cap-legend").innerHTML = legendHTML(leg);
  const drawCap = () => {
    const host = $("#hr-cap"), g = H.capital.grid;
    if (!host) return;
    lineChart(host, { dates: g.map((_, k) => `${2000 + k}-01-01`), xLabels: g.map(String), height: 240, format: v => Math.round(v) + "%",
      title: "Hit rate by overall NFL draft pick",
      series: ["QB", "RB", "WR", "TE"].map(p => ({ id: p, label: p, values: H.capital.positions[p].hit, highlight: true, color: `var(--series-${POS_SERIES[p]})` })) });
  };
  [drawRound, drawPos, drawLong, drawValue, drawSlot, drawKept, drawCap].forEach(f => f());
  onResize(drawRound, drawPos, drawLong, drawValue, drawSlot, drawKept, drawCap);
}

// ---------------------------------------------------------------- calendar
async function viewCalendar() {
  const C = await cachedApi("calendar", "/api/calendar");
  const KIND = { league: ["League", "res-even"], picks: ["Picks", "acc-Possible"], players: ["Players", "acc-Likely"] };
  const byMonth = {};
  for (const e of C.events) (byMonth[e.date.slice(0, 7)] ||= []).push(e);
  const monthName = k => { const d = new Date(k + "-01T00:00"); return `${d.toLocaleString(undefined, { month: "long" })} ${d.getFullYear()}`; };
  return `<div class="card"><h1>Calendar</h1>
    <p class="muted">Your league's key dates through next year's rookie draft, and what to do at each one. "Around" dates are estimates: typical months from past seasons, the NFL draft's usual week, and your rookie draft from last year's date.
      ${C.week ? `It's week ${C.week}.` : ""}</p></div>
  ${Object.entries(byMonth).map(([m, es]) => `<div class="card"><h2>${monthName(m)}</h2>
    ${es.map(e => `<div class="row" style="align-items:flex-start;gap:14px;margin:10px 0">
      <div style="min-width:76px"><b>${e.approx ? '<span class="muted small">around</span><br>' : ""}${shortDate(e.date)}</b></div>
      <div style="flex:1"><div><b>${esc(e.title)}</b> <span class="badge ${KIND[e.kind][1]}">${KIND[e.kind][0]}</span></div>
        <div class="small">${esc(e.what)}${e.link ? ` <a href="${e.link}">Open →</a>` : ""}</div></div></div>`).join("")}</div>`).join("")
    || '<div class="card"><p class="muted">Nothing on the calendar yet.</p></div>'}`;
}

// ---------------------------------------------------------------- trade plan
// The plan lives in this browser (per league): a list of { b, aGives, bGives } with you as Team A.
const planKey = () => `plan:${state.ov?.config?.league_id || ""}`;
function loadPlan() { try { return JSON.parse(localStorage.getItem(planKey()) || "[]"); } catch { return []; } }
function savePlan(p) { try { localStorage.setItem(planKey(), JSON.stringify(p)); } catch { /* private mode: the plan lasts until reload */ } }

async function viewPlan() {
  await overview();
  const plan = loadPlan();
  const head = `<div class="card"><h1>Trade plan</h1>
    <p class="muted">A rebuild is usually several trades. Add trades from <a href="#/trade">Evaluate</a> (you as Team A) and see them together: whether they clash, and what they do to your season, your rebuild timeline and your roster.
      Trades run in order, so a later trade can send on something an earlier one brought in. The plan is saved in this browser.</p></div>`;
  if (!plan.length) return head + `<div class="card"><p class="muted">Your plan is empty. Build a trade in <a href="#/trade">Evaluate</a> and click <b>Add to trade plan</b>.</p></div>`;
  const R = await api("/api/plan", { method: "POST", body: { trades: plan.map(t => ({ b_rid: t.b, a_gives: t.aGives, b_gives: t.bGives })) } });
  setTimeout(() => wirePlan(plan), 0);
  const list = xs => xs.map(a => `${a.kind === "player" ? posBadge(a.pos) + " " : ""}${esc(a.name)} <span class="muted small">${fmt(a.value)}</span>`).join("<br>") || '<span class="muted small">nothing</span>';
  // Only show a change that's visible at the displayed precision.
  const arrow = (b, a, f = fmt, better = (x, y) => x > y) => `${f(b)} → <b>${f(a)}</b>${f(a) !== f(b) ? ` <span class="small ${better(a, b) ? "delta-pos" : "delta-neg"}">${a - b > 0 ? "+" : ""}${f(a - b)}</span>` : ""}`;
  const T = R.timeline, C = R.composition, N = R.now;
  const p1 = v => (+v).toFixed(1);
  return head + `
  ${R.problems.length ? `<div class="warnbox"><b>Check these:</b><ul class="notes">${R.problems.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
  <div class="tiles" style="margin:0 0 16px">
    <div class="tile"><div class="k">Market value</div><div class="v">${R.total.get - R.total.give >= 0 ? "+" : ""}${fmt(R.total.get - R.total.give)}</div><div class="d muted">${fmt(R.total.get)} in · ${fmt(R.total.give)} out</div></div>
    <div class="tile"><div class="k">Team-context gain</div><div class="v ${signCls(R.total.gain)}">${R.total.gain >= 0 ? "+" : ""}${fmt(R.total.gain)}</div><div class="d muted">sum over the trades</div></div>
    ${T.years.slice(1).map((y, i) => `<div class="tile ${T.rank[1][i + 1] <= T.playoff_teams ? "mine" : ""}"><div class="k">${esc(y)} rank</div><div class="v">#${T.rank[0][i + 1]} → #${T.rank[1][i + 1]}</div>
      <div class="d muted">lineup ${compact(T.strength[0][i + 1])} → ${compact(T.strength[1][i + 1])}</div></div>`).join("")}
  </div>
  <div class="card"><h2>Trades, in order</h2>
    <div class="scroll"><table data-nosort><thead><tr><th>#</th><th>With</th><th>You give</th><th>You get</th><th class="num">Market</th><th class="num">Your gain</th><th class="num">They accept</th><th></th></tr></thead>
      <tbody>${R.trades.map((t, i) => `<tr><td>${i + 1}</td>${t.skipped ? `<td colspan="6" class="muted">${esc(t.manager || "")}: skipped (see above)</td>` : `
        <td><a href="#/team/${t.roster_id}">${esc(t.manager)}</a></td><td>${list(t.give)}</td><td>${list(t.get)}</td>
        <td class="num ${signCls(t.market_pct)}">${pct(t.market_pct, 0)}</td><td class="num ${signCls(t.gain_pct)}">${pct(t.gain_pct, 0)}</td>
        <td class="num">~${t.acceptance}% <div class="muted small">${esc(t.acceptance_label)}</div></td>`}
        <td class="small"><button data-up="${i}" ${i ? "" : "disabled"} aria-label="Move up">↑</button> <button data-down="${i}" ${i < R.trades.length - 1 ? "" : "disabled"} aria-label="Move down">↓</button>
          <button data-edit="${i}">Edit</button> <button data-remove="${i}">Remove</button></td></tr>`).join("")}</tbody></table></div>
    <div class="row"><button id="plan-clear">Clear plan</button><span class="muted small">Edit opens the trade in Evaluate and takes it out of the plan; add it back when you're done.</span></div></div>
  <div class="grid g2">
    <div class="card"><h2>Rebuild timeline</h2><table data-nosort><thead><tr><th>Year</th><th class="num">Lineup strength</th><th class="num">Rank</th><th class="num">Playoff line</th></tr></thead>
      <tbody>${T.years.map((y, i) => `<tr><td><b>${esc(y)}</b></td><td class="num">${arrow(T.strength[0][i], T.strength[1][i], compact)}</td>
        <td class="num">#${T.rank[0][i]} → <b>#${T.rank[1][i]}</b></td><td class="num">${compact(T.playoff_line[i])}</td></tr>`).join("")}</tbody></table>
      <p class="muted small">Other teams' rosters change too where they're in the plan. Top ${T.playoff_teams} make the playoffs.</p></div>
    <div class="card"><h2>This season</h2>${N ? `<table data-nosort><tbody>
      <tr><td>Playoff odds</td><td class="num">${arrow(N.playoff_pct[0], N.playoff_pct[1], v => Math.round(v) + "%")}</td></tr>
      <tr><td>Title odds</td><td class="num">${arrow(N.title_pct[0], N.title_pct[1], v => Math.round(v) + "%")}</td></tr>
      <tr><td>Projected points per week</td><td class="num">${arrow(N.weekly_proj[0], N.weekly_proj[1], p1)}</td></tr>
      <tr><td>Your own 1st (projected slot)</td><td class="num">${arrow(N.avg_slot[0], N.avg_slot[1], p1, (x, y) => x < y)}${N.own_first_owner ? `<div class="muted small">traded to ${esc(N.own_first_owner)}</div>` : ""}</td></tr>
      </tbody></table>` : '<p class="muted">The regular season is over.</p>'}</div>
  </div>
  <div class="grid g2">
    <div class="card"><h2>Roster</h2><table data-nosort><tbody>
      ${["QB", "RB", "WR", "TE"].map(p => `<tr><td>${posBadge(p)} value</td><td class="num">${arrow(C.before.pos[p], C.after.pos[p])}</td></tr>`).join("")}
      <tr><td>Pick capital</td><td class="num">${arrow(C.before.picks, C.after.picks)}</td></tr>
      <tr><td>Players</td><td class="num">${arrow(C.before.players, C.after.players, String, () => true)}</td></tr>
      <tr><td>Age (value-weighted)</td><td class="num">${arrow(C.before.age, C.after.age, p1, (x, y) => x < y)}</td></tr></tbody></table></div>
    <div class="card"><h2>Next offseason</h2><table data-nosort><tbody>
      <tr><td>Active roster (limit ${R.roster.limit})</td><td class="num">${arrow(R.roster.before.active, R.roster.after.active, String, (x, y) => x < y)}</td></tr>
      <tr><td>Cuts needed</td><td class="num">${arrow(R.roster.before.over, R.roster.after.over, String, (x, y) => x < y)}</td></tr></tbody></table>
      ${R.roster.after.cuts.length ? `<p class="small">First in line to cut: ${R.roster.after.cuts.map(esc).join(", ")}. <a href="#/roster">Roster room →</a></p>` : ""}</div>
  </div>`;
}

function wirePlan(plan) {
  const save = p => { savePlan(p); route(); };
  $$("[data-remove]").forEach(b => b.onclick = () => save(plan.filter((_, i) => i !== +b.dataset.remove)));
  $$("[data-up]").forEach(b => b.onclick = () => { const i = +b.dataset.up, p = [...plan]; [p[i - 1], p[i]] = [p[i], p[i - 1]]; save(p); });
  $$("[data-down]").forEach(b => b.onclick = () => { const i = +b.dataset.down, p = [...plan]; [p[i + 1], p[i]] = [p[i], p[i + 1]]; save(p); });
  $$("[data-edit]").forEach(b => b.onclick = () => {
    const i = +b.dataset.edit, t = plan[i];
    savePlan(plan.filter((_, j) => j !== i));
    openInEvaluator({ b: t.b, aGives: t.aGives, bGives: t.bGives });
  });
  const c = $("#plan-clear");
  if (c) c.onclick = () => { if (confirm("Clear every trade from your plan?")) save([]); };
}

// ---------------------------------------------------------------- navigation
// Pages are grouped into sections by what you're doing. URLs are unchanged, so old links work.
const ICONS = {
  home: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
  league: '<circle cx="12" cy="8" r="7"/><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/>',
  trades: '<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
  players: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  draft: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
};
const SECTIONS = [
  { id: "home", label: "Home", pages: [["#/", "Dashboard"], ["#/calendar", "Calendar"]] },
  { id: "league", label: "League", pages: [["#/rankings", "Rankings"], ["#/season", "Playoff odds"], ["#/future", "Timeline"], ["#/team", "Teams"], ["#/recap", "Weekly recap"], ["#/records", "Record book"]] },
  { id: "trades", label: "Trades", pages: [["#/partners", "Find trades"], ["#/trade", "Evaluate"], ["#/plan", "Plan"], ["#/deadline", "Deadline"], ["#/prices", "League prices"], ["#/history", "Trade history"]] },
  { id: "players", label: "Players", pages: [["#/players", "Rostered"], ["#/breakouts", "Breakouts"], ["#/buylow", "Buy low"], ["#/pickups", "Free agents"], ["#/waivers", "Pickup history"]] },
  { id: "draft", label: "Draft", pages: [["#/draftprep", "Upcoming draft"], ["#/hitrates", "Hit rates"], ["#/roster", "Roster room"], ["#/drafts", "Past drafts"]] },
];
const lastPage = {};  // section id -> last page visited there, so a section tab returns you to it

function sectionOf(h) {
  for (const s of SECTIONS)
    for (const [href] of s.pages)
      if (h === href || (href !== "#/" && h.startsWith(href + "/"))) return [s, href];
  if (h.startsWith("#/player/")) return [SECTIONS.find(s => s.id === "players"), null];
  return [null, null];
}

function renderNav(h) {
  const [sec, page] = sectionOf(h);
  if (sec && page) lastPage[sec.id] = h;
  $("#nav").innerHTML = SECTIONS.map(s => `<a href="${lastPage[s.id] || s.pages[0][0]}" class="${s === sec ? "active" : ""}"${s === sec ? ' aria-current="true"' : ""}>
    <svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS[s.id]}</svg><span>${s.label}</span></a>`).join("");
  const sub = $("#subnav");
  sub.hidden = !sec || sec.pages.length < 2;
  sub.innerHTML = sec ? sec.pages.map(([href, label]) => `<a href="${href}" class="${href === page ? "active" : ""}"${href === page ? ' aria-current="page"' : ""}>${label}</a>`).join("") : "";
  const act = $("#subnav a.active");  // on phones the page tabs can scroll sideways; keep the current one in view
  if (act && sub.scrollWidth > sub.clientWidth) sub.scrollLeft = act.offsetLeft - 40;
  $("#gear").classList.toggle("active", h === "#/settings");
}

// ---------------------------------------------------------------- router
const ROUTES = [
  [/^#?\/?$/, viewDashboard], [/^#\/partners$/, viewPartners], [/^#\/trade$/, viewTrade],
  [/^#\/team(?:\/(\d+))?$/, viewTeam], [/^#\/players$/, viewPlayers], [/^#\/history$/, viewHistory],
  [/^#\/drafts$/, viewDrafts], [/^#\/drafts\/(\d+)$/, viewDraftTeam],
  [/^#\/waivers$/, viewWaivers], [/^#\/waivers\/(\d+)$/, viewWaiverTeam],
  [/^#\/rankings$/, viewRankings], [/^#\/records$/, viewRecords], [/^#\/season$/, viewSeason], [/^#\/player\/(\w+)$/, viewPlayer], [/^#\/draftprep$/, viewDraftPrep], [/^#\/pickups$/, viewPickups], [/^#\/breakouts$/, viewBreakouts],
  [/^#\/deadline$/, viewDeadline], [/^#\/buylow$/, viewBuyLow], [/^#\/future$/, viewFuture], [/^#\/prices$/, viewPrices],
  [/^#\/recap(?:\/(\d+))?$/, viewRecap], [/^#\/roster$/, viewRoster], [/^#\/hitrates$/, viewHitRates], [/^#\/calendar$/, viewCalendar], [/^#\/plan$/, viewPlan],
  [/^#\/settings$/, viewSettings],
];
async function route() {
  const h = location.hash || "#/";
  renderNav(h);
  const view = $("#view");
  for (const [re, fn] of ROUTES) {
    const m = h.match(re);
    if (m) {
      if (!view.innerHTML.trim() || fn === viewPartners) view.innerHTML = `<p class="muted">Loading…</p>`;
      try {
        view.innerHTML = await fn(...m.slice(1));
        makeSortable(view);
        const ov = await overview();
        $("#league-name").textContent = `· ${ov.league.name} ${ov.league.season}`;
      } catch (e) { view.innerHTML = `<div class="warnbox">${esc(e.message)}</div>`; }
      return;
    }
  }
  view.innerHTML = `<p>Not found.</p>`;
}
window.addEventListener("hashchange", route);
route();
