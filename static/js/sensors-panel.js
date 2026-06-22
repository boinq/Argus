import { escapeHtml, formatDate } from "./utils.js";

export function renderSensors(sensors, elements) {
  if (!elements.summary || !elements.list) {
    return;
  }

  const online = sensors.filter((sensor) => sensorAgeMinutes(sensor) <= 5).length;
  const totalPosts = sensors.reduce((sum, sensor) => sum + Number(sensor.total_posts || 0), 0);
  const totalEvents = sensors.reduce((sum, sensor) => sum + Number(sensor.total_events || 0), 0);

  elements.summary.innerHTML = [
    ["Sensors", sensors.length],
    ["Online", online],
    ["Acquisitions", totalPosts],
    ["Events", totalEvents],
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

  if (!sensors.length) {
    elements.list.innerHTML = '<p class="empty">No sensors have posted data yet.</p>';
    return;
  }

  elements.list.innerHTML = sensors.map(sensorCard).join("");
}

function sensorCard(sensor) {
  const age = sensorAgeMinutes(sensor);
  const state = age <= 5 ? "online" : age <= 30 ? "idle" : "offline";
  return `
    <article class="source-card sensor-card">
      <div class="source-card-header">
        <h3>${escapeHtml(sensor.label || sensor.sensor_id)}</h3>
        <span class="tag sensor-state ${state}">${escapeHtml(state)}</span>
      </div>
      <dl class="source-details">
        <div>
          <dt>Sensor ID</dt>
          <dd>${escapeHtml(sensor.sensor_id)}</dd>
        </div>
        <div>
          <dt>Last seen</dt>
          <dd>${escapeHtml(formatDate(sensor.last_seen))}</dd>
        </div>
        <div>
          <dt>Last source</dt>
          <dd>${escapeHtml(sensor.last_source_id || "Unknown")}</dd>
        </div>
        <div>
          <dt>Total acquisitions</dt>
          <dd>${escapeHtml(String(sensor.total_posts || 0))}</dd>
        </div>
      </dl>
      <div class="sensor-metrics">
        ${metric("Observations", sensor.total_observations)}
        ${metric("Articles", sensor.total_articles)}
        ${metric("Events", sensor.total_events)}
        ${metric("Source status", sensor.total_status_updates)}
        ${metric("Scheduler", sensor.total_scheduler_updates)}
      </div>
    </article>
  `;
}

function metric(label, value) {
  return `
    <div>
      <strong>${escapeHtml(String(value || 0))}</strong>
      <span>${escapeHtml(label)}</span>
    </div>
  `;
}

function sensorAgeMinutes(sensor) {
  const seenAt = new Date(sensor.last_seen).getTime();
  if (!Number.isFinite(seenAt)) {
    return Number.POSITIVE_INFINITY;
  }
  return (Date.now() - seenAt) / 60000;
}
