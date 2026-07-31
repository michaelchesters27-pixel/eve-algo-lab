const $ = (selector) => document.querySelector(selector);
const formatNumber = (value) => new Intl.NumberFormat("en-GB").format(Number(value || 0));
const formatPrice = (value) => value == null ? "—" : Number(value).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 3 });
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

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = value;
  return node.innerHTML;
}

function defaultJobMessage(status, rows) {
  if (status === "paused") return "Download paused safely. Press Resume to continue from the saved point.";
  if (status === "error") return "The last download stopped with an error. Press Resume after checking the activity log.";
  if (rows > 0) return "Live M5 candles are being stored. The multi-year historical download has not started yet.";
  return "Ready to download the complete available XAU/USD M5 history.";
}

function renderDashboard(data) {
  const state = data.state || {};
  const job = data.backfill_job || {};
  const candle = data.latest_candle || {};
  const gaps = data.gaps || {};
  const status = state.status || "not_started";
  const historicalReady = Boolean(data.historical_ready || state.historical_complete);
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

$("#startBackfill").addEventListener("click", (event) => queueJob("backfill", event.currentTarget, "Historical download queued"));
$("#pauseBackfill").addEventListener("click", (event) => pauseBackfill(event.currentTarget));
$("#syncLatest").addEventListener("click", (event) => queueJob("sync", event.currentTarget, "Latest sync queued"));
$("#scanGaps").addEventListener("click", (event) => queueJob("gap-scan", event.currentTarget, "Gap scan queued"));
$("#refreshButton").addEventListener("click", () => refreshDashboard());

const navLinks = [...document.querySelectorAll(".nav-link")];
const sections = navLinks.map((link) => document.querySelector(link.getAttribute("href"))).filter(Boolean);
const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) {
      navLinks.forEach((link) => link.classList.toggle("active", link.getAttribute("href") === `#${entry.target.id}`));
    }
  });
}, { rootMargin: "-35% 0px -55%" });
sections.forEach((section) => observer.observe(section));

refreshDashboard(true);
refreshTimer = setInterval(() => refreshDashboard(true), 10_000);
