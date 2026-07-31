const $ = (selector) => document.querySelector(selector);
const formatNumber = (value) => new Intl.NumberFormat("en-GB").format(Number(value || 0));
const formatPrice = (value) => value == null ? "—" : Number(value).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 3 });
const formatMoney = (value) => value == null ? "—" : new Intl.NumberFormat("en-GB", { style: "currency", currency: "USD", minimumFractionDigits: 2 }).format(Number(value));
const formatSignedMoney = (value) => {
  if (value == null) return "—";
  const number = Number(value);
  const sign = number > 0 ? "+" : "";
  return `${sign}${formatMoney(number)}`;
};
const formatPercent = (value) => value == null ? "—" : `${Number(value).toFixed(2)}%`;
const formatDate = (value, includeTime = false) => {
  if (!value) return "None";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit", month: "short", year: "numeric",
    ...(includeTime ? { hour: "2-digit", minute: "2-digit", timeZoneName: "short" } : {}),
  }).format(date);
};

let refreshTimer;
let toastTimer;
let activeBacktestId = null;
const activeBackfillJobIds = { "5min": null, "1min": null };
const historicalReady = { "5min": false, "1min": false };

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 5200);
}

async function api(path, options = {}) {
  const response = await fetch(`/api/${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    cache: "no-store",
    ...options,
  });
  let payload;
  try { payload = await response.json(); }
  catch { payload = { ok: false, message: await response.text() }; }
  if (!response.ok || payload.ok === false) {
    const detail = payload.detail || payload.message || `Request failed (${response.status})`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

function setService(online, label) {
  $("#serviceStatus").textContent = label;
  $("#servicePulse").className = `pulse ${online ? "online" : "error"}`;
}

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = value == null ? "" : String(value);
  return node.innerHTML;
}

function renderEvents(events = []) {
  const host = $("#activityList");
  if (!events.length) {
    host.innerHTML = '<div class="empty-state">No system activity recorded yet.</div>';
    return;
  }
  host.innerHTML = events.map((event) => `
    <div class="activity-row">
      <time>${formatDate(event.created_at, true)}</time>
      <span class="event-level ${event.level}">${String(event.level || "info").toUpperCase()}</span>
      <p>${escapeHtml(event.message || "System event")}</p>
    </div>
  `).join("");
}

function defaultJobMessage(status, rows, interval) {
  const label = interval === "1min" ? "M1" : "M5";
  if (status === "paused") return `${label} download paused safely. Press Resume to continue from the saved point.`;
  if (status === "error") return `The last ${label} download stopped with an error. Press Resume after checking Activity.`;
  if (rows > 0) return `Recent ${label} candles are stored. The multi-year historical download has not completed yet.`;
  return `Ready to download the complete available XAU/USD ${label} history.`;
}

function updateBacktestAvailability() {
  const resolution = $("#resolutionMode").value;
  const ready = resolution === "m1_replay" ? historicalReady["1min"] : historicalReady["5min"];
  const button = $("#runBacktest");
  button.disabled = !ready || Boolean(activeBacktestId);
  button.textContent = resolution === "m1_replay" ? "Run M1 high-resolution replay" : "Run M5 approximation";

  if (resolution === "m1_replay") {
    $("#resolutionNote").textContent = historicalReady["1min"]
      ? "M1 Market Memory is complete. This run uses every verified one-minute candle in sequence."
      : "M1 replay is locked until the M1 historical download reaches 100%.";
  } else {
    $("#resolutionNote").textContent = "M5 baseline uses the completed broad historical dataset and a candle-path approximation.";
  }
}

function renderM5Dashboard(data) {
  const state = data.state || {};
  const job = data.backfill_job || {};
  const candle = data.latest_candle || {};
  const gaps = data.gaps || {};
  const status = state.status || "not_started";
  historicalReady["5min"] = Boolean(data.historical_ready || state.historical_complete);
  const progress = Number(data.historical_progress_percent ?? state.progress_percent ?? 0);
  const rows = Number(state.rows_in_database || state.rows_processed || 0);
  const active = ["queued", "running"].includes(job.status);

  activeBackfillJobIds["5min"] = active ? job.id : null;
  setService(true, "Online");
  $("#statePill").textContent = status.replaceAll("_", " ").toUpperCase();
  $("#statePill").className = `status-pill ${status}`;
  $("#progressValue").textContent = `${Math.min(100, progress).toFixed(progress > 0 && progress < 10 ? 1 : 0)}%`;
  $("#progressRing").style.setProperty("--progress", Math.min(100, progress));
  $("#progressBar").style.width = `${Math.min(100, progress)}%`;
  $("#jobMessage").textContent = job.message || state.last_error || defaultJobMessage(status, rows, "5min");
  $("#candleCount").textContent = formatNumber(rows);
  $("#batchCount").textContent = formatNumber(state.batches_completed);
  $("#gapCount").textContent = formatNumber(gaps.review);

  $("#earliestDate").textContent = formatDate(state.earliest_available);
  $("#oldestDate").textContent = formatDate(state.oldest_stored);

  $("#latestClose").textContent = formatPrice(candle.close);
  $("#latestTime").textContent = candle.candle_time ? formatDate(candle.candle_time, true) : "No candle stored yet";
  $("#latestOpen").textContent = formatPrice(candle.open);
  $("#latestHigh").textContent = formatPrice(candle.high);
  $("#latestLow").textContent = formatPrice(candle.low);
  $("#latestCloseSmall").textContent = formatPrice(candle.close);

  const start = $("#startBackfill");
  start.disabled = active || historicalReady["5min"];
  if (historicalReady["5min"]) start.textContent = "M5 historical database ready";
  else if (active) start.textContent = "M5 download in progress…";
  else if (["paused", "error"].includes(status) || Number(state.batches_completed || 0) > 0) start.textContent = "Resume M5 historical download";
  else start.textContent = "Start M5 historical download";

  const pause = $("#pauseBackfill");
  pause.hidden = !active;
  pause.disabled = !active;
  $("#syncLatest").disabled = active;
  $("#scanGaps").disabled = active || rows < 2;
  renderEvents(data.events || []);
  updateBacktestAvailability();
}

function renderM1Dashboard(data) {
  const state = data.state || {};
  const job = data.backfill_job || {};
  const gaps = data.gaps || {};
  const status = state.status || "not_started";
  historicalReady["1min"] = Boolean(data.historical_ready || state.historical_complete);
  const progress = Number(data.historical_progress_percent ?? state.progress_percent ?? 0);
  const rows = Number(state.rows_in_database || state.rows_processed || 0);
  const active = ["queued", "running"].includes(job.status);

  activeBackfillJobIds["1min"] = active ? job.id : null;
  $("#m1StatePill").textContent = status.replaceAll("_", " ").toUpperCase();
  $("#m1StatePill").className = `status-pill ${status}`;
  $("#m1ProgressValue").textContent = `${Math.min(100, progress).toFixed(progress > 0 && progress < 10 ? 1 : 0)}%`;
  $("#m1ProgressRing").style.setProperty("--progress", Math.min(100, progress));
  $("#m1ProgressBar").style.width = `${Math.min(100, progress)}%`;
  $("#m1JobMessage").textContent = job.message || state.last_error || defaultJobMessage(status, rows, "1min");
  $("#m1CandleCount").textContent = formatNumber(rows);
  $("#m1BatchCount").textContent = formatNumber(state.batches_completed);
  $("#m1GapCount").textContent = formatNumber(gaps.review);
  $("#m1LatestDate").textContent = formatDate(state.latest_stored);
  $("#m1OldestDate").textContent = formatDate(state.oldest_stored);
  $("#replayDataStatus").textContent = historicalReady["1min"] ? "M1 replay ready" : active ? "M1 downloading" : rows > 0 ? "M1 partial" : "Waiting";

  const start = $("#startM1Backfill");
  start.disabled = active || historicalReady["1min"];
  if (historicalReady["1min"]) start.textContent = "M1 historical database ready";
  else if (active) start.textContent = "M1 download in progress…";
  else if (["paused", "error"].includes(status) || Number(state.batches_completed || 0) > 0) start.textContent = "Resume M1 historical download";
  else start.textContent = "Download M1 history";

  const pause = $("#pauseM1Backfill");
  pause.hidden = !active;
  pause.disabled = !active;
  $("#syncM1Latest").disabled = active;
  $("#scanM1Gaps").disabled = active || rows < 2;
  updateBacktestAvailability();
}

async function refreshMarketStatus(interval, silent = false) {
  try {
    const payload = await api(`status?symbol=XAU%2FUSD&interval=${encodeURIComponent(interval)}`);
    if (interval === "1min") renderM1Dashboard(payload.data || {});
    else renderM5Dashboard(payload.data || {});
  } catch (error) {
    if (interval === "5min") {
      setService(false, "Setup needed");
      $("#jobMessage").textContent = error.message;
    } else {
      $("#m1JobMessage").textContent = error.message;
    }
    if (!silent) showToast(error.message, true);
  }
}

async function refreshDashboard(silent = false) {
  await Promise.all([
    refreshMarketStatus("5min", silent),
    refreshMarketStatus("1min", true),
  ]);
}

async function queueJob(endpoint, interval, button, successText) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Queuing…";
  try {
    const payload = await api(`jobs/${endpoint}`, {
      method: "POST",
      body: JSON.stringify({ symbol: "XAU/USD", interval, force_restart: false }),
    });
    showToast(payload.message || successText);
    await refreshMarketStatus(interval, true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function pauseBackfill(interval, button) {
  const jobId = activeBackfillJobIds[interval];
  if (!jobId) return;
  button.disabled = true;
  button.textContent = "Pausing…";
  try {
    const payload = await api(`jobs/${jobId}/cancel`, { method: "POST", body: "{}" });
    showToast(payload.message || "Pause requested");
    await refreshMarketStatus(interval, true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.textContent = interval === "1min" ? "Pause M1 download" : "Pause M5 download";
  }
}

function backtestPayload() {
  const resolution = $("#resolutionMode").value;
  return {
    name: resolution === "m1_replay" ? "Fixed Ladder v2.61 — Full M1 Replay" : "Fixed Ladder v2.61 — Full M5 History",
    symbol: "XAU/USD",
    interval: "5min",
    resolution,
    starting_balance: Number($("#startingBalance").value),
    fixed_lot: Number($("#fixedLot").value),
    spread_price: Number($("#spreadPrice").value),
    commission_per_001_lot: Number($("#commission").value),
    path_mode: $("#pathMode").value,
    profit_target_money: Number($("#profitTarget").value),
    peak_protection_activation_money: Number($("#peakActivation").value),
    peak_protection_giveback_money: Number($("#peakGiveback").value),
    levels_per_side: 8,
    spacing_price: 3.0,
    fallback_price: 2.0,
    first_bullet_quick_cut_price: 0.75,
    break_even_trigger_price: 1.5,
    break_even_buffer_price: 0.15,
    emergency_loss_money: 5.0,
    emergency_loss_percent: 1.0,
    slippage_price: 0.0,
    money_per_price_per_001_lot: 1.0,
  };
}

async function runBacktest(button) {
  const payloadBody = backtestPayload();
  const requiredInterval = payloadBody.resolution === "m1_replay" ? "1min" : "5min";
  if (!historicalReady[requiredInterval]) {
    showToast(`${requiredInterval === "1min" ? "M1" : "M5"} Market Memory is not complete yet.`, true);
    return;
  }
  button.disabled = true;
  button.textContent = "Starting…";
  try {
    const payload = await api("backtests/fixed-ladder-v2-61", {
      method: "POST",
      body: JSON.stringify(payloadBody),
    });
    activeBacktestId = payload.data.id;
    showToast(payload.message || "Backtest started");
    await refreshBacktests(true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    updateBacktestAvailability();
  }
}

async function cancelBacktest(button) {
  if (!activeBacktestId) return;
  button.disabled = true;
  button.textContent = "Cancelling…";
  try {
    const payload = await api(`backtests/${activeBacktestId}/cancel`, { method: "POST", body: "{}" });
    showToast(payload.message || "Cancellation requested");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.textContent = "Cancel backtest";
    button.disabled = false;
  }
}

function renderBacktest(run = null) {
  if (!run || !run.id) {
    activeBacktestId = null;
    $("#backtestTitle").textContent = "Not started";
    $("#backtestStatus").textContent = "WAITING";
    $("#backtestStatus").className = "status-pill";
    $("#backtestProgress").textContent = "0%";
    $("#backtestProgressBar").style.width = "0%";
    $("#cancelBacktest").hidden = true;
    updateBacktestAvailability();
    return;
  }
  const reliability = run.reliability || {};
  const status = run.status || "queued";
  const active = ["queued", "running"].includes(status);
  activeBacktestId = active ? run.id : null;
  const progress = Number(reliability.progress_percent || (status === "complete" ? 100 : 0));
  $("#backtestTitle").textContent = run.name || "Fixed Ladder v2.61";
  $("#backtestStatus").textContent = status.toUpperCase();
  $("#backtestStatus").className = `status-pill ${status}`;
  $("#backtestProgress").textContent = `${progress.toFixed(progress > 0 && progress < 10 ? 1 : 0)}%`;
  $("#backtestProgressBar").style.width = `${Math.min(100, progress)}%`;
  $("#backtestMessage").textContent = run.error || reliability.message || "Waiting for Railway";
  $("#cancelBacktest").hidden = !active;

  $("#resultNet").textContent = formatMoney(run.net_profit);
  $("#resultPF").textContent = run.profit_factor == null ? "—" : Number(run.profit_factor).toFixed(3);
  $("#resultDD").textContent = run.max_drawdown_percent == null ? "—" : formatPercent(run.max_drawdown_percent);
  $("#resultBasketWin").textContent = run.basket_win_rate == null ? "—" : formatPercent(run.basket_win_rate);
  $("#resultPositions").textContent = run.total_positions == null ? "—" : formatNumber(run.total_positions);
  $("#resultBaskets").textContent = run.total_baskets == null ? "—" : formatNumber(run.total_baskets);
  $("#resultBalance").textContent = formatMoney(run.ending_balance);
  $("#resultAmbiguous").textContent = reliability.ambiguous_candles == null ? "—" : formatNumber(reliability.ambiguous_candles);
  $("#ambiguousLabel").textContent = run.resolution === "m1_replay" ? "AMBIGUOUS M1 BARS" : "AMBIGUOUS M5 BARS";
  $("#accuracyWarning").textContent = reliability.warning || "M5 is an approximation. M1 reduces uncertainty but tick replay remains the final execution standard.";
  updateBacktestAvailability();
}

function renderBaskets(baskets = []) {
  const host = $("#basketRows");
  if (!baskets.length) {
    host.innerHTML = '<tr><td colspan="7">No completed baskets are available yet.</td></tr>';
    return;
  }
  host.innerHTML = baskets.slice(0, 100).map((basket) => {
    const pnl = Number(basket.net_pnl || 0);
    return `<tr>
      <td>${formatDate(basket.opened_at, true)}</td>
      <td>${escapeHtml(String(basket.side || "—").toUpperCase())}</td>
      <td>${formatNumber(basket.positions)}</td>
      <td class="${pnl >= 0 ? "pnl-positive" : "pnl-negative"}">${formatMoney(pnl)}</td>
      <td>${formatMoney(basket.peak_floating)}</td>
      <td>${formatMoney(basket.worst_floating)}</td>
      <td>${escapeHtml(basket.exit_reason || "—")}</td>
    </tr>`;
  }).join("");
}

function renderComparison(runs = []) {
  const m5 = runs.find((run) => run.status === "complete" && run.resolution === "candle");
  const m1 = runs.find((run) => run.status === "complete" && run.resolution === "m1_replay");

  $("#m5ComparePF").textContent = m5?.profit_factor == null ? "—" : Number(m5.profit_factor).toFixed(3);
  $("#m5CompareMeta").textContent = m5
    ? `${formatMoney(m5.net_profit)} net · ${formatPercent(m5.max_drawdown_percent)} drawdown`
    : "Run the M5 baseline";

  $("#m1ComparePF").textContent = m1?.profit_factor == null ? "—" : Number(m1.profit_factor).toFixed(3);
  $("#m1CompareMeta").textContent = m1
    ? `${formatMoney(m1.net_profit)} net · ${formatPercent(m1.max_drawdown_percent)} drawdown`
    : historicalReady["1min"] ? "Run the M1 replay" : "Download M1 history first";

  if (m5 && m1) {
    const delta = Number(m1.net_profit || 0) - Number(m5.net_profit || 0);
    $("#compareProfitDelta").textContent = formatSignedMoney(delta);
    const m5Ambiguous = Number(m5.reliability?.ambiguous_candles || 0);
    const m1Ambiguous = Number(m1.reliability?.ambiguous_candles || 0);
    $("#compareReliability").textContent = `${formatNumber(m5Ambiguous)} ambiguous M5 bars versus ${formatNumber(m1Ambiguous)} ambiguous M1 bars`;
  } else {
    $("#compareProfitDelta").textContent = "—";
    $("#compareReliability").textContent = "Waiting for both completed runs";
  }
}

async function refreshBacktests(silent = false) {
  try {
    const payload = await api("backtests?limit=20");
    const runs = payload.data || [];
    const latest = runs[0] || null;
    renderBacktest(latest);
    renderComparison(runs);
    if (latest && latest.status === "complete") {
      const detail = await api(`backtests/${latest.id}`);
      renderBaskets(detail.data.baskets || []);
    } else {
      renderBaskets([]);
    }
  } catch (error) {
    if (!silent) showToast(error.message, true);
  }
}

$("#startBackfill").addEventListener("click", (event) => queueJob("backfill", "5min", event.currentTarget, "M5 historical download queued"));
$("#pauseBackfill").addEventListener("click", (event) => pauseBackfill("5min", event.currentTarget));
$("#syncLatest").addEventListener("click", (event) => queueJob("sync", "5min", event.currentTarget, "Latest M5 sync queued"));
$("#scanGaps").addEventListener("click", (event) => queueJob("gap-scan", "5min", event.currentTarget, "M5 gap scan queued"));

$("#startM1Backfill").addEventListener("click", (event) => queueJob("backfill", "1min", event.currentTarget, "M1 historical download queued"));
$("#pauseM1Backfill").addEventListener("click", (event) => pauseBackfill("1min", event.currentTarget));
$("#syncM1Latest").addEventListener("click", (event) => queueJob("sync", "1min", event.currentTarget, "Latest M1 sync queued"));
$("#scanM1Gaps").addEventListener("click", (event) => queueJob("gap-scan", "1min", event.currentTarget, "M1 gap scan queued"));

$("#resolutionMode").addEventListener("change", updateBacktestAvailability);
$("#runBacktest").addEventListener("click", (event) => runBacktest(event.currentTarget));
$("#cancelBacktest").addEventListener("click", (event) => cancelBacktest(event.currentTarget));
$("#refreshBacktest").addEventListener("click", () => refreshBacktests());
$("#refreshButton").addEventListener("click", async () => { await refreshDashboard(); await refreshBacktests(true); });

const navLinks = [...document.querySelectorAll(".nav-link")];
const sections = navLinks.map((link) => document.querySelector(link.getAttribute("href"))).filter(Boolean);
const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) navLinks.forEach((link) => link.classList.toggle("active", link.getAttribute("href") === `#${entry.target.id}`));
  });
}, { rootMargin: "-35% 0px -55%" });
sections.forEach((section) => observer.observe(section));

(async () => {
  await refreshDashboard(true);
  await refreshBacktests(true);
})();
refreshTimer = setInterval(async () => {
  await refreshDashboard(true);
  await refreshBacktests(true);
}, 10_000);
