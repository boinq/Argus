import { escapeHtml, formatDate } from "./utils.js";
import { observationDisplayName, observationValue } from "./markers.js";

export function stationDetailLoadingHtml(station) {
  return stationDetailShell(station, '<p class="empty">Loading station history...</p>');
}

export function stationDetailHtml(station, history) {
  const rows = history
    .filter((observation) => observation.station_id === station.station_id)
    .sort(
    (a, b) => new Date(b.observed_at).getTime() - new Date(a.observed_at).getTime(),
    );
  const grouped = groupByParameter(rows);
  const latestRows = station.parameters;

  return stationDetailShell(
    station,
    `
      <section class="detail-section">
        <h3>Latest Readings</h3>
        <dl class="detail-grid">
          ${latestRows
            .map(
              (observation) => `
                <div>
                  <dt>${escapeHtml(observationDisplayName(observation.parameter_id))}</dt>
                  <dd>
                    ${escapeHtml(observationValue(observation))}
                    <small>${escapeHtml(observedAtLabel(observation))}</small>
                  </dd>
                </div>
              `,
            )
            .join("")}
        </dl>
      </section>

      <section class="detail-section">
        <h3>History</h3>
        ${
          rows.length
            ? `<div class="station-history">${rows.slice(0, 80).map(historyRow).join("")}</div>`
            : '<p class="empty">No stored history for this station yet.</p>'
        }
      </section>

      <section class="detail-section">
        <h3>Parameter Counts</h3>
        <dl class="detail-grid">
          ${Object.entries(grouped)
            .map(
              ([parameterId, values]) => `
                <div>
                  <dt>${escapeHtml(observationDisplayName(parameterId))}</dt>
                  <dd>${values.length} stored sample${values.length === 1 ? "" : "s"}</dd>
                </div>
              `,
            )
            .join("")}
        </dl>
      </section>
    `,
  );
}

function stationDetailShell(station, body) {
  const latest = station.latest_observed_at ? formatDate(station.latest_observed_at) : "Unknown";
  return `
    <header class="detail-header">
      <div>
        <p class="eyebrow">DMI Station</p>
        <h2>Station ${escapeHtml(station.station_id)}</h2>
      </div>
      <button type="button" class="detail-close" data-detail-action="close" aria-label="Close detail">
        &times;
      </button>
    </header>

    <div class="detail-severity weather-detail">
      <span>${station.parameters.length} live parameter${station.parameters.length === 1 ? "" : "s"}</span>
      <strong>${station.observation_count} loaded sample${station.observation_count === 1 ? "" : "s"}</strong>
    </div>

    <dl class="detail-grid">
      <div>
        <dt>Latest</dt>
        <dd>${escapeHtml(latest)}</dd>
      </div>
      <div>
        <dt>Coordinates</dt>
        <dd>${Number(station.latitude).toFixed(4)}, ${Number(station.longitude).toFixed(4)}</dd>
      </div>
    </dl>

    <div class="detail-actions">
      <button type="button" data-detail-action="focus-station">Focus Map</button>
      <button type="button" data-detail-action="refresh-station">Refresh History</button>
    </div>

    ${body}
  `;
}

function historyRow(observation) {
  return `
    <div class="station-history-row">
      <span>${escapeHtml(observedAtLabel(observation))}</span>
      <strong>${escapeHtml(observationDisplayName(observation.parameter_id))}</strong>
      <em>${escapeHtml(observationValue(observation))}</em>
    </div>
  `;
}

function observedAtLabel(observation) {
  return observation.observed_at ? formatDate(observation.observed_at) : "Observed time missing";
}

function groupByParameter(observations) {
  return observations.reduce((result, observation) => {
    result[observation.parameter_id] = result[observation.parameter_id] || [];
    result[observation.parameter_id].push(observation);
    return result;
  }, {});
}
