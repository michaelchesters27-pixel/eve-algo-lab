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

const TIMEFRAMES = [
  { interval: "1min", key: "m1", label: "M1", role: "Execution path", description: "Minute-by-minute price path for detailed replay and micro-pattern research." },
  { interval: "5min", key: "m5", label: "M5", role: "Intraday structure", description: "Detailed intraday movement and the broad benchmark for current research." },
  { interval: "15min", key: "m15", label: "M15", role: "Setup context", description: "Momentum transitions, compression and context around lower-timeframe patterns." },
  { interval: "1h", key: "h1", label: "H1", role: "Intraday regime", description: "Trend, range and volatility regime surrounding each intraday event." },
  { interval: "4h", key: "h4", label: "H4", role: "Major swing context", description: "Broader market structure and multi-session directional behaviour." },
  { interval: "1day", key: "d1", label: "D1", role: "Calendar context", description: "Daily ranges, weekdays, months, seasons and long-term market regimes." },
];

let refreshTimer;
let toastTimer;
let activeBacktestId = null;
let activeLearningRunId = null;
let learningDashboard = null;
let batchActionRunning = false;
const activeBackfillJobIds = Object.fromEntries(TIMEFRAMES.map((item) => [item.interval, null]));
const historicalReady = Object.fromEntries(TIMEFRAMES.map((item) => [item.interval, false]));
const marketStates = Object.fromEntries(TIMEFRAMES.map((item) => [item.interval, null]));

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

function timeframeCard(meta) {
  return `
    <article class="timeframe-card" data-interval="${meta.interval}">
      <div class="timeframe-head">
        <div class="timeframe-name"><span>${meta.label}</span><div><small>${meta.role.toUpperCase()}</small><h3>XAU/USD ${meta.label}</h3></div></div>
        <span class="status-pill" id="tf-${meta.key}-status">CHECKING</span>
      </div>
      <p class="timeframe-description">${meta.description}</p>
      <div class="timeframe-progress-row">
        <div class="progress-track"><span id="tf-${meta.key}-bar"></span></div>
        <strong id="tf-${meta.key}-progress">0%</strong>
      </div>
      <p class="timeframe-message" id="tf-${meta.key}-message">Checking stored candles and job state.</p>
      <div class="timeframe-metrics">
        <div><small>CANDLES</small><strong id="tf-${meta.key}-rows">0</strong></div>
        <div><small>BATCHES</small><strong id="tf-${meta.key}-batches">0</strong></div>
        <div><small>REVIEW GAPS</small><strong id="tf-${meta.key}-review">0</strong></div>
        <div><small>EXPECTED CLOSURES</small><strong id="tf-${meta.key}-expected">0</strong></div>
      </div>
      <div class="coverage-strip">
        <div><small>STORED FROM</small><strong id="tf-${meta.key}-oldest">None</strong></div>
        <div><small>LATEST</small><strong id="tf-${meta.key}-latest">None</strong></div>
      </div>
      <div class="actions compact-actions">
        <button class="button button-primary" data-action="backfill" data-interval="${meta.interval}">Download history</button>
        <button class="button" data-action="pause" data-interval="${meta.interval}" hidden>Pause</button>
        <button class="button" data-action="sync" data-interval="${meta.interval}">Sync latest</button>
        <button class="button button-quiet" data-action="gap-scan" data-interval="${meta.interval}">Scan gaps</button>
      </div>
    </article>
  `;
}

function createTimeframeCards() {
  $("#timeframeGrid").innerHTML = TIMEFRAMES.map(timeframeCard).join("");
}

function defaultJobMessage(meta, status, rows) {
  if (status === "paused") return `${meta.label} download paused safely. Press Resume to continue from the saved point.`;
  if (status === "error") return `The last ${meta.label} job stopped with an error. Check Activity, then press Resume.`;
  if (rows > 0) return `Recent ${meta.label} candles are stored. The complete available history has not finished yet.`;
  return `Ready to download the complete available XAU/USD ${meta.label} history.`;
}

function renderTimeframeDashboard(meta, data) {
  const state = data.state || {};
  const job = data.backfill_job || {};
  const gaps = data.gaps || {};
  const status = state.status || "not_started";
  const ready = Boolean(data.historical_ready || state.historical_complete);
  const progress = Number(data.historical_progress_percent ?? state.progress_percent ?? 0);
  const rows = Number(state.rows_in_database || state.rows_processed || 0);
  const active = ["queued", "running"].includes(job.status);

  marketStates[meta.interval] = data;
  historicalReady[meta.interval] = ready;
  activeBackfillJobIds[meta.interval] = active ? job.id : null;

  const statusNode = $(`#tf-${meta.key}-status`);
  statusNode.textContent = status.replaceAll("_", " ").toUpperCase();
  statusNode.className = `status-pill ${status}`;
  $(`#tf-${meta.key}-progress`).textContent = `${Math.min(100, progress).toFixed(progress > 0 && progress < 10 ? 1 : 0)}%`;
  $(`#tf-${meta.key}-bar`).style.width = `${Math.min(100, progress)}%`;
  $(`#tf-${meta.key}-message`).textContent = job.message || state.last_error || defaultJobMessage(meta, status, rows);
  $(`#tf-${meta.key}-rows`).textContent = formatNumber(rows);
  $(`#tf-${meta.key}-batches`).textContent = formatNumber(state.batches_completed);
  $(`#tf-${meta.key}-review`).textContent = formatNumber(gaps.review);
  $(`#tf-${meta.key}-expected`).textContent = formatNumber(gaps.expected);
  $(`#tf-${meta.key}-oldest`).textContent = formatDate(state.oldest_stored);
  $(`#tf-${meta.key}-latest`).textContent = formatDate(state.latest_stored);

  const card = document.querySelector(`.timeframe-card[data-interval="${meta.interval}"]`);
  const start = card.querySelector('[data-action="backfill"]');
  const pause = card.querySelector('[data-action="pause"]');
  const sync = card.querySelector('[data-action="sync"]');
  const scan = card.querySelector('[data-action="gap-scan"]');

  start.disabled = active || ready || batchActionRunning;
  if (ready) start.textContent = `${meta.label} database ready`;
  else if (active) start.textContent = `${meta.label} download in progress…`;
  else if (["paused", "error"].includes(status) || Number(state.batches_completed || 0) > 0) start.textContent = `Resume ${meta.label} history`;
  else start.textContent = `Download ${meta.label} history`;

  pause.hidden = !active;
  pause.disabled = !active || batchActionRunning;
  pause.textContent = `Pause ${meta.label}`;
  sync.disabled = active || batchActionRunning;
  scan.disabled = active || rows < 2 || batchActionRunning;
}

function renderM5Live(data) {
  const candle = data.latest_candle || {};
  $("#latestClose").textContent = formatPrice(candle.close);
  $("#latestTime").textContent = candle.candle_time ? formatDate(candle.candle_time, true) : "No candle stored yet";
  $("#latestOpen").textContent = formatPrice(candle.open);
  $("#latestHigh").textContent = formatPrice(candle.high);
  $("#latestLow").textContent = formatPrice(candle.low);
  $("#latestCloseSmall").textContent = formatPrice(candle.close);
}

function renderFoundationSummary() {
  const datasets = TIMEFRAMES.map((item) => marketStates[item.interval]).filter(Boolean);
  const ready = TIMEFRAMES.filter((item) => historicalReady[item.interval]).length;
  const active = TIMEFRAMES.filter((item) => Boolean(activeBackfillJobIds[item.interval])).length;
  const totalRows = datasets.reduce((sum, data) => sum + Number(data.state?.rows_in_database || data.state?.rows_processed || 0), 0);
  const totalReview = datasets.reduce((sum, data) => sum + Number(data.gaps?.review || 0), 0);
  const averageProgress = TIMEFRAMES.reduce((sum, item) => {
    const data = marketStates[item.interval];
    return sum + Number(data?.historical_progress_percent ?? data?.state?.progress_percent ?? 0);
  }, 0) / TIMEFRAMES.length;

  const pill = $("#foundationStatePill");
  if (ready === TIMEFRAMES.length) {
    pill.textContent = "COMPLETE";
    pill.className = "status-pill complete";
    $("#foundationMessage").textContent = "All six timeframes are stored and ready for continuous synchronisation.";
  } else if (active > 0) {
    pill.textContent = "DOWNLOADING";
    pill.className = "status-pill downloading";
    $("#foundationMessage").textContent = `${active} historical dataset${active === 1 ? " is" : "s are"} queued or downloading. Railway processes the queue one job at a time.`;
  } else {
    pill.textContent = "BUILDING";
    pill.className = "status-pill queued";
    $("#foundationMessage").textContent = `${ready} of ${TIMEFRAMES.length} datasets are complete. Queue the remaining history to finish the foundation.`;
  }

  $("#foundationProgressValue").textContent = `${Math.min(100, averageProgress).toFixed(0)}%`;
  $("#foundationProgressRing").style.setProperty("--progress", Math.min(100, averageProgress));
  $("#foundationProgressBar").style.width = `${Math.min(100, averageProgress)}%`;
  $("#totalCandleCount").textContent = formatNumber(totalRows);
  $("#datasetsReadyCount").textContent = `${ready} / ${TIMEFRAMES.length}`;
  $("#activeDownloadCount").textContent = formatNumber(active);
  $("#totalGapCount").textContent = formatNumber(totalReview);
  $("#queueAllHistory").disabled = ready === TIMEFRAMES.length || batchActionRunning;
  $("#queueAllHistory").textContent = ready === TIMEFRAMES.length ? "All history is stored" : "Queue all missing history";
  $("#syncAllFrames").disabled = batchActionRunning;
  $("#scanAllFrames").disabled = batchActionRunning || totalRows < 2;
  updateBacktestAvailability();
}

async function refreshMarketStatus(meta, silent = false) {
  try {
    const payload = await api(`status?symbol=XAU%2FUSD&interval=${encodeURIComponent(meta.interval)}`);
    const data = payload.data || {};
    renderTimeframeDashboard(meta, data);
    if (meta.interval === "5min") {
      renderM5Live(data);
      renderEvents(data.events || []);
      setService(true, "Online");
    }
  } catch (error) {
    marketStates[meta.interval] = null;
    const messageNode = $(`#tf-${meta.key}-message`);
    if (messageNode) messageNode.textContent = error.message;
    if (meta.interval === "5min") setService(false, "Setup needed");
    if (!silent) showToast(error.message, true);
  }
}

async function refreshDashboard(silent = false) {
  await Promise.all(TIMEFRAMES.map((meta) => refreshMarketStatus(meta, silent || meta.interval !== "5min")));
  renderFoundationSummary();
}

async function queueJob(endpoint, interval, button = null, successText = "Job queued") {
  const meta = TIMEFRAMES.find((item) => item.interval === interval);
  const original = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "Queuing…";
  }
  try {
    const payload = await api(`jobs/${endpoint}`, {
      method: "POST",
      body: JSON.stringify({ symbol: "XAU/USD", interval, force_restart: false }),
    });
    showToast(payload.message || successText);
    await refreshDashboard(true);
    return true;
  } catch (error) {
    showToast(error.message, true);
    return false;
  } finally {
    if (button && original) button.textContent = original;
    if (meta && marketStates[interval]) renderTimeframeDashboard(meta, marketStates[interval]);
  }
}

async function pauseBackfill(interval, button) {
  const jobId = activeBackfillJobIds[interval];
  if (!jobId) return;
  const meta = TIMEFRAMES.find((item) => item.interval === interval);
  button.disabled = true;
  button.textContent = "Pausing…";
  try {
    const payload = await api(`jobs/${jobId}/cancel`, { method: "POST", body: "{}" });
    showToast(payload.message || "Pause requested");
    await refreshDashboard(true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.textContent = `Pause ${meta?.label || "download"}`;
  }
}

async function queueAllMissingHistory(button) {
  if (batchActionRunning) return;
  batchActionRunning = true;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Queuing history…";
  let queued = 0;
  const errors = [];
  try {
    for (const meta of TIMEFRAMES) {
      if (historicalReady[meta.interval] || activeBackfillJobIds[meta.interval]) continue;
      try {
        await api("jobs/backfill", {
          method: "POST",
          body: JSON.stringify({ symbol: "XAU/USD", interval: meta.interval, force_restart: false }),
        });
        queued += 1;
      } catch (error) {
        errors.push(`${meta.label}: ${error.message}`);
      }
    }
    if (queued > 0) showToast(`${queued} historical download${queued === 1 ? "" : "s"} queued. Railway will process them one at a time.`);
    else if (!errors.length) showToast("Every available timeframe is already complete or queued.");
    if (errors.length) showToast(`Queued ${queued}. ${errors.join(" | ")}`, true);
    await refreshDashboard(true);
  } finally {
    batchActionRunning = false;
    button.textContent = original;
    renderFoundationSummary();
    TIMEFRAMES.forEach((meta) => marketStates[meta.interval] && renderTimeframeDashboard(meta, marketStates[meta.interval]));
  }
}

async function queueBatchJobs(endpoint, button, label) {
  if (batchActionRunning) return;
  batchActionRunning = true;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = `${label}…`;
  let queued = 0;
  const errors = [];
  try {
    for (const meta of TIMEFRAMES) {
      const data = marketStates[meta.interval];
      const rows = Number(data?.state?.rows_in_database || data?.state?.rows_processed || 0);
      if (!data || activeBackfillJobIds[meta.interval]) continue;
      if (endpoint === "gap-scan" && rows < 2) continue;
      try {
        await api(`jobs/${endpoint}`, {
          method: "POST",
          body: JSON.stringify({ symbol: "XAU/USD", interval: meta.interval, force_restart: false }),
        });
        queued += 1;
      } catch (error) {
        errors.push(`${meta.label}: ${error.message}`);
      }
    }
    if (queued > 0) showToast(`${queued} ${label.toLowerCase()} job${queued === 1 ? "" : "s"} queued.`);
    else if (!errors.length) showToast("No eligible datasets were available for this action.");
    if (errors.length) showToast(`Queued ${queued}. ${errors.join(" | ")}`, true);
    await refreshDashboard(true);
  } finally {
    batchActionRunning = false;
    button.textContent = original;
    renderFoundationSummary();
    TIMEFRAMES.forEach((meta) => marketStates[meta.interval] && renderTimeframeDashboard(meta, marketStates[meta.interval]));
  }
}

function updateBacktestAvailability() {
  const resolution = $("#resolutionMode")?.value || "candle";
  const ready = resolution === "m1_replay" ? historicalReady["1min"] : historicalReady["5min"];
  const button = $("#runBacktest");
  if (!button) return;
  button.disabled = !ready || Boolean(activeBacktestId);
  button.textContent = resolution === "m1_replay" ? "Run M1 high-resolution replay" : "Run M5 approximation";

  if (resolution === "m1_replay") {
    $("#resolutionNote").textContent = historicalReady["1min"]
      ? "M1 Market Memory is complete. This run uses every verified one-minute candle in sequence."
      : "M1 replay is locked until the M1 historical dataset reaches 100%.";
  } else {
    $("#resolutionNote").textContent = historicalReady["5min"]
      ? "M5 baseline uses the completed broad historical dataset and a candle-path approximation."
      : "M5 Market Memory must be complete before this run can start.";
  }
}


function topStatistic(rows, dimension, metric) {
  const candidates = rows.filter((row) => row.dimension === dimension && Number(row.sample_count || 0) > 0);
  if (!candidates.length) return null;
  return candidates.reduce((best, row) => Number(row[metric] || 0) > Number(best[metric] || 0) ? row : best, candidates[0]);
}

function renderResearchQuestions(questions = []) {
  const host = $("#researchQuestionList");
  $("#questionCountBadge").textContent = formatNumber(questions.length);
  if (!questions.length) {
    host.innerHTML = '<div class="empty-state">Questions will appear after the first learning build.</div>';
    return;
  }
  host.innerHTML = questions.map((question) => {
    const status = String(question.status || "queued").toUpperCase();
    const evidence = question.sample_count == null
      ? `PRIORITY ${formatNumber(question.priority)}`
      : `${formatNumber(question.sample_count)} TEST · ${question.confidence_score == null ? "UNSCORED" : `${Number(question.confidence_score).toFixed(0)}%`}`;
    return `
      <div class="research-item">
        <div class="research-item-head"><small>${escapeHtml(status)} · ${escapeHtml(String(question.category || "research").toUpperCase())}</small><span class="score">${escapeHtml(evidence)}</span></div>
        <strong>${escapeHtml(question.question || "Untitled research question")}</strong>
        <p>${escapeHtml(question.rationale || "Waiting for formal testing.")}</p>
      </div>`;
  }).join("");
}

function renderDiscoveries(discoveries = []) {
  const host = $("#discoveryList");
  $("#discoveryCountBadge").textContent = formatNumber(discoveries.length);
  if (!discoveries.length) {
    host.innerHTML = '<div class="empty-state">Exploratory findings will appear here.</div>';
    return;
  }
  host.innerHTML = discoveries.map((item) => `
    <div class="research-item ${escapeHtml(String(item.status || "exploratory"))}">
      <div class="research-item-head"><small>${escapeHtml(String(item.status || "exploratory").toUpperCase())}</small><span class="score">${item.confidence_score == null ? "UNSCORED" : `${Number(item.confidence_score).toFixed(0)}% CONFIDENCE`}</span></div>
      <strong>${escapeHtml(item.title || "Untitled observation")}</strong>
      <p>${escapeHtml(item.summary || "Awaiting validation.")}</p>
    </div>
  `).join("");
}

function setCalendarInsight(nameId, metaId, row, metric, suffix) {
  if (!row) {
    $(nameId).textContent = "—";
    $(metaId).textContent = "Build learning first";
    return;
  }
  $(nameId).textContent = row.bucket_label || row.bucket_key || "—";
  const value = Number(row[metric] || 0);
  $(metaId).textContent = `${value.toFixed(metric === "directional_day_rate" ? 1 : 2)}${suffix} · ${formatNumber(row.sample_count)} days`;
}

function renderResearchReport(reports = []) {
  const report = reports[0] || null;
  if (!report) {
    $("#researchReportTitle").textContent = "Waiting for first cycle";
    $("#researchReportStatus").textContent = "WAITING";
    $("#researchReportStatus").className = "status-pill";
    $("#researchReportSummary").textContent = "Historical research runs continuously. Market hours do not control or pause it.";
    $("#reportQuestionsTested").textContent = "0";
    $("#reportQuestionsRejected").textContent = "0";
    $("#reportPromising").textContent = "0";
    $("#reportValidated").textContent = "0";
    return;
  }
  $("#researchReportTitle").textContent = `Research report · ${formatDate(report.report_date)}`;
  $("#researchReportStatus").textContent = "COMPLETE";
  $("#researchReportStatus").className = "status-pill complete";
  $("#researchReportSummary").textContent = report.summary || "Autonomous research cycle complete.";
  $("#reportQuestionsTested").textContent = formatNumber(report.questions_tested);
  $("#reportQuestionsRejected").textContent = formatNumber(report.questions_rejected);
  $("#reportPromising").textContent = formatNumber(report.discoveries_promising);
  $("#reportValidated").textContent = formatNumber(report.discoveries_validated);
}

function renderHistoricalResearch(payload = {}) {
  const state = payload.state || {};
  const current = payload.current_job || {};
  const latest = payload.latest_job || {};
  const heartbeatTime = state.heartbeat_at ? new Date(state.heartbeat_at).getTime() : 0;
  const heartbeatFresh = heartbeatTime > 0 && (Date.now() - heartbeatTime) < 5 * 60 * 1000;
  const rawStatus = String(state.status || "waiting");
  const status = state.last_error ? "error" : (heartbeatFresh ? rawStatus : (heartbeatTime ? "waiting" : rawStatus));
  const displayStatus = heartbeatFresh && ["active", "loading", "researching"].includes(rawStatus) ? "ACTIVE" : status.toUpperCase();

  $("#historyResearchStatus").textContent = displayStatus;
  $("#historyResearchStatus").className = `status-pill ${heartbeatFresh ? rawStatus : status}`;
  $("#historyResearchHeartbeat").textContent = formatDate(state.heartbeat_at, true);
  $("#historyResearchQueue").textContent = formatNumber(state.queue_count);
  $("#historyResearchCompleted").textContent = formatNumber(state.completed_count);
  $("#historyResearchRowsScanned").textContent = formatNumber(state.rows_scanned_total);
  $("#historyResearchRejected").textContent = formatNumber(state.rejected_count);
  $("#historyResearchPromising").textContent = formatNumber(state.promising_count);
  $("#historyResearchValidated").textContent = formatNumber(state.validated_count);
  $("#historyResearchGeneration").textContent = formatNumber(state.generator_generation);
  $("#historyResearchCurrentQuestion").textContent = current.question || state.current_question || (heartbeatFresh
    ? "Worker is refilling or claiming the next historical question"
    : "Waiting for the Railway worker heartbeat");
  $("#historyResearchMessage").textContent = state.last_error || (heartbeatFresh
    ? "Dedicated historical research is running in parallel with live learning. It does not wait for the market to open or close."
    : "The worker has not reported a recent heartbeat yet. Railway may still be starting after deployment.");
  $("#historyResearchLastResult").textContent = state.last_result || latest.summary || "EVE will continuously generate, test and challenge historical questions.";
}

function renderLearning(data = {}) {
  learningDashboard = data;
  const state = data.state || {};
  const run = data.latest_run || {};
  const autonomousRun = data.latest_autonomous_run || {};
  const activeBuild = ["queued", "running"].includes(run.status);
  activeLearningRunId = activeBuild ? run.id : null;
  const autonomousEnabled = state.autonomous_learning_enabled !== false && state.initial_build_complete;
  const status = activeBuild ? run.status : (autonomousEnabled ? (state.autonomous_status || "active") : (state.status || "not_started"));
  const progress = Number(activeBuild ? run.progress_percent || 0 : (state.initial_build_complete ? 100 : 0));
  const stage = activeBuild ? run.stage || "queued" : (autonomousEnabled ? "autonomous learning" : (state.initial_build_complete ? "ready" : "not built"));

  $("#learningTitle").textContent = stage.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  $("#learningStatus").textContent = status.replaceAll("_", " ").toUpperCase();
  $("#learningStatus").className = `status-pill ${status}`;
  $("#learningProgress").textContent = `${Math.min(100, progress).toFixed(progress > 0 && progress < 10 ? 1 : 0)}%`;
  $("#learningProgressBar").style.width = `${Math.min(100, progress)}%`;
  $("#learningMessage").textContent = run.error || (activeBuild ? run.message : null) || state.last_auto_error || state.last_auto_message || state.last_error || (autonomousEnabled
    ? "Autonomous learning is active on Railway. No button press is required."
    : "Build the foundation once. Railway will then take over automatically.");

  $("#learningSnapshots").textContent = formatNumber(state.snapshots_count);
  $("#learningOutcomes").textContent = formatNumber(state.outcome_labels_count);
  $("#learningPendingOutcomes").textContent = formatNumber(state.pending_outcomes_count);
  $("#learningPredictionsGraded").textContent = formatNumber(state.graded_prediction_count);
  $("#learningQuestionsTested").textContent = formatNumber(state.questions_tested_total);
  $("#learningValidatedDiscoveries").textContent = formatNumber(state.discoveries_validated_count);
  $("#learningLatest").textContent = formatDate(state.last_snapshot_time, true);
  $("#learningAutoUpdate").textContent = autonomousEnabled ? "ACTIVE" : "After first build";

  $("#autonomyStatus").textContent = autonomousEnabled ? String(state.autonomous_status || "active").replaceAll("_", " ").toUpperCase() : "WAITING";
  $("#autonomyLastCycle").textContent = formatDate(state.last_auto_cycle_at || autonomousRun.started_at, true);
  $("#autonomyNextCycle").textContent = formatDate(state.next_auto_cycle_at, true);
  $("#autonomyLastResearch").textContent = formatDate(state.last_research_cycle_at, true);

  const foundationReady = TIMEFRAMES.every((item) => historicalReady[item.interval]);
  const build = $("#buildLearning");
  if (state.initial_build_complete) {
    build.hidden = true;
  } else {
    build.hidden = false;
    build.disabled = activeBuild || !foundationReady;
    if (!foundationReady) build.textContent = "Finish data foundation first";
    else if (activeBuild) build.textContent = "Learning build in progress…";
    else build.textContent = "Build initial learning foundation";
  }

  const runNow = $("#runAutonomyNow");
  runNow.disabled = !autonomousEnabled || autonomousRun.status === "running";
  runNow.textContent = autonomousRun.status === "running" ? "Autonomous cycle running…" : "Run diagnostic cycle now";

  const cancel = $("#cancelLearning");
  cancel.hidden = !activeBuild;
  cancel.disabled = !activeBuild;

  const calendarRows = data.calendar_statistics || [];
  const topRangeWeekday = topStatistic(calendarRows, "weekday", "average_range_pct");
  const topDirectionalWeekday = topStatistic(calendarRows, "weekday", "directional_day_rate");
  const topRangeMonth = topStatistic(calendarRows, "month", "average_range_pct");
  const topDirectionalMonth = topStatistic(calendarRows, "month", "directional_day_rate");
  setCalendarInsight("#topRangeWeekday", "#topRangeWeekdayMeta", topRangeWeekday, "average_range_pct", "% daily range");
  setCalendarInsight("#topDirectionalWeekday", "#topDirectionalWeekdayMeta", topDirectionalWeekday, "directional_day_rate", "% directional");
  setCalendarInsight("#topRangeMonth", "#topRangeMonthMeta", topRangeMonth, "average_range_pct", "% daily range");
  setCalendarInsight("#topDirectionalMonth", "#topDirectionalMonthMeta", topDirectionalMonth, "directional_day_rate", "% directional");
  $("#calendarStatus").textContent = calendarRows.length ? "READY" : "WAITING";
  $("#calendarStatus").className = `status-pill ${calendarRows.length ? "complete" : ""}`;

  const approved = data.approved_model || {};
  const challenger = data.challenger_model || {};
  $("#approvedModelName").textContent = approved.name || "EVE Statistical Baseline";
  $("#approvedModelVersion").textContent = approved.version ? `Version ${approved.version}` : "Version 1.0";
  $("#approvedModelNotes").textContent = approved.notes || "The trusted baseline used to judge future models.";
  $("#challengerModelName").textContent = challenger.name || "Waiting for first autonomous training cycle";
  $("#challengerModelVersion").textContent = challenger.version ? `Version ${challenger.version}` : "Railway trains challengers automatically";
  $("#challengerModelNotes").textContent = challenger.promotion_reason || challenger.notes || "A challenger will never replace the approved model unless it wins on chronological unseen data.";

  renderResearchQuestions(data.questions || []);
  renderDiscoveries(data.discoveries || []);
  renderResearchReport(data.research_reports || []);
  renderHistoricalResearch(data.historical_research || {});
}

async function refreshLearning(silent = false) {
  try {
    const payload = await api("learning/status?symbol=XAU%2FUSD");
    renderLearning(payload.data || {});
  } catch (error) {
    if (!silent) showToast(error.message, true);
    $("#learningMessage").textContent = error.message;
  }
}

async function buildLearning(button) {
  button.disabled = true;
  button.textContent = "Queuing…";
  try {
    const payload = await api("learning/build", {
      method: "POST",
      body: JSON.stringify({ symbol: "XAU/USD", full_rebuild: false }),
    });
    activeLearningRunId = payload.data.id;
    showToast(payload.message || "Learning foundation queued");
    await refreshLearning(true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    if (learningDashboard) renderLearning(learningDashboard);
  }
}

async function runAutonomyNow(button) {
  button.disabled = true;
  button.textContent = "Requesting cycle…";
  try {
    const payload = await api("autonomy/run", { method: "POST", body: "{}" });
    showToast(payload.message || "Autonomous cycle requested");
    await refreshLearning(true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Run diagnostic cycle now";
  }
}

async function cancelLearning(button) {
  if (!activeLearningRunId) return;
  button.disabled = true;
  button.textContent = "Cancelling…";
  try {
    const payload = await api(`learning/runs/${activeLearningRunId}/cancel`, { method: "POST", body: "{}" });
    showToast(payload.message || "Learning cancellation requested");
    await refreshLearning(true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.textContent = "Cancel learning build";
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

$("#timeframeGrid").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action][data-interval]");
  if (!button) return;
  const interval = button.dataset.interval;
  const action = button.dataset.action;
  const meta = TIMEFRAMES.find((item) => item.interval === interval);
  if (action === "pause") await pauseBackfill(interval, button);
  else if (action === "backfill") await queueJob("backfill", interval, button, `${meta.label} historical download queued`);
  else if (action === "sync") await queueJob("sync", interval, button, `${meta.label} latest-candle sync queued`);
  else if (action === "gap-scan") await queueJob("gap-scan", interval, button, `${meta.label} gap scan queued`);
});

$("#queueAllHistory").addEventListener("click", (event) => queueAllMissingHistory(event.currentTarget));
$("#syncAllFrames").addEventListener("click", (event) => queueBatchJobs("sync", event.currentTarget, "Syncing"));
$("#scanAllFrames").addEventListener("click", (event) => queueBatchJobs("gap-scan", event.currentTarget, "Scanning"));
$("#buildLearning").addEventListener("click", (event) => buildLearning(event.currentTarget));
$("#runAutonomyNow").addEventListener("click", (event) => runAutonomyNow(event.currentTarget));
$("#cancelLearning").addEventListener("click", (event) => cancelLearning(event.currentTarget));
$("#refreshLearning").addEventListener("click", () => refreshLearning());
$("#resolutionMode").addEventListener("change", updateBacktestAvailability);
$("#runBacktest").addEventListener("click", (event) => runBacktest(event.currentTarget));
$("#cancelBacktest").addEventListener("click", (event) => cancelBacktest(event.currentTarget));
$("#refreshBacktest").addEventListener("click", () => refreshBacktests());
$("#refreshButton").addEventListener("click", async () => { await refreshDashboard(); await refreshLearning(true); await refreshBacktests(true); });

const navLinks = [...document.querySelectorAll(".nav-link")];
const sections = navLinks.map((link) => document.querySelector(link.getAttribute("href"))).filter(Boolean);
const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) navLinks.forEach((link) => link.classList.toggle("active", link.getAttribute("href") === `#${entry.target.id}`));
  });
}, { rootMargin: "-35% 0px -55%" });
sections.forEach((section) => observer.observe(section));

(async () => {
  createTimeframeCards();
  await refreshDashboard(true);
  await refreshLearning(true);
  await refreshBacktests(true);
})();
refreshTimer = setInterval(async () => {
  await refreshDashboard(true);
  await refreshLearning(true);
  await refreshBacktests(true);
}, 10_000);
