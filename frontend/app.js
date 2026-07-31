const $ = (selector) => document.querySelector(selector);
const formatNumber = (value) => new Intl.NumberFormat("en-GB").format(Number(value || 0));
const formatPrice = (value) => value == null ? "—" : Number(value).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 3 });
const formatMoney = (value) => value == null ? "—" : new Intl.NumberFormat("en-GB", { style: "currency", currency: "USD", minimumFractionDigits: 2 }).format(Number(value));
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
let activeBackfillJobId = null;
let activeBacktestId = null;
let historicalReady = false;

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

function defaultJobMessage(status, rows) {
  if (status === "paused") return "Download paused safely. Press Resume to continue from the saved point.";
  if (status === "error") return "The last download stopped with an error. Press Resume after checking Activity.";
  if (rows > 0) return "Live M5 candles are stored. The multi-year historical download has not started yet.";
  return "Ready to download the complete available XAU/USD M5 history.";
}

function renderDashboard(data) {
  const state = data.state || {};
  const job = data.backfill_job || {};
  const candle = data.latest_candle || {};
  const gaps = data.gaps || {};
  const status = state.status || "not_started";
  historicalReady = Boolean(data.historical_ready || state.historical_complete);
  const progress = Number(data.historical_progress_percent ?? state.progress_percent ?? 0);
  const rows = Number(state.rows_in_database || state.rows_processed || 0);
  const active = ["queued", "running"].includes(job.status);

  activeBackfillJobId = active ? job.id : null;
  setService(true, "Online");
  $("#statePill").textContent = status.replaceAll("_", " ").toUpperCase();
  $("#statePill").className = `status-pill ${status}`;
  $("#progressValue").textContent = `${Math.min(100, progress).toFixed(progress > 0 && progress < 10 ? 1 : 0)}%`;
  $("#progressRing").style.setProperty("--progress", Math.min(100, progress));
  $("#progressBar").style.width = `${Math.min(100, progress)}%`;
  $("#jobMessage").textContent = job.message || state.last_error || defaultJobMessage(status, rows);
  $("#candleCount").textContent = formatNumber(rows);
  $("#batchCount").textContent = formatNumber(state.batches_completed);
  $("#gapCount").textContent = formatNumber(gaps.review);

  $("#earliestDate").textContent = formatDate(state.earliest_available);
  $("#oldestDate").textContent = formatDate(state.oldest_stored);
  $("#latestDate").textContent = formatDate(state.latest_stored);
  $("#dataStatus").textContent = historicalReady ? "Historical ready" : rows > 0 ? "Live sync only" : status.replaceAll("_", " ");

  $("#latestClose").textContent = formatPrice(candle.close);
  $("#latestTime").textContent = candle.candle_time ? formatDate(candle.candle_time, true) : "No candle stored yet";
  $("#latestOpen").textContent = formatPrice(candle.open);
  $("#latestHigh").textContent = formatPrice(candle.high);
  $("#latestLow").textContent = formatPrice(candle.low);
  $("#latestCloseSmall").textContent = formatPrice(candle.close);

  const start = $("#startBackfill");
  start.disabled = active || historicalReady;
  if (historicalReady) start.textContent = "Historical database ready";
  else if (active) start.textContent = "Download in progress…";
  else if (["paused", "error"].includes(status) || Number(state.batches_completed || 0) > 0) start.textContent = "Resume historical download";
  else start.textContent = "Start historical download";

  const pause = $("#pauseBackfill");
  pause.hidden = !active;
  pause.disabled = !active;
  $("#syncLatest").disabled = active;
  $("#scanGaps").disabled = active || rows < 2;
  $("#runBacktest").disabled = !historicalReady || Boolean(activeBacktestId);
  renderEvents(data.events || []);
}

async function refreshDashboard(silent = false) {
  try {
    const payload = await api("status?symbol=XAU%2FUSD&interval=5min");
    renderDashboard(payload.data || {});
  } catch (error) {
    setService(false, "Setup needed");
    $("#jobMessage").textContent = error.message;
    if (!silent) showToast(error.message, true);
  }
}

async function queueJob(endpoint, button, successText) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Queuing…";
  try {
    const payload = await api(`jobs/${endpoint}`, {
      method: "POST",
      body: JSON.stringify({ symbol: "XAU/USD", interval: "5min", force_restart: false }),
    });
    showToast(payload.message || successText);
    await refreshDashboard(true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function pauseBackfill(button) {
  if (!activeBackfillJobId) return;
  button.disabled = true;
  button.textContent = "Pausing…";
  try {
    const payload = await api(`jobs/${activeBackfillJobId}/cancel`, { method: "POST", body: "{}" });
    showToast(payload.message || "Pause requested");
    await refreshDashboard(true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.textContent = "Pause download";
  }
}

function backtestPayload() {
  return {
    name: "Fixed Ladder v2.61 — Full M5 History",
    symbol: "XAU/USD",
    interval: "5min",
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
  button.disabled = true;
  button.textContent = "Starting…";
  try {
    const payload = await api("backtests/fixed-ladder-v2-61", {
      method: "POST",
      body: JSON.stringify(backtestPayload()),
    });
    activeBacktestId = payload.data.id;
    showToast(payload.message || "Backtest started");
    await refreshBacktests(true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.textContent = "Run full backtest";
    button.disabled = Boolean(activeBacktestId) || !historicalReady;
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
    $("#runBacktest").disabled = !historicalReady;
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
  $("#runBacktest").disabled = active || !historicalReady;

  $("#resultNet").textContent = formatMoney(run.net_profit);
  $("#resultPF").textContent = run.profit_factor == null ? "—" : Number(run.profit_factor).toFixed(3);
  $("#resultDD").textContent = run.max_drawdown_percent == null ? "—" : formatPercent(run.max_drawdown_percent);
  $("#resultBasketWin").textContent = run.basket_win_rate == null ? "—" : formatPercent(run.basket_win_rate);
  $("#resultPositions").textContent = run.total_positions == null ? "—" : formatNumber(run.total_positions);
  $("#resultBaskets").textContent = run.total_baskets == null ? "—" : formatNumber(run.total_baskets);
  $("#resultBalance").textContent = formatMoney(run.ending_balance);
  $("#resultAmbiguous").textContent = reliability.ambiguous_candles == null ? "—" : formatNumber(reliability.ambiguous_candles);
  $("#accuracyWarning").textContent = reliability.warning || "This first backtest is an M5 approximation. M1 and tick replay will be added before any live approval.";
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

async function refreshBacktests(silent = false) {
  try {
    const payload = await api("backtests?limit=1");
    const run = (payload.data || [])[0] || null;
    renderBacktest(run);
    if (run && run.status === "complete") {
      const detail = await api(`backtests/${run.id}`);
      renderBaskets(detail.data.baskets || []);
    } else if (!run || run.status !== "complete") {
      renderBaskets([]);
    }
  } catch (error) {
    if (!silent) showToast(error.message, true);
  }
}

$("#startBackfill").addEventListener("click", (event) => queueJob("backfill", event.currentTarget, "Historical download queued"));
$("#pauseBackfill").addEventListener("click", (event) => pauseBackfill(event.currentTarget));
$("#syncLatest").addEventListener("click", (event) => queueJob("sync", event.currentTarget, "Latest sync queued"));
$("#scanGaps").addEventListener("click", (event) => queueJob("gap-scan", event.currentTarget, "Gap scan queued"));
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
