const denmarkBounds = [
  [54.45, 7.75],
  [58.05, 15.35],
];

const severityColors = {
  critical: "#e03131",
  high: "#ff8f1f",
  medium: "#f2c94c",
  low: "#3fb950",
};

const map = L.map("map", {
  maxBounds: denmarkBounds,
  maxBoundsViscosity: 0.8,
  zoomControl: false,
}).fitBounds(denmarkBounds);

L.control.zoom({ position: "bottomright" }).addTo(map);
map.createPane("weatherPane");
map.getPane("weatherPane").style.zIndex = 450;
map.createPane("eventPane");
map.getPane("eventPane").style.zIndex = 500;

L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  {
    attribution:
      "Tiles &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    maxZoom: 18,
  },
).addTo(map);

L.tileLayer(
  "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
  {
    attribution: "Boundaries &copy; Esri",
    maxZoom: 18,
    opacity: 0.74,
  },
).addTo(map);

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
const sourcesView = document.querySelector("#sources-view");
const reportsView = document.querySelector("#reports-view");
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
const reportScope = document.querySelector("#report-scope");
const reportCategory = document.querySelector("#report-category");
const reportSummary = document.querySelector("#report-summary");
const reportBrief = document.querySelector("#report-brief");
const reportList = document.querySelector("#report-list");
const refreshReport = document.querySelector("#refresh-report");
const sourceFilter = document.querySelector("#source-filter");
const sourceSummary = document.querySelector("#source-summary");
const sourceList = document.querySelector("#source-list");
const sourceNote = document.querySelector("#source-note");
const observationNote = document.querySelector("#observation-note");
const syncSource = document.querySelector("#sync-source");
const sourceSyncTarget = document.querySelector("#source-sync-target");
const layerCount = document.querySelector("#layer-count");
const layersAll = document.querySelector("#layers-all");
const layersNone = document.querySelector("#layers-none");
const observationLayerToggle = document.querySelector("#observation-layer-toggle");
const categoryLayerOptions = document.querySelector("#category-layer-options");
const sourceLayerOptions = document.querySelector("#source-layer-options");
let sources = [];
let schedulerJobs = [];
let observations = [];
let dataMarkers = [];
let knownLayerCategories = new Set();
let knownLayerSources = new Set();
let enabledLayerCategories = new Set();
let enabledLayerSources = new Set();

function createMarkerLayer(kind) {
  if (typeof L.markerClusterGroup !== "function") {
    return L.layerGroup();
  }
  return L.markerClusterGroup({
    chunkedLoading: true,
    disableClusteringAtZoom: 11,
    maxClusterRadius: kind === "event" ? 46 : 38,
    showCoverageOnHover: false,
    spiderfyDistanceMultiplier: 1.3,
    iconCreateFunction: (cluster) => clusterIcon(cluster, kind),
  });
}

function clusterIcon(cluster, kind) {
  const count = cluster.getChildCount();
  const size = count >= 100 ? 52 : count >= 25 ? 46 : 40;
  const severity = highestClusterSeverity(cluster);
  const color = kind === "observation" ? "#8fb8ff" : severityColors[severity] || severityColors.low;
  return L.divIcon({
    className: `argus-cluster argus-cluster-${kind}`,
    html: `
      <span
        class="argus-cluster-badge"
        style="--cluster-color: ${color}; width: ${size}px; height: ${size}px"
      >
        ${count}
      </span>
    `,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function highestClusterSeverity(cluster) {
  const ranks = { critical: 4, high: 3, medium: 2, low: 1 };
  return cluster
    .getAllChildMarkers()
    .map((marker) => marker.options.argusSeverity || "low")
    .sort((a, b) => (ranks[b] || 0) - (ranks[a] || 0))[0] || "low";
}

function formatDate(value) {
  return new Intl.DateTimeFormat("en-DK", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatOptionalDate(value) {
  return value ? formatDate(value) : "Not set";
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return entities[character];
  });
}

function eventColor(event) {
  return severityColors[event.severity] || severityColors.low;
}

const markerIcons = {
  weather: '<path d="M8 15a5 5 0 1 1 4.6-7h.4a4 4 0 0 1 0 8H8z"></path>',
  lightning: '<path d="M13 2 6 13h5l-2 9 8-12h-5l1-8z"></path>',
  electrical: '<path d="M13 2 6 13h5l-2 9 8-12h-5l1-8z"></path>',
  maritime: '<path d="M12 3l7 4-7 4-7-4 7-4z"></path><path d="M5 13c2 0 2 2 4 2s2-2 4-2 2 2 4 2 2-2 4-2"></path><path d="M5 18c2 0 2 2 4 2s2-2 4-2 2 2 4 2 2-2 4-2"></path>',
  transport: '<path d="M5 11h14l-2-5H7l-2 5z"></path><path d="M7 16h.01"></path><path d="M17 16h.01"></path><path d="M6 11v5h12v-5"></path>',
  emergency: '<path d="M12 3v18"></path><path d="M3 12h18"></path><path d="M7 7l10 10"></path><path d="M17 7 7 17"></path>',
  health: '<path d="M12 21s-7-4.4-7-10a4 4 0 0 1 7-2.7A4 4 0 0 1 19 11c0 5.6-7 10-7 10z"></path><path d="M12 8v7"></path><path d="M8.5 11.5h7"></path>',
  hybrid: '<path d="M12 3 4 6v5c0 5 3.4 8.5 8 10 4.6-1.5 8-5 8-10V6l-8-3z"></path><path d="M9 12l2 2 4-5"></path>',
  food: '<path d="M7 3v8"></path><path d="M10 3v8"></path><path d="M7 7h3"></path><path d="M8.5 11v10"></path><path d="M16 3v18"></path><path d="M16 3c3 2 3 6 0 8"></path>',
  news: '<path d="M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2V4z"></path><path d="M8 8h8"></path><path d="M8 12h8"></path><path d="M8 16h5"></path>',
  other: '<path d="M12 8v4"></path><path d="M12 16h.01"></path><path d="M10.3 4.3a2 2 0 0 1 3.4 0l7.1 12.4a2 2 0 0 1-1.7 3H4.9a2 2 0 0 1-1.7-3l7.1-12.4z"></path>',
};

function markerIconKey(event) {
  const source = event.source.toLowerCase();
  if (source.includes("dmi")) {
    return "weather";
  }
  if (source.includes("trafikinfo")) {
    return "transport";
  }
  if (source.includes("niord") || source.includes("maritime")) {
    return "maritime";
  }
  if (source.includes("odin")) {
    return "emergency";
  }
  if (source.includes("green power") || source.includes("energi")) {
    return "electrical";
  }
  if (source.includes("sundhed")) {
    return "health";
  }
  if (source.includes("dr nyheder")) {
    return "news";
  }
  return markerIcons[event.category] ? event.category : "other";
}

function markerIconSvg(event) {
  const paths = markerIcons[markerIconKey(event)] || markerIcons.other;
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      ${paths}
    </svg>
  `;
}

function markerFor(event) {
  const markerSize = event.severity === "critical" ? 34 : 30;
  return L.marker([event.latitude, event.longitude], {
    pane: "eventPane",
    keyboard: true,
    title: event.title,
    argusSeverity: event.severity,
    icon: L.divIcon({
      className: `event-marker-icon event-marker-${escapeHtml(markerIconKey(event))}`,
      html: `
        <span
          class="event-marker-pin"
          style="--marker-color: ${eventColor(event)}"
        >
          ${markerIconSvg(event)}
        </span>
      `,
      iconSize: [markerSize, markerSize],
      iconAnchor: [markerSize / 2, markerSize / 2],
      popupAnchor: [0, -markerSize / 2],
    }),
  }).bindPopup(`
    <article class="event-popup">
      <header class="event-popup-header">
        <span class="popup-severity" style="background: ${eventColor(event)}"></span>
        <div>
          <p class="popup-title">${escapeHtml(event.title)}</p>
          <div class="event-meta popup-meta">
            <span class="tag">${escapeHtml(event.category)}</span>
            <span class="tag">${escapeHtml(event.severity)}</span>
            <span class="tag">${escapeHtml(event.status)}</span>
          </div>
        </div>
      </header>
      <p class="popup-copy">${escapeHtml(event.description)}</p>
      <dl class="popup-details">
        <div>
          <dt>Source</dt>
          <dd>${escapeHtml(event.source)}</dd>
        </div>
        <div>
          <dt>Starts</dt>
          <dd>${escapeHtml(formatDate(event.starts_at))}</dd>
        </div>
        <div>
          <dt>Ends</dt>
          <dd>${escapeHtml(formatOptionalDate(event.ends_at))}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>${escapeHtml(formatDate(event.updated_at))}</dd>
        </div>
        <div>
          <dt>Coordinates</dt>
          <dd>${Number(event.latitude).toFixed(4)}, ${Number(event.longitude).toFixed(4)}</dd>
        </div>
      </dl>
      <button class="popup-action" type="button" data-popup-event-id="${event.id}">
        Show in feed
      </button>
    </article>
  `);
}

function markerForObservation(observation) {
  const label = observationLabel(observation);
  const marker = L.marker([observation.latitude, observation.longitude], {
    pane: "weatherPane",
    keyboard: true,
    title: label,
    icon: L.divIcon({
      className: "weather-marker-icon",
      html: `
        <span class="event-marker-pin weather-marker-pin">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            ${markerIcons.weather}
          </svg>
        </span>
      `,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
      popupAnchor: [0, -10],
    }),
  });
  marker.bindPopup(`
    <article class="weather-popup">
      <header class="event-popup-header">
        <span class="popup-severity weather"></span>
        <div>
          <p class="popup-title">${escapeHtml(label)}</p>
          <div class="event-meta popup-meta">
            <span class="tag">DMI</span>
            <span class="tag">weather</span>
          </div>
        </div>
      </header>
      <dl class="popup-details">
        <div>
          <dt>Station</dt>
          <dd>${escapeHtml(observation.station_id)}</dd>
        </div>
        <div>
          <dt>Parameter</dt>
          <dd>${escapeHtml(observation.parameter_id)}</dd>
        </div>
        <div>
          <dt>Value</dt>
          <dd>${escapeHtml(observationValue(observation))}</dd>
        </div>
        <div>
          <dt>Observed</dt>
          <dd>${escapeHtml(formatDate(observation.observed_at))}</dd>
        </div>
        <div>
          <dt>Coordinates</dt>
          <dd>${Number(observation.latitude).toFixed(4)}, ${Number(observation.longitude).toFixed(4)}</dd>
        </div>
      </dl>
    </article>
  `);
  return marker;
}

function observationLabel(observation) {
  return `${observationDisplayName(observation.parameter_id)}: ${observationValue(observation)}`;
}

function observationValue(observation) {
  const unit = observationUnit(observation.parameter_id);
  return `${Number(observation.value).toFixed(1)}${unit ? ` ${unit}` : ""}`;
}

function observationDisplayName(parameterId) {
  const labels = {
    temp_dry: "Temperature",
    wind_speed: "Wind speed",
    wind_gust_always_past1h: "Wind gust",
    precip_past10min: "Precipitation",
  };
  return labels[parameterId] || parameterId;
}

function observationUnit(parameterId) {
  const units = {
    temp_dry: "C",
    wind_speed: "m/s",
    wind_gust_always_past1h: "m/s",
    precip_past10min: "mm / 10 min",
  };
  return units[parameterId] || "";
}

function filteredEvents() {
  const category = categoryFilter.value;
  return category === "all"
    ? events
    : events.filter((event) => event.category === category);
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
    return events;
  }
  return filteredEvents();
}

function syncLayerSelections() {
  const categories = [...new Set(events.map((event) => event.category))].sort();
  const eventSources = [...new Set(events.map((event) => event.source))].sort();
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
    renderObservationLayer(observations);
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
  const observationCount = shouldShowObservationLayer() ? observations.length : 0;
  layerCount.textContent = `${visibleEventCount + observationCount} shown`;
  categoryLayerOptions.innerHTML = categories
    .map((category) =>
      layerOption({
        kind: "category",
        value: category,
        label: categoryLabel(category),
        checked: enabledLayerCategories.has(category),
        count: events.filter((event) => event.category === category).length,
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
        count: events.filter((event) => event.source === source).length,
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

function categoryLabel(category) {
  return category.charAt(0).toUpperCase() + category.slice(1);
}

function renderObservationLayer(items) {
  clearObservationLayer();
  if (!map.hasLayer(observationMarkerLayer)) {
    observationMarkerLayer.addTo(map);
  }
  dataMarkers = items.map((observation) => {
    const marker = markerForObservation(observation);
    const openObservation = () => {
      map.panTo([observation.latitude, observation.longitude], { animate: true });
      marker.openPopup();
    };
    marker.on("click", openObservation);
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

function render() {
  const items = filteredEvents();
  renderSummary(items);
  renderMap(mapLayerEvents(currentMapBaseEvents()));
  renderEvents(items);
  renderReports();
  renderSources();
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
    fillSettings(settings);
    renderProxySnippet(settings);
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

async function loadObservations() {
  try {
    const response = await fetch("api/observations?source_id=dmi-metobs&limit=500");
    if (!response.ok) {
      throw new Error(`Observations API responded with ${response.status}`);
    }
    observations = await response.json();
    observationNote.textContent =
      observations.length > 0
        ? `${observations.length} recent DMI observations plotted on the map.`
        : "No DMI observations stored yet.";
    observationNote.classList.remove("error");
    if (shouldShowObservationLayer()) {
      renderMap(mapLayerEvents(currentMapBaseEvents()));
    } else {
      renderLayerControls(markers.size);
    }
  } catch (error) {
    observationNote.textContent = error.message;
    observationNote.classList.add("error");
  }
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
  const payload = {
    public_base_url: publicBaseUrl.value.trim(),
    path_prefix: pathPrefix.value.trim(),
    trusted_hosts: trustedHosts.value.trim(),
    proxy_headers: proxyHeaders.checked,
    ntfy_enabled: ntfyEnabled.checked,
    ntfy_server_url: ntfyServerUrl.value.trim(),
    ntfy_topic: ntfyTopic.value.trim(),
    ntfy_token: ntfyToken.value,
    ntfy_priority: ntfyPriority.value,
  };

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
    fillSettings(settings);
    renderProxySnippet(settings);
    settingsNote.textContent = "Settings saved. Restart the container after changing proxy runtime values.";
    settingsNote.classList.remove("error");
  } catch (error) {
    settingsNote.textContent = error.message;
    settingsNote.classList.add("error");
  }
}

function fillSettings(settings) {
  publicBaseUrl.value = settings.public_base_url || "";
  pathPrefix.value = settings.path_prefix || "";
  trustedHosts.value = settings.trusted_hosts || "";
  proxyHeaders.checked = Boolean(settings.proxy_headers);
  ntfyEnabled.checked = Boolean(settings.ntfy_enabled);
  ntfyServerUrl.value = settings.ntfy_server_url || "";
  ntfyTopic.value = settings.ntfy_topic || "";
  ntfyToken.value = settings.ntfy_token || "";
  ntfyPriority.value = settings.ntfy_priority || "default";
}

function renderProxySnippet(settings) {
  const prefix = settings.path_prefix || "";
  const lines = [
    "ARGUS_PUBLIC_BASE_URL=" + (settings.public_base_url || ""),
    "ARGUS_ROOT_PATH=" + prefix,
    "ARGUS_TRUSTED_HOSTS=" + (settings.trusted_hosts || "*"),
    "ARGUS_PROXY_HEADERS=" + String(Boolean(settings.proxy_headers)),
    "ARGUS_NTFY_ENABLED=" + String(Boolean(settings.ntfy_enabled)),
    "ARGUS_NTFY_SERVER_URL=" + (settings.ntfy_server_url || ""),
    "ARGUS_NTFY_TOPIC=" + (settings.ntfy_topic || ""),
    "ARGUS_NTFY_TOKEN=" + (settings.ntfy_token ? "[configured]" : ""),
    "ARGUS_NTFY_PRIORITY=" + (settings.ntfy_priority || "default"),
  ];
  proxySnippet.textContent = lines.join("\n");
}

function reportEvents() {
  const scope = reportScope.value;
  const category = reportCategory.value;
  return events.filter((event) => {
    const matchesScope = scope === "all" || event.status === scope;
    const matchesCategory = category === "all" || event.category === category;
    return matchesScope && matchesCategory;
  });
}

function severityRank(severity) {
  const ranks = { critical: 4, high: 3, medium: 2, low: 1 };
  return ranks[severity] || 0;
}

function renderReports() {
  if (!reportSummary || !reportBrief || !reportList) {
    return;
  }

  const items = reportEvents();
  const highRisk = items.filter((event) => ["critical", "high"].includes(event.severity));
  const current = items.filter((event) => event.status === "current");
  const upcoming = items.filter((event) => event.status === "upcoming");
  const monitoring = items.filter((event) => event.status === "monitoring");
  const categories = new Set(items.map((event) => event.category));

  reportSummary.innerHTML = [
    ["Events", items.length],
    ["Current", current.length],
    ["High Risk", highRisk.length],
    ["Categories", categories.size],
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

  if (items.length === 0) {
    reportBrief.innerHTML = '<p class="empty">No events match this report scope.</p>';
    reportList.innerHTML = "";
    return;
  }

  const leadingCategory = mostCommon(items.map((event) => event.category));
  const priority = [...items].sort(
    (a, b) => severityRank(b.severity) - severityRank(a.severity),
  )[0];

  reportBrief.innerHTML = `
    <p>
      ${items.length} event${items.length === 1 ? "" : "s"} match the selected report scope.
      ${current.length} current, ${upcoming.length} upcoming, and ${monitoring.length} under monitoring.
    </p>
    <p>
      The leading category is ${escapeHtml(leadingCategory)}, with
      ${highRisk.length} high or critical severity item${highRisk.length === 1 ? "" : "s"}.
      Highest priority: ${escapeHtml(priority.title)}.
    </p>
  `;

  reportList.innerHTML = [...items]
    .sort((a, b) => severityRank(b.severity) - severityRank(a.severity))
    .slice(0, 6)
    .map(
      (event) => `
        <article class="report-item" style="border-left-color: ${eventColor(event)}">
          <h4>${escapeHtml(event.title)}</h4>
          <div class="event-meta">
            <span class="tag">${escapeHtml(event.category)}</span>
            <span class="tag">${escapeHtml(event.severity)}</span>
            <span class="tag">${escapeHtml(event.status)}</span>
          </div>
          <p>${escapeHtml(event.description)}</p>
          <div class="event-time">Starts ${formatDate(event.starts_at)}</div>
        </article>
      `,
    )
    .join("");
}

function mostCommon(values) {
  const counts = values.reduce((result, value) => {
    result[value] = (result[value] || 0) + 1;
    return result;
  }, {});
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || "none";
}

function filteredSources() {
  const filter = sourceFilter.value;
  return filter === "all" ? sources : sources.filter((source) => source.status === filter);
}

function renderSources() {
  if (!sourceSummary || !sourceList) {
    return;
  }

  const items = filteredSources();
  const connected = sources.filter((source) => source.status === "connected").length;
  const planned = sources.filter((source) => source.status === "planned").length;
  const manual = sources.filter((source) => source.status === "manual").length;
  const error = sources.filter((source) => source.status === "error").length;

  sourceSummary.innerHTML = [
    ["Total", sources.length],
    ["Connected", connected],
    ["Planned", planned],
    ["Manual", manual],
    ["Error", error],
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

  if (items.length === 0) {
    sourceList.innerHTML = '<p class="empty">No sources match this filter.</p>';
    return;
  }

  sourceList.innerHTML = items
    .map(
      (source) => {
        const job = schedulerJobs.find((item) => item.source_id === source.id);
        return `
        <article class="source-card">
          <div class="source-card-header">
            <h3>${escapeHtml(source.name)}</h3>
            <span class="tag source-status ${escapeHtml(source.status)}">
              ${escapeHtml(source.status)}
            </span>
          </div>
          <dl class="source-details">
            <div>
              <dt>Type</dt>
              <dd>${escapeHtml(source.type)}</dd>
            </div>
            <div>
              <dt>Coverage</dt>
              <dd>${escapeHtml(source.coverage)}</dd>
            </div>
            <div>
              <dt>Cadence</dt>
              <dd>${escapeHtml(source.cadence)}</dd>
            </div>
            <div>
              <dt>Polling</dt>
              <dd>${job ? `${job.enabled ? "Enabled" : "Disabled"} / ${job.interval_seconds}s` : "Not scheduled"}</dd>
            </div>
            <div>
              <dt>Last check</dt>
              <dd>${source.last_check ? formatDate(source.last_check) : "Never"}</dd>
            </div>
            <div>
              <dt>Last success</dt>
              <dd>${source.last_success ? formatDate(source.last_success) : "Never"}</dd>
            </div>
            <div>
              <dt>Endpoint</dt>
              <dd>${escapeHtml(source.endpoint || "Not configured")}</dd>
            </div>
            <div>
              <dt>Last error</dt>
              <dd>${escapeHtml(source.last_error || "None")}</dd>
            </div>
          </dl>
        </article>
      `;
      },
    )
    .join("");
}

function renderSourceSyncTargets() {
  sourceSyncTarget.innerHTML = schedulerJobs
    .map((job) => `<option value="${escapeHtml(job.id)}">${escapeHtml(job.name)}</option>`)
    .join("");
  syncSource.disabled = schedulerJobs.length === 0;
}

function setView(viewName) {
  activeView = viewName;
  eventsView.hidden = viewName !== "events";
  sourcesView.hidden = viewName !== "sources";
  reportsView.hidden = viewName !== "reports";
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
  if (viewName === "reports") {
    renderReports();
    renderMap(mapLayerEvents(currentMapBaseEvents()));
  } else if (viewName === "sources") {
    renderSources();
    renderMap(mapLayerEvents(currentMapBaseEvents()));
  } else {
    renderMap(mapLayerEvents(currentMapBaseEvents()));
  }
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
menuToggle.addEventListener("click", () => {
  const isOpen = sideMenu.classList.contains("open");
  setMenuOpen(!isOpen);
});
menuScrim.addEventListener("click", () => setMenuOpen(false));
menuItems.forEach((item) => {
  item.addEventListener("click", () => setView(item.dataset.view));
});
settingsForm.addEventListener("submit", saveSettings);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setMenuOpen(false);
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
loadEvents();
loadSources();
setInterval(loadEvents, 60000);
