import { escapeHtml, eventColor, formatDate, formatOptionalDate } from "./utils.js";

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

export function markerFor(event) {
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

export function markerForObservation(observation) {
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

export function markerForObservationStation(station) {
  const label = `DMI station ${station.station_id}`;
  const latest = station.latest_observed_at ? formatDate(station.latest_observed_at) : "Unknown";
  const marker = L.marker([station.latitude, station.longitude], {
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
            <span class="tag">${station.observation_count} obs</span>
          </div>
        </div>
      </header>
      <dl class="popup-details">
        ${station.parameters.map(stationParameterDetail).join("")}
        <div>
          <dt>Latest</dt>
          <dd>${escapeHtml(latest)}</dd>
        </div>
      </dl>
      <button class="popup-action" type="button" data-popup-station-id="${escapeHtml(station.station_id)}">
        Station history
      </button>
    </article>
  `);
  return marker;
}

export function observationDisplayName(parameterId) {
  const labels = {
    temp_dry: "Temperature",
    wind_speed: "Wind speed",
    wind_gust_always_past1h: "Wind gust",
    precip_past10min: "Precipitation",
  };
  return labels[parameterId] || parameterId;
}

export function observationValue(observation) {
  const unit = observationUnit(observation.parameter_id);
  return `${Number(observation.value).toFixed(1)}${unit ? ` ${unit}` : ""}`;
}

function observationLabel(observation) {
  return `${observationDisplayName(observation.parameter_id)}: ${observationValue(observation)}`;
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

function stationParameterDetail(observation) {
  return `
    <div>
      <dt>${escapeHtml(observationDisplayName(observation.parameter_id))}</dt>
      <dd>${escapeHtml(observationValue(observation))}</dd>
    </div>
  `;
}
