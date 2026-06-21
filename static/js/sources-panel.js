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

export function updateSourceCountdowns(root = document) {
  root.querySelectorAll("[data-next-run-at]").forEach((element) => {
    const nextRunAt = element.dataset.nextRunAt;
    const running = element.dataset.running === "true";
    const enabled = element.dataset.enabled === "true";
    const paused = element.dataset.paused === "true";
    element.textContent = countdownLabel(nextRunAt, { running, enabled, paused });
  });
}

function filteredSources(sources, filter) {
  return filter === "all" ? sources : sources.filter((source) => source.status === filter);
}

function sourceCard(source, job) {
  return `
    <article class="source-card">
      <div class="source-card-header">
        <h3>${escapeHtml(source.name)}</h3>
        <div class="source-card-badges">
          ${job?.paused ? '<span class="tag source-status paused">paused</span>' : ""}
          <span class="tag source-status ${escapeHtml(source.status)}">
            ${escapeHtml(source.status)}
          </span>
        </div>
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
          <dd>${job ? pollingLabel(job) : "Not scheduled"}</dd>
        </div>
        <div>
          <dt>Next poll</dt>
          <dd>
            ${job ? countdownElement(job) : "Not scheduled"}
          </dd>
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
      ${job ? sourceActions(job) : ""}
    </article>
  `;
}

function pollingLabel(job) {
  if (!job.enabled) {
    return `Disabled / ${job.interval_seconds}s`;
  }
  return `${job.paused ? "Paused" : "Enabled"} / ${job.interval_seconds}s`;
}

function sourceActions(job) {
  const action = job.paused ? "resume" : "pause";
  const label = job.paused ? "Resume polling" : "Pause polling";
  return `
    <div class="source-actions">
      <button
        type="button"
        data-source-poll-action="${action}"
        data-source-poll-job="${escapeHtml(job.id)}"
        ${job.running ? "disabled" : ""}
      >
        ${escapeHtml(label)}
      </button>
    </div>
  `;
}

function countdownElement(job) {
  return `
    <span
      data-next-run-at="${escapeHtml(job.next_run_at || "")}"
      data-running="${job.running ? "true" : "false"}"
      data-enabled="${job.enabled ? "true" : "false"}"
      data-paused="${job.paused ? "true" : "false"}"
    >
      ${escapeHtml(countdownLabel(job.next_run_at, {
        running: job.running,
        enabled: job.enabled,
        paused: job.paused,
      }))}
    </span>
  `;
}

function countdownLabel(nextRunAt, { running, enabled, paused }) {
  if (running) {
    return "Running now";
  }
  if (paused) {
    return "Paused";
  }
  if (!enabled) {
    return "Scheduler disabled";
  }
  if (!nextRunAt) {
    return "Calculating";
  }

  const remainingMs = new Date(nextRunAt).getTime() - Date.now();
  if (!Number.isFinite(remainingMs)) {
    return "Calculating";
  }
  if (remainingMs <= 0) {
    return "Due now";
  }

  const totalSeconds = Math.ceil(remainingMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    return `${hours}h ${remainingMinutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
  }
  return `${seconds}s`;
}
