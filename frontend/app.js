const API = "";
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = { offset: 0, limit: 100, total: 0, sort: "Runs", searchTimer: null };
const number = (value, digits = 0) => Number(value || 0).toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
const safe = (value) => String(value ?? "—").replace(/[&<>"']/g, char => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[char]));
const shortName = (value) => safe(value).replace(/\s+/g, " ").trim();
function toast(message) { const el = $("#toast"); el.textContent = message; el.classList.add("show"); setTimeout(() => el.classList.remove("show"), 2600); }
async function api(path) {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) { let message = `API error (${response.status})`; try { message = (await response.json()).detail || message; } catch {} throw new Error(message); }
  return response.json();
}
function showError(container, message, colspan = 1) {
  const el = $(container); if (el) el.innerHTML = `<div class="error">${safe(message)}</div>`;
}
function renderLeaders(items, metric, label) {
  if (!items?.length) return `<div class="loading">No records found.</div>`;
  return items.slice(0, 5).map((p, i) => `<div class="leader"><div class="leader-rank">${String(i+1).padStart(2,"0")}</div><div><div class="leader-name">${shortName(p["Player Name"])}</div><div class="leader-meta">${safe(p.Team)} · ${safe(p.Player_Type)}</div></div><div class="leader-value">${number(p[metric], metric === "Average" || metric === "Strike_Rate" ? 2 : 0)}<div class="leader-meta">${label}</div></div></div>`).join("");
}
async function loadOverview() {
  const data = await api("/api/summary");
  $("#total-players").textContent = number(data.total_players);
  $("#total-teams").textContent = number(data.teams);
  $("#capped-players").textContent = number(data.capped_players);
  $("#type-count").textContent = number(Object.keys(data.player_types || {}).length);
  const roles = Object.entries(data.player_types || {}).sort((a,b) => b[1]-a[1]);
  const max = Math.max(1, ...roles.map(x => x[1]));
  const roleColors = ["#8064f4","#3985f7","#12a878","#f19a38"];
  $("#role-chart").innerHTML = roles.map(([role,count],i) => `<div class="role-row"><span class="role-name">${safe(role)}</span><div class="role-track"><div class="role-fill" style="width:${count/max*100}%;background:${roleColors[i%roleColors.length]}"></div></div><span class="role-count">${number(count)}</span></div>`).join("");
  $("#snapshot").innerHTML = renderLeaders(data.top_wickets, "Wickets", "wickets");
  $("#top-runs-body").innerHTML = (data.top_runs || []).map(p => `<tr><td class="player-name">${shortName(p["Player Name"])}</td><td><span class="team-pill">${safe(p.Team)}</span></td><td><span class="role-pill">${safe(p.Player_Type)}</span></td><td><b>${number(p.Runs)}</b></td><td>${number(p.Average,2)}</td><td>${number(p.Strike_Rate,2)}</td></tr>`).join("");
}
function playerParams() {
  const params = new URLSearchParams();
  const search = $("#search-input").value.trim(), type = $("#type-filter").value, team = $("#team-filter").value;
  if (search) params.set("search", search);
  if (type !== "all") params.set("type", type);
  if (team !== "all") params.set("team", team);
  if ($("#capped-filter").checked) params.set("capped_only", "true");
  params.set("sort_by", $("#sort-filter").value);
  params.set("order", $("#sort-filter").value === "Economy" ? "asc" : "desc");
  params.set("limit", String(state.limit)); params.set("offset", String(state.offset));
  return params.toString();
}
async function loadPlayers(reset = true) {
  if (reset) state.offset = 0;
  const body = $("#players-body");
  body.innerHTML = '<tr><td colspan="9" class="loading">Loading players…</td></tr>';
  try {
    const data = await api(`/api/players?${playerParams()}`);
    state.total = data.total;
    const rows = (data.players || []).map(p => `<tr><td class="player-name">${shortName(p["Player Name"])}</td><td><span class="team-pill">${safe(p.Team)}</span></td><td>${safe(p.Nationality)}</td><td><span class="role-pill">${safe(p.Player_Type)}</span></td><td>${number(p.Matches_Played)}</td><td><b>${number(p.Runs)}</b></td><td>${number(p.Average,2)}</td><td>${number(p.Strike_Rate,2)}</td><td>${number(p.Wickets)}</td></tr>`).join("");
    body.innerHTML = rows || '<tr><td colspan="9" class="loading">No players match these filters.</td></tr>';
    $("#player-count").textContent = `${number(data.total)} PLAYERS`;
    $("#results-label").textContent = `Showing ${data.total ? state.offset+1 : 0}–${Math.min(state.offset+data.players.length,data.total)} of ${number(data.total)} players`;
    $("#show-more").style.display = state.offset + data.players.length >= data.total ? "none" : "inline-block";
  } catch (error) { body.innerHTML = `<tr><td colspan="9" class="error">${safe(error.message)}</td></tr>`; }
}
async function loadTeams() {
  const teams = await api("/api/teams");
  const names = [...new Set(teams.map(t => t.team))].sort();
  $("#team-filter").innerHTML = '<option value="all">All teams</option>' + names.map(name => `<option value="${safe(name)}">${safe(name)}</option>`).join("");
  $("#team-cards").innerHTML = teams.map(t => `<article class="team-card"><h3>${safe(t.team)}</h3><strong>${number(t.players)}</strong><small>players in dataset</small><div class="team-stats"><span>Runs <b>${number(t.runs)}</b></span><span>Wickets <b>${number(t.wickets)}</b></span></div></article>`).join("");
  $("#teams-body").innerHTML = teams.map(t => `<tr><td class="player-name">${safe(t.team)}</td><td>${number(t.players)}</td><td>${number(t.capped_players)}</td><td><b>${number(t.runs)}</b></td><td>${number(t.wickets)}</td><td>${number(t.average_player_runs,2)}</td></tr>`).join("");
}
async function loadXI() {
  $("#xi-list").innerHTML = '<div class="loading">Building suggested XI…</div>';
  try {
    const data = await api("/api/best-xi");
    $("#xi-note").textContent = `${data.selected} of ${data.target} slots filled. ${data.note}`;
    $("#xi-list").innerHTML = (data.players || []).map((p,i) => {
      const stat = p.XI_Role === "Bowler" ? `${number(p.Wickets)} wkts` : `${number(p.Runs)} runs`;
      const sub = p.XI_Role === "Bowler" ? `Economy ${number(p.Economy,2)}` : `Avg ${number(p.Average,2)} · SR ${number(p.Strike_Rate,2)}`;
      return `<article class="xi-card"><div class="xi-number">${String(i+1).padStart(2,"0")}</div><div><div class="xi-name">${shortName(p["Player Name"])}</div><div class="xi-sub">${safe(p.Team)} · ${safe(p.XI_Role)}</div></div><div class="xi-stat">${stat}<small>${sub}</small></div></article>`;
    }).join("") || '<div class="loading">No players meet the selection rules.</div>';
  } catch(error) { showError("#xi-list", error.message); }
}
async function refreshAll() {
  $("#api-status").textContent = "Checking API…";
  try {
    const health = await api("/api/health");
    if (health.status !== "ok") throw new Error(health.error || "Dataset could not be loaded");
    $("#api-status").textContent = `${number(health.dataset_rows)} dataset rows`;
    await Promise.all([loadOverview(), loadTeams(), loadXI()]);
    if ($("#view-players").classList.contains("active-view")) await loadPlayers();
    toast("Dashboard data refreshed");
  } catch (error) {
    $("#api-status").textContent = "API unavailable";
    ["#role-chart","#snapshot"].forEach(sel => showError(sel, error.message));
    toast(error.message);
  }
}
function navigate(view) {
  const target = ["overview","players","teams","best-xi"].includes(view) ? view : "overview";
  $$(".view").forEach(el => el.classList.remove("active-view"));
  $(`#view-${target}`).classList.add("active-view");
  $$(".nav-link").forEach(el => el.classList.toggle("active", el.dataset.view === target));
  const titles = {overview:"Auction overview",players:"Player explorer",teams:"Team analysis","best-xi":"Suggested Best XI"};
  $("#page-title").textContent = titles[target];
  if (target === "players") loadPlayers();
  if (target === "teams") loadTeams();
  if (target === "best-xi") loadXI();
}
$$("[data-view]").forEach(link => link.addEventListener("click", event => {
  event.preventDefault(); navigate(link.dataset.view); history.replaceState(null,"",`#${link.dataset.view}`);
}));
$("#refresh-btn").addEventListener("click", refreshAll);
$("#xi-refresh").addEventListener("click", loadXI);
$("#show-more").addEventListener("click", () => { state.offset += state.limit; loadPlayers(false); });
["#type-filter","#team-filter","#sort-filter","#capped-filter"].forEach(sel => $(sel).addEventListener("change", () => loadPlayers()));
$("#search-input").addEventListener("input", () => {
  clearTimeout(state.searchTimer); state.searchTimer = setTimeout(() => loadPlayers(), 250);
});
window.addEventListener("hashchange", () => navigate(location.hash.slice(1)));
refreshAll().then(() => { if (location.hash) navigate(location.hash.slice(1)); });
