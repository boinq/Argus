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

const apiStatus = document.querySelector("#api-status");
const eventList = document.querySelector("#event-list");
const summary = document.querySelector("#summary");
const categoryFilter = document.querySelector("#category-filter");
const menuToggle = document.querySelector("#menu-toggle");
const sideMenu = document.querySelector("#side-menu");
const menuScrim = document.querySelector("#menu-scrim");
const menuItems = document.querySelectorAll(".menu-item[data-view]");
const eventsView = document.querySelector("#events-view");
const settingsView = document.querySelector("#settings-view");
const settingsForm = document.querySelector("#settings-form");
const settingsNote = document.querySelector("#settings-note");
const proxySnippet = document.querySelector("#proxy-snippet");
const publicBaseUrl = document.querySelector("#public-base-url");
const pathPrefix = document.querySelector("#path-prefix");
const trustedHosts = document.querySelector("#trusted-hosts");
const proxyHeaders = document.querySelector("#proxy-headers");

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
  renderMap(items);
  renderEvents(items);
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
}

function renderProxySnippet(settings) {
  const prefix = settings.path_prefix || "";
  const lines = [
    "ARGUS_PUBLIC_BASE_URL=" + (settings.public_base_url || ""),
    "ARGUS_ROOT_PATH=" + prefix,
    "ARGUS_TRUSTED_HOSTS=" + (settings.trusted_hosts || "*"),
    "ARGUS_PROXY_HEADERS=" + String(Boolean(settings.proxy_headers)),
  ];
  proxySnippet.textContent = lines.join("\n");
}

function setView(viewName) {
  const showingSettings = viewName === "settings";
  eventsView.hidden = showingSettings;
  settingsView.hidden = !showingSettings;
  menuItems.forEach((item) => {
    item.classList.toggle("active", item.dataset.view === viewName);
  });
  setMenuOpen(false);
  if (showingSettings) {
    loadSettings();
  }
}

categoryFilter.addEventListener("change", render);
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
