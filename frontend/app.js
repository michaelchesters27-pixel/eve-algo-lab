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

const LIQUIDITY_STRATEGIES = new Set(["liquidity_continuation", "liquidity_basket"]);
const isLiquidityStrategy = (strategy) => LIQUIDITY_STRATEGIES.has(strategy);
const isTrendStrategy = (strategy) => strategy === "gold_h4_trend";
const isLondonStrategy = (strategy) => strategy === "london_opening_range";
const isChronologicalStrategy = (strategy) => isTrendStrategy(strategy) || isLondonStrategy(strategy) || isLiquidityStrategy(strategy);
const isSinglePositionStrategy = (strategy) => isTrendStrategy(strategy) || isLondonStrategy(strategy);
const liquidityEntryModel = (strategy) => strategy === "liquidity_continuation" ? "breakout_continuation" : "sweep_reversal";
const liquidityStrategyName = (strategy) => strategy === "liquidity_continuation" ? "Liquidity Continuation v1" : "Liquidity Basket v1";

function setText(selector, value) {
  const node = $(selector);
  if (node) node.textContent = value == null ? "" : String(value);
}
function setClass(selector, value) {
  const node = $(selector);
  if (node) node.className = value;
}
function setWidth(selector, value) {
  const node = $(selector);
  if (node) node.style.width = value;
}
function setHtml(selector, value) {
  const node = $(selector);
  if (node) node.innerHTML = value;
}

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
let legacyBacktesterOpen = false;
let legacyBacktestHistoryOpen = false;
let legacyBacktestRuns = [];
let selectedLegacyBacktestId = null;
let backtestViewMode = "current";
let activeLearningRunId = null;
let learningDashboard = null;
let batchActionRunning = false;
let discoveryExplorerItems = [];
let discoveryExplorerFilter = "all";
let discoveryExplorerOrder = "confidence";
let selectedDiscoveryId = null;
let discoveryRefreshTimer;
let strategyLabDashboard = null;
let strategyCandidateItems = [];
let strategyCandidateFilter = "all";
let strategyCandidateOrder = "profit_factor";
let selectedStrategyCandidateId = null;
let strategyRefreshTimer;
let evolutionDashboard = null;
let evolutionCandidateItems = [];
let evolutionCandidateFilter = "all";
let evolutionCandidateOrder = "validation_improvement";
let selectedEvolutionCandidateId = null;
let evolutionRefreshTimer;
let validationDashboard = null;
let validationJobItems = [];
let validationJobFilter = "all";
let validationJobOrder = "profit_factor";
let selectedValidationJobId = null;
let validationRefreshTimer;
let mt5Dashboard = null;
let mt5PackageItems = [];
let mt5RefreshTimer;
let demoEligibilityDashboard = null;
let demoBotItems = [];
let botLibraryCategory = "all";
let botLibrarySearch = "";
let fleetDashboard = null;
let fleetRefreshTimer;
let currentWorkspace = "home";
let currentAppMode = localStorage.getItem("eve-app-mode") === "research" ? "research" : "operator";
let currentFactoryStage = "build";
let currentBotView = "organised";
let serviceOnline = false;
let demoRefreshTimer;
const activeBackfillJobIds = Object.fromEntries(TIMEFRAMES.map((item) => [item.interval, null]));
const historicalReady = Object.fromEntries(TIMEFRAMES.map((item) => [item.interval, false]));
const marketStates = Object.fromEntries(TIMEFRAMES.map((item) => [item.interval, null]));



function londonClockParts() {
  const formatter = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    weekday: "long",
    day: "numeric",
    month: "long",
    hour: "2-digit",
    hourCycle: "h23",
  });
  return Object.fromEntries(formatter.formatToParts(new Date()).map((part) => [part.type, part.value]));
}

function setJourneyState(selector, state, detail) {
  const node = $(selector);
  if (!node) return;
  node.classList.remove("complete", "current", "pending", "attention");
  node.classList.add(state);
  if (detail) node.title = detail;
}

function homeStatusClass(status) {
  if (status === "attached") return "complete";
  if (status === "visibility_required") return "error";
  if (status === "active_now") return "test-now";
  if (status === "attach_now_waiting_market_condition") return "attach-leave";
  if (status === "waiting_for_trading_window") return "wait-time";
  if (status === "waiting_for_period") return "wait-period";
  if (status === "market_closed") return "market-closed";
  return "waiting";
}

function updateCommandCentre() {
  const clock = londonClockParts();
  const hour = Number(clock.hour || 12);
  const greeting = hour < 12 ? "Good morning." : hour < 18 ? "Good afternoon." : "Good evening.";
  setText("#briefingGreeting", greeting);
  setText("#briefingDate", `${clock.weekday || "Today"} ${clock.day || ""} ${clock.month || ""}`.trim().toUpperCase());

  const learningState = learningDashboard?.state || {};
  const strategyState = strategyLabDashboard?.state || {};
  const evolutionState = evolutionDashboard?.state || {};
  const validationState = validationDashboard?.state || {};
  const mt5State = mt5Dashboard?.state || {};
  const demo = demoEligibilityDashboard || {};
  const recommended = demo.recommended || {};
  const readyDatasets = TIMEFRAMES.filter((item) => historicalReady[item.interval]).length;
  const latestM5 = marketStates["5min"]?.latest_candle || {};

  const researchTests = Number(learningState.questions_tested_total || 0);
  const strategiesTested = Number(strategyState.completed_count || 0);
  const mt5Ready = Number(validationState.mt5_ready_count || 0);
  const botsGenerated = Number(mt5State.generated_count || mt5PackageItems.length || 0);
  const fleetCounts = fleetDashboard?.counts || {};
  const fleetOnline = Number(fleetCounts.online || 0);

  setText("#homeResearchCount", formatNumber(researchTests));
  setText("#homeStrategyCount", formatNumber(strategiesTested));
  setText("#homeValidatedCount", formatNumber(mt5Ready));
  setText("#homeBotCount", formatNumber(botsGenerated));
  setText("#homeFleetCount", formatNumber(fleetOnline));
  setText("#homeFleetState", !fleetDashboard ? "Checking heartbeats" : fleetDashboard?.setup_required ? "One-time setup required" : fleetOnline ? `${formatNumber(fleetCounts.in_trade || 0)} currently in trade` : "0 visible; old EAs may still be attached");
  setText("#homeResearchState", learningState.autonomous_learning_enabled !== false && learningState.initial_build_complete ? "Working automatically" : "Foundation check");
  setText("#homeStrategyState", strategiesTested ? `${formatNumber(Number(strategyState.validated_count || 0) + Number(strategyState.elite_count || 0))} strong survivors` : "Waiting for evidence");
  setText("#homeProofState", mt5Ready ? "Rules frozen for bots" : "No rules frozen yet");
  setText("#homeBotState", botsGenerated ? "Available in Bot Library" : "Waiting for proof");

  const recommendedPresence = fleetPresenceForPackage(recommended.package_id);
  const recommendedAttached = recommendedPresence.count > 0;
  const fleetLoaded = fleetDashboard !== null;
  const fleetItems = Array.isArray(fleetDashboard?.items) ? fleetDashboard.items : [];
  const fleetKnownAttachments = fleetItems.length;
  const fleetVisibilityMissing = fleetLoaded && fleetOnline === 0;
  const visibilityCard = $("#homeFleetVisibility");
  if (visibilityCard) visibilityCard.hidden = !fleetVisibilityMissing;
  setText("#homeVisibleReportingCount", formatNumber(fleetOnline));

  let actionStatus = "waiting";
  let actionLabel = "CHECKING";
  let actionTitle = "Checking which bots EVE can see";
  let actionCopy = "EVE will not recommend another bot until the Demo Fleet check has completed.";
  let actionMeta = "No action yet.";
  let primaryHref = "#demo-fleet";
  let primaryLabel = "Open Demo Fleet";
  let secondaryHref = "#";
  let secondaryLabel = "No bot action";
  let secondaryEnabled = false;

  if (fleetVisibilityMissing) {
    actionStatus = "visibility_required";
    actionLabel = "CANNOT SEE MT5";
    actionTitle = "Do not attach another bot yet";
    actionCopy = "You may already have bots attached, but EVE is receiving zero fleet heartbeats. The dashboard cannot safely recommend another EA until it can see what is running.";
    actionMeta = "Your existing bots may be working correctly. Upgrade them to fleet-ready versions only when they have no open trade.";
    primaryHref = "#demo-fleet";
    primaryLabel = "Fix MT5 visibility";
    secondaryHref = "#bot-library?view=files";
    secondaryLabel = "Open Bot Factory";
    secondaryEnabled = true;
  } else if (recommendedAttached) {
    actionStatus = "attached";
    actionLabel = "RUNNING IN MT5";
    actionTitle = recommended.strategy_name || "Recommended bot";
    actionCopy = `${recommendedPresence.count} live attachment${recommendedPresence.count === 1 ? " is" : "s are"} already reporting. Do not attach another copy.`;
    actionMeta = "Open Demo Fleet to see its current state, chart, switches and demo P/L.";
    primaryHref = "#demo-fleet";
    primaryLabel = "Open Demo Fleet";
    secondaryHref = "#bot-library";
    secondaryLabel = "Open Bot Schedule";
    secondaryEnabled = true;
  } else if (fleetLoaded && recommended.package_id) {
    actionStatus = recommended.status || "waiting";
    actionLabel = recommended.status_label || "NEXT TEST";
    actionTitle = recommended.strategy_name || "Recommended bot";
    actionCopy = recommended.headline || recommended.next_action || "EVE has identified the next practical demo candidate.";
    actionMeta = recommended.next_action || `Attach to ${recommended.attach_to || "XAUUSD M5"}. Demo only.`;
    primaryHref = "#bot-library";
    primaryLabel = "Open Bot Schedule";
    secondaryHref = `/api/mt5/packages/${encodeURIComponent(recommended.package_id)}/download`;
    secondaryLabel = "Download recommended bot";
    secondaryEnabled = true;
  }

  setText("#homeActionStatus", actionLabel);
  setClass("#homeActionStatus", `status-pill ${homeStatusClass(actionStatus)}`);
  setText("#homeActionTitle", actionTitle);
  setText("#homeActionCopy", actionCopy);
  setText("#homeActionMeta", actionMeta);
  const actionCard = $("#homeActionCard");
  if (actionCard) actionCard.dataset.status = actionStatus;
  const primary = $("#homeActionPrimary");
  if (primary) { primary.href = primaryHref; primary.textContent = primaryLabel; }
  const download = $("#homeActionDownload");
  if (download) {
    download.href = secondaryEnabled ? secondaryHref : "#";
    download.textContent = secondaryLabel;
    download.toggleAttribute("aria-disabled", !secondaryEnabled);
    download.classList.toggle("disabled-link", !secondaryEnabled);
  }

  const activeAction = ["active_now", "attach_now_waiting_market_condition", "attached"].includes(actionStatus);
  const futureAction = ["waiting_for_trading_window", "waiting_for_period", "market_closed"].includes(actionStatus);
  if (!fleetLoaded) {
    setText("#briefingStatus", "CHECKING DEMO FLEET");
    setText("#briefingHeadline", "EVE is checking which MT5 bots it can actually see.");
    setText("#briefingCopy", "No new attachment recommendation will appear until that check is complete.");
  } else if (fleetVisibilityMissing) {
    setText("#briefingStatus", "MT5 VISIBILITY REQUIRED");
    setText("#briefingHeadline", "EVE cannot yet see the bots you already have attached.");
    setText("#briefingCopy", "Do not add another bot from this dashboard until Demo Fleet is receiving heartbeats. Your existing EAs may still be trading normally.");
  } else if (fleetOnline > 0) {
    const inTrade = Number(fleetCounts.in_trade || 0);
    setText("#briefingStatus", "DEMO FLEET LIVE");
    setText("#briefingHeadline", `${fleetOnline} bot${fleetOnline === 1 ? " is" : "s are"} attached and reporting to EVE.`);
    setText("#briefingCopy", inTrade ? `${inTrade} bot${inTrade === 1 ? " is" : "s are"} currently in a trade. Open Demo Fleet for exact status.` : "All visible bots are being monitored. Open Demo Fleet for their exact waiting reasons and results.");
  } else if (activeAction) {
    setText("#briefingStatus", "ACTION AVAILABLE");
    setText("#briefingHeadline", recommended.headline || `${actionTitle} can be prepared for demo testing.`);
    setText("#briefingCopy", actionMeta);
  } else if (futureAction && recommended.package_id) {
    setText("#briefingStatus", "NEXT TEST IDENTIFIED");
    setText("#briefingHeadline", recommended.headline || `${actionTitle} is the next practical bot to test.`);
    setText("#briefingCopy", actionMeta);
  } else {
    setText("#briefingStatus", "EVE IS WORKING");
    setText("#briefingHeadline", "EVE is researching, testing and building in the background.");
    setText("#briefingCopy", botsGenerated ? `${formatNumber(botsGenerated)} MT5 bot package${botsGenerated === 1 ? " is" : "s are"} available. Bot Schedule explains exactly when each one is for.` : "No intervention is required while the autonomous workers continue.");
  }

  const allDataReady = readyDatasets === TIMEFRAMES.length;
  setText("#homeDataHealth", allDataReady ? "All 6 datasets ready" : `${readyDatasets} of ${TIMEFRAMES.length} datasets ready`);
  setText("#homeRailwayHealth", serviceOnline ? "Online and responding" : "Needs attention");
  setText("#homeMarketHealth", latestM5.candle_time ? `M5 stored ${formatDate(latestM5.candle_time, true)}` : "No stored M5 candle yet");
  setText("#homeLastUpdate", new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/London" }).format(new Date()));
  const healthy = serviceOnline && readyDatasets >= 5;
  setText("#homeOverallHealth", healthy ? "RUNNING" : serviceOnline ? "BUILDING" : "CHECK");
  setClass("#homeOverallHealth", `status-pill ${healthy ? "complete" : serviceOnline ? "queued" : "error"}`);

  const learningActive = learningState.initial_build_complete;
  const strategiesActive = strategiesTested > 0 || ["active", "testing", "generating"].includes(strategyState.status);
  const evolutionActive = Number(evolutionState.completed_count || 0) > 0 || Number(evolutionState.lineages_total || 0) > 0;
  const proofActive = mt5Ready > 0 || Number(validationState.replay_validated_count || 0) > 0;
  const botActive = botsGenerated > 0;
  setJourneyState("#journeyResearch", learningActive ? "complete" : "current", learningActive ? "Autonomous research is active" : "Research foundation is still building");
  setJourneyState("#journeyBuild", strategiesActive ? "complete" : learningActive ? "current" : "pending", `${formatNumber(strategiesTested)} strategies tested`);
  setJourneyState("#journeyImprove", evolutionActive ? "complete" : strategiesActive ? "current" : "pending", `${formatNumber(evolutionState.completed_count || 0)} mutations tested`);
  setJourneyState("#journeyProof", proofActive ? "complete" : evolutionActive ? "current" : "pending", `${formatNumber(mt5Ready)} strategies ready for MT5`);
  setJourneyState("#journeyBot", botActive ? "complete" : proofActive ? "current" : "pending", `${formatNumber(botsGenerated)} generated packages`);
  setJourneyState("#journeyDemo", activeAction ? "attention" : botActive ? "current" : "pending", recommended.status_label || "Waiting for a generated bot");
}

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
  serviceOnline = Boolean(online);
  $("#serviceStatus").textContent = label;
  $("#servicePulse").className = `pulse ${online ? "online" : "error"}`;
  updateCommandCentre();
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
  updateCommandCentre();
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
  const strategy = $("#testerStrategy")?.value || "gold_h4_trend";
  const resolution = $("#resolutionMode")?.value || "candle";
  const chronological = isChronologicalStrategy(strategy);
  const trend = isTrendStrategy(strategy);
  const london = isLondonStrategy(strategy);
  const requiredInterval = chronological || resolution === "m1_replay" ? "1min" : "5min";
  const ready = trend
    ? historicalReady["1min"] && historicalReady["4h"] && historicalReady["1day"]
    : historicalReady[requiredInterval];
  const button = $("#runBacktest");
  if (!button) return;
  button.disabled = !ready || Boolean(activeBacktestId);
  const segment = $("#testPeriod")?.value || "development";
  if (chronological) {
    const labels = { full: "Run full M1 test", development: "Run development test", untouched: "Run untouched test", custom: "Run custom M1 test" };
    button.textContent = labels[segment] || labels.full;
    $("#resolutionNote").textContent = ready
      ? (trend
        ? "M1, H4 and D1 Market Memory are ready. Signals use completed H4/D1 candles; entries, stops, costs, overnight financing and gaps use M1 replay."
        : (london
        ? "M1 Market Memory is ready. EVE reconstructs completed M5 candles, applies London daylight-saving time, sizes risk, and includes spread and commission."
        : "M1 Market Memory is ready. The signal candle must close before EVE enters at the next candle open. Costs and the zero-balance account stop are included."))
      : (trend ? "This test is locked until M1, H4 and D1 Market Memory all reach 100%." : "This test is locked until M1 Market Memory reaches 100%.");
  } else {
    button.textContent = resolution === "m1_replay" ? "Run Fixed Ladder M1 replay" : "Run Fixed Ladder M5 approximation";
    $("#resolutionNote").textContent = ready
      ? `${requiredInterval === "1min" ? "M1" : "M5"} Market Memory is ready for the legacy Fixed Ladder diagnostic.`
      : `${requiredInterval === "1min" ? "M1" : "M5"} Market Memory must be complete before this run can start.`;
  }
}

function updateTesterForm() {
  const strategy = $("#testerStrategy")?.value || "gold_h4_trend";
  const liquidity = isLiquidityStrategy(strategy);
  const trend = isTrendStrategy(strategy);
  const london = isLondonStrategy(strategy);
  const riskSized = trend || london;
  const chronological = isChronologicalStrategy(strategy);
  const continuation = strategy === "liquidity_continuation";
  document.querySelectorAll("[data-liquidity-field]").forEach((node) => { node.hidden = !liquidity; });
  document.querySelectorAll("[data-trend-field]").forEach((node) => { node.hidden = !trend; });
  document.querySelectorAll("[data-london-field]").forEach((node) => { node.hidden = !london; });
  document.querySelectorAll("[data-chronological-field]").forEach((node) => { node.hidden = !chronological; });
  document.querySelectorAll("[data-replay-field]").forEach((node) => { node.hidden = !chronological; });
  document.querySelectorAll("[data-non-london-field]").forEach((node) => { node.hidden = riskSized; });
  document.querySelectorAll("[data-fixed-field]").forEach((node) => { node.hidden = chronological; });
  const custom = chronological && ($("#testPeriod")?.value || "development") === "custom";
  document.querySelectorAll("[data-custom-date]").forEach((node) => { node.hidden = !custom; });
  setText("#testerFormTitle", trend ? "Gold H4 Trend 55/20 v1" : (london ? "London Opening Range v1" : (liquidity ? liquidityStrategyName(strategy) : "Fixed Ladder v2.61")));
  setText("#testerSourceName", trend
    ? "EVE Gold H4 Trend 55/20 v1 · H4/D1 signal / M1 replay"
    : (london ? "EVE London Opening Range v1 · M5 signal / M1 replay"
    : (liquidity ? `EVE ${liquidityStrategyName(strategy)} · Python M1 replay` : "EVE_Twelve_Data_Fixed_Ladder_v2.61.mq5")));
  setText("#testerSourceDetail", trend
    ? "60-day direction → 55-H4 breakout → first M1 open → 2 ATR stop → 20-H4 trailing exit"
    : (london ? "08:00–08:30 London range → confirmed M5 breakout → next M5 open → midpoint stop → 2R"
    : (liquidity
    ? (continuation
      ? "Close beyond prior liquidity → follow breakout at next open → four equal positions → combined-money exit"
      : "Sweep and close back inside → reverse at next open → four equal positions → combined-money exit")
    : "Source-verified legacy reconstruction · SHA-256 f033bc756b8a…d02da9")));
  setHtml("#testerRuleStrip", trend
    ? "<span>60-DAY DIRECTION</span><span>55-H4 BREAKOUT</span><span>FIRST M1 OPEN</span><span>0.25% RISK</span><span>2 ATR STOP</span><span>20-H4 EXIT</span>"
    : (london ? "<span>08:00–08:30 LONDON</span><span>M5 CLOSE CONFIRMS</span><span>NEXT M5 OPEN</span><span>0.25% RISK</span><span>MIDPOINT STOP</span><span>2R TARGET</span>"
    : (liquidity
    ? (continuation
      ? "<span>CLOSE BEYOND LIQUIDITY</span><span>FOLLOW BREAKOUT</span><span>ENTRY NEXT OPEN</span><span>4 EQUAL POSITIONS</span><span>ZERO-BALANCE STOP</span><span>COSTS INCLUDED</span>"
      : "<span>SWEEP + CLOSE INSIDE</span><span>FADE SWEEP</span><span>ENTRY NEXT OPEN</span><span>4 EQUAL POSITIONS</span><span>ZERO-BALANCE STOP</span><span>COSTS INCLUDED</span>")
    : "<span>8 BUY STOP</span><span>8 SELL STOP</span><span>3.000 SPACING</span><span>2.000 FALLBACK</span><span>0.750 FIRST CUT</span><span>BE +0.150 AT +1.500</span>")));
  setText("#minimumMoveLabel", continuation ? "Minimum close beyond level" : "Minimum sweep distance");
  if (liquidity && Number($("#fixedLot")?.value || 0) === 0.01) $("#fixedLot").value = "0.02";
  if (!liquidity && Number($("#fixedLot")?.value || 0) === 0.02) $("#fixedLot").value = "0.01";
  if (liquidity && Number($("#profitTarget")?.value || 0) === 5) $("#profitTarget").value = "4.00";
  if (!liquidity && Number($("#profitTarget")?.value || 0) === 4) $("#profitTarget").value = "5.00";
  if (riskSized && Number($("#startingBalance")?.value || 0) === 1000) $("#startingBalance").value = "10000";
  if (!riskSized && Number($("#startingBalance")?.value || 0) === 10000) $("#startingBalance").value = "1000";
  if (legacyBacktestRuns.length) renderComparison(legacyBacktestRuns);
  updateBacktestAvailability();
}


function topStatistic(rows, dimension, metric) {
  const candidates = rows.filter((row) => row.dimension === dimension && Number(row.sample_count || 0) > 0);
  if (!candidates.length) return null;
  return candidates.reduce((best, row) => Number(row[metric] || 0) > Number(best[metric] || 0) ? row : best, candidates[0]);
}

function renderResearchQuestions(questions = []) {
  const host = $("#researchQuestionList");
  setText("#questionCountBadge", formatNumber(questions.length));
  if (!host) return;
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
  setText("#discoveryCountBadge", formatNumber(discoveries.length));
  if (!host) return;
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
    setText(nameId, "—");
    setText(metaId, "Build learning first");
    return;
  }
  setText(nameId, row.bucket_label || row.bucket_key || "—");
  const value = Number(row[metric] || 0);
  setText(metaId, `${value.toFixed(metric === "directional_day_rate" ? 1 : 2)}${suffix} · ${formatNumber(row.sample_count)} days`);
}

function renderResearchReport(reports = []) {
  const report = reports[0] || null;
  if (!report) {
    setText("#researchReportTitle", "Waiting for first cycle");
    setText("#researchReportStatus", "WAITING");
    setClass("#researchReportStatus", "status-pill");
    setText("#researchReportSummary", "Historical research runs continuously. Market hours do not control or pause it.");
    setText("#reportQuestionsTested", "0");
    setText("#reportQuestionsRejected", "0");
    setText("#reportPromising", "0");
    setText("#reportValidated", "0");
    return;
  }
  setText("#researchReportTitle", `Research report · ${formatDate(report.report_date)}`);
  setText("#researchReportStatus", "COMPLETE");
  setClass("#researchReportStatus", "status-pill complete");
  setText("#researchReportSummary", report.summary || "Autonomous research cycle complete.");
  setText("#reportQuestionsTested", formatNumber(report.questions_tested));
  setText("#reportQuestionsRejected", formatNumber(report.questions_rejected));
  setText("#reportPromising", formatNumber(report.discoveries_promising));
  setText("#reportValidated", formatNumber(report.discoveries_validated));
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

  setText("#historyResearchStatus", displayStatus);
  setClass("#historyResearchStatus", `status-pill ${heartbeatFresh ? rawStatus : status}`);
  setText("#historyResearchHeartbeat", formatDate(state.heartbeat_at, true));
  setText("#historyResearchQueue", formatNumber(state.queue_count));
  setText("#historyResearchCompleted", formatNumber(state.completed_count));
  setText("#historyResearchRowsScanned", formatNumber(state.rows_scanned_total));
  setText("#historyResearchRejected", formatNumber(state.rejected_count));
  setText("#historyResearchPromising", formatNumber(state.promising_count));
  setText("#historyResearchValidated", formatNumber(state.validated_count));
  setText("#historyResearchGeneration", formatNumber(state.generator_generation));
  setText("#historyResearchCurrentQuestion", current.question || state.current_question || (heartbeatFresh
    ? "Worker is refilling or claiming the next historical question"
    : "Waiting for the Railway worker heartbeat"));
  setText("#historyResearchMessage", state.last_error || (heartbeatFresh
    ? "Dedicated historical research is running in parallel with live learning. It does not wait for the market to open or close."
    : "The worker has not reported a recent heartbeat yet. Railway may still be starting after deployment."));
  setText("#historyResearchLastResult", state.last_result || latest.summary || "EVE will continuously generate, test and challenge historical questions.");

  setText("#explorerTestedCount", formatNumber(state.completed_count));
  setText("#explorerRejectedCount", formatNumber(state.rejected_count));
  setText("#explorerPromisingCount", formatNumber(state.promising_count));
  setText("#explorerValidatedCount", formatNumber(state.validated_count));
}

const WEEKDAY_LABELS = { 1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday" };
const MONTH_LABELS = { 1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June", 7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December" };

function humaniseToken(value) {
  return String(value ?? "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function conditionLabel(condition = {}) {
  const field = String(condition.field || "condition");
  const value = condition.value;
  if (field === "weekday") return WEEKDAY_LABELS[value] || `Weekday ${value}`;
  if (field === "month") return MONTH_LABELS[value] || `Month ${value}`;
  if (field === "hour_utc") return `${String(value).padStart(2, "0")}:00 UTC`;
  if (field === "quarter") return `Quarter ${value}`;
  if (field === "week_of_month") return `Week ${value} of month`;
  if (field === "direction") return Number(value) > 0 ? "Bullish M5 candle" : Number(value) < 0 ? "Bearish M5 candle" : "Neutral M5 candle";
  return `${humaniseToken(field)}: ${humaniseToken(value)}`;
}

function metricUnit(item) {
  const metric = String(item.evidence?.metric || item.test_definition?.metric || "");
  return ["continuation", "same_direction", "alignment_follow", "up_probability"].includes(metric) ? "pp" : "%";
}

function formatEffect(item, value = item.effect_size) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)} ${metricUnit(item)}`;
}

function resultExplanation(item) {
  const status = String(item.result_status || "rejected");
  const evidence = item.evidence || {};
  if (status === "validated") {
    return "Validated: the effect remained strong in the locked unseen period, agreed with validation direction, stayed reasonably stable by year and cleared EVE's multiple-testing confidence threshold.";
  }
  if (status === "promising") {
    return "Promising: the result survived the basic unseen-data and stability checks, but it was not strong or stable enough to be called validated yet.";
  }
  const reasons = [];
  const metric = String(evidence.metric || item.test_definition?.metric || "");
  const rateMetric = ["continuation", "same_direction", "alignment_follow", "up_probability"].includes(metric);
  if (Number(item.sample_count || 0) < 60) reasons.push("the locked-test sample was below 60");
  if (evidence.direction_consistent === false) reasons.push("validation and locked-test effects pointed in different directions");
  if (Math.abs(Number(item.effect_size || 0)) < (rateMetric ? 3 : 6)) reasons.push("the measured effect was too small");
  if (Number(item.stability_score || 0) < 55) reasons.push("year-by-year stability was too weak");
  if (Number(item.confidence_score || 0) < 62) reasons.push("confidence remained below EVE's minimum threshold after the multiple-testing penalty");
  return `Rejected: ${reasons.length ? reasons.join("; ") : "the combined validation safeguards were not met"}.`;
}

function renderDiscoveryDetail(item) {
  const host = $("#discoveryDetail");
  if (!host) return;
  if (!item) {
    host.innerHTML = '<div class="discovery-detail-empty"><small>SELECT A FINDING</small><strong>Click any result to inspect the evidence</strong><p>You will see its sample size, locked-test effect, stability, conditions and why it was validated, marked promising or rejected.</p></div>';
    return;
  }
  const evidence = item.evidence || {};
  const definition = item.test_definition || {};
  const conditions = evidence.conditions || definition.conditions || [];
  const split = evidence.chronological_split || {};
  const horizon = evidence.horizon_minutes || definition.horizon_minutes || "—";
  const metric = humaniseToken(evidence.metric || definition.metric || "unknown metric");
  host.innerHTML = `
    <small class="discovery-detail-label">${escapeHtml(String(item.result_status || "result").toUpperCase())} · GENERATION ${formatNumber(item.generation)}</small>
    <h3>${escapeHtml(item.question || "Historical research result")}</h3>
    <p class="discovery-detail-summary">${escapeHtml(item.summary || "No summary stored.")}</p>
    <div class="discovery-verdict">${escapeHtml(resultExplanation(item))}</div>
    <div class="discovery-detail-metrics">
      <div><small>LOCKED EFFECT</small><strong>${escapeHtml(formatEffect(item))}</strong></div>
      <div><small>CONFIDENCE</small><strong>${item.confidence_score == null ? "—" : `${Number(item.confidence_score).toFixed(1)}%`}</strong></div>
      <div><small>YEAR STABILITY</small><strong>${item.stability_score == null ? "—" : `${Number(item.stability_score).toFixed(1)}%`}</strong></div>
      <div><small>LOCKED SAMPLE</small><strong>${formatNumber(item.sample_count)}</strong></div>
      <div><small>STATES SCANNED</small><strong>${formatNumber(item.rows_scanned)}</strong></div>
      <div><small>HORIZON</small><strong>${Number.isFinite(Number(horizon)) ? `${formatNumber(horizon)} MIN` : "—"}</strong></div>
    </div>
    <div class="discovery-subsection"><small>CONDITIONS TESTED</small><div class="condition-chip-list">${conditions.length ? conditions.map((condition) => `<span class="condition-chip">${escapeHtml(conditionLabel(condition))}</span>`).join("") : '<span class="condition-chip">No additional condition</span>'}</div></div>
    <div class="discovery-subsection"><small>TEST EVIDENCE</small><div class="evidence-list">
      <div class="evidence-row"><span>Metric</span><strong>${escapeHtml(metric)}</strong></div>
      <div class="evidence-row"><span>Validation effect</span><strong>${escapeHtml(formatEffect(item, evidence.validation_effect))}</strong></div>
      <div class="evidence-row"><span>Locked-test effect</span><strong>${escapeHtml(formatEffect(item, evidence.locked_test_effect ?? item.effect_size))}</strong></div>
      <div class="evidence-row"><span>Direction agreed</span><strong>${evidence.direction_consistent === false ? "NO" : "YES"}</strong></div>
      <div class="evidence-row"><span>Chronological split</span><strong>${formatNumber(split.train)} / ${formatNumber(split.validation)} / ${formatNumber(split.test)}</strong></div>
      <div class="evidence-row"><span>Multiple-testing penalty</span><strong>${evidence.multiple_testing_penalty_applied ? "APPLIED" : "NOT RECORDED"}</strong></div>
      <div class="evidence-row"><span>Tests considered</span><strong>${formatNumber(evidence.tests_considered)}</strong></div>
      <div class="evidence-row"><span>Finished</span><strong>${escapeHtml(formatDate(item.finished_at, true))}</strong></div>
    </div></div>
    <p class="discovery-warning">This is historical research evidence, not an instruction to enter a trade. A validated statistical tendency can still fail in any individual market event.</p>`;
}

function renderDiscoveryExplorer(items = []) {
  discoveryExplorerItems = items;
  const host = $("#discoveryExplorerList");
  if (!host) return;
  if (!items.length) {
    host.innerHTML = `<div class="empty-state">No ${escapeHtml(discoveryExplorerFilter === "all" ? "completed" : discoveryExplorerFilter)} results are available yet.</div>`;
    renderDiscoveryDetail(null);
    return;
  }
  if (!selectedDiscoveryId || !items.some((item) => item.id === selectedDiscoveryId)) selectedDiscoveryId = items[0].id;
  host.innerHTML = items.map((item) => `
    <button class="discovery-result-card ${escapeHtml(String(item.result_status || "rejected"))} ${item.id === selectedDiscoveryId ? "selected" : ""}" type="button" data-discovery-id="${escapeHtml(item.id)}">
      <div class="discovery-result-head"><span class="discovery-result-status">${escapeHtml(String(item.result_status || "rejected").toUpperCase())}</span><span class="discovery-result-date">${escapeHtml(formatDate(item.finished_at))}</span></div>
      <h3>${escapeHtml(item.question || "Historical research result")}</h3>
      <p>${escapeHtml(item.summary || resultExplanation(item))}</p>
      <div class="discovery-result-metrics">
        <span><small>SAMPLE</small><strong>${formatNumber(item.sample_count)}</strong></span>
        <span><small>EFFECT</small><strong>${escapeHtml(formatEffect(item))}</strong></span>
        <span><small>CONFIDENCE</small><strong>${item.confidence_score == null ? "—" : `${Number(item.confidence_score).toFixed(0)}%`}</strong></span>
        <span><small>STABILITY</small><strong>${item.stability_score == null ? "—" : `${Number(item.stability_score).toFixed(0)}%`}</strong></span>
      </div>
    </button>`).join("");
  renderDiscoveryDetail(items.find((item) => item.id === selectedDiscoveryId) || items[0]);
}

async function refreshDiscoveryExplorer(silent = false) {
  setText("#discoveryExplorerStatus", "LOADING");
  setClass("#discoveryExplorerStatus", "status-pill loading");
  try {
    const payload = await api(`research/results?symbol=XAU%2FUSD&result_status=${encodeURIComponent(discoveryExplorerFilter)}&order=${encodeURIComponent(discoveryExplorerOrder)}&limit=150`);
    renderDiscoveryExplorer(payload.data?.items || []);
    setText("#discoveryExplorerStatus", "READY");
    setClass("#discoveryExplorerStatus", "status-pill complete");
    setText("#discoveryExplorerMessage", `Showing ${formatNumber(payload.data?.items?.length || 0)} ${discoveryExplorerFilter === "all" ? "completed historical tests" : discoveryExplorerFilter + " results"}. Click a result to inspect exactly why EVE classified it.`);
  } catch (error) {
    setText("#discoveryExplorerStatus", "ERROR");
    setClass("#discoveryExplorerStatus", "status-pill error");
    setText("#discoveryExplorerMessage", error.message);
    if (!silent) showToast(error.message, true);
  }
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

  setText("#learningTitle", stage.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()));
  setText("#learningStatus", status.replaceAll("_", " ").toUpperCase());
  setClass("#learningStatus", `status-pill ${status}`);
  setText("#learningProgress", `${Math.min(100, progress).toFixed(progress > 0 && progress < 10 ? 1 : 0)}%`);
  setWidth("#learningProgressBar", `${Math.min(100, progress)}%`);
  setText("#learningMessage", run.error || (activeBuild ? run.message : null) || state.last_auto_error || state.last_auto_message || state.last_error || (autonomousEnabled
    ? "Autonomous learning is active on Railway. No button press is required."
    : "Build the foundation once. Railway will then take over automatically."));

  setText("#learningSnapshots", formatNumber(state.snapshots_count));
  setText("#learningOutcomes", formatNumber(state.outcome_labels_count));
  setText("#learningPendingOutcomes", formatNumber(state.pending_outcomes_count));
  setText("#learningPredictionsGraded", formatNumber(state.graded_prediction_count));
  setText("#learningQuestionsTested", formatNumber(state.questions_tested_total));
  setText("#learningValidatedDiscoveries", formatNumber(state.discoveries_validated_count));
  setText("#learningLatest", formatDate(state.last_snapshot_time, true));
  setText("#learningAutoUpdate", autonomousEnabled ? "ACTIVE" : "After first build");

  setText("#autonomyStatus", autonomousEnabled ? String(state.autonomous_status || "active").replaceAll("_", " ").toUpperCase() : "WAITING");
  setText("#autonomyLastCycle", formatDate(state.last_auto_cycle_at || autonomousRun.started_at, true));
  setText("#autonomyNextCycle", formatDate(state.next_auto_cycle_at, true));
  setText("#autonomyLastResearch", formatDate(state.last_research_cycle_at, true));

  const foundationReady = TIMEFRAMES.every((item) => historicalReady[item.interval]);
  const build = $("#buildLearning");
  if (build) {
    if (state.initial_build_complete) {
      build.hidden = true;
    } else {
      build.hidden = false;
      build.disabled = activeBuild || !foundationReady;
      if (!foundationReady) build.textContent = "Finish data foundation first";
      else if (activeBuild) build.textContent = "Learning build in progress…";
      else build.textContent = "Build initial learning foundation";
    }
  }

  const runNow = $("#runAutonomyNow");
  if (runNow) {
    runNow.disabled = !autonomousEnabled || autonomousRun.status === "running";
    runNow.textContent = autonomousRun.status === "running" ? "Autonomous cycle running…" : "Run diagnostic cycle now";
  }

  const cancel = $("#cancelLearning");
  if (cancel) {
    cancel.hidden = !activeBuild;
    cancel.disabled = !activeBuild;
  }

  const calendarRows = data.calendar_statistics || [];
  const topRangeWeekday = topStatistic(calendarRows, "weekday", "average_range_pct");
  const topDirectionalWeekday = topStatistic(calendarRows, "weekday", "directional_day_rate");
  const topRangeMonth = topStatistic(calendarRows, "month", "average_range_pct");
  const topDirectionalMonth = topStatistic(calendarRows, "month", "directional_day_rate");
  setCalendarInsight("#topRangeWeekday", "#topRangeWeekdayMeta", topRangeWeekday, "average_range_pct", "% daily range");
  setCalendarInsight("#topDirectionalWeekday", "#topDirectionalWeekdayMeta", topDirectionalWeekday, "directional_day_rate", "% directional");
  setCalendarInsight("#topRangeMonth", "#topRangeMonthMeta", topRangeMonth, "average_range_pct", "% daily range");
  setCalendarInsight("#topDirectionalMonth", "#topDirectionalMonthMeta", topDirectionalMonth, "directional_day_rate", "% directional");
  setText("#calendarStatus", calendarRows.length ? "READY" : "WAITING");
  setClass("#calendarStatus", `status-pill ${calendarRows.length ? "complete" : ""}`);

  const approved = data.approved_model || {};
  const challenger = data.challenger_model || {};
  setText("#approvedModelName", approved.name || "EVE Statistical Baseline");
  setText("#approvedModelVersion", approved.version ? `Version ${approved.version}` : "Version 1.0");
  setText("#approvedModelNotes", approved.notes || "The trusted baseline used to judge future models.");
  setText("#challengerModelName", challenger.name || "Waiting for first autonomous training cycle");
  setText("#challengerModelVersion", challenger.version ? `Version ${challenger.version}` : "Railway trains challengers automatically");
  setText("#challengerModelNotes", challenger.promotion_reason || challenger.notes || "A challenger will never replace the approved model unless it wins on chronological unseen data.");

  renderResearchQuestions(data.questions || []);
  renderDiscoveries(data.discoveries || []);
  renderResearchReport(data.research_reports || []);
  renderHistoricalResearch(data.historical_research || {});
  updateCommandCentre();
}

async function refreshLearning(silent = false) {
  try {
    const payload = await api("learning/status?symbol=XAU%2FUSD");
    renderLearning(payload.data || {});
  } catch (error) {
    if (!silent) showToast(error.message, true);
    setText("#learningMessage", error.message);
    console.error("Learning dashboard render failed", error);
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
  const strategy = $("#testerStrategy")?.value || "gold_h4_trend";
  if (isTrendStrategy(strategy)) {
    const testSegment = $("#testPeriod")?.value || "development";
    const startDate = $("#testDateFrom")?.value || "";
    const endDate = $("#testDateTo")?.value || "";
    return {
      strategy,
      name: "Gold H4 Trend 55/20 v1",
      symbol: "XAU/USD",
      interval: "1min",
      resolution: "m1_replay",
      test_segment: testSegment,
      date_from: testSegment === "custom" && startDate ? `${startDate}T00:00:00Z` : null,
      date_to: testSegment === "custom" && endDate ? `${endDate}T23:59:59Z` : null,
      starting_balance: Number($("#startingBalance").value),
      entry_lookback_h4: 55,
      exit_lookback_h4: 20,
      daily_trend_lookback: 60,
      atr_period_h4: 20,
      atr_multiplier: 2.0,
      risk_percent: Number($("#trendRiskPercent").value),
      minimum_lot: Number($("#trendMinimumLot").value),
      lot_step: Number($("#trendLotStep").value),
      maximum_lot: Number($("#trendMaximumLot").value),
      spread_price: Number($("#spreadPrice").value),
      commission_per_001_lot: Number($("#commission").value),
      slippage_price: Number($("#slippagePrice").value),
      money_per_price_per_001_lot: Number($("#moneyPerPrice").value),
      overnight_long_cost_per_001_lot: Number($("#trendLongOvernight").value),
      overnight_short_cost_per_001_lot: Number($("#trendShortOvernight").value),
      triple_swap_weekday: 2,
      path_mode: $("#pathMode").value,
    };
  }
  if (isLondonStrategy(strategy)) {
    const testSegment = $("#testPeriod")?.value || "development";
    const startDate = $("#testDateFrom")?.value || "";
    const endDate = $("#testDateTo")?.value || "";
    return {
      strategy,
      name: "London Opening Range v1",
      symbol: "XAU/USD",
      interval: "1min",
      resolution: "m1_replay",
      test_segment: testSegment,
      date_from: testSegment === "custom" && startDate ? `${startDate}T00:00:00Z` : null,
      date_to: testSegment === "custom" && endDate ? `${endDate}T23:59:59Z` : null,
      starting_balance: Number($("#startingBalance").value),
      risk_percent: Number($("#londonRiskPercent").value),
      breakout_buffer_fraction: Number($("#londonBreakoutBuffer").value) / 100,
      reward_risk: Number($("#londonRewardRisk").value),
      minimum_lot: Number($("#londonMinimumLot").value),
      lot_step: Number($("#londonLotStep").value),
      maximum_lot: Number($("#londonMaximumLot").value),
      timezone_name: "Europe/London",
      range_start_hour: 8,
      range_start_minute: 0,
      range_minutes: 30,
      entry_cutoff_hour: 11,
      entry_cutoff_minute: 30,
      force_exit_hour: 16,
      force_exit_minute: 0,
      spread_price: Number($("#spreadPrice").value),
      commission_per_001_lot: Number($("#commission").value),
      slippage_price: Number($("#slippagePrice").value),
      money_per_price_per_001_lot: Number($("#moneyPerPrice").value),
      path_mode: $("#pathMode").value,
    };
  }
  if (isLiquidityStrategy(strategy)) {
    const testSegment = $("#testPeriod")?.value || "development";
    const startDate = $("#testDateFrom")?.value || "";
    const endDate = $("#testDateTo")?.value || "";
    return {
      strategy,
      name: liquidityStrategyName(strategy),
      entry_model: liquidityEntryModel(strategy),
      symbol: "XAU/USD",
      interval: "1min",
      resolution: "m1_replay",
      test_segment: testSegment,
      date_from: testSegment === "custom" && startDate ? `${startDate}T00:00:00Z` : null,
      date_to: testSegment === "custom" && endDate ? `${endDate}T23:59:59Z` : null,
      starting_balance: Number($("#startingBalance").value),
      positions_per_basket: Number($("#positionsPerBasket").value),
      fixed_lot: Number($("#fixedLot").value),
      lookback_candles: Number($("#liquidityLookback").value),
      trend_period: 50,
      use_trend_filter: $("#trendFilter").value === "true",
      minimum_sweep_price: Number($("#minimumSweep").value),
      profit_target_money: Number($("#profitTarget").value),
      basket_stop_money: Number($("#basketStop").value),
      maximum_hold_minutes: Number($("#maximumHold").value),
      cooldown_candles: Number($("#cooldownCandles").value),
      spread_price: Number($("#spreadPrice").value),
      commission_per_001_lot: Number($("#commission").value),
      slippage_price: Number($("#slippagePrice").value),
      money_per_price_per_001_lot: Number($("#moneyPerPrice").value),
      path_mode: $("#pathMode").value,
    };
  }
  const resolution = $("#resolutionMode").value;
  return {
    strategy: "fixed_ladder",
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
  const chronological = isChronologicalStrategy(payloadBody.strategy);
  const requiredInterval = chronological || payloadBody.resolution === "m1_replay" ? "1min" : "5min";
  const memoryReady = isTrendStrategy(payloadBody.strategy)
    ? historicalReady["1min"] && historicalReady["4h"] && historicalReady["1day"]
    : historicalReady[requiredInterval];
  if (!memoryReady) {
    showToast(isTrendStrategy(payloadBody.strategy)
      ? "M1, H4 and D1 Market Memory must all be complete first."
      : `${requiredInterval === "1min" ? "M1" : "M5"} Market Memory is not complete yet.`, true);
    return;
  }
  button.disabled = true;
  button.textContent = "Starting…";
  selectedLegacyBacktestId = null;
  backtestViewMode = "current";
  setLegacyHistoryOpen(false);
  clearBacktestWorkspace({ message: "Starting a new test. Previous results remain archived and are not being reused." });
  try {
    const endpoint = isTrendStrategy(payloadBody.strategy)
      ? "backtests/gold-h4-trend"
      : (isLondonStrategy(payloadBody.strategy)
      ? "backtests/london-opening-range"
      : (isLiquidityStrategy(payloadBody.strategy) ? "backtests/liquidity-basket" : "backtests/fixed-ladder-v2-61"));
    const payload = await api(endpoint, {
      method: "POST",
      body: JSON.stringify(payloadBody),
    });
    activeBacktestId = payload.data.id;
    renderBacktest({
      id: activeBacktestId,
      name: payload.data.name || payloadBody.name,
      status: payload.data.status || "queued",
      resolution: payloadBody.resolution,
      settings: payloadBody,
      reliability: {
        progress_percent: 0,
        message: "Railway accepted this new test and is preparing the replay.",
        strategy: payloadBody.strategy,
        test_segment: payloadBody.test_segment || "full",
      },
      created_at: new Date().toISOString(),
    });
    showToast(payload.message || "Backtest started");
    await refreshBacktests(true);
  } catch (error) {
    clearBacktestWorkspace({ message: error.message });
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

function clearBacktestMetrics() {
  $("#resultNet").textContent = "—";
  $("#resultPF").textContent = "—";
  $("#resultDD").textContent = "—";
  $("#resultBasketWin").textContent = "—";
  $("#resultPositions").textContent = "—";
  $("#resultBaskets").textContent = "—";
  $("#resultBalance").textContent = "—";
  $("#resultAmbiguous").textContent = "—";
  $("#resultWorstBasket").textContent = "—";
  $("#resultLosingStreak").textContent = "—";
  $("#resultFrequency").textContent = "—";
  $("#resultExpectancy").textContent = "—";
  $("#resultAverageWin").textContent = "—";
  $("#resultAverageLoss").textContent = "—";
  $("#backtestVerdict").hidden = true;
  $("#backtestVerdict").removeAttribute("data-tone");
  $("#testerEquityPanel").hidden = true;
  $("#testerEquityCurve").innerHTML = "";
  $("#testerEquityRange").textContent = "—";
}

function clearBacktestWorkspace({ message = "This panel will show only the test you start now, or an archived test you deliberately select." } = {}) {
  activeBacktestId = null;
  selectedLegacyBacktestId = null;
  backtestViewMode = "current";
  $("#backtestContextLabel").textContent = "CURRENT TEST";
  $("#backtestTitle").textContent = "No test running";
  $("#backtestStatus").textContent = "READY";
  $("#backtestStatus").className = "status-pill";
  $("#backtestRunMeta").textContent = "Choose your settings and press Run. No previous result is loaded automatically.";
  $("#backtestProgress").textContent = "0%";
  $("#backtestProgressBar").style.width = "0%";
  $("#backtestMessage").textContent = message;
  $("#cancelBacktest").hidden = true;
  $("#clearLegacySelection").hidden = true;
  $("#accuracyWarning").textContent = "No result selected. M5 is an approximation; M1 is higher resolution; MT5 real-tick testing remains the execution standard.";
  clearBacktestMetrics();
  renderBaskets([], { hidden: true });
  updateBacktestAvailability();
}

function backtestResolutionLabel(run = {}) {
  const strategy = run.reliability?.strategy || run.settings?.strategy || "fixed_ladder";
  if (isTrendStrategy(strategy)) {
    const segments = { full: "Full history", development: "Development first ⅔", untouched: "Untouched final ⅓", custom: "Custom period" };
    return `Gold H4 Trend 55/20 v1 · ${segments[run.reliability?.test_segment || run.settings?.test_segment] || "H4/D1 signal with M1 replay"}`;
  }
  if (isLondonStrategy(strategy)) {
    const segments = { full: "Full M1 history", development: "Development first ⅔", untouched: "Untouched final ⅓", custom: "Custom M1 period" };
    return `London Opening Range v1 · ${segments[run.reliability?.test_segment || run.settings?.test_segment] || "M1 replay"}`;
  }
  if (isLiquidityStrategy(strategy)) {
    const segments = { full: "Full M1 history", development: "Development first ⅔", untouched: "Untouched final ⅓", custom: "Custom M1 period" };
    return `${liquidityStrategyName(strategy)} · ${segments[run.reliability?.test_segment || run.settings?.test_segment] || "M1 replay"}`;
  }
  return run.resolution === "m1_replay" ? "M1 high-resolution replay" : "M5 approximation";
}

function renderBacktestVerdict(run = {}) {
  const verdict = run.reliability?.verdict;
  const host = $("#backtestVerdict");
  if (!verdict || run.status !== "complete") {
    host.hidden = true;
    return;
  }
  host.hidden = false;
  host.dataset.tone = verdict.tone || "waiting";
  setText("#backtestVerdictLabel", verdict.label || "RESULT COMPLETE");
  setText("#backtestVerdictSummary", verdict.summary || "EVE completed the historical replay.");
  setText("#backtestVerdictNext", verdict.next_action || "Inspect the evidence before doing anything else.");
}

function renderBacktestEquity(run = {}) {
  const monthly = run.reliability?.monthly_net || {};
  const entries = Object.entries(monthly).sort(([a], [b]) => a.localeCompare(b));
  const panel = $("#testerEquityPanel");
  const host = $("#testerEquityCurve");
  if (run.status !== "complete" || !entries.length) {
    panel.hidden = true;
    host.innerHTML = "";
    return;
  }
  const start = Number(run.starting_balance || run.settings?.starting_balance || 0);
  let balance = start;
  const values = [start, ...entries.map(([, pnl]) => (balance += Number(pnl || 0)))];
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = Math.max(1, maximum - minimum);
  const points = values.map((value, index) => {
    const x = values.length === 1 ? 0 : index / (values.length - 1) * 100;
    const y = 34 - ((value - minimum) / range * 30);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  const positive = values.at(-1) >= values[0];
  host.innerHTML = `<svg viewBox="0 0 100 38" role="img" aria-label="Monthly balance path from ${escapeHtml(formatMoney(values[0]))} to ${escapeHtml(formatMoney(values.at(-1)))}" preserveAspectRatio="none"><line x1="0" y1="34" x2="100" y2="34"></line><polyline class="${positive ? "positive" : "negative"}" points="${points}"></polyline></svg>`;
  setText("#testerEquityRange", `${entries[0][0]} → ${entries.at(-1)[0]} · ${formatMoney(values.at(-1))}`);
  panel.hidden = false;
}

function renderBacktest(run = null, { archived = false } = {}) {
  if (!run || !run.id) {
    clearBacktestWorkspace();
    return;
  }
  const reliability = run.reliability || {};
  const status = run.status || "queued";
  const active = !archived && ["queued", "running"].includes(status);
  if (active) activeBacktestId = run.id;
  else if (!archived) activeBacktestId = null;
  backtestViewMode = archived ? "archive" : "current";
  selectedLegacyBacktestId = archived ? run.id : null;
  const progress = Number(reliability.progress_percent || (status === "complete" ? 100 : 0));
  $("#backtestContextLabel").textContent = archived ? "ARCHIVED TEST" : (status === "complete" ? "CURRENT TEST RESULT" : "CURRENT TEST");
  $("#backtestTitle").textContent = run.name || "Fixed Ladder v2.61";
  $("#backtestStatus").textContent = status.toUpperCase();
  $("#backtestStatus").className = `status-pill ${status}`;
  const timestamp = run.finished_at || run.created_at || run.started_at;
  const archivePrefix = archived ? "Stored historical result" : "Test started in this workspace";
  $("#backtestRunMeta").textContent = `${archivePrefix} · ${backtestResolutionLabel(run)} · ${formatDate(timestamp, true)}`;
  $("#backtestProgress").textContent = `${progress.toFixed(progress > 0 && progress < 10 ? 1 : 0)}%`;
  $("#backtestProgressBar").style.width = `${Math.min(100, progress)}%`;
  const baseMessage = run.error || reliability.message || "Waiting for Railway";
  $("#backtestMessage").textContent = archived
    ? `ARCHIVED: ${baseMessage} This is not a new or current result.`
    : baseMessage;
  $("#cancelBacktest").hidden = !active;
  $("#clearLegacySelection").hidden = !archived;

  const basketMetrics = reliability.basket_metrics || {};
  const strategy = reliability.strategy || run.settings?.strategy;
  const singlePosition = isSinglePositionStrategy(strategy);
  setText("#resultPFLabel", singlePosition ? "TRADE PROFIT FACTOR" : "BASKET PROFIT FACTOR");
  setText("#resultWinLabel", singlePosition ? "TRADE WIN RATE" : "BASKET WIN RATE");
  setText("#resultCountLabel", singlePosition ? "TRADES" : "BASKETS");
  setText("#resultWorstLabel", singlePosition ? "WORST TRADE" : "WORST BASKET");
  setText("#resultFrequencyLabel", singlePosition ? "TRADES / WEEK" : "BASKETS / WEEK");
  setText("#resultExpectancyLabel", singlePosition ? "EXPECTANCY / TRADE" : "EXPECTANCY / BASKET");
  $("#resultNet").textContent = formatMoney(run.net_profit);
  $("#resultPF").textContent = run.profit_factor == null
    ? (Number(basketMetrics.total_trades || 0) > 0 && Number(basketMetrics.losses || 0) === 0 ? "∞" : "—")
    : Number(run.profit_factor).toFixed(3);
  $("#resultDD").textContent = run.max_drawdown_percent == null ? "—" : formatPercent(run.max_drawdown_percent);
  $("#resultBasketWin").textContent = run.basket_win_rate == null ? "—" : formatPercent(run.basket_win_rate);
  $("#resultPositions").textContent = run.total_positions == null ? "—" : formatNumber(run.total_positions);
  $("#resultBaskets").textContent = run.total_baskets == null ? "—" : formatNumber(run.total_baskets);
  $("#resultBalance").textContent = formatMoney(run.ending_balance);
  $("#resultAmbiguous").textContent = reliability.ambiguous_candles == null ? "—" : formatNumber(reliability.ambiguous_candles);
  $("#resultWorstBasket").textContent = reliability.worst_basket == null ? "—" : formatMoney(reliability.worst_basket);
  $("#resultLosingStreak").textContent = reliability.longest_losing_streak == null ? "—" : `${formatNumber(reliability.longest_losing_streak)} ${singlePosition ? "trades" : "baskets"}`;
  $("#resultFrequency").textContent = reliability.baskets_per_week == null ? "—" : Number(reliability.baskets_per_week).toFixed(2);
  $("#resultExpectancy").textContent = run.expectancy == null ? "—" : formatMoney(run.expectancy);
  $("#resultAverageWin").textContent = basketMetrics.average_win == null ? "—" : formatMoney(basketMetrics.average_win);
  $("#resultAverageLoss").textContent = basketMetrics.average_loss == null ? "—" : formatMoney(-Math.abs(Number(basketMetrics.average_loss)));
  $("#ambiguousLabel").textContent = run.resolution === "m1_replay" ? "AMBIGUOUS M1 BARS" : "AMBIGUOUS M5 BARS";
  $("#accuracyWarning").textContent = archived
    ? "Archived diagnostic result. Do not treat it as current live evidence or as proof of profitability."
    : (reliability.warning || "M5 is an approximation. M1 reduces uncertainty but MT5 real-tick testing remains the execution standard.");
  renderBacktestVerdict(run);
  renderBacktestEquity(run);
  updateBacktestAvailability();
}

function renderBaskets(baskets = [], { archived = false, hidden = false, run = null } = {}) {
  const panel = $("#legacyBasketPanel");
  const host = $("#basketRows");
  if (hidden || !run || run.status !== "complete") {
    panel.hidden = true;
    host.innerHTML = '<tr><td colspan="7">No test selected.</td></tr>';
    return;
  }
  panel.hidden = false;
  $("#basketReportLabel").textContent = archived ? "ARCHIVED TEST BASKETS" : "CURRENT TEST BASKETS";
  $("#basketReportTitle").textContent = run.name || "Completed baskets";
  $("#basketReportNote").textContent = archived
    ? `Stored baskets from ${formatDate(run.finished_at || run.created_at, true)}. These are not today’s trades.`
    : "Baskets generated by the new test started in this workspace.";
  if (!baskets.length) {
    host.innerHTML = '<tr><td colspan="7">This completed test has no stored baskets.</td></tr>';
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
  const selected = $("#testerStrategy")?.value || "gold_h4_trend";
  const strategy = isChronologicalStrategy(selected) ? selected : "gold_h4_trend";
  const strategyRuns = runs.filter((run) => run.status === "complete" && (run.reliability?.strategy || run.settings?.strategy) === strategy);
  const m5 = strategyRuns.find((run) => (run.reliability?.test_segment || run.settings?.test_segment) === "development");
  const m1 = strategyRuns.find((run) => (run.reliability?.test_segment || run.settings?.test_segment) === "untouched");

  $("#m5ComparePF").textContent = m5?.profit_factor == null ? "—" : Number(m5.profit_factor).toFixed(3);
  $("#m5CompareMeta").textContent = m5
    ? `${formatDate(m5.finished_at || m5.created_at, true)} · ${formatMoney(m5.net_profit)} net`
    : "No development run";

  $("#m1ComparePF").textContent = m1?.profit_factor == null ? "—" : Number(m1.profit_factor).toFixed(3);
  $("#m1CompareMeta").textContent = m1
    ? `${formatDate(m1.finished_at || m1.created_at, true)} · ${formatMoney(m1.net_profit)} net`
    : "No untouched run";

  if (m5 && m1) {
    const delta = Number(m1.net_profit || 0) - Number(m5.net_profit || 0);
    $("#compareProfitDelta").textContent = formatSignedMoney(delta);
    const settingsKeys = isTrendStrategy(strategy)
      ? [
        "strategy", "symbol", "starting_balance", "entry_lookback_h4", "exit_lookback_h4", "daily_trend_lookback",
        "atr_period_h4", "atr_multiplier", "risk_percent", "minimum_lot", "lot_step", "maximum_lot", "spread_price",
        "commission_per_001_lot", "slippage_price", "money_per_price_per_001_lot", "overnight_long_cost_per_001_lot",
        "overnight_short_cost_per_001_lot", "triple_swap_weekday", "path_mode",
      ]
      : (isLondonStrategy(strategy)
      ? [
        "strategy", "symbol", "starting_balance", "risk_percent", "breakout_buffer_fraction", "reward_risk",
        "minimum_lot", "lot_step", "maximum_lot", "timezone_name", "range_start_hour", "range_start_minute",
        "range_minutes", "entry_cutoff_hour", "entry_cutoff_minute", "force_exit_hour", "force_exit_minute",
        "spread_price", "commission_per_001_lot", "slippage_price", "money_per_price_per_001_lot", "path_mode",
      ]
      : [
        "strategy", "entry_model", "symbol", "starting_balance", "positions_per_basket", "fixed_lot", "lookback_candles", "trend_period",
        "use_trend_filter", "minimum_sweep_price", "profit_target_money", "basket_stop_money", "maximum_hold_minutes",
        "cooldown_candles", "spread_price", "commission_per_001_lot", "slippage_price", "money_per_price_per_001_lot", "path_mode",
      ]);
    const settingsMatch = settingsKeys
      .every((key) => String(m5.settings?.[key]) === String(m1.settings?.[key]));
    $("#compareReliability").textContent = settingsMatch
      ? "Settings match — this is a valid locked comparison"
      : "WARNING: settings differ, so this is not a valid untouched test";
  } else {
    $("#compareProfitDelta").textContent = "—";
    $("#compareReliability").textContent = "Run both periods with identical settings";
  }
}

function renderLegacyHistory(runs = []) {
  const host = $("#legacyHistoryList");
  if (!runs.length) {
    host.innerHTML = '<div class="empty-state">No previous Strategy Tester runs are stored.</div>';
    return;
  }
  host.innerHTML = runs.map((run) => {
    const selected = selectedLegacyBacktestId === run.id;
    const status = String(run.status || "unknown").toUpperCase();
    return `<button type="button" class="legacy-history-card${selected ? " selected" : ""}" data-legacy-run-id="${escapeHtml(run.id)}">
      <span class="legacy-history-date">${formatDate(run.finished_at || run.created_at, true)}</span>
      <strong>${escapeHtml(run.name || "Fixed Ladder v2.61")}</strong>
      <span>${backtestResolutionLabel(run)} · ${status}</span>
      <span class="legacy-history-metrics">PF ${run.profit_factor == null ? "—" : Number(run.profit_factor).toFixed(3)} · ${formatMoney(run.net_profit)}</span>
    </button>`;
  }).join("");
}

async function fetchLegacyHistory(silent = false) {
  try {
    const payload = await api("backtests?limit=20");
    legacyBacktestRuns = payload.data || [];
    renderLegacyHistory(legacyBacktestRuns);
    renderComparison(legacyBacktestRuns);
    return legacyBacktestRuns;
  } catch (error) {
    if (!silent) showToast(error.message, true);
    return [];
  }
}

async function loadLegacyBacktest(runId, { archived = true, silent = false } = {}) {
  try {
    const detail = await api(`backtests/${runId}`);
    const run = detail.data?.run || detail.data || {};
    const baskets = detail.data?.baskets || [];
    renderBacktest(run, { archived });
    renderBaskets(baskets, { archived, run });
    if (archived) renderLegacyHistory(legacyBacktestRuns);
    return run;
  } catch (error) {
    if (!silent) showToast(error.message, true);
    return null;
  }
}

async function restoreActiveBacktest(silent = true) {
  try {
    const payload = await api("backtests/active?limit=5");
    const active = (payload.data || [])[0] || null;
    if (active) {
      selectedLegacyBacktestId = null;
      backtestViewMode = "current";
      await loadLegacyBacktest(active.id, { archived: false, silent });
    }
  } catch (error) {
    if (!silent) showToast(error.message, true);
  }
}

async function refreshBacktests(silent = false) {
  if (activeBacktestId) {
    const currentId = activeBacktestId;
    await loadLegacyBacktest(currentId, { archived: false, silent });
    return;
  }
  if (legacyBacktestHistoryOpen) {
    await fetchLegacyHistory(silent);
    if (selectedLegacyBacktestId) await loadLegacyBacktest(selectedLegacyBacktestId, { archived: true, silent });
  }
}

function setLegacyHistoryOpen(open) {
  legacyBacktestHistoryOpen = Boolean(open);
  const panel = $("#legacyHistoryPanel");
  panel.hidden = !legacyBacktestHistoryOpen;
  panel.setAttribute("aria-hidden", String(!legacyBacktestHistoryOpen));
  $("#showLegacyHistory").textContent = legacyBacktestHistoryOpen ? "Archive open" : "View previous tests";
  $("#showLegacyHistory").disabled = legacyBacktestHistoryOpen;
  if (legacyBacktestHistoryOpen) fetchLegacyHistory(true);
}

function setLegacyBacktesterOpen(open, { scroll = true, updateHash = true } = {}) {
  const trigger = $("#openLegacyBacktester");
  if (!trigger) return;
  legacyBacktesterOpen = Boolean(open);
  trigger.setAttribute("aria-expanded", String(legacyBacktesterOpen));

  if (legacyBacktesterOpen) {
    clearBacktestWorkspace();
    setLegacyHistoryOpen(false);
    restoreActiveBacktest(true);
    if (updateHash && window.location.hash !== "#backtester") window.location.hash = "#backtester";
    else if (scroll) requestAnimationFrame(() => $("#backtester")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  } else {
    setLegacyHistoryOpen(false);
    clearBacktestWorkspace();
    if (updateHash && window.location.hash === "#backtester") window.location.hash = "#advanced";
    else if (scroll) requestAnimationFrame(() => $("#advanced")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }
}


function formatR(value) {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) return "—";
  return `${numberValue >= 0 ? "+" : ""}${numberValue.toFixed(3)}R`;
}

function renderStrategyLabStatus(data = {}) {
  strategyLabDashboard = data;
  const state = data.state || {};
  const current = data.current_candidate || {};
  const status = state.status || "waiting";
  setText("#strategyLabStatus", status.toUpperCase());
  setClass("#strategyLabStatus", `status-pill ${status === "active" || status === "testing" || status === "generating" ? "complete" : status}`);
  setText("#strategyLabMessage", state.last_error || "EVE converts research findings into strategy candidates and tests them without waiting for market hours.");
  setText("#strategyCurrentCandidate", current.name || state.current_candidate_name || "Waiting for the next candidate");
  setText("#strategyHeartbeat", formatDate(state.heartbeat_at, true));
  setText("#strategyQueued", formatNumber(state.queue_count));
  setText("#strategyCompleted", formatNumber(state.completed_count));
  setText("#strategyRowsScanned", formatNumber(state.rows_scanned_total));
  setText("#strategyRejected", formatNumber(state.rejected_count));
  setText("#strategyPromising", formatNumber(state.promising_count));
  setText("#strategyValidated", formatNumber(state.validated_count));
  setText("#strategyElite", formatNumber(state.elite_count));
  setText("#strategyLastResult", state.last_result || "Waiting for validated research findings to become strategy candidates.");
  setText("#strategyTestedCount", formatNumber(state.completed_count));
  setText("#strategyRejectedCount", formatNumber(state.rejected_count));
  setText("#strategyPromisingCount", formatNumber(state.promising_count));
  setText("#strategyStrongCount", formatNumber(Number(state.validated_count || 0) + Number(state.elite_count || 0)));
  updateCommandCentre();
}

function strategyStatusExplanation(item) {
  const status = String(item.result_status || "rejected");
  if (status === "elite") return "Elite: strong locked-test performance, positive validation, stable yearly expectancy and a clear improvement over the comparable baseline. It is ready for high-resolution replay and forward testing—not live deployment.";
  if (status === "validated") return "Validated: the candidate stayed positive on unseen data and improved sufficiently on its baseline. It still requires M1/tick replay and forward testing.";
  if (status === "promising") return "Promising: the candidate was profitable on locked data but did not clear every robustness threshold.";
  return "Rejected: the rule set failed profitability, sample-size, stability or baseline-improvement requirements.";
}

function strategyRulesText(item) {
  const rules = item.rules || {};
  const mode = rules.condition_mode === "exclude" ? "Avoid the source condition" : "Require the source condition";
  const direction = String(rules.direction_rule || "current_direction").replaceAll("_", " ");
  return [
    mode,
    `Direction: ${direction}`,
    `Stop: ${Number(rules.stop_atr || 0).toFixed(2)} ATR`,
    `Target: ${Number(rules.target_atr || 0).toFixed(2)} ATR`,
    `Maximum hold: ${formatNumber(rules.horizon_minutes)} minutes`,
    `Cooldown: ${formatNumber(rules.cooldown_minutes)} minutes`,
  ];
}

function renderStrategyCandidateDetail(item) {
  const host = $("#strategyCandidateDetail");
  if (!host) return;
  if (!item) {
    host.innerHTML = '<div class="discovery-detail-empty"><small>SELECT A CANDIDATE</small><strong>Click a strategy idea to inspect its rules</strong><p>You will see its entry direction, filters, stop, target and locked-test evidence.</p></div>';
    return;
  }
  const test = item.metrics?.locked_test || {};
  const validation = item.metrics?.validation || {};
  const baseline = item.metrics?.baseline_locked_test || {};
  const caveats = item.evidence?.caveats || [];
  host.innerHTML = `
    <small class="discovery-detail-label">${escapeHtml(String(item.result_status || "result").toUpperCase())} · ${escapeHtml(String(item.family || "strategy").replaceAll("_", " ").toUpperCase())}</small>
    <h2>${escapeHtml(item.name || "Strategy candidate")}</h2>
    <p class="discovery-detail-summary">${escapeHtml(item.hypothesis || "No hypothesis stored.")}</p>
    <div class="discovery-verdict">${escapeHtml(strategyStatusExplanation(item))}</div>
    <div class="discovery-detail-metrics strategy-detail-metrics">
      <div><small>LOCKED PF</small><strong>${Number(item.profit_factor || 0).toFixed(2)}</strong></div>
      <div><small>EXPECTANCY</small><strong>${formatR(item.expectancy_r)}</strong></div>
      <div><small>MAX DRAWDOWN</small><strong>${formatR(-Math.abs(Number(item.max_drawdown_r || 0)))}</strong></div>
      <div><small>WIN RATE</small><strong>${Number(item.win_rate || 0).toFixed(1)}%</strong></div>
      <div><small>LOCKED TRADES</small><strong>${formatNumber(item.trades_total)}</strong></div>
      <div><small>YEAR STABILITY</small><strong>${Number(item.stability_score || 0).toFixed(1)}%</strong></div>
    </div>
    <div class="discovery-subsection"><small>BOT RULE SPECIFICATION</small><div class="condition-chip-list">${strategyRulesText(item).map((rule) => `<span class="condition-chip">${escapeHtml(rule)}</span>`).join("")}</div></div>
    <div class="discovery-subsection"><small>SOURCE RESEARCH</small><p>${escapeHtml(item.source_question || "No source question stored.")}</p></div>
    <div class="discovery-subsection"><small>ROBUSTNESS EVIDENCE</small><div class="evidence-list">
      <div><span>Validation profit factor</span><strong>${Number(validation.profit_factor || 0).toFixed(2)}</strong></div>
      <div><span>Locked-test profit factor</span><strong>${Number(test.profit_factor || 0).toFixed(2)}</strong></div>
      <div><span>Unfiltered baseline PF</span><strong>${Number(baseline.profit_factor || item.baseline_profit_factor || 0).toFixed(2)}</strong></div>
      <div><span>Locked-test net result</span><strong>${formatR(test.net_r)}</strong></div>
      <div><span>Locked-test expectancy</span><strong>${formatR(test.expectancy_r)}</strong></div>
      <div><span>Historical states scanned</span><strong>${formatNumber(item.rows_scanned)}</strong></div>
    </div></div>
    <div class="discovery-subsection"><small>LIMITATIONS BEFORE MT5</small><ul class="strategy-caveat-list">${caveats.map((caveat) => `<li>${escapeHtml(caveat)}</li>`).join("")}</ul></div>
    <p class="discovery-warning">This candidate is an evidence-backed bot specification, not a live trading instruction. It must pass high-resolution replay and forward testing before implementation.</p>`;
}

function renderStrategyCandidates(items = []) {
  strategyCandidateItems = items;
  const host = $("#strategyCandidateList");
  if (!host) return;
  if (!items.length) {
    host.innerHTML = `<div class="empty-state">No ${escapeHtml(strategyCandidateFilter === "all" ? "completed" : strategyCandidateFilter)} strategy candidates are available yet. EVE will create them automatically from validated and promising research.</div>`;
    renderStrategyCandidateDetail(null);
    return;
  }
  if (!selectedStrategyCandidateId || !items.some((item) => item.id === selectedStrategyCandidateId)) selectedStrategyCandidateId = items[0].id;
  host.innerHTML = items.map((item) => `
    <button class="discovery-result-card strategy-result-card ${escapeHtml(String(item.result_status || "rejected"))} ${item.id === selectedStrategyCandidateId ? "selected" : ""}" type="button" data-strategy-id="${escapeHtml(item.id)}">
      <div class="discovery-result-head"><span class="discovery-result-status">${escapeHtml(String(item.result_status || "rejected").toUpperCase())}</span><span class="discovery-result-date">${escapeHtml(formatDate(item.finished_at))}</span></div>
      <h3>${escapeHtml(item.name || "Strategy candidate")}</h3>
      <p>${escapeHtml(item.source_question || item.hypothesis || "Evidence-backed candidate")}</p>
      <div class="discovery-result-metrics strategy-result-metrics">
        <div><small>PF</small><strong>${Number(item.profit_factor || 0).toFixed(2)}</strong></div>
        <div><small>EXPECTANCY</small><strong>${formatR(item.expectancy_r)}</strong></div>
        <div><small>TRADES</small><strong>${formatNumber(item.trades_total)}</strong></div>
        <div><small>DRAWDOWN</small><strong>${Number(item.max_drawdown_r || 0).toFixed(1)}R</strong></div>
      </div>
    </button>`).join("");
  renderStrategyCandidateDetail(items.find((item) => item.id === selectedStrategyCandidateId) || items[0]);
}

async function refreshStrategyLab(silent = false) {
  try {
    const [statusPayload, candidatesPayload] = await Promise.all([
      api("strategy-lab/status?symbol=XAU%2FUSD"),
      api(`strategy-lab/candidates?symbol=XAU%2FUSD&result_status=${encodeURIComponent(strategyCandidateFilter)}&order=${encodeURIComponent(strategyCandidateOrder)}&limit=150`),
    ]);
    renderStrategyLabStatus(statusPayload.data || {});
    renderStrategyCandidates(candidatesPayload.data?.items || []);
    setText("#strategyExplorerStatus", "READY");
    setClass("#strategyExplorerStatus", "status-pill complete");
    setText("#strategyExplorerMessage", `Showing ${formatNumber(candidatesPayload.data?.items?.length || 0)} completed candidates. EVE keeps generating and testing new bot ideas in Railway.`);
  } catch (error) {
    setText("#strategyExplorerStatus", "ERROR");
    setClass("#strategyExplorerStatus", "status-pill error");
    setText("#strategyExplorerMessage", error.message);
    if (!silent) showToast(error.message, true);
  }
}

async function wakeStrategyLab(button) {
  button.disabled = true;
  try {
    const payload = await api("strategy-lab/wake", { method: "POST", body: "{}" });
    showToast(payload.message || "Strategy Factory wake requested");
    await refreshStrategyLab(true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}


function evolutionStatusExplanation(item) {
  const status = String(item?.result_status || "rejected");
  if (status === "elite") return "Elite: this mutation improved the development champion on validation-only selection and remained exceptionally strong on the sealed locked period. It is still research grade until M1/tick replay and forward testing.";
  if (status === "champion") return "Champion: the child beat its parent on validation-only selection and remained positive and stable on the sealed locked period.";
  if (status === "development") return "Development champion: validation improved enough for EVE to keep evolving this rule set, but the sealed locked evidence is not yet strong enough for readiness status.";
  return "Rejected: the mutation did not improve its direct parent on validation-only selection, or the sealed locked period triggered the catastrophic-loss safety veto.";
}

function renderEvolutionBest(lineage = {}) {
  const status = String(lineage.champion_result_status || "waiting");
  setText("#evolutionBestName", lineage.champion_name || lineage.name || "Waiting for a strategy lineage");
  setText("#evolutionBestStatus", status.toUpperCase());
  setClass("#evolutionBestStatus", `status-pill ${["elite", "champion", "validated", "promising"].includes(status) ? "complete" : "waiting"}`);
  setText("#evolutionBestMessage", lineage.last_result || "The best lineage will appear after EVE seeds strong Strategy Factory candidates.");
  setText("#evolutionBestPF", lineage.champion_profit_factor == null ? "—" : Number(lineage.champion_profit_factor).toFixed(2));
  setText("#evolutionBestExpectancy", lineage.champion_expectancy_r == null ? "—" : formatR(lineage.champion_expectancy_r));
  setText("#evolutionBestDrawdown", lineage.champion_max_drawdown_r == null ? "—" : `${Number(lineage.champion_max_drawdown_r).toFixed(1)}R`);
  setText("#evolutionBestTrades", lineage.champion_trades == null ? "—" : formatNumber(lineage.champion_trades));
  setText("#evolutionBestGeneration", formatNumber(lineage.current_generation));
  setText("#evolutionBestImprovements", formatNumber(lineage.improvements));
  setText("#evolutionBestValidationScore", lineage.champion_validation_score == null ? "—" : Number(lineage.champion_validation_score).toFixed(2));
  const rulesHost = $("#evolutionBestRules");
  if (rulesHost) {
    const rules = lineage.champion_rules || {};
    const chips = Object.keys(rules).length ? strategyRulesText({ rules }) : ["Waiting for rules"];
    rulesHost.innerHTML = chips.map((item) => `<span class="condition-chip">${escapeHtml(item)}</span>`).join("");
  }
}

function renderEvolutionLineages(lineages = []) {
  const host = $("#evolutionLineageList");
  if (!host) return;
  if (!lineages.length) {
    host.innerHTML = '<div class="empty-state">Waiting for strong Strategy Factory candidates to seed evolution lineages.</div>';
    return;
  }
  host.innerHTML = lineages.map((lineage, index) => `
    <article class="evolution-lineage-card ${index === 0 ? "leader" : ""}">
      <div class="discovery-result-head"><span class="discovery-result-status">${index === 0 ? "LEADER" : escapeHtml(String(lineage.champion_result_status || "SEED").toUpperCase())}</span><span>GEN ${formatNumber(lineage.current_generation)}</span></div>
      <h3>${escapeHtml(lineage.champion_name || lineage.name || "Strategy lineage")}</h3>
      <p>${escapeHtml(lineage.last_result || "EVE is testing controlled mutations against this lineage champion.")}</p>
      <div class="evolution-lineage-metrics">
        <div><small>PF</small><strong>${Number(lineage.champion_profit_factor || 0).toFixed(2)}</strong></div>
        <div><small>EXPECTANCY</small><strong>${formatR(lineage.champion_expectancy_r)}</strong></div>
        <div><small>MUTATIONS</small><strong>${formatNumber(lineage.mutations_tested)}</strong></div>
        <div><small>IMPROVEMENTS</small><strong>${formatNumber(lineage.improvements)}</strong></div>
      </div>
    </article>`).join("");
}

function renderEvolutionStatus(data = {}) {
  evolutionDashboard = data;
  const state = data.state || {};
  const current = data.current_child || {};
  const status = state.status || "waiting";
  setText("#evolutionStatus", status.toUpperCase());
  setClass("#evolutionStatus", `status-pill ${["active", "testing", "generating", "loading"].includes(status) ? "complete" : status}`);
  setText("#evolutionMessage", state.last_error || "EVE mutates surviving strategies one controlled rule at a time and compares every child directly with its parent.");
  setText("#evolutionCurrentChild", current.name || state.current_child_name || "Waiting for the next mutation");
  setText("#evolutionHeartbeat", formatDate(state.heartbeat_at, true));
  setText("#evolutionQueued", formatNumber(state.queue_count));
  setText("#evolutionCompleted", formatNumber(state.completed_count));
  setText("#evolutionRowsScanned", formatNumber(state.rows_scanned_total));
  setText("#evolutionLineages", formatNumber(state.lineages_total));
  setText("#evolutionRejected", formatNumber(state.rejected_count));
  setText("#evolutionDevelopment", formatNumber(state.development_count));
  setText("#evolutionChampionCount", formatNumber(Number(state.champion_count || 0) + Number(state.elite_count || 0)));
  setText("#evolutionLastResult", state.last_result || "Waiting for the first controlled mutation.");
  setText("#evolutionTestedCount", formatNumber(state.completed_count));
  setText("#evolutionRejectedCount", formatNumber(state.rejected_count));
  setText("#evolutionDevelopmentCount", formatNumber(state.development_count));
  setText("#evolutionStrongCount", formatNumber(Number(state.champion_count || 0) + Number(state.elite_count || 0)));
  renderEvolutionBest(data.best_lineage || {});
  renderEvolutionLineages(data.lineages || []);
  updateCommandCentre();
}

function evolutionChangesText(item) {
  const changes = item?.changes || {};
  const entries = Object.entries(changes);
  return entries.length ? entries.map(([key, value]) => `${String(key).replaceAll("_", " ")}: ${value}`) : ["No change description stored"];
}

function renderEvolutionCandidateDetail(item) {
  const host = $("#evolutionCandidateDetail");
  if (!host) return;
  if (!item) {
    host.innerHTML = '<div class="discovery-detail-empty"><small>SELECT A MUTATION</small><strong>Click any result to inspect the parent comparison</strong><p>You will see what changed, whether validation improved and how the sealed locked period behaved.</p></div>';
    return;
  }
  const childValidation = item.metrics?.child_validation || {};
  const childTest = item.metrics?.child_locked_test || {};
  const parentValidation = item.metrics?.parent_validation || {};
  const parentTest = item.metrics?.parent_locked_test || {};
  const validationDelta = item.parent_comparison?.validation_delta || {};
  const lockedDelta = item.parent_comparison?.locked_test_delta || {};
  const protocols = item.evidence?.selection_protocol || [];
  host.innerHTML = `
    <small class="discovery-detail-label">${escapeHtml(String(item.result_status || "result").toUpperCase())} · GENERATION ${formatNumber(item.generation)} · ${escapeHtml(String(item.mutation_type || "mutation").replaceAll("_", " ").toUpperCase())}</small>
    <h2>${escapeHtml(item.name || "Evolution mutation")}</h2>
    <p class="discovery-detail-summary">${escapeHtml(item.hypothesis || "No hypothesis stored.")}</p>
    <div class="discovery-verdict">${escapeHtml(item.evidence?.verdict || evolutionStatusExplanation(item))}</div>
    <div class="discovery-detail-metrics strategy-detail-metrics">
      <div><small>LOCKED PF</small><strong>${Number(item.profit_factor || 0).toFixed(2)}</strong></div>
      <div><small>LOCKED EXPECTANCY</small><strong>${formatR(item.expectancy_r)}</strong></div>
      <div><small>MAX DRAWDOWN</small><strong>${Number(item.max_drawdown_r || 0).toFixed(1)}R</strong></div>
      <div><small>LOCKED TRADES</small><strong>${formatNumber(item.trades_total)}</strong></div>
      <div><small>VALIDATION SCORE Δ</small><strong>${Number(item.validation_improvement || 0) >= 0 ? "+" : ""}${Number(item.validation_improvement || 0).toFixed(2)}</strong></div>
      <div><small>YEAR STABILITY</small><strong>${Number(item.stability_score || 0).toFixed(1)}%</strong></div>
    </div>
    <div class="discovery-subsection"><small>WHAT EVE CHANGED</small><div class="condition-chip-list">${evolutionChangesText(item).map((change) => `<span class="condition-chip">${escapeHtml(change)}</span>`).join("")}</div></div>
    <div class="discovery-subsection"><small>CHILD RULES</small><div class="condition-chip-list">${strategyRulesText(item).map((rule) => `<span class="condition-chip">${escapeHtml(rule)}</span>`).join("")}</div></div>
    <div class="discovery-subsection"><small>VALIDATION-ONLY SELECTION</small><div class="evidence-list">
      <div><span>Parent validation PF</span><strong>${Number(parentValidation.profit_factor || 0).toFixed(2)}</strong></div>
      <div><span>Child validation PF</span><strong>${Number(childValidation.profit_factor || 0).toFixed(2)}</strong></div>
      <div><span>PF change</span><strong>${Number(validationDelta.profit_factor || 0) >= 0 ? "+" : ""}${Number(validationDelta.profit_factor || 0).toFixed(2)}</strong></div>
      <div><span>Expectancy change</span><strong>${formatR(validationDelta.expectancy_r)}</strong></div>
      <div><span>Drawdown change</span><strong>${formatR(validationDelta.max_drawdown_r)}</strong></div>
      <div><span>Selected for next generation</span><strong>${item.promoted_for_next_generation ? "YES" : "NO"}</strong></div>
    </div></div>
    <div class="discovery-subsection"><small>SEALED LOCKED AUDIT</small><div class="evidence-list">
      <div><span>Parent locked PF</span><strong>${Number(parentTest.profit_factor || 0).toFixed(2)}</strong></div>
      <div><span>Child locked PF</span><strong>${Number(childTest.profit_factor || 0).toFixed(2)}</strong></div>
      <div><span>Locked PF change</span><strong>${Number(lockedDelta.profit_factor || 0) >= 0 ? "+" : ""}${Number(lockedDelta.profit_factor || 0).toFixed(2)}</strong></div>
      <div><span>Locked-test readiness</span><strong>${item.locked_test_passed ? "PASSED" : "NOT PASSED"}</strong></div>
      <div><span>Historical states scanned</span><strong>${formatNumber(item.rows_scanned)}</strong></div>
      <div><span>Locked data used to choose mutation</span><strong>${item.parent_comparison?.selection_used_locked_test ? "YES" : "NO"}</strong></div>
    </div></div>
    <div class="discovery-subsection"><small>ANTI-OVERFITTING PROTOCOL</small><ul class="strategy-caveat-list">${protocols.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul></div>
    <p class="discovery-warning">Evolution status is not permission to trade. Champion and elite children still require M1/tick replay, broker-cost stress and forward testing.</p>`;
}

function renderEvolutionCandidates(items = []) {
  evolutionCandidateItems = items;
  const host = $("#evolutionCandidateList");
  if (!host) return;
  if (!items.length) {
    host.innerHTML = `<div class="empty-state">No ${escapeHtml(evolutionCandidateFilter === "all" ? "completed" : evolutionCandidateFilter)} evolution results are available yet. EVE will seed lineages and mutate them automatically.</div>`;
    renderEvolutionCandidateDetail(null);
    return;
  }
  if (!selectedEvolutionCandidateId || !items.some((item) => item.id === selectedEvolutionCandidateId)) selectedEvolutionCandidateId = items[0].id;
  host.innerHTML = items.map((item) => `
    <button class="discovery-result-card evolution-result-card ${escapeHtml(String(item.result_status || "rejected"))} ${item.id === selectedEvolutionCandidateId ? "selected" : ""}" type="button" data-evolution-id="${escapeHtml(item.id)}">
      <div class="discovery-result-head"><span class="discovery-result-status">${escapeHtml(String(item.result_status || "rejected").toUpperCase())}</span><span class="discovery-result-date">GEN ${formatNumber(item.generation)} · ${escapeHtml(formatDate(item.finished_at))}</span></div>
      <h3>${escapeHtml(item.name || "Evolution mutation")}</h3>
      <p>${escapeHtml(evolutionChangesText(item).join(" · "))}</p>
      <div class="discovery-result-metrics strategy-result-metrics">
        <div><small>LOCKED PF</small><strong>${Number(item.profit_factor || 0).toFixed(2)}</strong></div>
        <div><small>EXPECTANCY</small><strong>${formatR(item.expectancy_r)}</strong></div>
        <div><small>VALIDATION Δ</small><strong>${Number(item.validation_improvement || 0) >= 0 ? "+" : ""}${Number(item.validation_improvement || 0).toFixed(2)}</strong></div>
        <div><small>TRADES</small><strong>${formatNumber(item.trades_total)}</strong></div>
      </div>
    </button>`).join("");
  renderEvolutionCandidateDetail(items.find((item) => item.id === selectedEvolutionCandidateId) || items[0]);
}

async function refreshEvolution(silent = false) {
  try {
    const [statusPayload, candidatesPayload] = await Promise.all([
      api("evolution/status?symbol=XAU%2FUSD"),
      api(`evolution/candidates?symbol=XAU%2FUSD&result_status=${encodeURIComponent(evolutionCandidateFilter)}&order=${encodeURIComponent(evolutionCandidateOrder)}&limit=150`),
    ]);
    renderEvolutionStatus(statusPayload.data || {});
    renderEvolutionCandidates(candidatesPayload.data?.items || []);
    setText("#evolutionExplorerStatus", "READY");
    setClass("#evolutionExplorerStatus", "status-pill complete");
    setText("#evolutionExplorerMessage", `Showing ${formatNumber(candidatesPayload.data?.items?.length || 0)} completed mutations. EVE continues evolving lineages in Railway.`);
  } catch (error) {
    setText("#evolutionExplorerStatus", "ERROR");
    setClass("#evolutionExplorerStatus", "status-pill error");
    setText("#evolutionExplorerMessage", error.message);
    if (!silent) showToast(error.message, true);
  }
}

async function wakeEvolution(button) {
  button.disabled = true;
  try {
    const payload = await api("evolution/wake", { method: "POST", body: "{}" });
    showToast(payload.message || "Strategy Evolution wake requested");
    await refreshEvolution(true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

const timeframeGrid = $("#timeframeGrid");
if (timeframeGrid) timeframeGrid.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action][data-interval]");
  if (!button) return;
  const interval = button.dataset.interval;
  const action = button.dataset.action;
  const meta = TIMEFRAMES.find((item) => item.interval === interval);
  if (!meta) return;
  if (action === "pause") await pauseBackfill(interval, button);
  else if (action === "backfill") await queueJob("backfill", interval, button, `${meta.label} historical download queued`);
  else if (action === "sync") await queueJob("sync", interval, button, `${meta.label} latest-candle sync queued`);
  else if (action === "gap-scan") await queueJob("gap-scan", interval, button, `${meta.label} gap scan queued`);
});


function validationStatusLabel(status) {
  const labels = {
    ready_for_mt5_generation: "READY FOR MT5",
    replay_validated: "REPLAY VALIDATED",
    needs_more_evidence: "NEEDS EVIDENCE",
    rejected: "REJECTED",
  };
  return labels[status] || String(status || "WAITING").replaceAll("_", " ").toUpperCase();
}

function renderValidationBest(item = {}) {
  const ready = item && item.id;
  setText("#validationBestName", ready ? item.name : "Waiting for a strategy to pass");
  setText("#validationBestStatus", ready ? "READY FOR MT5" : "WAITING");
  setClass("#validationBestStatus", `status-pill ${ready ? "complete" : "waiting"}`);
  setText("#validationBestVerdict", ready ? (item.evidence?.verdict || "The rules passed M1 validation and are frozen for MT5 generation.") : "EVE will freeze a rule set only after M1 replay, elevated-cost stress and parameter-neighbourhood checks pass.");
  setText("#validationBestPF", ready ? Number(item.profit_factor || 0).toFixed(2) : "—");
  setText("#validationBestExpectancy", ready ? formatR(item.expectancy_r) : "—");
  setText("#validationBestDrawdown", ready ? `${Number(item.max_drawdown_r || 0).toFixed(1)}R` : "—");
  setText("#validationBestTrades", ready ? formatNumber(item.trades_total) : "—");
  setText("#validationBestRobustness", ready ? `${Number(item.robust_profile_ratio || 0).toFixed(0)}%` : "—");
  setText("#validationBestStability", ready ? `${Number(item.year_stability || 0).toFixed(0)}%` : "—");
  const rulesHost = $("#validationBestRules");
  if (rulesHost) {
    const chips = ready ? strategyRulesText({ rules: item.frozen_rules || item.rules || {} }) : ["Waiting for frozen rules"];
    rulesHost.innerHTML = chips.map((rule) => `<span class="condition-chip">${escapeHtml(rule)}</span>`).join("");
  }
}

function renderValidationStatus(data = {}) {
  validationDashboard = data;
  const state = data.state || {};
  const current = data.current_job || {};
  const status = state.status || "waiting";
  setText("#validationStatus", status.toUpperCase());
  setClass("#validationStatus", `status-pill ${["active", "loading", "replaying"].includes(status) ? "complete" : status}`);
  setText("#validationMessage", state.last_error || "EVE automatically replays surviving strategies on stored M1 candles and challenges their execution assumptions.");
  setText("#validationCurrentJob", current.name || state.current_job_name || "Waiting for the next surviving strategy");
  setText("#validationHeartbeat", formatDate(state.heartbeat_at, true));
  setText("#validationQueued", formatNumber(state.queue_count));
  setText("#validationCompleted", formatNumber(state.completed_count));
  setText("#validationWindows", formatNumber(state.m1_windows_scanned_total));
  setText("#validationRejected", formatNumber(state.rejected_count));
  setText("#validationNeedsEvidence", formatNumber(state.needs_evidence_count));
  setText("#validationReplayValidated", formatNumber(state.replay_validated_count));
  setText("#validationMt5Ready", formatNumber(state.mt5_ready_count));
  setText("#validationLastResult", state.last_result || "Waiting for a Champion, Elite or validated strategy.");
  setText("#validationTestedCount", formatNumber(state.completed_count));
  setText("#validationRejectedCount", formatNumber(state.rejected_count));
  setText("#validationPassedCount", formatNumber(state.replay_validated_count));
  setText("#validationReadyCount", formatNumber(state.mt5_ready_count));
  renderValidationBest(data.best_ready || {});
  updateCommandCentre();
}

function validationExplanation(item) {
  const status = String(item?.result_status || "rejected");
  if (status === "ready_for_mt5_generation") return "Passed: M1 replay, elevated execution-cost stress and enough nearby parameter settings stayed healthy. EVE froze the exact rules for the MT5-generator stage.";
  if (status === "replay_validated") return "M1 replay passed, but one or more final MT5-readiness thresholds still need stronger evidence.";
  if (status === "needs_more_evidence") return "The high-resolution trades stayed positive, but the sample is still too small for a final decision.";
  return "Rejected: the strategy failed M1 replay, execution-cost stress, data completeness, stability or parameter-neighbourhood safeguards.";
}

function validationProfileRows(item) {
  const profiles = item.metrics?.parameter_neighbourhood || {};
  return Object.entries(profiles).map(([name, result]) => {
    const label = name.replaceAll("_", " ");
    const locked = result.locked_test || {};
    return `<div><span>${escapeHtml(label)}</span><strong>${result.passed ? "PASS" : "FAIL"} · PF ${Number(locked.profit_factor || 0).toFixed(2)}</strong></div>`;
  }).join("");
}

function renderValidationJobDetail(item) {
  const host = $("#validationJobDetail");
  if (!host) return;
  if (!item) {
    host.innerHTML = '<div class="discovery-detail-empty"><small>SELECT A VALIDATION</small><strong>Click any result to inspect the M1 evidence</strong><p>You will see the exact rules, M1 result, cost stresses, parameter robustness and EVE\'s next action.</p></div>';
    return;
  }
  const standard = item.metrics?.standard_cost || {};
  const validation = standard.validation || {};
  const locked = standard.locked_test || {};
  const elevated = item.metrics?.elevated_cost?.locked_test || {};
  const severe = item.metrics?.severe_cost?.locked_test || {};
  const reasons = item.evidence?.reasons || [];
  const status = String(item.result_status || "rejected");
  host.innerHTML = `
    <small class="discovery-detail-label">${escapeHtml(validationStatusLabel(status))} · M1 VALIDATION</small>
    <h2>${escapeHtml(item.name || "Validated strategy")}</h2>
    <p class="discovery-detail-summary">${escapeHtml(item.evidence?.entry_protocol || "The strategy was replayed using the stored M1 execution path.")}</p>
    <div class="discovery-verdict">${escapeHtml(item.evidence?.verdict || validationExplanation(item))}</div>
    <div class="discovery-detail-metrics strategy-detail-metrics">
      <div><small>M1 LOCKED PF</small><strong>${Number(item.profit_factor || 0).toFixed(2)}</strong></div>
      <div><small>EXPECTANCY</small><strong>${formatR(item.expectancy_r)}</strong></div>
      <div><small>MAX DRAWDOWN</small><strong>${Number(item.max_drawdown_r || 0).toFixed(1)}R</strong></div>
      <div><small>WIN RATE</small><strong>${Number(item.win_rate || 0).toFixed(1)}%</strong></div>
      <div><small>M1 TRADES</small><strong>${formatNumber(item.trades_total)}</strong></div>
      <div><small>YEAR STABILITY</small><strong>${Number(item.year_stability || 0).toFixed(1)}%</strong></div>
      <div><small>RESOLVED ENTRIES</small><strong>${Number(item.resolved_rate || 0).toFixed(1)}%</strong></div>
      <div><small>ROBUST PROFILES</small><strong>${Number(item.robust_profile_ratio || 0).toFixed(1)}%</strong></div>
    </div>
    <div class="discovery-subsection"><small>EXACT RULES TESTED</small><div class="condition-chip-list">${strategyRulesText(item).map((rule) => `<span class="condition-chip">${escapeHtml(rule)}</span>`).join("")}</div></div>
    <div class="discovery-subsection"><small>M1 CHRONOLOGICAL EVIDENCE</small><div class="evidence-list">
      <div><span>Validation PF</span><strong>${Number(validation.profit_factor || 0).toFixed(2)}</strong></div>
      <div><span>Locked PF</span><strong>${Number(locked.profit_factor || 0).toFixed(2)}</strong></div>
      <div><span>Locked net result</span><strong>${formatR(locked.net_r)}</strong></div>
      <div><span>Locked expectancy</span><strong>${formatR(locked.expectancy_r)}</strong></div>
      <div><span>M1 windows fetched</span><strong>${formatNumber(item.m1_windows_scanned)}</strong></div>
      <div><span>Rules SHA-256</span><strong>${escapeHtml(String(item.rules_hash || "—").slice(0, 16))}…</strong></div>
    </div></div>
    <div class="discovery-subsection"><small>EXECUTION-COST STRESS</small><div class="evidence-list">
      <div><span>Standard-cost locked PF</span><strong>${Number(locked.profit_factor || 0).toFixed(2)}</strong></div>
      <div><span>Elevated-cost locked PF</span><strong>${Number(elevated.profit_factor || 0).toFixed(2)}</strong></div>
      <div><span>Elevated-cost expectancy</span><strong>${formatR(elevated.expectancy_r)}</strong></div>
      <div><span>Severe-cost locked PF</span><strong>${Number(severe.profit_factor || 0).toFixed(2)}</strong></div>
    </div></div>
    <div class="discovery-subsection"><small>NEARBY PARAMETER CHALLENGE</small><div class="evidence-list validation-profile-list">${validationProfileRows(item) || '<div><span>No profiles stored</span><strong>—</strong></div>'}</div></div>
    ${reasons.length ? `<div class="discovery-subsection"><small>WHY IT DID NOT FULLY PASS</small><ul class="strategy-caveat-list">${reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul></div>` : ""}
    <div class="discovery-subsection"><small>NEXT ACTION</small><p>${escapeHtml(item.evidence?.next_action || "Keep this result in research.")}</p></div>
    <p class="discovery-warning">Ready for MT5 means eligible for code generation and independent MT5 testing. It is not permission to trade real money.</p>`;
}

function renderValidationJobs(items = []) {
  validationJobItems = items;
  const host = $("#validationJobList");
  if (!host) return;
  if (!items.length) {
    host.innerHTML = `<div class="empty-state">No ${escapeHtml(validationJobFilter === "all" ? "completed" : validationJobFilter.replaceAll("_", " "))} M1 validation results are available yet. EVE will queue surviving strategies automatically.</div>`;
    renderValidationJobDetail(null);
    return;
  }
  if (!selectedValidationJobId || !items.some((item) => item.id === selectedValidationJobId)) selectedValidationJobId = items[0].id;
  host.innerHTML = items.map((item) => `
    <button class="discovery-result-card validation-result-card ${escapeHtml(String(item.result_status || "rejected"))} ${item.id === selectedValidationJobId ? "selected" : ""}" type="button" data-validation-id="${escapeHtml(item.id)}">
      <div class="discovery-result-head"><span class="discovery-result-status">${escapeHtml(validationStatusLabel(item.result_status))}</span><span class="discovery-result-date">${escapeHtml(formatDate(item.finished_at))}</span></div>
      <h3>${escapeHtml(item.name || "M1 validation")}</h3>
      <p>${escapeHtml(item.evidence?.verdict || validationExplanation(item))}</p>
      <div class="discovery-result-metrics strategy-result-metrics">
        <div><small>M1 PF</small><strong>${Number(item.profit_factor || 0).toFixed(2)}</strong></div>
        <div><small>EXPECTANCY</small><strong>${formatR(item.expectancy_r)}</strong></div>
        <div><small>TRADES</small><strong>${formatNumber(item.trades_total)}</strong></div>
        <div><small>ROBUST</small><strong>${Number(item.robust_profile_ratio || 0).toFixed(0)}%</strong></div>
      </div>
    </button>`).join("");
  renderValidationJobDetail(items.find((item) => item.id === selectedValidationJobId) || items[0]);
}

async function refreshValidation(silent = false) {
  try {
    const [statusPayload, jobsPayload] = await Promise.all([
      api("validation/status?symbol=XAU%2FUSD"),
      api(`validation/jobs?symbol=XAU%2FUSD&result_status=${encodeURIComponent(validationJobFilter)}&order=${encodeURIComponent(validationJobOrder)}&limit=150`),
    ]);
    renderValidationStatus(statusPayload.data || {});
    renderValidationJobs(jobsPayload.data?.items || []);
    setText("#validationExplorerStatus", "READY");
    setClass("#validationExplorerStatus", "status-pill complete");
    setText("#validationExplorerMessage", `Showing ${formatNumber(jobsPayload.data?.items?.length || 0)} completed high-resolution validations. Railway continues automatically.`);
  } catch (error) {
    setText("#validationExplorerStatus", "ERROR");
    setClass("#validationExplorerStatus", "status-pill error");
    setText("#validationExplorerMessage", error.message);
    if (!silent) showToast(error.message, true);
  }
}

async function wakeValidation(button) {
  button.disabled = true;
  try {
    const payload = await api("validation/wake", { method: "POST", body: "{}" });
    showToast(payload.message || "Proof worker wake requested");
    await refreshValidation(true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}


function mt5LockedMetrics(item = {}) {
  const report = item.validation_report || {};
  const metrics = report.validation_metrics || {};
  return metrics.standard_cost?.locked_test || {};
}

function setDownloadLink(selector, packageId, suffix = "download") {
  const link = $(selector);
  if (!link) return;
  if (!packageId) {
    link.href = "#";
    link.setAttribute("aria-disabled", "true");
    link.classList.add("disabled-link");
    return;
  }
  link.href = `/api/mt5/packages/${encodeURIComponent(packageId)}/${suffix}`;
  link.removeAttribute("aria-disabled");
  link.classList.remove("disabled-link");
}

function renderMt5Best(item = {}) {
  const hasPackage = Boolean(item.id);
  const locked = mt5LockedMetrics(item);
  setText("#mt5BestName", item.strategy_name || "Waiting for the first package");
  setText("#mt5BestStatus", hasPackage ? "READY TO COMPILE" : "WAITING");
  setClass("#mt5BestStatus", `status-pill ${hasPackage ? "complete" : "waiting"}`);
  setText("#mt5BestVerdict", hasPackage
    ? "EVE generated guarded source from immutable frozen rules. Compile it in MetaEditor and use demo only."
    : "A strategy must finish M1 replay and freeze its rules before code generation.");
  setText("#mt5BestCode", item.strategy_code || "—");
  setText("#mt5BestVersion", item.frozen_version || "—");
  setText("#mt5BestPF", hasPackage ? Number(locked.profit_factor || 0).toFixed(2) : "—");
  setText("#mt5BestExpectancy", hasPackage ? formatR(locked.expectancy_r) : "—");
  setText("#mt5BestTrades", hasPackage ? formatNumber(locked.trades) : "—");
  setText("#mt5BestSha", item.source_sha256 ? `${String(item.source_sha256).slice(0, 12)}…` : "—");
  setDownloadLink("#mt5BestDownload", item.id, "download");
  setDownloadLink("#mt5BestSource", item.id, "source");
}

function renderMt5Status(data = {}) {
  mt5Dashboard = data;
  const state = data.state || {};
  const current = data.current_job || {};
  const status = String(state.status || "waiting");
  setText("#mt5Status", status.toUpperCase());
  setClass("#mt5Status", `status-pill ${["active", "generating"].includes(status) ? "complete" : status}`);
  setText("#mt5Message", state.last_error || "EVE generates versioned MT5 source packages only from frozen strategies.");
  setText("#mt5CurrentJob", current.strategy_name || state.current_job_name || "Waiting for a frozen strategy");
  setText("#mt5Heartbeat", formatDate(state.heartbeat_at, true));
  setText("#mt5Queued", formatNumber(state.queue_count));
  setText("#mt5Completed", formatNumber(state.completed_count));
  setText("#mt5Generated", formatNumber(state.generated_count));
  setText("#mt5Failed", formatNumber(state.failed_count));
  setText("#mt5LastResult", state.last_result || "Only frozen rules can enter this worker.");
  renderMt5Best(data.best_package || {});
  updateCommandCentre();
}

function renderMt5Packages(items = []) {
  mt5PackageItems = items;
  const host = $("#mt5PackageList");
  if (!host) return;
  if (!items.length) {
    host.innerHTML = '<div class="empty-state">No MT5 packages have been generated yet. EVE will build one automatically when a frozen strategy is ready.</div>';
    return;
  }
  host.innerHTML = items.map((item) => {
    const locked = mt5LockedMetrics(item);
    return `<article class="mt5-package-card">
      <div class="mt5-package-head"><div><small>READY FOR METAEDITOR COMPILE</small><h3>${escapeHtml(item.strategy_name || item.strategy_code || "EVE strategy")}</h3></div><span class="status-pill complete">DEMO ONLY</span></div>
      <p>${escapeHtml(item.package_code || "Versioned MT5 package")}</p>
      <div class="strategy-summary-grid mt5-package-metrics">
        <div><small>LOCKED PF</small><strong>${Number(locked.profit_factor || 0).toFixed(2)}</strong></div>
        <div><small>EXPECTANCY</small><strong>${formatR(locked.expectancy_r)}</strong></div>
        <div><small>TRADES</small><strong>${formatNumber(locked.trades)}</strong></div>
        <div><small>VERSION</small><strong>${escapeHtml(item.frozen_version || "1.0")}</strong></div>
      </div>
      <div class="mt5-package-identity"><span>Rule hash</span><strong>${escapeHtml(String(item.rule_hash || "").slice(0, 16))}…</strong><span>Source SHA-256</span><strong>${escapeHtml(String(item.source_sha256 || "").slice(0, 16))}…</strong></div>
      <div class="actions compact-actions">
        <a class="button button-primary" href="/api/mt5/packages/${encodeURIComponent(item.id)}/download">Download package</a>
        <a class="button" href="/api/mt5/packages/${encodeURIComponent(item.id)}/source">Download .mq5</a>
      </div>
    </article>`;
  }).join("");
}

async function refreshMt5(silent = false) {
  try {
    const [statusPayload, packagesPayload] = await Promise.all([
      api("mt5/status?symbol=XAU%2FUSD"),
      api("mt5/packages?symbol=XAU%2FUSD&limit=100"),
    ]);
    renderMt5Status(statusPayload.data || {});
    const items = packagesPayload.data?.items || [];
    renderMt5Packages(items);
    setText("#mt5ExplorerStatus", "READY");
    setClass("#mt5ExplorerStatus", "status-pill complete");
    setText("#mt5ExplorerMessage", `Showing ${formatNumber(items.length)} generated MT5 packages. Frozen rules and checksums are included in every download.`);
  } catch (error) {
    setText("#mt5ExplorerStatus", "ERROR");
    setClass("#mt5ExplorerStatus", "status-pill error");
    setText("#mt5ExplorerMessage", error.message);
    if (!silent) showToast(error.message, true);
  }
}

async function wakeMt5(button) {
  button.disabled = true;
  try {
    const payload = await api("mt5/wake", { method: "POST", body: "{}" });
    showToast(payload.message || "MT5 generator wake requested");
    await refreshMt5(true);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}


function demoStatusClass(status) {
  if (status === "active_now") return "test-now";
  if (status === "attach_now_waiting_market_condition") return "attach-leave";
  if (status === "waiting_for_trading_window") return "wait-time";
  if (status === "waiting_for_period") return "wait-period";
  if (status === "market_closed") return "market-closed";
  return "waiting";
}

function scheduleExplanationForDisplay(item = {}) {
  const explanation = String(item.schedule_explanation || "Frozen schedule unavailable.");
  const rawHour = item.hour_utc;
  if (rawHour == null || rawHour === "" || Number.isNaN(Number(rawHour))) return explanation;
  const now = new Date();
  const utcDate = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), Number(rawHour), 0, 0));
  const london = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Europe/London", timeZoneName: "short" }).format(utcDate);
  return `${explanation} Today that clock time is ${london} in London.`;
}

function fleetPresenceForPackage(packageId) {
  const matches = (fleetDashboard?.items || []).filter((fleetItem) => String(fleetItem.package_id || "") === String(packageId || ""));
  const online = matches.filter((fleetItem) => fleetItem.connection === "online");
  const known = matches.filter((fleetItem) => fleetItem.connection !== "detached");
  return { matches, online, known, count: online.length, duplicate: online.some((fleetItem) => fleetItem.duplicate) };
}

function renderDemoRecommended(item = {}) {
  const hasItem = Boolean(item.package_id);
  const presence = fleetPresenceForPackage(item.package_id);
  const isAttached = presence.count > 0;
  setText("#demoRecommendedName", item.strategy_name || "Waiting for generated EAs");
  setText("#demoRecommendedStatus", isAttached ? "RUNNING IN MT5" : hasItem ? item.status_label : "WAITING");
  setClass("#demoRecommendedStatus", `status-pill ${isAttached ? "complete" : hasItem ? demoStatusClass(item.status) : "waiting"}`);
  setText("#demoRecommendedHeadline", isAttached ? `${presence.count} live MT5 attachment${presence.count === 1 ? " is" : "s are"} already reporting for this bot.` : (item.headline || "EVE will prioritise bots that can actually operate in the current period."));
  setText("#demoRecommendedRule", item.rule_summary || "Frozen rule summary will appear here.");
  setText("#demoRecommendedPF", hasItem ? Number(item.locked_profit_factor || 0).toFixed(2) : "—");
  setText("#demoRecommendedExpectancy", hasItem ? formatR(item.locked_expectancy_r) : "—");
  setText("#demoRecommendedTrades", hasItem ? formatNumber(item.locked_trades) : "—");
  setText("#demoRecommendedChart", item.attach_to || "XAUUSD M5");
  setText("#demoRecommendedAction", isAttached ? "Already attached. Do not attach another copy; monitor it in Demo Fleet." : (item.next_action || "Wait for EVE to finish checking the packages."));
  setDownloadLink("#demoRecommendedDownload", item.package_id, "download");
  setDownloadLink("#demoRecommendedSource", item.package_id, "source");
}

function botMatchesCategory(item, category) {
  if (category === "all") return true;
  if (category === "test_now") return ["active_now", "attach_now_waiting_market_condition"].includes(item.status);
  return (item.usage_tags || []).includes(category);
}

function renderDemoBotList(items = demoBotItems) {
  const host = $("#demoBotList");
  if (!host) return;
  const needle = botLibrarySearch.trim().toLowerCase();
  const filtered = items.filter((item) => {
    if (!botMatchesCategory(item, botLibraryCategory)) return false;
    if (!needle) return true;
    return [item.strategy_name, item.strategy_code, item.package_code, item.usage_title, item.rule_summary]
      .some((value) => String(value || "").toLowerCase().includes(needle));
  });
  const categoryNames = {
    all: "every generated bot",
    test_now: "bots practical to test now",
    everyday: "everyday bots",
    weekday_monday: "Monday bots",
    weekday_tuesday: "Tuesday bots",
    weekday_wednesday: "Wednesday bots",
    weekday_thursday: "Thursday bots",
    weekday_friday: "Friday bots",
    short_window: "short-window bots",
    seasonal: "monthly and seasonal bots",
  };
  setText("#botCategorySummary", `Showing ${formatNumber(filtered.length)} of ${formatNumber(items.length)} — ${categoryNames[botLibraryCategory] || "selected bots"}.`);
  if (!filtered.length) {
    host.innerHTML = '<div class="empty-state">No bots match this schedule category or search.</div>';
    return;
  }
  host.innerHTML = filtered.map((item, index) => {
    const chips = (item.conditions || []).map((condition) => `<span class="demo-condition-chip ${condition.matched ? "match" : "missing"}">${condition.matched ? "✓" : "○"} ${escapeHtml(condition.label)}</span>`).join("");
    const presence = fleetPresenceForPackage(item.package_id);
    const isAttached = presence.count > 0;
    const fleetBanner = isAttached
      ? `<div class="bot-fleet-banner ${presence.duplicate ? "duplicate" : "online"}"><small>MT5 STATUS</small><strong>${presence.duplicate ? "DUPLICATE ATTACHMENTS" : "RUNNING IN MT5"} · ${presence.count} LIVE</strong><span>${presence.duplicate ? "Open Demo Fleet and remove the extra copy." : "EVE is receiving this bot's heartbeat. Do not attach another copy."}</span></div>`
      : "";
    const actions = isAttached
      ? `<div class="actions compact-actions"><a class="button button-primary" href="#demo-fleet">Open Demo Fleet</a><a class="button" href="${escapeHtml(item.download_url || "#")}">Download again only if replacing it</a></div>`
      : `<div class="actions compact-actions"><a class="button button-primary" href="${escapeHtml(item.download_url || "#")}">Download fleet-ready package</a><a class="button" href="${escapeHtml(item.source_url || "#")}">Download fleet-ready .mq5</a></div>`;
    return `<article class="demo-bot-card ${escapeHtml(item.status || "")} ${isAttached ? "already-attached" : ""}" data-package-id="${escapeHtml(item.package_id || "")}">
      <div class="demo-bot-head">
        <div><small>${index === 0 && botLibraryCategory === "test_now" ? "TOP PRACTICAL CHOICE" : escapeHtml(item.package_code || "GENERATED EA")}</small><h3>${escapeHtml(item.strategy_name || item.strategy_code || "EVE strategy")}</h3></div>
        <span class="status-pill ${demoStatusClass(item.status)}">${escapeHtml(item.status_label || "WAITING")}</span>
      </div>
      ${fleetBanner}
      <div class="bot-usage-banner"><small>WHEN THIS BOT IS FOR</small><strong>${escapeHtml(item.usage_title || "General bot")}</strong><span>${escapeHtml(scheduleExplanationForDisplay(item))}</span></div>
      <p class="demo-bot-rule">${escapeHtml(item.rule_summary || "Frozen strategy rules")}</p>
      ${chips ? `<div class="demo-condition-list">${chips}</div>` : ""}
      <div class="strategy-summary-grid demo-bot-metrics">
        <div><small>LOCKED PF</small><strong>${Number(item.locked_profit_factor || 0).toFixed(2)}</strong></div>
        <div><small>EXPECTANCY</small><strong>${formatR(item.locked_expectancy_r)}</strong></div>
        <div><small>TRADES</small><strong>${formatNumber(item.locked_trades)}</strong></div>
      </div>
      <div class="demo-bot-action"><small>WHAT YOU DO</small><strong>${escapeHtml(item.next_action || "Wait for the next eligibility check.")}</strong></div>
      <p><strong>Attach to:</strong> ${escapeHtml(item.attach_to || "XAUUSD M5")}<br><strong>Can it stay attached?</strong> ${escapeHtml(item.attach_guidance || "Yes — frozen filters keep it idle outside its window.")}<br><strong>Demo setting:</strong> ${escapeHtml(item.demo_switch || "Set InpEnableTrading=true")}</p>
      ${actions}
    </article>`;
  }).join("");
}

function renderDemoEligibility(data = {}) {
  demoEligibilityDashboard = data;
  const counts = data.counts || {};
  const open = Boolean(data.market_open_estimate);
  setText("#demoMarketStatus", open ? "MARKET OPEN" : "MARKET CLOSED");
  setClass("#demoMarketStatus", `status-pill ${open ? "complete" : "market-closed"}`);
  setText("#demoMarketHeadline", open ? "Gold is open — EVE has ranked the bots you can test" : "Gold is closed — EVE has calculated the next practical windows");
  setText("#demoMessage", data.disclaimer || "Eligibility is based on each bot's frozen rules and EVE's latest M5 context.");
  setText("#demoUtcNow", data.time?.utc_label || "—");
  setText("#demoUkNow", data.time?.uk_label || "—");
  setText("#demoSnapshotTime", formatDate(data.latest_snapshot_time, true));
  setText("#demoTestNowCount", formatNumber(counts.test_now));
  setText("#demoAttachCount", formatNumber(counts.attach_and_leave));
  setText("#demoWaitingCount", formatNumber(Number(counts.waiting_for_time || 0) + Number(counts.waiting_for_period || 0) + Number(counts.market_closed || 0)));
  renderDemoRecommended(data.recommended || {});
  demoBotItems = data.items || [];
  renderDemoBotList();
  setText("#demoListStatus", "READY");
  setClass("#demoListStatus", "status-pill complete");
  setText("#demoDisclaimer", data.disclaimer || "Demo only.");
  updateCommandCentre();
}

async function refreshDemoEligibility(silent = false) {
  try {
    const payload = await api("mt5/eligibility?symbol=XAU%2FUSD&limit=100");
    renderDemoEligibility(payload.data || {});
  } catch (error) {
    setText("#demoListStatus", "ERROR");
    setClass("#demoListStatus", "status-pill error");
    setText("#demoMessage", error.message);
    if (!silent) showToast(error.message, true);
  }
}

function fleetConnectionClass(connection) {
  if (connection === "online") return "fleet-online";
  if (connection === "stale") return "fleet-stale";
  if (connection === "detached") return "fleet-detached";
  return "fleet-offline";
}

function fleetStateLabel(item) {
  const labels = {
    starting: "Starting",
    running: "Monitoring",
    trading_disabled: "Trading input is OFF",
    position_open: "Position open",
    cooldown: "Cooldown",
    spread_blocked: "Spread safety block",
    daily_loss_guard: "Daily loss guard",
    waiting_anchor: "Waiting for 15-minute checkpoint",
    waiting_rule_condition: "Waiting for frozen setup",
    waiting_direction: "Waiting for direction",
    waiting_data: "Waiting for chart data",
    direction_blocked: "Direction disabled",
    order_failed: "Order failed",
    time_exit: "Time exit completed",
    detached: "Detached",
  };
  return labels[item.state] || String(item.state || "Unknown").replaceAll("_", " ");
}

function renderFleet(data = {}) {
  fleetDashboard = data;
  const counts = data.counts || {};
  if (demoEligibilityDashboard?.recommended) renderDemoRecommended(demoEligibilityDashboard.recommended);
  if (demoBotItems.length) renderDemoBotList();
  const setup = Boolean(data.setup_required);
  const online = Number(counts.online || 0);
  const attention = Number(counts.attention || 0);
  const items = data.items || [];
  const needsConnection = setup || (!online && !items.length);
  setText("#fleetOnlineCount", formatNumber(online));
  setText("#fleetTradeCount", formatNumber(counts.in_trade));
  setText("#fleetAttentionCount", formatNumber(attention));
  setText("#fleetDuplicateCount", formatNumber(counts.duplicates));
  setText("#fleetClosedPnl", formatSignedMoney(data.combined_closed_profit_today || 0));
  setText("#fleetOpenPnl", formatSignedMoney(data.combined_open_profit || 0));
  setText("#fleetHeadline", setup ? "One-time fleet setup is required" : online ? `${online} EVE bot${online === 1 ? " is" : "s are"} attached and reporting` : "EVE can currently see 0 bots");
  setText("#fleetMessage", online ? (data.message || "A bot appears online only while its heartbeat is arriving.") : "This does not mean no bots are attached in MT5. It means no fleet-ready heartbeat is reaching EVE.");
  setText("#fleetOverallStatus", setup ? "SETUP" : attention ? "ATTENTION" : online ? "LIVE" : "WAITING");
  setClass("#fleetOverallStatus", `status-pill ${setup ? "queued" : attention ? "error" : online ? "complete" : "waiting"}`);
  setText("#fleetListStatus", setup ? "SETUP" : online ? "LIVE" : "WAITING");
  setClass("#fleetListStatus", `status-pill ${setup ? "queued" : online ? "complete" : "waiting"}`);
  const setupPanel = $("#fleetSetupPanel");
  if (setupPanel) setupPanel.hidden = !needsConnection;
  setText("#fleetSetupStatus", setup ? "DATABASE" : "CONNECT EAS");
  setHtml("#fleetDatabaseStep", setup ? "<strong>Database:</strong> run SUPABASE_UPDATE_v3.1.sql once, then refresh this page." : "<strong>Database:</strong> ready. Do not run Supabase SQL again.");

  const host = $("#fleetList");
  if (!host) return;
  if (!items.length) {
    host.innerHTML = `<div class="empty-state"><strong>0 bots are visible to EVE.</strong><br>${setup ? "Complete the one-time steps above, then attach a fleet-ready EA." : "Older EAs may still be attached and trading. Download the exact bots again from Bot Factory and replace them only when they have no open trade."}</div>`;
    updateCommandCentre();
    return;
  }
  host.innerHTML = items.map((item) => {
    const isReal = item.account_type === "real";
    const warnings = [];
    if (isReal) warnings.push("REAL ACCOUNT DETECTED — remove this EA. EVE packages are demo-only.");
    if (item.duplicate) warnings.push("Duplicate attachment detected for the same strategy, account, symbol and timeframe.");
    if (item.connection === "online" && !item.trading_enabled) warnings.push("The EA safety input InpEnableTrading is OFF.");
    if (item.connection === "online" && !item.algo_trading_enabled) warnings.push("MT5 Algo Trading is OFF for this EA or terminal.");
    const connectionLabel = String(item.connection || "offline").toUpperCase();
    return `<article class="fleet-card ${escapeHtml(item.connection || "offline")} ${isReal ? "real-account" : ""}">
      <div class="fleet-card-head">
        <div><small>${escapeHtml(item.package_code || item.strategy_code || "EVE BOT")}</small><h3>${escapeHtml(item.strategy_name || item.strategy_code || "EVE strategy")}</h3></div>
        <span class="status-pill ${fleetConnectionClass(item.connection)}">${escapeHtml(connectionLabel)}</span>
      </div>
      ${warnings.map((warning) => `<div class="fleet-warning">${escapeHtml(warning)}</div>`).join("")}
      <div class="fleet-status-line"><small>CURRENT STATE</small><strong>${escapeHtml(fleetStateLabel(item))}${item.state_detail ? ` — ${escapeHtml(item.state_detail)}` : ""}</strong></div>
      <div class="bot-usage-banner"><small>WHEN THIS BOT IS FOR</small><strong>${escapeHtml(item.usage_title || "Schedule unavailable")}</strong><span>${escapeHtml(scheduleExplanationForDisplay(item))}</span></div>
      <div class="fleet-passport">
        <div><small>ACCOUNT</small><strong>${escapeHtml(item.account_login_masked || "—")} · ${escapeHtml(String(item.account_type || "unknown").toUpperCase())}</strong></div>
        <div><small>BROKER</small><strong>${escapeHtml(item.broker_server || item.broker_company || "—")}</strong></div>
        <div><small>CHART</small><strong>${escapeHtml(item.symbol || "—")} · ${escapeHtml(item.timeframe || "—")}</strong></div>
        <div><small>LAST HEARTBEAT</small><strong>${item.heartbeat_age_seconds == null ? "—" : `${Math.round(item.heartbeat_age_seconds)} seconds ago`}</strong></div>
        <div><small>TRADING INPUT</small><strong>${item.trading_enabled ? "ON" : "OFF"}</strong></div>
        <div><small>ALGO TRADING</small><strong>${item.algo_trading_enabled ? "ON" : "OFF"}</strong></div>
      </div>
      <div class="fleet-pnl">
        <div><small>CLOSED TODAY</small><strong>${formatSignedMoney(item.closed_profit_today || 0)}</strong></div>
        <div><small>OPEN NOW</small><strong>${formatSignedMoney(item.open_profit || 0)}</strong></div>
      </div>
    </article>`;
  }).join("");
  updateCommandCentre();
}

async function refreshFleet(silent = false) {
  try {
    const payload = await api("fleet?symbol=XAU%2FUSD&limit=200");
    renderFleet(payload.data || {});
  } catch (error) {
    setText("#fleetOverallStatus", "ERROR");
    setClass("#fleetOverallStatus", "status-pill error");
    setText("#fleetMessage", error.message);
    if (!silent) showToast(error.message, true);
  }
}

function modeForRoute(route) {
  if (route.workspace === "research" || route.workspace === "strategy" || route.workspace === "tester" || route.workspace === "advanced") return "research";
  if (route.workspace === "bot-library" && route.view === "files") return "research";
  return "operator";
}

function setAppMode(mode, { navigate = false } = {}) {
  currentAppMode = mode === "research" ? "research" : "operator";
  localStorage.setItem("eve-app-mode", currentAppMode);
  document.body.dataset.appMode = currentAppMode;
  document.querySelectorAll("[data-app-mode]").forEach((button) => {
    const active = button.dataset.appMode === currentAppMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-mode-nav]").forEach((group) => { group.hidden = group.dataset.modeNav !== currentAppMode; });
  setText("#topbarEyebrow", currentAppMode === "operator" ? "EVE OPERATOR · v3.4" : "EVE RESEARCH ENGINE · v3.4");
  setText("#topbarSummary", currentAppMode === "operator" ? "See only what is running, what is waiting and what you need to do." : "Inspect research, controlled mutations, validation and generated MT5 packages.");
  if (navigate) window.location.hash = currentAppMode === "operator" ? "#home" : "#research";
}

const WORKSPACE_ALIASES = {
  home: "home", overview: "home",
  research: "research", learning: "research",
  "strategy-factory": "strategy", "strategy-lab": "strategy", evolution: "strategy", validation: "strategy",
  "bot-library": "bot-library", "demo-lab": "bot-library", "mt5-lab": "bot-library",
  "demo-fleet": "demo-fleet",
  backtester: "tester",
  advanced: "advanced", foundation: "advanced", memory: "advanced", pipeline: "advanced", activity: "advanced",
};

function parseWorkspaceRoute() {
  const raw = (window.location.hash || "#home").slice(1);
  const [path, query = ""] = raw.split("?");
  const params = new URLSearchParams(query);
  const workspace = WORKSPACE_ALIASES[path] || "home";
  let stage = params.get("stage") || currentFactoryStage;
  if (path === "evolution") stage = "improve";
  if (path === "validation") stage = "prove";
  if (path === "strategy-lab") stage = "build";
  let view = params.get("view") || currentBotView;
  if (path === "mt5-lab") view = "files";
  if (path === "demo-lab" || path === "bot-library") view = "organised";
  return { path, workspace, stage, view };
}

function showWorkspace(workspace, { stage = currentFactoryStage, view = currentBotView, scrollTarget = null } = {}) {
  currentWorkspace = workspace;
  currentFactoryStage = ["build", "improve", "prove"].includes(stage) ? stage : "build";
  currentBotView = ["organised", "files"].includes(view) ? view : "organised";
  document.querySelectorAll("[data-workspace]").forEach((section) => {
    let visible = section.dataset.workspace === currentWorkspace;
    if (visible && currentWorkspace === "strategy" && section.dataset.factoryStage) visible = section.dataset.factoryStage === currentFactoryStage;
    if (visible && currentWorkspace === "bot-library" && section.dataset.botView) visible = section.dataset.botView === currentBotView;
    section.hidden = !visible;
    section.setAttribute("aria-hidden", visible ? "false" : "true");
  });
  document.querySelectorAll("[data-workspace-link]").forEach((link) => {
    const linkView = link.dataset.navView || currentAppMode;
    let active = link.dataset.workspaceLink === currentWorkspace && linkView === currentAppMode;
    if (active && currentWorkspace === "bot-library") active = currentAppMode === "research" ? currentBotView === "files" : currentBotView === "organised";
    link.classList.toggle("active", active);
  });
  document.querySelectorAll("[data-factory-target]").forEach((button) => button.classList.toggle("active", button.dataset.factoryTarget === currentFactoryStage));
  document.querySelectorAll("[data-bot-view-target]").forEach((button) => button.classList.toggle("active", button.dataset.botViewTarget === currentBotView));
  requestAnimationFrame(() => {
    const target = scrollTarget ? document.getElementById(scrollTarget) : null;
    if (target && !target.hidden) target.scrollIntoView({ block: "start" });
    else window.scrollTo({ top: 0, behavior: "auto" });
  });
}

function applyWorkspaceRoute() {
  const route = parseWorkspaceRoute();
  setAppMode(modeForRoute(route));
  if (route.path === "backtester") legacyBacktesterOpen = true;
  showWorkspace(route.workspace, { stage: route.stage, view: route.view, scrollTarget: ["foundation", "memory", "backtester", "pipeline", "activity"].includes(route.path) ? route.path : null });
}

function listen(selector, eventName, handler) {
  const node = $(selector);
  if (node) node.addEventListener(eventName, handler);
}

listen("#queueAllHistory", "click", (event) => queueAllMissingHistory(event.currentTarget));
listen("#syncAllFrames", "click", (event) => queueBatchJobs("sync", event.currentTarget, "Syncing"));
listen("#scanAllFrames", "click", (event) => queueBatchJobs("gap-scan", event.currentTarget, "Scanning"));
listen("#buildLearning", "click", (event) => buildLearning(event.currentTarget));
listen("#runAutonomyNow", "click", (event) => runAutonomyNow(event.currentTarget));
listen("#cancelLearning", "click", (event) => cancelLearning(event.currentTarget));
listen("#refreshLearning", "click", async () => { await refreshLearning(); await refreshDiscoveryExplorer(true); });
listen("#testerStrategy", "change", updateTesterForm);
listen("#testPeriod", "change", updateTesterForm);
listen("#resolutionMode", "change", updateBacktestAvailability);
listen("#runBacktest", "click", (event) => runBacktest(event.currentTarget));
listen("#cancelBacktest", "click", (event) => cancelBacktest(event.currentTarget));
listen("#showLegacyHistory", "click", () => setLegacyHistoryOpen(true));
listen("#hideLegacyHistory", "click", () => setLegacyHistoryOpen(false));
listen("#refreshLegacyHistory", "click", () => fetchLegacyHistory());
listen("#clearLegacySelection", "click", () => {
  clearBacktestWorkspace();
  if (legacyBacktestHistoryOpen) renderLegacyHistory(legacyBacktestRuns);
});
listen("#legacyHistoryList", "click", async (event) => {
  const card = event.target.closest("[data-legacy-run-id]");
  if (!card) return;
  selectedLegacyBacktestId = card.dataset.legacyRunId;
  await loadLegacyBacktest(selectedLegacyBacktestId, { archived: true });
  $("#backtestTitle")?.scrollIntoView({ behavior: "smooth", block: "center" });
});
listen("#refreshButton", "click", async () => {
  await refreshDashboard();
  await refreshLearning(true);
  await refreshDiscoveryExplorer(true);
  await refreshStrategyLab(true);
  await refreshEvolution(true);
  await refreshValidation(true);
  await refreshMt5(true);
  await refreshDemoEligibility(true);
  await refreshFleet(true);
  if (legacyBacktesterOpen && (activeBacktestId || legacyBacktestHistoryOpen)) await refreshBacktests(true);
});
listen("#discoverySort", "change", async (event) => {
  discoveryExplorerOrder = event.currentTarget.value || "confidence";
  selectedDiscoveryId = null;
  await refreshDiscoveryExplorer();
});

document.querySelectorAll("[data-discovery-filter]").forEach((button) => {
  button.addEventListener("click", async () => {
    discoveryExplorerFilter = button.dataset.discoveryFilter || "all";
    selectedDiscoveryId = null;
    document.querySelectorAll("[data-discovery-filter]").forEach((item) => item.classList.toggle("active", item === button));
    await refreshDiscoveryExplorer();
  });
});

listen("#discoveryExplorerList", "click", (event) => {
  const card = event.target.closest("[data-discovery-id]");
  if (!card) return;
  selectedDiscoveryId = card.dataset.discoveryId;
  renderDiscoveryExplorer(discoveryExplorerItems);
});


listen("#wakeStrategyLab", "click", (event) => wakeStrategyLab(event.currentTarget));
listen("#refreshStrategyLab", "click", () => refreshStrategyLab());
listen("#strategySort", "change", async (event) => {
  strategyCandidateOrder = event.currentTarget.value || "profit_factor";
  selectedStrategyCandidateId = null;
  await refreshStrategyLab();
});
document.querySelectorAll("[data-strategy-filter]").forEach((button) => {
  button.addEventListener("click", async () => {
    strategyCandidateFilter = button.dataset.strategyFilter || "all";
    selectedStrategyCandidateId = null;
    document.querySelectorAll("[data-strategy-filter]").forEach((item) => item.classList.toggle("active", item === button));
    await refreshStrategyLab();
  });
});
listen("#strategyCandidateList", "click", (event) => {
  const card = event.target.closest("[data-strategy-id]");
  if (!card) return;
  selectedStrategyCandidateId = card.dataset.strategyId;
  renderStrategyCandidates(strategyCandidateItems);
});

listen("#wakeEvolution", "click", (event) => wakeEvolution(event.currentTarget));
listen("#refreshEvolution", "click", () => refreshEvolution());
listen("#evolutionSort", "change", async (event) => {
  evolutionCandidateOrder = event.currentTarget.value || "validation_improvement";
  selectedEvolutionCandidateId = null;
  await refreshEvolution();
});
document.querySelectorAll("[data-evolution-filter]").forEach((button) => {
  button.addEventListener("click", async () => {
    evolutionCandidateFilter = button.dataset.evolutionFilter || "all";
    selectedEvolutionCandidateId = null;
    document.querySelectorAll("[data-evolution-filter]").forEach((item) => item.classList.toggle("active", item === button));
    await refreshEvolution();
  });
});
listen("#evolutionCandidateList", "click", (event) => {
  const card = event.target.closest("[data-evolution-id]");
  if (!card) return;
  selectedEvolutionCandidateId = card.dataset.evolutionId;
  renderEvolutionCandidates(evolutionCandidateItems);
});


listen("#wakeValidation", "click", (event) => wakeValidation(event.currentTarget));
listen("#refreshValidation", "click", () => refreshValidation());
listen("#wakeMt5", "click", (event) => wakeMt5(event.currentTarget));
listen("#refreshMt5", "click", () => refreshMt5());
listen("#refreshDemoLab", "click", () => refreshDemoEligibility());
listen("#refreshFleet", "click", () => refreshFleet());
listen("#botLibrarySearch", "input", (event) => {
  botLibrarySearch = event.currentTarget.value || "";
  renderDemoBotList();
});
document.querySelectorAll("[data-bot-category]").forEach((button) => {
  button.addEventListener("click", () => {
    botLibraryCategory = button.dataset.botCategory || "all";
    document.querySelectorAll("[data-bot-category]").forEach((item) => item.classList.toggle("active", item === button));
    renderDemoBotList();
  });
});
listen("#validationSort", "change", async (event) => {
  validationJobOrder = event.currentTarget.value || "profit_factor";
  selectedValidationJobId = null;
  await refreshValidation();
});
document.querySelectorAll("[data-validation-filter]").forEach((button) => {
  button.addEventListener("click", async () => {
    validationJobFilter = button.dataset.validationFilter || "all";
    selectedValidationJobId = null;
    document.querySelectorAll("[data-validation-filter]").forEach((item) => item.classList.toggle("active", item === button));
    await refreshValidation();
  });
});
listen("#validationJobList", "click", (event) => {
  const card = event.target.closest("[data-validation-id]");
  if (!card) return;
  selectedValidationJobId = card.dataset.validationId;
  renderValidationJobs(validationJobItems);
});

listen("#openLegacyBacktester", "click", () => setLegacyBacktesterOpen(true));
listen("#closeLegacyBacktester", "click", () => setLegacyBacktesterOpen(false));
document.querySelectorAll("[data-app-mode]").forEach((button) => {
  button.addEventListener("click", () => setAppMode(button.dataset.appMode, { navigate: true }));
});
document.querySelectorAll("[data-workspace-link]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    window.location.hash = link.getAttribute("href");
  });
});
document.querySelectorAll("[data-factory-target]").forEach((button) => {
  button.addEventListener("click", () => {
    currentFactoryStage = button.dataset.factoryTarget || "build";
    window.location.hash = `#strategy-factory?stage=${currentFactoryStage}`;
  });
});
document.querySelectorAll("[data-bot-view-target]").forEach((button) => {
  button.addEventListener("click", () => {
    currentBotView = button.dataset.botViewTarget || "organised";
    window.location.hash = currentBotView === "files" ? "#bot-library?view=files" : "#bot-library";
  });
});
document.querySelectorAll(".advanced-link-grid a").forEach((link) => {
  link.addEventListener("click", () => { currentWorkspace = "advanced"; });
});
window.addEventListener("hashchange", applyWorkspaceRoute);
setAppMode(currentAppMode);
applyWorkspaceRoute();
updateTesterForm();

updateCommandCentre();
(async () => {
  createTimeframeCards();
  await refreshDashboard(true);
  await refreshLearning(true);
  await refreshDiscoveryExplorer(true);
  await refreshStrategyLab(true);
  await refreshEvolution(true);
  await refreshValidation(true);
  await refreshMt5(true);
  await refreshDemoEligibility(true);
  await refreshFleet(true);
  if (window.location.hash === "#backtester") setLegacyBacktesterOpen(true, { scroll: false, updateHash: false });
  updateCommandCentre();
})();
refreshTimer = setInterval(async () => {
  await refreshDashboard(true);
  await refreshLearning(true);
  await refreshStrategyLab(true);
  await refreshEvolution(true);
  await refreshValidation(true);
  await refreshMt5(true);
  await refreshDemoEligibility(true);
  await refreshFleet(true);
  if (legacyBacktesterOpen && (activeBacktestId || legacyBacktestHistoryOpen)) await refreshBacktests(true);
}, 10_000);

discoveryRefreshTimer = setInterval(() => refreshDiscoveryExplorer(true), 30_000);
strategyRefreshTimer = setInterval(() => refreshStrategyLab(true), 30_000);
evolutionRefreshTimer = setInterval(() => refreshEvolution(true), 30_000);
validationRefreshTimer = setInterval(() => refreshValidation(true), 30_000);
mt5RefreshTimer = setInterval(() => refreshMt5(true), 30_000);
demoRefreshTimer = setInterval(() => refreshDemoEligibility(true), 30_000);
fleetRefreshTimer = setInterval(() => refreshFleet(true), 30_000);
