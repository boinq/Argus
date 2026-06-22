import { createMarkerLayer, setupMap } from "./js/map.js";
import { eventDetailHtml } from "./js/event-detail.js";
import { markerFor, markerForObservationStation } from "./js/markers.js";
import {
  renderMlCandidates,
  renderMlOverview,
  renderMlScore,
  renderMlSources,
  renderMlTerms,
} from "./js/ml-panel.js";
import { renderReports as renderReportsPanel, reportEvents as filterReportEvents } from "./js/reports-panel.js";
import { renderSensors as renderSensorsPanel } from "./js/sensors-panel.js?v=20260622-sensors";
import {
  fillSettings,
  renderProxySnippet,
  settingsPayload,
} from "./js/settings-panel.js";
import {
  renderSources as renderSourcesPanel,
  renderSourceSyncTargets as renderSyncTargets,
  updateSourceCountdowns,
} from "./js/sources-panel.js?v=20260621-poll-controls";
import { stationDetailHtml, stationDetailLoadingHtml } from "./js/station-detail.js";
import {
  categoryLabel,
  escapeHtml,
  eventColor,
  formatDate,
} from "./js/utils.js";

const map = setupMap();
const markers = new Map();
const eventMarkerLayer = createMarkerLayer("event");
const observationMarkerLayer = createMarkerLayer("observation");
let events = [];
let activeEventId = null;
let activeView = "events";

const apiStatus = document.querySelector("#api-status");
const eventList = document.querySelector("#event-list");
const summary = document.querySelector("#summary");
const categoryFilter = document.querySelector("#category-filter");
const menuToggle = document.querySelector("#menu-toggle");
const sideMenu = document.querySelector("#side-menu");
const menuScrim = document.querySelector("#menu-scrim");
const menuItems = document.querySelectorAll(".menu-item[data-view]");
const eventsView = document.querySelector("#events-view");
const sensorsView = document.querySelector("#sensors-view");
const sourcesView = document.querySelector("#sources-view");
const reportsView = document.querySelector("#reports-view");
const mlView = document.querySelector("#ml-view");
const settingsView = document.querySelector("#settings-view");
const settingsForm = document.querySelector("#settings-form");
const settingsNote = document.querySelector("#settings-note");
const proxySnippet = document.querySelector("#proxy-snippet");
const publicBaseUrl = document.querySelector("#public-base-url");
const pathPrefix = document.querySelector("#path-prefix");
const trustedHosts = document.querySelector("#trusted-hosts");
const proxyHeaders = document.querySelector("#proxy-headers");
const ntfyEnabled = document.querySelector("#ntfy-enabled");
const ntfyServerUrl = document.querySelector("#ntfy-server-url");
const ntfyTopic = document.querySelector("#ntfy-topic");
const ntfyToken = document.querySelector("#ntfy-token");
const ntfyPriority = document.querySelector("#ntfy-priority");
const resetDatabase = document.querySelector("#reset-database");
const reportScope = document.querySelector("#report-scope");
const reportCategory = document.querySelector("#report-category");
const reportSummary = document.querySelector("#report-summary");
const reportBrief = document.querySelector("#report-brief");
const reportList = document.querySelector("#report-list");
const refreshReport = document.querySelector("#refresh-report");
const refreshSensors = document.querySelector("#refresh-sensors");
const sensorNote = document.querySelector("#sensor-note");
const sensorSummary = document.querySelector("#sensor-summary");
const sensorList = document.querySelector("#sensor-list");
const sourceFilter = document.querySelector("#source-filter");
const sourceSummary = document.querySelector("#source-summary");
const sourceList = document.querySelector("#source-list");
const sourceNote = document.querySelector("#source-note");
const observationNote = document.querySelector("#observation-note");
const syncSource = document.querySelector("#sync-source");
const sourceSyncTarget = document.querySelector("#source-sync-target");
const mlRefresh = document.querySelector("#ml-refresh");
const mlNote = document.querySelector("#ml-note");
const mlSummary = document.querySelector("#ml-summary");
const mlScoreText = document.querySelector("#ml-score-text");
const mlScoreButton = document.querySelector("#ml-score-button");
const mlScoreResult = document.querySelector("#ml-score-result");
const mlSourceFilter = document.querySelector("#ml-source-filter");
const mlCandidateList = document.querySelector("#ml-candidate-list");
const mlTermList = document.querySelector("#ml-term-list");
const mlClearLearned = document.querySelector("#ml-clear-learned");
const layerCount = document.querySelector("#layer-count");
const layersAll = document.querySelector("#layers-all");
const layersNone = document.querySelector("#layers-none");
const observationLayerToggle = document.querySelector("#observation-layer-toggle");
const categoryLayerOptions = document.querySelector("#category-layer-options");
const sourceLayerOptions = document.querySelector("#source-layer-options");
const timelineRange = document.querySelector("#timeline-range");
const timelineLabel = document.querySelector("#timeline-label");
const timelineReset = document.querySelector("#timeline-reset");
const timelineStart = document.querySelector("#timeline-start");
const timelineEnd = document.querySelector("#timeline-end");
const timelineWindowButtons = document.querySelectorAll("[data-timeline-window]");
const eventDetailDrawer = document.querySelector("#event-detail-drawer");
const eventDetailBody = document.querySelector("#event-detail-body");
let sources = [];
let sensors = [];
let schedulerJobs = [];
let observations = [];
let observationStations = [];
let dataMarkers = [];
let activeStationId = null;
let knownLayerCategories = new Set();
let knownLayerSources = new Set();
let enabledLayerCategories = new Set();
let enabledLayerSources = new Set();
let sourceRefreshTimer = null;
let sourceCountdownTimer = null;
let mlOverview = null;
let mlCandidates = [];
let mlTerms = [];
let timelineValue = null;
let timelineWindowStart = null;
let timelineWindowDays = null;
let timelineBounds = null;

const settingsElements = {
  publicBaseUrl,
  pathPrefix,
  trustedHosts,
  proxyHeaders,
  ntfyEnabled,
  ntfyServerUrl,
  ntfyTopic,
  ntfyToken,
  ntfyPriority,
};

const reportElements = {
  scope: reportScope,
  category: reportCategory,
  summary: reportSummary,
  brief: reportBrief,
  list: reportList,
};

const sourceElements = {
  filter: sourceFilter,
  summary: sourceSummary,
  list: sourceList,
};

const sourceSyncElements = {
  target: sourceSyncTarget,
  button: syncSource,
};

const sensorElements = {
  summary: sensorSummary,
  list: sensorList,
};

function filteredEvents() {
  const category = categoryFilter.value;
  const timeItems = timelineFilteredEvents(events);
  return category === "all"
    ? timeItems
    : timeItems.filter((event) => event.category === category);
}

function timelineFilteredEvents(items) {
  if (timelineWindowStart !== null && timelineBounds) {
    return items.filter((event) => eventOverlapsRange(event, timelineWindowStart, timelineBounds.max));
  }
  if (timelineValue === null) {
    return items;
  }
  return items.filter((event) => eventActiveAt(event, timelineValue));
}

function eventActiveAt(event, timestamp) {
  const startsAt = Date.parse(event.starts_at);
  if (!Number.isFinite(startsAt) || startsAt > timestamp) {
    return false;
  }
  const endsAt = event.ends_at ? Date.parse(event.ends_at) : Number.POSITIVE_INFINITY;
  return !Number.isFinite(endsAt) || endsAt >= timestamp;
}

function eventOverlapsRange(event, startTimestamp, endTimestamp) {
  const startsAt = Date.parse(event.starts_at);
  if (!Number.isFinite(startsAt)) {
    return false;
  }
  const endsAt = event.ends_at ? Date.parse(event.ends_at) : Number.POSITIVE_INFINITY;
  return startsAt <= endTimestamp && endsAt >= startTimestamp;
}

function eventContributesToTimelineBounds(event) {
  const source = String(event.source || "").toLowerCase();
  return event.category !== "maritime" && !source.includes("maritime") && !source.includes("niord");
}

function timelineRangeEvents() {
  const rangeEvents = events.filter(eventContributesToTimelineBounds);
  const sourceEvents = rangeEvents.length ? rangeEvents : events;
  const startTimestamps = sourceEvents
    .map((event) => Date.parse(event.starts_at))
    .filter((value) => Number.isFinite(value));
  if (startTimestamps.length === 0) {
    return null;
  }
  const endTimestamps = sourceEvents
    .map((event) => Date.parse(event.ends_at || event.starts_at))
    .filter((value) => Number.isFinite(value));
  return {
    min: Math.min(...startTimestamps),
    max: Math.max(...endTimestamps, ...startTimestamps),
  };
}

function syncTimelineControl() {
  if (!timelineRange || !timelineLabel || !timelineStart || !timelineEnd || !timelineReset) {
    return;
  }
  timelineBounds = timelineRangeEvents();
  if (!timelineBounds) {
    timelineValue = null;
    timelineWindowStart = null;
    timelineWindowDays = null;
    timelineRange.disabled = true;
    timelineRange.min = "0";
    timelineRange.max = "0";
    timelineRange.value = "0";
    timelineLabel.textContent = "All time";
    timelineStart.textContent = "No events";
    timelineEnd.textContent = "No events";
    timelineReset.disabled = true;
    timelineWindowButtons.forEach((button) => {
      button.classList.remove("active");
      button.disabled = true;
    });
    return;
  }

  if (timelineValue !== null) {
    timelineValue = Math.min(Math.max(timelineValue, timelineBounds.min), timelineBounds.max);
  }
  if (timelineWindowStart !== null) {
    timelineWindowStart = Math.min(Math.max(timelineWindowStart, timelineBounds.min), timelineBounds.max);
  }

  timelineRange.disabled = false;
  timelineRange.min = String(timelineBounds.min);
  timelineRange.max = String(timelineBounds.max);
  timelineRange.value = String(timelineValue ?? timelineWindowStart ?? timelineBounds.max);
  timelineLabel.textContent = timelineLabelText();
  timelineStart.textContent = formatDate(new Date(timelineBounds.min).toISOString());
  timelineEnd.textContent = formatDate(new Date(timelineBounds.max).toISOString());
  timelineReset.disabled = timelineValue === null && timelineWindowStart === null;
  timelineWindowButtons.forEach((button) => {
    const days = Number(button.dataset.timelineWindow);
    button.classList.toggle("active", timelineWindowDays === days);
    button.disabled = !timelineBounds;
  });
}

function timelineLabelText() {
  if (timelineWindowStart !== null && timelineBounds) {
    return `Since ${formatDate(new Date(timelineWindowStart).toISOString())}`;
  }
  return timelineValue === null ? "All time" : formatDate(new Date(timelineValue).toISOString());
}

function timelineWindowStartForDays(days) {
  if (!timelineBounds || !Number.isFinite(days)) {
    return null;
  }
  const duration = days * 24 * 60 * 60 * 1000;
  return Math.max(timelineBounds.min, timelineBounds.max - duration);
}

function currentEventPool() {
  return timelineFilteredEvents(events);
}

function mapLayerEvents(items) {
  syncLayerSelections();
  return items.filter(
    (event) =>
      enabledLayerCategories.has(event.category) && enabledLayerSources.has(event.source),
  );
}

function currentMapBaseEvents() {
  if (activeView === "reports") {
    return reportEvents();
  }
  if (activeView === "sources") {
    return currentEventPool();
  }
  return filteredEvents();
}

function syncLayerSelections() {
  const categories = [...new Set(events.map((event) => event.category))].sort();
  const sourceNames = sources.map((source) => source.name);
  const eventSources = [...new Set([...events.map((event) => event.source), ...sourceNames])].sort();
  categories.forEach((category) => {
    if (!knownLayerCategories.has(category)) {
      knownLayerCategories.add(category);
      enabledLayerCategories.add(category);
    }
  });
  eventSources.forEach((source) => {
    if (!knownLayerSources.has(source)) {
      knownLayerSources.add(source);
      enabledLayerSources.add(source);
    }
  });
}

function renderSummary(items) {
  const counts = {
    current: items.filter((event) => event.status === "current").length,
    upcoming: items.filter((event) => event.status === "upcoming").length,
    high: items.filter((event) => ["high", "critical"].includes(event.severity)).length,
    total: items.length,
  };

  summary.innerHTML = [
    ["Current", counts.current],
    ["Upcoming", counts.upcoming],
    ["High Risk", counts.high],
    ["Total", counts.total],
  ]
    .map(
      ([label, count]) => `
        <div class="summary-item">
          <strong>${count}</strong>
          <span>${label}</span>
        </div>
      `,
    )
    .join("");
}

function renderMap(items) {
  eventMarkerLayer.clearLayers();
  markers.clear();
  if (!map.hasLayer(eventMarkerLayer)) {
    eventMarkerLayer.addTo(map);
  }

  if (shouldShowObservationLayer()) {
    renderObservationLayer(observationStations);
  } else {
    clearObservationLayer();
  }

  items.forEach((event) => {
    const marker = markerFor(event);
    marker.on("click", () => setActiveEvent(event.id, true));
    marker.on("popupopen", () => bindPopupAction(marker));
    markers.set(event.id, marker);
    eventMarkerLayer.addLayer(marker);
  });
  renderLayerControls(items.length);
}

function shouldShowObservationLayer() {
  return (
    observationLayerToggle.checked &&
    (activeView === "events" || activeView === "sources")
  );
}

function renderLayerControls(visibleEventCount = markers.size) {
  if (!categoryLayerOptions || !sourceLayerOptions || !layerCount) {
    return;
  }
  syncLayerSelections();
  const categories = [...knownLayerCategories].sort();
  const eventSources = [...knownLayerSources].sort();
  const layerCountBase = currentEventPool();
  const observationCount = shouldShowObservationLayer() ? observationStations.length : 0;
  layerCount.textContent = `${visibleEventCount + observationCount} shown`;
  categoryLayerOptions.innerHTML = categories
    .map((category) =>
      layerOption({
        kind: "category",
        value: category,
        label: categoryLabel(category),
        checked: enabledLayerCategories.has(category),
        count: layerCountBase.filter((event) => event.category === category).length,
      }),
    )
    .join("");
  sourceLayerOptions.innerHTML = eventSources
    .map((source) =>
      layerOption({
        kind: "source",
        value: source,
        label: source,
        checked: enabledLayerSources.has(source),
        count: layerCountBase.filter((event) => event.source === source).length,
      }),
    )
    .join("");
}

function layerOption({ kind, value, label, checked, count }) {
  return `
    <label class="layer-toggle">
      <input
        type="checkbox"
        data-layer-kind="${escapeHtml(kind)}"
        data-layer-value="${escapeHtml(value)}"
        ${checked ? "checked" : ""}
      />
      <span>${escapeHtml(label)}</span>
      <small>${count}</small>
    </label>
  `;
}

function renderObservationLayer(items) {
  clearObservationLayer();
  if (!map.hasLayer(observationMarkerLayer)) {
    observationMarkerLayer.addTo(map);
  }
  dataMarkers = items.map((station) => {
    const marker = markerForObservationStation(station);
    const openObservation = () => {
      map.panTo([station.latitude, station.longitude], { animate: true });
      marker.openPopup();
      renderStationDetail(station);
    };
    marker.on("click", openObservation);
    marker.on("popupopen", () => bindStationPopupAction(marker));
    marker.on("keypress", (event) => {
      if (event.originalEvent.key === "Enter" || event.originalEvent.key === " ") {
        openObservation();
      }
    });
    observationMarkerLayer.addLayer(marker);
    return marker;
  });
}

function clearObservationLayer() {
  observationMarkerLayer.clearLayers();
  dataMarkers = [];
}

function renderEvents(items) {
  if (items.length === 0) {
    eventList.innerHTML = '<p class="empty">No events match this filter.</p>';
    return;
  }

  eventList.innerHTML = items
    .map(
      (event) => `
        <article
          class="event-card ${event.id === activeEventId ? "active" : ""}"
          style="border-left-color: ${eventColor(event)}"
          data-event-id="${event.id}"
          tabindex="0"
        >
          <h3>${escapeHtml(event.title)}</h3>
          <div class="event-meta">
            <span class="tag">${escapeHtml(event.category)}</span>
            <span class="tag">${escapeHtml(event.severity)}</span>
            <span class="tag">${escapeHtml(event.status)}</span>
          </div>
          <p>${escapeHtml(event.description)}</p>
          <div class="event-time">
            Starts ${formatDate(event.starts_at)}
          </div>
        </article>
      `,
    )
    .join("");

  eventList.querySelectorAll(".event-card").forEach((card) => {
    const eventId = Number(card.dataset.eventId);
    card.addEventListener("click", () => setActiveEvent(eventId, true));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        setActiveEvent(eventId, true);
      }
    });
  });
}

function setActiveEvent(eventId, openPopup) {
  activeEventId = eventId;
  const event = events.find((item) => item.id === eventId);
  const marker = markers.get(eventId);
  if (event) {
    renderEventDetail(event);
  }
  if (event && marker) {
    const reveal = () => {
      map.setView([event.latitude, event.longitude], Math.max(map.getZoom(), 8), {
        animate: true,
      });
      if (openPopup) {
        marker.openPopup();
      }
    };
    if (typeof eventMarkerLayer.zoomToShowLayer === "function") {
      eventMarkerLayer.zoomToShowLayer(marker, reveal);
    } else {
      reveal();
    }
  }
  renderEvents(filteredEvents());
  scrollActiveEventIntoView();
}

function scrollActiveEventIntoView() {
  const activeCard = eventList.querySelector(".event-card.active");
  if (activeCard && activeView === "events") {
    activeCard.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

function bindPopupAction(marker) {
  const element = marker.getPopup()?.getElement();
  const button = element?.querySelector("[data-popup-event-id]");
  if (!button) {
    return;
  }
  button.onclick = () => {
    const eventId = Number(button.dataset.popupEventId);
    categoryFilter.value = "all";
    setView("events");
    setActiveEvent(eventId, true);
  };
}

function bindStationPopupAction(marker) {
  const element = marker.getPopup()?.getElement();
  const button = element?.querySelector("[data-popup-station-id]");
  if (!button) {
    return;
  }
  button.onclick = () => {
    const station = observationStations.find((item) => item.station_id === button.dataset.popupStationId);
    if (station) {
      renderStationDetail(station);
    }
  };
}

function renderEventDetail(event) {
  activeStationId = null;
  eventDetailBody.innerHTML = eventDetailHtml(event, { events, sources });
  eventDetailDrawer.hidden = false;
}

function closeEventDetail() {
  eventDetailDrawer.hidden = true;
  activeStationId = null;
}

async function renderStationDetail(station) {
  activeEventId = null;
  activeStationId = station.station_id;
  eventDetailBody.innerHTML = stationDetailLoadingHtml(station);
  eventDetailDrawer.hidden = false;
  try {
    const response = await fetch(
      `api/observations?source_id=dmi-metobs&station_id=${encodeURIComponent(station.station_id)}&limit=2000`,
    );
    if (!response.ok) {
      throw new Error(`Observations API responded with ${response.status}`);
    }
    const history = await response.json();
    eventDetailBody.innerHTML = stationDetailHtml(station, history);
  } catch (error) {
    eventDetailBody.innerHTML = stationDetailHtml(station, []);
    const note = document.createElement("p");
    note.className = "settings-note error";
    note.textContent = error.message;
    eventDetailBody.appendChild(note);
  }
}

function focusActiveEvent() {
  if (activeEventId === null) {
    return;
  }
  setActiveEvent(activeEventId, true);
}

function focusStation(stationId) {
  const station = observationStations.find((item) => item.station_id === stationId);
  if (!station) {
    return;
  }
  map.setView([station.latitude, station.longitude], Math.max(map.getZoom(), 9), {
    animate: true,
  });
}

async function refreshActiveStationDetail() {
  if (!activeStationId) {
    return;
  }
  const station = observationStations.find((item) => item.station_id === activeStationId);
  if (station) {
    await renderStationDetail(station);
  }
}

function showActiveEventInFeed() {
  if (activeEventId === null) {
    return;
  }
  categoryFilter.value = "all";
  setView("events");
  renderEvents(filteredEvents());
  scrollActiveEventIntoView();
}

function refreshActiveEventDetail() {
  if (eventDetailDrawer.hidden || activeEventId === null) {
    return;
  }
  const event = events.find((item) => item.id === activeEventId);
  if (event) {
    renderEventDetail(event);
  } else {
    closeEventDetail();
  }
}

function render() {
  syncTimelineControl();
  const items = filteredEvents();
  renderSummary(items);
  renderMap(mapLayerEvents(currentMapBaseEvents()));
  renderEvents(items);
  renderReports();
  renderSources();
  refreshActiveEventDetail();
}

async function loadEvents() {
  try {
    const response = await fetch("api/events");
    if (!response.ok) {
      throw new Error(`API responded with ${response.status}`);
    }
    events = await response.json();
    apiStatus.textContent = "Online";
    apiStatus.classList.remove("error");
    render();
  } catch (error) {
    apiStatus.textContent = "Offline";
    apiStatus.classList.add("error");
    eventList.innerHTML = `<p class="empty">${escapeHtml(error.message)}</p>`;
  }
}

async function loadSettings() {
  try {
    const response = await fetch("api/settings");
    if (!response.ok) {
      throw new Error(`API responded with ${response.status}`);
    }
    const settings = await response.json();
    fillSettings(settings, settingsElements);
    renderProxySnippet(settings, proxySnippet);
    settingsNote.textContent = "Settings loaded.";
    settingsNote.classList.remove("error");
  } catch (error) {
    settingsNote.textContent = error.message;
    settingsNote.classList.add("error");
  }
}

async function loadSources() {
  try {
    const [sourcesResponse, schedulerResponse] = await Promise.all([
      fetch("api/sources"),
      fetch("api/scheduler/jobs"),
    ]);
    if (!sourcesResponse.ok) {
      throw new Error(`Sources API responded with ${sourcesResponse.status}`);
    }
    if (!schedulerResponse.ok) {
      throw new Error(`Scheduler API responded with ${schedulerResponse.status}`);
    }
    sources = await sourcesResponse.json();
    schedulerJobs = await schedulerResponse.json();
    renderSourceSyncTargets();
    sourceNote.textContent = "";
    sourceNote.classList.remove("error");
    renderSources();
    await loadObservations();
  } catch (error) {
    sourceNote.textContent = error.message;
    sourceNote.classList.add("error");
  }
}

async function loadSensors() {
  try {
    const response = await fetch("api/sensors");
    if (!response.ok) {
      throw new Error(`Sensors API responded with ${response.status}`);
    }
    sensors = await response.json();
    sensorNote.textContent = sensors.length
      ? `${sensors.length} sensor${sensors.length === 1 ? "" : "s"} have posted acquisitions.`
      : "No sensors have posted acquisitions yet.";
    sensorNote.classList.remove("error");
    renderSensors();
  } catch (error) {
    sensorNote.textContent = error.message;
    sensorNote.classList.add("error");
  }
}

async function refreshSchedulerJobs() {
  if (activeView !== "sources") {
    return;
  }
  try {
    const response = await fetch("api/scheduler/jobs");
    if (!response.ok) {
      throw new Error(`Scheduler API responded with ${response.status}`);
    }
    schedulerJobs = await response.json();
    renderSourceSyncTargets();
    renderSources();
  } catch (error) {
    sourceNote.textContent = error.message;
    sourceNote.classList.add("error");
  }
}

async function setSourcePolling(button) {
  const jobId = button.dataset.sourcePollJob;
  const action = button.dataset.sourcePollAction;
  if (!jobId || !["pause", "resume"].includes(action)) {
    return;
  }
  button.disabled = true;
  sourceNote.textContent = `${action === "pause" ? "Pausing" : "Resuming"} polling...`;
  sourceNote.classList.remove("error");
  try {
    const response = await fetch(
      `api/scheduler/jobs/${encodeURIComponent(jobId)}/${action}`,
      { method: "POST" },
    );
    if (!response.ok) {
      throw new Error(`Scheduler API responded with ${response.status}`);
    }
    const updatedJob = await response.json();
    schedulerJobs = schedulerJobs.map((job) => (job.id === updatedJob.id ? updatedJob : job));
    renderSourceSyncTargets();
    renderSources();
    sourceNote.textContent = action === "pause" ? "Polling paused." : "Polling resumed.";
    sourceNote.classList.remove("error");
  } catch (error) {
    sourceNote.textContent = error.message;
    sourceNote.classList.add("error");
  } finally {
    button.disabled = false;
  }
}

async function loadMl() {
  try {
    if (!sources.length) {
      await loadSources();
    }
    const query = mlSourceFilter.value
      ? `?source_id=${encodeURIComponent(mlSourceFilter.value)}`
      : "";
    const [overviewResponse, candidatesResponse, termsResponse] = await Promise.all([
      fetch("api/ml/overview"),
      fetch(`api/ml/candidates${query}`),
      fetch(`api/ml/terms${query}`),
    ]);
    if (!overviewResponse.ok || !candidatesResponse.ok || !termsResponse.ok) {
      throw new Error("ML API request failed.");
    }
    mlOverview = await overviewResponse.json();
    mlCandidates = await candidatesResponse.json();
    mlTerms = await termsResponse.json();
    renderMlSources(sources, mlSourceFilter);
    renderMl();
    mlNote.textContent = "ML state loaded.";
    mlNote.classList.remove("error");
  } catch (error) {
    mlNote.textContent = error.message;
    mlNote.classList.add("error");
  }
}

function renderMl() {
  if (!mlOverview) {
    return;
  }
  renderMlOverview(mlOverview, mlSummary);
  renderMlCandidates(mlCandidates, mlCandidateList);
  renderMlTerms(mlTerms, mlTermList);
}

async function scoreMlText() {
  const text = mlScoreText.value.trim();
  if (!text) {
    return;
  }
  mlScoreButton.disabled = true;
  try {
    const response = await fetch("api/ml/score", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) {
      throw new Error(`ML API responded with ${response.status}`);
    }
    renderMlScore(await response.json(), mlScoreResult);
  } catch (error) {
    mlScoreResult.innerHTML = `<p class="empty">${escapeHtml(error.message)}</p>`;
  } finally {
    mlScoreButton.disabled = false;
  }
}

async function promoteMlCandidate(button) {
  const card = button.closest("[data-ml-candidate]");
  const field = (name) => card.querySelector(`[data-ml-field="${name}"]`)?.value || "";
  const payload = {
    source_id: button.dataset.sourceId,
    term: button.dataset.term,
    rule_group: field("rule-group"),
    category: field("category"),
    severity: field("severity"),
    score: Number(field("score") || 1),
  };
  button.disabled = true;
  try {
    const response = await fetch("api/ml/terms/promote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(`ML API responded with ${response.status}`);
    }
    mlNote.textContent = "Candidate promoted to active rule.";
    mlNote.classList.remove("error");
    await loadMl();
  } catch (error) {
    mlNote.textContent = error.message;
    mlNote.classList.add("error");
  } finally {
    button.disabled = false;
  }
}

async function clearLearnedMlRules() {
  if (!window.confirm("Delete active rules whose source is marked learned? Reviewed rules and candidates remain.")) {
    return;
  }
  mlClearLearned.disabled = true;
  try {
    const response = await fetch("api/ml/terms/learned", { method: "DELETE" });
    if (!response.ok) {
      throw new Error(`ML API responded with ${response.status}`);
    }
    const result = await response.json();
    mlNote.textContent = `${result.deleted} learned active rules deleted.`;
    mlNote.classList.remove("error");
    await loadMl();
  } catch (error) {
    mlNote.textContent = error.message;
    mlNote.classList.add("error");
  } finally {
    mlClearLearned.disabled = false;
  }
}

async function loadObservations() {
  try {
    const response = await fetch("api/observations?source_id=dmi-metobs&limit=2000");
    if (!response.ok) {
      throw new Error(`Observations API responded with ${response.status}`);
    }
    observations = await response.json();
    observationStations = groupObservationStations(observations);
    observationNote.textContent =
      observationStations.length > 0
        ? `${observationStations.length} DMI stations plotted from ${observations.length} recent observations.`
        : "No DMI observations stored yet.";
    observationNote.classList.remove("error");
    if (shouldShowObservationLayer()) {
      renderMap(mapLayerEvents(currentMapBaseEvents()));
    } else {
      renderLayerControls(markers.size);
    }
    await refreshActiveStationDetail();
  } catch (error) {
    observationNote.textContent = error.message;
    observationNote.classList.add("error");
  }
}

function groupObservationStations(items) {
  const stations = new Map();
  items.forEach((observation) => {
    const existing = stations.get(observation.station_id) || {
      station_id: observation.station_id,
      latitude: observation.latitude,
      longitude: observation.longitude,
      latest_observed_at: observation.observed_at,
      observation_count: 0,
      parametersById: new Map(),
    };
    existing.observation_count += 1;
    if (new Date(observation.observed_at) > new Date(existing.latest_observed_at)) {
      existing.latest_observed_at = observation.observed_at;
      existing.latitude = observation.latitude;
      existing.longitude = observation.longitude;
    }

    const currentParameter = existing.parametersById.get(observation.parameter_id);
    if (
      !currentParameter ||
      new Date(observation.observed_at) > new Date(currentParameter.observed_at)
    ) {
      existing.parametersById.set(observation.parameter_id, observation);
    }
    stations.set(observation.station_id, existing);
  });

  return [...stations.values()].map((station) => ({
    station_id: station.station_id,
    latitude: station.latitude,
    longitude: station.longitude,
    latest_observed_at: station.latest_observed_at,
    observation_count: station.observation_count,
    parameters: [...station.parametersById.values()].sort((a, b) =>
      a.parameter_id.localeCompare(b.parameter_id),
    ),
  }));
}

async function syncSelectedSource() {
  const jobId = sourceSyncTarget.value;
  if (!jobId) {
    return;
  }
  syncSource.disabled = true;
  sourceNote.textContent = "Syncing selected source...";
  sourceNote.classList.remove("error");
  try {
    const response = await fetch(`api/scheduler/jobs/${encodeURIComponent(jobId)}/run`, {
      method: "POST",
    });
    if (!response.ok) {
      throw new Error(`API responded with ${response.status}`);
    }
    const result = await response.json();
    sourceNote.textContent =
      `${result.message} ${result.observations_stored} new observations, ` +
      `${result.events_created} events created, ${result.events_updated} updated.`;
    await loadSources();
    await loadEvents();
    await loadObservations();
  } catch (error) {
    sourceNote.textContent = error.message;
    sourceNote.classList.add("error");
  } finally {
    syncSource.disabled = sourceSyncTarget.value === "";
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const payload = settingsPayload(settingsElements);

  try {
    const response = await fetch("api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(`API responded with ${response.status}`);
    }
    const settings = await response.json();
    fillSettings(settings, settingsElements);
    renderProxySnippet(settings, proxySnippet);
    settingsNote.textContent = "Settings saved. Restart the container after changing proxy runtime values.";
    settingsNote.classList.remove("error");
  } catch (error) {
    settingsNote.textContent = error.message;
    settingsNote.classList.add("error");
  }
}

async function resetDatabaseFromSettings() {
  const confirmed = window.confirm(
    "Clear the entire local database? This removes events, raw source data, learned terms, locations, settings, and history.",
  );
  if (!confirmed) {
    return;
  }
  resetDatabase.disabled = true;
  settingsNote.textContent = "Clearing database...";
  settingsNote.classList.remove("error");
  try {
    const response = await fetch("api/debug/reset-database", { method: "POST" });
    if (!response.ok) {
      throw new Error(`API responded with ${response.status}`);
    }
    events = [];
    timelineValue = null;
    timelineWindowStart = null;
    timelineWindowDays = null;
    timelineBounds = null;
    observations = [];
    observationStations = [];
    sources = [];
    sensors = [];
    schedulerJobs = [];
    knownLayerCategories.clear();
    knownLayerSources.clear();
    enabledLayerCategories.clear();
    enabledLayerSources.clear();
    activeEventId = null;
    activeStationId = null;
    closeEventDetail();
    settingsNote.textContent = "Database cleared. Sources and default settings were reinitialized.";
    await loadSettings();
    await loadSources();
    await loadEvents();
  } catch (error) {
    settingsNote.textContent = error.message;
    settingsNote.classList.add("error");
  } finally {
    resetDatabase.disabled = false;
  }
}

function reportEvents() {
  return filterReportEvents(currentEventPool(), {
    scope: reportScope.value,
    category: reportCategory.value,
  });
}

function renderReports() {
  renderReportsPanel(currentEventPool(), reportElements);
}

function renderSources() {
  renderSourcesPanel(sources, schedulerJobs, sourceElements);
  updateSourceCountdowns(sourceList);
}

function renderSensors() {
  renderSensorsPanel(sensors, sensorElements);
}

function renderSourceSyncTargets() {
  renderSyncTargets(schedulerJobs, sourceSyncElements);
}

function setView(viewName) {
  activeView = viewName;
  eventsView.hidden = viewName !== "events";
  sensorsView.hidden = viewName !== "sensors";
  sourcesView.hidden = viewName !== "sources";
  reportsView.hidden = viewName !== "reports";
  mlView.hidden = viewName !== "ml";
  settingsView.hidden = viewName !== "settings";
  menuItems.forEach((item) => {
    item.classList.toggle("active", item.dataset.view === viewName);
  });
  setMenuOpen(false);
  if (viewName === "settings") {
    loadSettings();
  }
  if (viewName === "sources") {
    loadSources();
  }
  if (viewName === "sensors") {
    loadSensors();
  }
  if (viewName === "ml") {
    loadMl();
  }
  if (viewName === "reports") {
    renderReports();
    renderMap(mapLayerEvents(currentMapBaseEvents()));
  } else if (viewName === "sources") {
    renderSources();
    renderMap(mapLayerEvents(currentMapBaseEvents()));
  } else if (viewName === "sensors") {
    renderSensors();
    renderMap(mapLayerEvents(currentMapBaseEvents()));
  } else if (viewName === "ml") {
    renderMap(mapLayerEvents(currentMapBaseEvents()));
  } else {
    renderMap(mapLayerEvents(currentMapBaseEvents()));
  }
}

function startSourceTimers() {
  sourceCountdownTimer = window.setInterval(() => {
    if (activeView === "sources") {
      updateSourceCountdowns(sourceList);
    }
  }, 1000);
  sourceRefreshTimer = window.setInterval(() => {
    refreshSchedulerJobs();
    if (activeView === "sensors") {
      loadSensors();
    }
  }, 30000);
}

categoryFilter.addEventListener("change", render);
observationLayerToggle.addEventListener("change", () => {
  renderMap(mapLayerEvents(currentMapBaseEvents()));
});
categoryLayerOptions.addEventListener("change", (event) => {
  if (!event.target.matches("[data-layer-kind='category']")) {
    return;
  }
  const value = event.target.dataset.layerValue;
  if (event.target.checked) {
    enabledLayerCategories.add(value);
  } else {
    enabledLayerCategories.delete(value);
  }
  renderMap(mapLayerEvents(currentMapBaseEvents()));
});
sourceLayerOptions.addEventListener("change", (event) => {
  if (!event.target.matches("[data-layer-kind='source']")) {
    return;
  }
  const value = event.target.dataset.layerValue;
  if (event.target.checked) {
    enabledLayerSources.add(value);
  } else {
    enabledLayerSources.delete(value);
  }
  renderMap(mapLayerEvents(currentMapBaseEvents()));
});
layersAll.addEventListener("click", () => {
  syncLayerSelections();
  enabledLayerCategories = new Set(knownLayerCategories);
  enabledLayerSources = new Set(knownLayerSources);
  observationLayerToggle.checked = true;
  renderMap(mapLayerEvents(currentMapBaseEvents()));
});
layersNone.addEventListener("click", () => {
  enabledLayerCategories.clear();
  enabledLayerSources.clear();
  observationLayerToggle.checked = false;
  renderMap([]);
});
sourceFilter.addEventListener("change", renderSources);
sourceList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-source-poll-action]");
  if (button) {
    event.preventDefault();
    setSourcePolling(button);
  }
});
sourceSyncTarget.addEventListener("change", () => {
  syncSource.disabled = sourceSyncTarget.value === "";
});
syncSource.addEventListener("click", syncSelectedSource);
reportScope.addEventListener("change", () => {
  renderReports();
  renderMap(mapLayerEvents(currentMapBaseEvents()));
});
reportCategory.addEventListener("change", () => {
  renderReports();
  renderMap(mapLayerEvents(currentMapBaseEvents()));
});
refreshReport.addEventListener("click", loadEvents);
refreshSensors.addEventListener("click", loadSensors);
timelineRange.addEventListener("input", () => {
  timelineValue = Number(timelineRange.value);
  timelineWindowStart = null;
  timelineWindowDays = null;
  syncTimelineControl();
  render();
});
timelineWindowButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const days = Number(button.dataset.timelineWindow);
    const start = timelineWindowStartForDays(days);
    if (start === null) {
      return;
    }
    timelineValue = null;
    timelineWindowStart = start;
    timelineWindowDays = days;
    render();
  });
});
timelineReset.addEventListener("click", () => {
  timelineValue = null;
  timelineWindowStart = null;
  timelineWindowDays = null;
  render();
});
mlRefresh.addEventListener("click", loadMl);
mlSourceFilter.addEventListener("change", loadMl);
mlScoreButton.addEventListener("click", scoreMlText);
mlClearLearned.addEventListener("click", clearLearnedMlRules);
mlCandidateList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-ml-action='promote']");
  if (button) {
    promoteMlCandidate(button);
  }
});
menuToggle.addEventListener("click", () => {
  const isOpen = sideMenu.classList.contains("open");
  setMenuOpen(!isOpen);
});
menuScrim.addEventListener("click", () => setMenuOpen(false));
menuItems.forEach((item) => {
  item.addEventListener("click", () => setView(item.dataset.view));
});
settingsForm.addEventListener("submit", saveSettings);
resetDatabase.addEventListener("click", resetDatabaseFromSettings);
eventDetailDrawer.addEventListener("click", (event) => {
  const relatedButton = event.target.closest("[data-related-event-id]");
  if (relatedButton) {
    setActiveEvent(Number(relatedButton.dataset.relatedEventId), true);
    return;
  }

  const actionButton = event.target.closest("[data-detail-action]");
  if (!actionButton) {
    return;
  }

  const action = actionButton.dataset.detailAction;
  if (action === "close") {
    closeEventDetail();
  } else if (action === "focus") {
    focusActiveEvent();
  } else if (action === "feed") {
    showActiveEventInFeed();
  } else if (action === "focus-station") {
    focusStation(activeStationId);
  } else if (action === "refresh-station") {
    refreshActiveStationDetail();
  } else if (action === "toggle-raw") {
    const raw = eventDetailDrawer.querySelector("#event-detail-raw");
    if (raw) {
      raw.hidden = !raw.hidden;
    }
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (!eventDetailDrawer.hidden) {
      closeEventDetail();
    } else {
      setMenuOpen(false);
    }
  }
});

function setMenuOpen(isOpen) {
  sideMenu.classList.toggle("open", isOpen);
  sideMenu.setAttribute("aria-hidden", String(!isOpen));
  menuToggle.setAttribute("aria-expanded", String(isOpen));
  menuToggle.setAttribute("aria-label", isOpen ? "Close menu" : "Open menu");
  menuScrim.hidden = !isOpen;
  if (isOpen) {
    sideMenu.removeAttribute("inert");
  } else {
    sideMenu.setAttribute("inert", "");
  }
}

setMenuOpen(false);
startSourceTimers();
loadEvents();
loadSources();
setInterval(loadEvents, 15000);
setInterval(loadObservations, 30000);
