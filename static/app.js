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

const sources = [
  {
    name: "DMI Weather Warnings",
    type: "weather",
    status: "planned",
    coverage: "Denmark, Faroe Islands, Greenland waters",
    cadence: "Every 10 minutes",
    lastCheck: "Not connected",
  },
  {
    name: "Energinet Operational Messages",
    type: "electrical",
    status: "planned",
    coverage: "National grid and regional transmission",
    cadence: "Every 5 minutes",
    lastCheck: "Not connected",
  },
  {
    name: "Maritime Domain Watch",
    type: "hybrid",
    status: "planned",
    coverage: "Danish straits, ports, offshore infrastructure",
    cadence: "Every 15 minutes",
    lastCheck: "Not connected",
  },
  {
    name: "Police and Civil Protection Bulletins",
    type: "security",
    status: "planned",
    coverage: "National and regional incident notices",
    cadence: "Every 15 minutes",
    lastCheck: "Not connected",
  },
  {
    name: "Municipal Situation Reports",
    type: "municipal",
    status: "manual",
    coverage: "Municipal preparedness and logistics",
    cadence: "Manual entry",
    lastCheck: "Awaiting operator input",
  },
  {
    name: "Danish Health Alerts",
    type: "health",
    status: "planned",
    coverage: "Public health and hospital capacity signals",
    cadence: "Every 30 minutes",
    lastCheck: "Not connected",
  },
  {
    name: "Trafikinfo Disruption Feed",
    type: "transport",
    status: "planned",
    coverage: "Road, rail, bridge, and ferry disruptions",
    cadence: "Every 5 minutes",
    lastCheck: "Not connected",
  },
  {
    name: "Manual Intelligence Notes",
    type: "manual",
    status: "manual",
    coverage: "Analyst-entered observations and reports",
    cadence: "Manual entry",
    lastCheck: "Available",
  },
];

function formatDate(value) {
  return new Intl.DateTimeFormat("en-DK", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
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

function markerFor(event) {
  return L.circleMarker([event.latitude, event.longitude], {
    radius: event.severity === "critical" ? 12 : 10,
    color: "#ffffff",
    weight: 2,
    fillColor: eventColor(event),
    fillOpacity: 0.88,
  }).bindPopup(`
    <p class="popup-title">${escapeHtml(event.title)}</p>
    <p class="popup-copy">${escapeHtml(event.description)}</p>
  `);
}

function filteredEvents() {
  const category = categoryFilter.value;
  return category === "all"
    ? events
    : events.filter((event) => event.category === category);
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
  markers.forEach((marker) => marker.remove());
  markers.clear();

  items.forEach((event) => {
    const marker = markerFor(event).addTo(map);
    marker.on("click", () => setActiveEvent(event.id, false));
    markers.set(event.id, marker);
  });
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
    map.setView([event.latitude, event.longitude], Math.max(map.getZoom(), 8), {
      animate: true,
    });
    if (openPopup) {
      marker.openPopup();
    }
  }
  renderEvents(filteredEvents());
}

function render() {
  const items = filteredEvents();
  renderSummary(items);
  renderMap(activeView === "reports" ? reportEvents() : items);
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

  sourceSummary.innerHTML = [
    ["Total", sources.length],
    ["Connected", connected],
    ["Planned", planned],
    ["Manual", manual],
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
      (source) => `
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
              <dt>Last check</dt>
              <dd>${escapeHtml(source.lastCheck)}</dd>
            </div>
          </dl>
        </article>
      `,
    )
    .join("");
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
  if (viewName === "reports") {
    renderReports();
    renderMap(reportEvents());
  } else if (viewName === "sources") {
    renderSources();
    renderMap(events);
  } else {
    renderMap(filteredEvents());
  }
}

categoryFilter.addEventListener("change", render);
sourceFilter.addEventListener("change", renderSources);
reportScope.addEventListener("change", () => {
  renderReports();
  renderMap(reportEvents());
});
reportCategory.addEventListener("change", () => {
  renderReports();
  renderMap(reportEvents());
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
setInterval(loadEvents, 60000);
