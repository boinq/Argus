import { escapeHtml, formatDate } from "./utils.js";

export function renderSources(sources, schedulerJobs, elements) {
  if (!elements.summary || !elements.list) {
    return;
  }

  const items = filteredSources(sources, elements.filter.value);
  const connected = sources.filter((source) => source.status === "connected").length;
  const planned = sources.filter((source) => source.status === "planned").length;
  const manual = sources.filter((source) => source.status === "manual").length;
  const error = sources.filter((source) => source.status === "error").length;

  elements.summary.innerHTML = [
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
    elements.list.innerHTML = '<p class="empty">No sources match this filter.</p>';
    return;
  }

  elements.list.innerHTML = items
    .map((source) => sourceCard(source, schedulerJobs.find((item) => item.source_id === source.id)))
    .join("");
}

export function renderSourceSyncTargets(schedulerJobs, elements) {
  elements.target.innerHTML = schedulerJobs
    .map((job) => `<option value="${escapeHtml(job.id)}">${escapeHtml(job.name)}</option>`)
    .join("");
  elements.button.disabled = schedulerJobs.length === 0;
}

function filteredSources(sources, filter) {
  return filter === "all" ? sources : sources.filter((source) => source.status === filter);
}

function sourceCard(source, job) {
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
}
