import { escapeHtml, eventColor, formatDate, formatOptionalDate, severityRank } from "./utils.js";

export function eventDetailHtml(event, { events, sources }) {
  const source = sourceForEvent(event, sources);
  const related = relatedEvents(event, events);
  const timeline = timelineEntries(event);
  const raw = JSON.stringify({ event, source }, null, 2);

  return `
    <header class="detail-header">
      <div>
        <p class="eyebrow">Event Detail</p>
        <h2>${escapeHtml(event.title)}</h2>
      </div>
      <button type="button" class="detail-close" data-detail-action="close" aria-label="Close detail">
        &times;
      </button>
    </header>

    <div class="detail-severity" style="--detail-color: ${eventColor(event)}">
      <span>${escapeHtml(event.severity)}</span>
      <strong>${priorityScore(event)}</strong>
    </div>

    <div class="event-meta detail-tags">
      <span class="tag">${escapeHtml(event.category)}</span>
      <span class="tag">${escapeHtml(event.status)}</span>
      <span class="tag">${escapeHtml(event.source)}</span>
    </div>

    <p class="detail-description">${escapeHtml(event.description)}</p>

    <div class="detail-actions">
      <button type="button" data-detail-action="focus">Focus Map</button>
      <button type="button" data-detail-action="feed">Show In Feed</button>
    </div>

    <section class="detail-section">
      <h3>Timing</h3>
      <dl class="detail-grid">
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
    </section>

    <section class="detail-section">
      <h3>Source</h3>
      <dl class="detail-grid">
        <div>
          <dt>Name</dt>
          <dd>${escapeHtml(source?.name || event.source)}</dd>
        </div>
        <div>
          <dt>Coverage</dt>
          <dd>${escapeHtml(source?.coverage || "Source registry match unavailable")}</dd>
        </div>
        <div>
          <dt>Cadence</dt>
          <dd>${escapeHtml(source?.cadence || "Unknown")}</dd>
        </div>
        <div>
          <dt>Endpoint</dt>
          <dd>${source?.endpoint ? endpointLink(source.endpoint) : "Unknown"}</dd>
        </div>
      </dl>
    </section>

    <section class="detail-section">
      <h3>Lifecycle</h3>
      <ol class="detail-timeline">
        ${timeline
          .map(
            (item) => `
              <li>
                <strong>${escapeHtml(item.label)}</strong>
                <span>${escapeHtml(item.value)}</span>
              </li>
            `,
          )
          .join("")}
      </ol>
    </section>

    <section class="detail-section">
      <h3>Related Nearby</h3>
      ${
        related.length
          ? `<div class="related-list">${related.map(relatedEvent).join("")}</div>`
          : '<p class="empty">No nearby related events in the current dataset.</p>'
      }
    </section>

    <section class="detail-section">
      <button type="button" class="raw-toggle" data-detail-action="toggle-raw">
        Raw JSON
      </button>
      <pre class="raw-json" id="event-detail-raw" hidden>${escapeHtml(raw)}</pre>
    </section>
  `;
}

function sourceForEvent(event, sources) {
  const exact = sources.find((source) => source.name === event.source);
  if (exact) {
    return exact;
  }
  const lowerName = event.source.toLowerCase();
  const fuzzy = sources.find((source) => {
    const sourceName = source.name.toLowerCase();
    return sourceName.includes(lowerName) || lowerName.includes(sourceName);
  });
  if (fuzzy) {
    return fuzzy;
  }
  const categoryMatches = sources.filter((source) => source.type === event.category);
  return categoryMatches.length === 1 ? categoryMatches[0] : null;
}

function endpointLink(endpoint) {
  const safeEndpoint = escapeHtml(endpoint);
  return `<a href="${safeEndpoint}" target="_blank" rel="noreferrer">${safeEndpoint}</a>`;
}

function timelineEntries(event) {
  const entries = [
    { label: "Starts", value: formatDate(event.starts_at) },
    { label: "Status", value: event.status },
    { label: "Last updated", value: formatDate(event.updated_at) },
  ];
  if (event.ends_at) {
    entries.push({ label: "Expected end", value: formatDate(event.ends_at) });
  }
  return entries;
}

function priorityScore(event) {
  const statusWeight = {
    current: 20,
    monitoring: 14,
    upcoming: 10,
    resolved: 0,
  };
  const score = severityRank(event.severity) * 20 + (statusWeight[event.status] || 0);
  return `${Math.min(score, 100)} priority`;
}

function relatedEvents(event, events) {
  return events
    .filter((item) => item.id !== event.id)
    .map((item) => ({ ...item, distanceKm: distanceKm(event, item) }))
    .filter(
      (item) =>
        item.distanceKm <= 40 ||
        item.source === event.source ||
        item.category === event.category,
    )
    .sort((a, b) => {
      const rankDelta = severityRank(b.severity) - severityRank(a.severity);
      return rankDelta || a.distanceKm - b.distanceKm;
    })
    .slice(0, 4);
}

function relatedEvent(event) {
  return `
    <button type="button" class="related-event" data-related-event-id="${event.id}">
      <span>${escapeHtml(event.title)}</span>
      <small>${escapeHtml(event.category)} · ${event.distanceKm.toFixed(1)} km</small>
    </button>
  `;
}

function distanceKm(a, b) {
  const earthRadiusKm = 6371;
  const dLat = radians(b.latitude - a.latitude);
  const dLon = radians(b.longitude - a.longitude);
  const lat1 = radians(a.latitude);
  const lat2 = radians(b.latitude);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * earthRadiusKm * Math.asin(Math.sqrt(h));
}

function radians(value) {
  return (value * Math.PI) / 180;
}
