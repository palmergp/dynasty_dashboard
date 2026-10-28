// Dynasty Trade Helper UI — plain JS, hash routing, no build step.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = n => (n == null || isNaN(n) ? "–" : Math.round(n).toLocaleString());
const pct = (n, d = 1) => (n == null ? "–" : `${n > 0 ? "+" : ""}${Number(n).toFixed(d)}%`);
const signCls = n => (n > 0.5 ? "delta-pos" : n < -0.5 ? "delta-neg" : "");
const SRC = { fantasycalc: "FC", ktc: "KTC", dynastyprocess: "DP" };
const WINDOW_LABEL = { contend: "Contender", middle: "Middle", rebuild: "Rebuilder" };

const state = { ov: null, trade: { a: null, b: null, aGives: [], bGives: [] }, teamCache: {} };

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
  state.pickupsData = null; state.breakoutsData = null; state.reviewData = null; state.recordsData = null;
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
const accBadge = s => `<span class="badge acc-${s.acceptance_label}" ${tipAttr(`Model estimate of how likely they are to accept, 0–100: their team-context gain (with their trade tendencies) blended 50/50 with market value. 65+ Likely, 40–64 Possible, under 40 Unlikely.`)}>${s.acceptance_label} (${s.acceptance})</span>`;

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
  if (me) setTimeout(() => dashOpportunity(me.roster_id), 0);
  return `
    ${errs.length ? `<div class="warnbox">Some value sources failed and were skipped: ${errs.map(([k, v]) => `${k} (${esc(v)})`).join("; ")}</div>` : ""}
    ${me ? `<div class="card">
      <div class="row spread">
        <div><h1>${esc(me.manager)} ${windowBadge(me.window, me.window_source)}</h1>
          <div class="muted">${ov.league.season} · ${me.wins}-${me.losses}${me.ties ? "-" + me.ties : ""} · ${fmt(me.fpts)} pts for</div></div>
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
          ${sells.length ? sells.map(a => assetLine(a, { notes: true })).join("") : `<p class="muted">None flagged.</p>`}
        </div>
        <div>
          <h3>${hint("Positional outlook", HELP.outlook)}</h3>
          ${posTable(meT)}
          <p class="muted small">Now = starters' win-now value vs. league. Future = dynasty value of your top players at each position.</p>
          <p><a href="#/partners">See best trade partners →</a></p>
        </div>
      </div>
    </div>` : `<div class="warnbox">Couldn't find "${esc(ov.config.username)}" in this league. Check Settings.</div>`}
    ${me ? `<div class="card" id="dash-opp"><h2>Waiver wire &amp; breakout targets</h2><p class="muted">Loading…</p></div>` : ""}
    <div class="card">
      <h2>League landscape</h2>
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

async function dashOpportunity(me) {
  const host = $("#dash-opp");
  let W, B;
  try { [W, B] = await Promise.all([pickupsData(), breakoutsData()]); }
  catch (e) { if (host) host.innerHTML = `<h2>Waiver wire &amp; breakout targets</h2><div class="warnbox">${esc(e.message)}</div>`; return; }
  if (!$("#dash-opp")) return;
  const targets = B.players.filter(r => r.owner_rid != null && r.owner_rid !== me && r.value < 4000).slice(0, 4);
  const line = (a, right) => `<div class="asset">${posBadge(a.pos)}<div class="name">${esc(a.name)} <span class="muted small">${assetMeta(a)}</span>
    <div>${sigChips(a)}</div></div><span class="val small">${right}</span></div>`;
  $("#dash-opp").innerHTML = `<h2>Waiver wire &amp; breakout targets</h2><div class="grid g2">
    <div><h3>${hint("Best adds for you", HELP.pickupScore)}</h3>
      ${W.suggestions.slice(0, 4).map(s => line(s.asset, `${hint("score", HELP.pickupScore)} ${fmt(s.score)}<br><span class="muted">bid ~$${s.bid.mid}</span>`)).join("") || '<p class="muted">Nobody beats your weakest player right now.</p>'}
      <p><a href="#/pickups">Waiver wire →</a></p></div>
    <div><h3>${hint("Buy before the breakout", "Players on other rosters (worth under 4,000) with the highest breakout scores.")}</h3>
      ${targets.map(r => line(r, `${hint("breakout", HELP.breakout)} ${r.breakout}<br><span class="muted">${esc(r.owner)}</span>`)).join("") || '<p class="muted">None flagged.</p>'}
      <p><a href="#/breakouts">Breakout watch →</a></p></div>
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
  return `<div class="card"><h1>Best trade partners</h1>
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
  let r;
  try { r = await api("/api/evaluate", { method: "POST", body: { a_rid: tr.a, a_gives: tr.aGives, b_rid: tr.b, b_gives: tr.bGives } }); }
  catch (e) { out.innerHTML = `<div class="warnbox">${esc(e.message)}</div>`; return; }
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
    <div class="grid g2">${side(A, r.b_gives)}${side(B, r.a_gives)}</div>`;
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
        <td><b>${esc(a.name)}</b> ${a.starter ? '<span class="badge tag">starter</span>' : ""}${t.sell_candidates.includes(a.id) ? ' <span class="badge w-rebuild">sell?</span>' : ""}${a.breakout >= 35 ? ` <span class="badge tag" ${tipAttr(HELP.breakout)}>breakout ${a.breakout}</span>` : ""}
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
    <div class="scroll"><table id="p-table"><thead><tr><th></th><th>Player</th><th>Owner</th><th class="num">Value</th><th class="num">Win-now</th><th class="num">FC</th><th class="num">KTC</th><th class="num">DP</th><th class="num">30d</th><th class="num">${hint("Breakout", HELP.breakout)}</th><th>Your override</th><th>Your note</th></tr></thead><tbody></tbody></table></div>
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
      <td><b>${esc(a.name)}</b> <span class="muted small">${assetMeta(a)}</span>${a.notes.length ? `<ul class="notes">${a.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}</td>
      <td><a href="#/team/${a.owner_rid}">${esc(a.owner)}</a></td>
      <td class="num"><b>${fmt(a.value)}</b>${a.override != null ? `<div class="muted small">mkt ${fmt(a.market)}</div>` : ""}</td>
      <td class="num">${fmt(a.redraft)}</td>
      <td class="num">${fmt(a.sources.fantasycalc)}</td><td class="num">${fmt(a.sources.ktc)}</td><td class="num">${fmt(a.sources.dynastyprocess)}</td>
      <td class="num ${signCls(a.trend)}">${a.trend ? (a.trend > 0 ? "+" : "") + fmt(a.trend) : ""}</td>
      <td class="num" data-sort="${a.breakout ?? 0}">${a.breakout ? `<span class="${a.breakout >= 40 ? "bo-hi" : ""}">${a.breakout}</span>` : '<span class="muted">0</span>'}</td>
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
  return `<div class="card"><h1>Trade review</h1>
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
  </div>`;
}
function wireSettings() {
  $$(".s-w").forEach(r => r.oninput = () => (r.nextElementSibling.textContent = r.value));
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
  return `<div class="card"><h1>Draft performance</h1>
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
      <div><h1>${esc(team.manager)} · drafts</h1><div class="muted"><a href="#/drafts">← League drafts</a> · <a href="#/waivers/${rid}">Pickup report</a> · <a href="#/team/${rid}">Team page</a></div></div>
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
  return `<div class="card"><h1>Waiver &amp; free-agent pickups</h1>
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
      <div><h1>${esc(team.manager)} · pickups</h1><div class="muted"><a href="#/waivers">← League pickups</a> · <a href="#/drafts/${rid}">Draft report</a> · <a href="#/team/${rid}">Team page</a></div></div>
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
  efficient: "Scores more fantasy points per opportunity (carries + 1.5× targets; dropbacks for QBs) than the median regular at his position, so a bigger role should pay off. The strongest single signal in the 2025 backtest.",
  vacancy_now: "A player ahead of him on the depth chart is out right now. Full credit when that player is on IR or PUP, half for a likely short absence (Out, Doubtful, suspended). No credit if he's on IR himself, since the starter will probably be back first.",
  injured: "He's on IR or PUP himself. Any breakout case is about next season, not now. Injuries ahead of him don't count toward his score.",
  vacancy_next: "A player ahead of him may not be back next season: contract ending, or the team can cut him cheaply. Weak on its own in the backtest, because teams often draft or sign a replacement.",
  fa_move: "His contract ends this season while he's stuck behind a starter, so he may sign somewhere with a bigger role. This is the Isaiah Likely path, and the second-strongest signal in the backtest.",
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
  backtest: "The model run as it would have looked at the end of last season: last season's usage, contracts in force then and values then, compared with values now. Players already worth 4,000+ are excluded. A hit gained 500+ value.",
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
const playerCell = a => `<td><b>${esc(a.name)}</b>${metaLine(a)}</td>`;
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
  <div class="card"><h1>Waiver wire</h1>
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
  const bt = B.backtest || {};
  setTimeout(() => drawBreakouts(B, rows), 0);
  const btRow = r => `<tr><td class="num">${r.rank}</td><td>${posBadge(r.pos)}</td><td><b>${esc(r.name)}</b><div class="muted small">${esc(r.team)}${r.now_team && r.now_team !== r.team ? ` → ${esc(r.now_team)}` : ""}</div></td>
    <td class="num">${r.breakout}</td><td class="num">${fmt(r.then)}</td><td class="num">${fmt(r.now)}</td><td class="num ${signCls(r.change)}">${r.change > 0 ? "+" : ""}${fmt(r.change)}</td>
    <td>${(r.notes || []).map(n => `<span class="badge tag" ${tipAttr(n.text + ".")}>${SIGNAL_LABEL[n.key]}</span>`).join(" ")}</td></tr>`;
  const btHead = `<thead><tr><th class="num">Rank</th><th></th><th>Player</th><th class="num">Score then</th><th class="num">Value then</th><th class="num">Now</th><th class="num">Change</th><th>Signals then</th></tr></thead>`;
  const nextTxt = n => `<b>${esc(n.name)}</b> <span class="small muted">${esc(n.depth || "")}${n.age ? ` · ${n.age}y` : ""} · ${fmt(n.value)} · breakout ${n.breakout} · ${n.owner_rid == null ? "free agent" : n.owner_rid === me ? "<b>yours</b>" : esc(n.owner)}</span>`;
  return `${B.error ? `<div class="warnbox">Usage/contract data failed to load (${esc(B.error)}).</div>` : ""}
  <div class="card"><h1>Breakout watch</h1>
    <p class="muted">Players whose role is likely to grow before the market prices it in: ${Object.keys(SIGNAL_LABEL).filter(k => k !== "injured").map(k => `<span class="badge tag" ${tipAttr(SIGNAL_HELP[k])}>${SIGNAL_LABEL[k]}</span>`).join(" ")}.
      Free agents are pickup targets; players on other teams are buy-low ${hint("trade targets", "In trade suggestions, rebuilding teams value breakout upside up to 15% more, and suggestions flag players to buy before a breakout.")}. Based on ${usageNote(B)} and OverTheCap contracts.</p>
    ${bt.n ? `<div class="tiles">
      <div class="tile"><div class="k">${hint(`Backtest: top ${bt.top} hit rate`, HELP.backtest)}</div><div class="v">${Math.round(bt.top_hit_rate * 100)}%</div><div class="d muted">gained ${fmt(bt.hit)}+ value · vs ${(bt.base_hit_rate * 100).toFixed(1)}% of all ${bt.n} players</div></div>
      <div class="tile"><div class="k">${hint("Backtest: value vs. similar players", HELP.backtest)}</div><div class="v">${bt.top_excess > 0 ? "+" : ""}${fmt(bt.top_excess)}</div><div class="d muted">average, top ${bt.top}, ${bt.then_date} → ${bt.now_date}</div></div>
      ${bt.spotlight ? `<div class="tile"><div class="k">Isaiah Likely, end of ${bt.as_of}</div><div class="v">#${bt.spotlight.rank}</div>
        <div class="d muted">of ${bt.n} · score ${bt.spotlight.breakout}${bt.spotlight.notes.length ? ` · ${bt.spotlight.notes.map(n => SIGNAL_LABEL[n.key]).join(", ").toLowerCase()}` : ""} · ${fmt(bt.spotlight.then)} → ${fmt(bt.spotlight.now)}</div></div>` : ""}
    </div>` : ""}</div>
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
  ${bt.n ? `<div class="card"><h2>${hint("Model check: how last season's flags did", HELP.backtest)}</h2>
    <p class="muted small">The model as it would have looked at the end of ${bt.as_of} (${bt.then_date}), compared with values on ${bt.now_date}. One season is a small sample, so treat this as a sanity check, not proof.
      Injuries aren't known historically, so the "opening now" signal is off here.</p>
    <div class="grid g2">
      <div><h3>Top ${bt.top} breakout scores then</h3><div class="scroll"><table>${btHead}<tbody>${bt.picks.map(btRow).join("")}</tbody></table></div></div>
      <div><h3>Biggest risers since, and where the model ranked them</h3><div class="scroll"><table>${btHead}<tbody>${bt.risers.map(btRow).join("")}</tbody></table></div></div>
    </div></div>` : ""}`;
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
    <div class="small muted rec-gaps">At the time: ${x.then_gap.leader ? `${esc(x.then_gap.leader)} +${fmt(x.then_gap.gap)}` : "even"} · Today: ${x.now_gap.leader ? `${esc(x.now_gap.leader)} +${fmt(x.now_gap.gap)}` : "even"} · <a href="#/history">Trade review</a></div></div>`;
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

// ---------------------------------------------------------------- router
const ROUTES = [
  [/^#?\/?$/, viewDashboard], [/^#\/partners$/, viewPartners], [/^#\/trade$/, viewTrade],
  [/^#\/team(?:\/(\d+))?$/, viewTeam], [/^#\/players$/, viewPlayers], [/^#\/history$/, viewHistory],
  [/^#\/drafts$/, viewDrafts], [/^#\/drafts\/(\d+)$/, viewDraftTeam],
  [/^#\/waivers$/, viewWaivers], [/^#\/waivers\/(\d+)$/, viewWaiverTeam],
  [/^#\/rankings$/, viewRankings], [/^#\/records$/, viewRecords], [/^#\/pickups$/, viewPickups], [/^#\/breakouts$/, viewBreakouts],
  [/^#\/settings$/, viewSettings],
];
async function route() {
  const h = location.hash || "#/";
  $$("#nav a").forEach(a => { const href = a.getAttribute("href"); a.classList.toggle("active", h === href || h.startsWith(href + "/")); });
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
