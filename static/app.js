const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = (n) => (n || n === 0) ? "₹" + Number(n).toLocaleString("en-IN") : "?";
const usd = (n) => "$" + (n < 0.01 ? Number(n).toFixed(4) : Number(n).toFixed(2));
const tierOf = (label) => /ultra/i.test(label) ? "ultra" : /super/i.test(label) ? "super" : "nano";
const safeUrl = (u) => /^https?:\/\//i.test(u || "") ? u : null;

const VERDICT_TEXT = {
  good_deal: "Good deal", fair: "Fair", overpriced: "Overpriced",
  suspicious: "Suspicious", likely_bait: "Likely bait",
};
const ACTION_TEXT = {
  buy: "Go ahead and buy", wait: "Wait for now", avoid: "Avoid this listing",
  buy_elsewhere: "Buy it elsewhere",
};

/* ---------- tabs ---------- */
function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + name));
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  if (name === "watch") loadWatch();
  if (name === "hood") loadHood();
  history.replaceState(null, "", "#" + name);
}
document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", (e) => {
  e.preventDefault(); showTab(b.dataset.tab);
}));

/* ---------- check ---------- */
async function loadExamples() {
  const list = await fetch("/api/examples").then((r) => r.json()).catch(() => []);
  $("#examples").innerHTML = list.map((x, i) => `<button class="chip" data-i="${i}">${esc(x.label)}</button>`).join("");
  $("#examples").onclick = (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    $("#url").value = list[b.dataset.i].url;
    runCheck({ url: list[b.dataset.i].url });
  };
}

$("#form").addEventListener("submit", (e) => { e.preventDefault(); runCheck({ url: $("#url").value }); });
$("#form-text").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("#text").value.trim();
  if (text) runCheck({ text, url: $("#url").value || null });
});

let started = 0, timer = null;

async function runCheck(payload) {
  $("#go").disabled = true;
  $("#steps").innerHTML = "";
  $("#run").hidden = false;
  $("#result").hidden = true;
  $("#error").hidden = true;
  started = Date.now();
  clearInterval(timer);
  timer = setInterval(() => { $("#run-meta").textContent = ((Date.now() - started) / 1000).toFixed(1) + "s"; }, 100);
  $("#run").scrollIntoView({ behavior: "smooth", block: "start" });

  try {
    const res = await fetch("/api/check", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || "Something went wrong.");
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (line) handle(JSON.parse(line.slice(6)));
      }
    }
  } catch (err) {
    showError(err.message);
  } finally {
    clearInterval(timer);
    $("#go").disabled = false;
  }
}

function handle(ev) {
  if (ev.type === "step") return upsertStep(ev);
  if (ev.type === "cached") {
    $("#steps").innerHTML = `<li class="step done"><span class="dot"></span><div><div class="label">Recent result</div>
      <div class="sum">Someone checked this listing in the last hour, so Asli reused that run for free.</div></div><div></div></li>`;
    return;
  }
  if (ev.type === "error") return showError(ev.message);
  if (ev.type === "result") return renderResult(ev);
}

function upsertStep(ev) {
  let li = document.getElementById("step-" + ev.id);
  if (!li) {
    li = document.createElement("li");
    li.id = "step-" + ev.id;
    $("#steps").appendChild(li);
  }
  li.className = "step " + ev.status;
  const calls = ev.calls || [];
  const badges = calls.length
    ? groupCalls(calls).map((g) => `<span class="badge ${g.tier}" title="${esc(g.model)}">${esc(g.short)} ×${g.n} · ${g.tokens.toLocaleString()} tok · ${usd(g.cost)}</span>`).join("")
    : (ev.status === "done" && ev.id !== "history" ? `<span class="badge tool">${ev.id === "read" && ev.method ? esc(ev.method) : "Tavily"}</span>` : "");
  li.innerHTML = `<span class="dot"></span>
    <div><div class="label">${esc(ev.label)}</div>${ev.summary ? `<div class="sum">${esc(ev.summary)}</div>` : ""}</div>
    <div class="badges">${badges}</div>`;
}

function groupCalls(calls) {
  const by = {};
  for (const c of calls) {
    const g = by[c.model] ||= { model: c.model, tier: tierOf(c.model), short: c.model.replace("Nemotron 3 ", ""), n: 0, tokens: 0, cost: 0 };
    g.n++; g.tokens += c.prompt_tokens + c.completion_tokens; g.cost += c.cost_usd;
  }
  return Object.values(by);
}

function showError(msg) {
  const el = $("#error");
  el.textContent = msg;
  el.hidden = false;
  document.querySelectorAll(".step.running").forEach((s) => s.className = "step error");
}

function renderResult(r) {
  const v = r.verdict || {};
  const l = r.listing || {};
  const m = r.market || {};
  const rec = v.recommendation || {};
  const offer = rec.offer;
  const score = Math.max(0, Math.min(100, Number(v.trust_score) || 0));
  const severe = v.verdict === "overpriced" && score < 30 ? " severe" : "";

  const reasons = (v.reasons || []).map((x) => `<li><span class="sev ${esc(x.severity)}"></span><div>
      <b>${esc(x.label)}</b><span>${esc(x.detail)}</span>
      ${safeUrl(x.source_url) ? `<div><a href="${esc(x.source_url)}" target="_blank" rel="noopener">${esc(hostOf(x.source_url))}</a></div>` : ""}
    </div></li>`).join("");

  const saving = offer && l.price_inr && offer.price_inr < l.price_inr ? l.price_inr - offer.price_inr : 0;
  const recHtml = `<div class="card rec">
      <small class="muted">What to do</small>
      <div class="action">${esc(ACTION_TEXT[rec.action] || "Think it over")}</div>
      <div class="muted">${esc(rec.why)}</div>
      ${offer ? `<div class="offer">
        <small class="muted">${esc(offer.store)}${offer.in_stock ? " · in stock" : ""}</small>
        <div>${esc(offer.product_name)}</div>
        <div class="price">${inr(offer.price_inr)}</div>
        ${saving ? `<div class="save">Saves ${inr(saving)} vs this listing</div>` : ""}
        ${safeUrl(offer.product_url) ? `<a class="btn" href="${esc(offer.product_url)}" target="_blank" rel="noopener" style="text-align:center;text-decoration:none">Open at ${esc(offer.store)}</a>` : ""}
      </div>` : ""}
    </div>`;

  const rows = [`<tr class="this"><td>${esc(l.store)} <span class="muted">(this listing)</span></td><td>${esc(l.title)}</td>
      <td class="num">${inr(l.price_inr)}</td><td>${stockCell(l.in_stock, l.availability_text)}</td></tr>`]
    .concat((m.offers || []).map((o) => `<tr><td>${esc(o.store)}</td>
      <td>${safeUrl(o.product_url) ? `<a href="${esc(o.product_url)}" target="_blank" rel="noopener">${esc(o.product_name)}</a>` : esc(o.product_name)}</td>
      <td class="num">${inr(o.price_inr)}</td><td>${stockCell(o.in_stock)}</td></tr>`)).join("");

  const sig = (r.signals || []).map((s) => `<span class="signal">${esc(s.text)}</span>`).join("");
  const reports = ((r.community || {}).reports || []).slice(0, 5).map((x) => `<li><span class="sev ${x.tone === "negative" ? "bad" : x.tone === "positive" ? "good" : "warn"}"></span>
      <div><span>${esc(x.claim)}</span>${safeUrl(x.url) ? `<div><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(hostOf(x.url))}</a></div>` : ""}</div></li>`).join("");

  const u = r.usage || {};
  const models = Object.entries(u.by_model || {}).map(([name, x]) =>
    `<span class="badge ${tierOf(name)}">${esc(name.replace("Nemotron 3 ", ""))} ×${x.calls} · ${usd(x.cost_usd)}</span>`).join(" ");
  const savedPct = u.all_ultra_cost_usd ? Math.round(100 * (1 - u.cost_usd / u.all_ultra_cost_usd)) : 0;

  const hist = r.history || {};
  const histHtml = (hist.points || []).length >= 2 ? `<div class="card panel"><h3>Price and stock over time</h3>${sparkline(hist.points, 720, 60)}
      <div class="muted" style="font-size:13px">In stock ${hist.times_in_stock} of ${hist.snapshots} checks over ${hist.days_tracked} days. Green dots were buyable.</div></div>` : "";

  $("#result").innerHTML = `
    <div class="card verdict ${esc(v.verdict)}${severe}">
      <div class="ring" style="--p:${score}"><div><div><b>${score}</b><small>trust</small></div></div></div>
      <div>
        <span class="pill">${esc(VERDICT_TEXT[v.verdict] || v.verdict)}</span>
        <h2>${esc(v.headline)}</h2>
        <p>${esc(v.summary)}</p>
        <div class="item-line">${esc(l.title)} · ${inr(l.price_inr)}${l.mrp_inr ? ` (MRP ${inr(l.mrp_inr)})` : ""} · ${esc(l.store)}${l.seller ? " · " + esc(l.seller) : ""}</div>
      </div>
    </div>
    ${sig ? `<div class="signals">${sig}</div>` : ""}
    <div class="grid2">
      <div class="card panel"><h3>Why</h3><ul class="reasons">${reasons}</ul></div>
      ${recHtml}
    </div>
    <div class="card panel"><h3>Same card at trusted Indian stores</h3>
      <div class="table-wrap"><table><thead><tr><th>Store</th><th>Product</th><th class="num">Price</th><th>Stock</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${m.median_in_stock_inr ? `<p class="muted" style="font-size:13px;margin:10px 0 0">Median in-stock price: ${inr(m.median_in_stock_inr)} across ${esc((m.stores_checked || []).join(", "))}.</p>` : ""}
    </div>
    ${histHtml}
    ${reports ? `<div class="card panel"><h3>What buyers are saying</h3><ul class="reasons">${reports}</ul></div>` : ""}
    <div class="card usage">
      <span>${r.cached ? "Reused a recent run · " : ""}<b>${u.calls}</b> model calls</span>
      <span><b>${(u.tokens || 0).toLocaleString()}</b> tokens</span>
      <span><b>${usd(u.cost_usd || 0)}</b> total</span>
      ${savedPct >= 20 ? `<span><b>${savedPct}%</b> cheaper than running every step on Ultra</span>` : ""}
      <span>${models}</span>
    </div>`;
  $("#result").hidden = false;
}

function stockCell(v, text) {
  if (v === true) return `<span class="stock yes">In stock</span>`;
  if (v === false) return `<span class="stock no">${esc(text || "Not buyable")}</span>`;
  return `<span class="stock unk">Unknown</span>`;
}
function hostOf(u) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } }

function sparkline(points, w = 600, h = 34) {
  const ps = points.filter((p) => p.price_inr);
  if (ps.length < 2) return "";
  const xs = ps.map((p) => p.ts), ys = ps.map((p) => p.price_inr);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = (t) => 4 + (w - 8) * (x1 === x0 ? 0.5 : (t - x0) / (x1 - x0));
  const Y = (y) => h - 6 - (h - 12) * (y1 === y0 ? 0.5 : (y - y0) / (y1 - y0));
  const path = ps.map((p, i) => (i ? "L" : "M") + X(p.ts).toFixed(1) + " " + Y(p.price_inr).toFixed(1)).join(" ");
  const dots = ps.map((p) => `<circle cx="${X(p.ts).toFixed(1)}" cy="${Y(p.price_inr).toFixed(1)}" r="3" fill="${p.in_stock ? "var(--good)" : "var(--bad)"}"/>`).join("");
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Price history">
    <path d="${path}" fill="none" stroke="var(--muted)" stroke-width="1.5" vector-effect="non-scaling-stroke"/>${dots}</svg>`;
}

/* ---------- watchlist ---------- */
async function loadWatch() {
  const rows = await fetch("/api/watchlist").then((r) => r.json()).catch(() => []);
  if (!rows.length) { $("#watch").innerHTML = `<div class="card empty">Nothing tracked yet. Check a deal and it shows up here.</div>`; return; }
  $("#watch").innerHTML = rows.map((r) => {
    const ratio = r.checks ? `In stock ${r.in_stock_checks || 0} of ${r.checks} checks` : "Not checked yet";
    return `<div class="card wrow">
      <div><div class="t">${safeUrl(r.url) ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.label || r.url)}</a>` : esc(r.label)}</div>
        <div class="s">${esc(r.store)} · ${esc(r.gpu || "")} · ${ratio}${r.last_ts ? " · last seen " + ago(r.last_ts) : ""}</div></div>
      <div style="text-align:right"><b>${inr(r.price_inr)}</b><div>${stockCell(r.in_stock === null || r.in_stock === undefined ? null : !!r.in_stock, r.availability)}</div></div>
      ${sparkline(r.points || [])}
    </div>`;
  }).join("");
}
function ago(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 3600) return Math.max(1, Math.round(s / 60)) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " h ago";
  return Math.round(s / 86400) + " d ago";
}

/* ---------- under the hood ---------- */
async function loadHood() {
  const s = await fetch("/api/stats").then((r) => r.json()).catch(() => null);
  if (!s) { $("#hood").innerHTML = `<div class="card empty">Stats unavailable.</div>`; return; }
  const pct = (a, b) => Math.min(100, b ? 100 * a / b : 0);
  const routing = Object.entries(s.routing).map(([task, tier]) => `<tr><td>${esc(TASKS[task] || task)}</td>
      <td><span class="badge ${tier}">${esc(s.models[tier].label)}</span></td>
      <td class="num">$${s.models[tier].price[0]} / $${s.models[tier].price[1]}</td></tr>`).join("");
  const usage = (s.by_model || []).map((r) => `<tr><td>${esc(TASKS[r.task] || r.task)}</td>
      <td><span class="badge ${r.model}">${esc(s.models[r.model]?.label || r.model)}</span></td>
      <td class="num">${r.calls}</td><td class="num">${((r.prompt_tokens || 0) + (r.completion_tokens || 0)).toLocaleString()}</td>
      <td class="num">${usd(r.cost_usd || 0)}</td><td class="num">${(r.latency_s || 0).toFixed(1)}s</td></tr>`).join("");

  $("#hood").innerHTML = `
    <div class="kpis">
      <div class="card kpi"><small>Deal checks</small><b>${s.checks}</b></div>
      <div class="card kpi"><small>Watcher snapshots</small><b>${s.snapshots}</b></div>
      <div class="card kpi"><small>Nemotron spend</small><b>${usd(s.total_usd)}</b>
        <div class="bar"><i style="width:${pct(s.total_usd, s.caps.total_usd)}%"></i></div>
        <small>cap $${s.caps.total_usd}, then Asli pauses itself</small></div>
      <div class="card kpi"><small>Tavily credits this month</small><b>${Math.round(s.tavily_credits_month)}</b>
        <div class="bar"><i style="width:${pct(s.tavily_credits_month, s.caps.tavily_credits_month)}%"></i></div>
        <small>budget ${s.caps.tavily_credits_month}</small></div>
    </div>
    <div class="hood-grid">
      ${evalHtml(s.eval, s.models)}
      <div class="card panel"><h3>Routing in production</h3>
        <div class="table-wrap"><table><thead><tr><th>Step</th><th>Model</th><th class="num">$ per 1M in / out</th></tr></thead><tbody>${routing}</tbody></table></div></div>
      <div class="card panel"><h3>Live usage by step</h3>
        <div class="table-wrap"><table><thead><tr><th>Step</th><th>Model</th><th class="num">Calls</th><th class="num">Tokens</th><th class="num">Cost</th><th class="num">Avg time</th></tr></thead><tbody>${usage || `<tr><td colspan="6" class="muted">No calls yet</td></tr>`}</tbody></table></div></div>
    </div>`;
}

const TASKS = {
  read_listing: "Read the listing", market_prices: "Price trusted stores",
  community: "Summarise forum reports", verdict: "Final verdict",
};

function evalHtml(ev, models) {
  if (!ev) return `<div class="card panel"><h3>Model evaluation</h3><p class="muted">Not run yet.</p></div>`;
  const rows = (ev.results || []).map((r) => `<tr class="${r.chosen ? "this" : ""}"><td>${esc(TASKS[r.task] || r.task)}</td>
      <td><span class="badge ${r.tier}">${esc(models[r.tier]?.label || r.tier)}${r.think ? " + reasoning" : ""}</span></td>
      <td class="num">${(100 * r.accuracy).toFixed(0)}%</td><td class="num">${usd(r.cost_per_call)}</td>
      <td class="num">${r.latency_s.toFixed(1)}s</td><td>${r.chosen ? "<b>chosen</b>" : ""}</td></tr>`).join("");
  return `<div class="card panel"><h3>Model evaluation</h3>
    <p class="muted" style="margin-top:0;font-size:14px">${esc(ev.description || "")}</p>
    <div class="table-wrap"><table><thead><tr><th>Step</th><th>Model</th><th class="num">Accuracy</th><th class="num">Cost per call</th><th class="num">Avg time</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
    ${(ev.notes || []).length ? `<ul class="notes">${ev.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    <p class="muted" style="font-size:13px;margin:10px 0 0">Rule: the cheapest setup within ${ev.tolerance_pct || 2} points of the best accuracy wins. Run ${esc(ev.run_at || "")}, ${ev.cases || "?"} cases.</p></div>`;
}

/* ---------- boot ---------- */
loadExamples();
const startTab = (location.hash || "").slice(1);
showTab(["check", "watch", "hood"].includes(startTab) ? startTab : "check");
window.addEventListener("hashchange", () => {
  const t = location.hash.slice(1);
  if (["check", "watch", "hood"].includes(t)) showTab(t);
});
