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

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 4200);
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

function renderDashboard(data) {
  const state = data.state || {};
  const job = data.latest_job || {};
  const candle = data.latest_candle || {};
  const gaps = data.gaps || {};
  const status = state.status || "not_started";
  const progress = Number(state.progress_percent || job.progress_percent || 0);

  setService(true, "Online");
  $("#statePill").textContent = status.replaceAll("_", " ").toUpperCase();
  $("#statePill").className = `status-pill ${status}`;
  $("#progressValue").textContent = `${Math.min(100, progress).toFixed(progress > 0 && progress < 10 ? 1 : 0)}%`;
  $("#progressRing").style.setProperty("--progress", Math.min(100, progress));
  $("#progressBar").style.width = `${Math.min(100, progress)}%`;
  $("#jobMessage").textContent = job.message || state.last_error || "Ready to download the complete available XAU/USD M5 history.";
  $("#candleCount").textContent = formatNumber(state.rows_in_database || state.rows_processed);
  $("#batchCount").textContent = formatNumber(state.batches_completed);
  $("#gapCount").textContent = formatNumber(gaps.review);

  $("#earliestDate").textContent = formatDate(state.earliest_available);
  $("#oldestDate").textContent = formatDate(state.oldest_stored);
  $("#latestDate").textContent = formatDate(state.latest_stored);
  $("#dataStatus").textContent = status === "complete" ? "Ready" : status.replaceAll("_", " ");

  $("#latestClose").textContent = formatPrice(candle.close);
  $("#latestTime").textContent = candle.candle_time ? formatDate(candle.candle_time, true) : "No candle stored yet";
  $("#latestOpen").textContent = formatPrice(candle.open);
  $("#latestHigh").textContent = formatPrice(candle.high);
  $("#latestLow").textContent = formatPrice(candle.low);
  $("#latestCloseSmall").textContent = formatPrice(candle.close);

  const active = ["queued", "downloading", "syncing"].includes(status) || ["queued", "running"].includes(job.status);
  $("#startBackfill").disabled = active || status === "complete";
  $("#startBackfill").textContent = status === "complete" ? "Historical database ready" : active ? "Download in progress…" : "Start historical download";

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

$("#startBackfill").addEventListener("click", (event) => queueJob("backfill", event.currentTarget, "Historical download queued"));
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
