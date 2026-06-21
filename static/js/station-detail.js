import { escapeHtml, formatDate } from "./utils.js";
import { observationDisplayName, observationValue } from "./markers.js";

const CHARTS = [
  {
    id: "wind",
    title: "Wind speed",
    parameterIds: ["wind_speed", "wind_gust_always_past1h"],
    color: "#8fb8ff",
    unit: "m/s",
    style: "line",
  },
  {
    id: "temperature",
    title: "Temperature",
    parameterIds: ["temp_dry"],
    color: "#ffd166",
    unit: "C",
    style: "line",
  },
  {
    id: "precipitation",
    title: "Precipitation",
    parameterIds: ["precip_past10min"],
    color: "#21c7a8",
    unit: "mm / 10 min",
    style: "bar",
  },
];

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
  const charts = stationCharts(grouped);

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
          charts.length
            ? `<div class="station-charts">${charts.join("")}</div>`
            : '<p class="empty">No chartable DMI history for this station yet.</p>'
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

function stationCharts(grouped) {
  return CHARTS.map((chart) => chartHtml(chart, chartObservations(chart, grouped))).filter(Boolean);
}

function chartObservations(chart, grouped) {
  return chart.parameterIds
    .flatMap((parameterId) => grouped[parameterId] || [])
    .filter(
      (observation) =>
        Number.isFinite(Number(observation.value)) &&
        Number.isFinite(Date.parse(observation.observed_at)),
    )
    .sort((a, b) => new Date(a.observed_at).getTime() - new Date(b.observed_at).getTime())
    .slice(-180);
}

function chartHtml(chart, observations) {
  if (!observations.length) {
    return "";
  }

  const values = observations.map((observation) => Number(observation.value));
  const latest = observations[observations.length - 1];
  const parameterNames = [...new Set(observations.map((observation) => observation.parameter_id))]
    .map(observationDisplayName)
    .join(" / ");

  return `
    <article class="station-chart-card">
      <header class="station-chart-header">
        <div>
          <h4>${escapeHtml(chart.title)}</h4>
          <p>${escapeHtml(parameterNames)}</p>
        </div>
        <strong>${escapeHtml(formatChartValue(latest.value, chart.unit))}</strong>
      </header>
      ${chartSvg(chart, observations)}
      <dl class="station-chart-stats">
        <div>
          <dt>Samples</dt>
          <dd>${observations.length}</dd>
        </div>
        <div>
          <dt>Min</dt>
          <dd>${escapeHtml(formatChartValue(Math.min(...values), chart.unit))}</dd>
        </div>
        <div>
          <dt>Max</dt>
          <dd>${escapeHtml(formatChartValue(Math.max(...values), chart.unit))}</dd>
        </div>
        <div>
          <dt>Latest</dt>
          <dd>${escapeHtml(observedAtLabel(latest))}</dd>
        </div>
      </dl>
    </article>
  `;
}

function chartSvg(chart, observations) {
  const width = 320;
  const height = 132;
  const padding = { top: 14, right: 12, bottom: 22, left: 34 };
  const values = observations.map((observation) => Number(observation.value));
  const times = observations.map((observation) => Date.parse(observation.observed_at));
  const domain = valueDomain(values);
  const timeMin = Math.min(...times);
  const timeMax = Math.max(...times);
  const x = (time, index) =>
    timeMax === timeMin
      ? padding.left + ((width - padding.left - padding.right) * index) / Math.max(1, observations.length - 1)
      : padding.left + ((time - timeMin) / (timeMax - timeMin)) * (width - padding.left - padding.right);
  const y = (value) =>
    height - padding.bottom - ((value - domain.min) / (domain.max - domain.min)) * (height - padding.top - padding.bottom);
  const points = observations.map((observation, index) => ({
    x: x(Date.parse(observation.observed_at), index),
    y: y(Number(observation.value)),
    value: Number(observation.value),
  }));

  const body = chart.style === "bar"
    ? barSeries(points, y(0), chart.color)
    : lineSeries(points, height - padding.bottom, chart.color);

  return `
    <svg class="station-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(chart.title)} history">
      <line class="station-chart-axis" x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}"></line>
      <line class="station-chart-axis" x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${height - padding.bottom}"></line>
      <text class="station-chart-label" x="${padding.left}" y="10">${escapeHtml(formatChartValue(domain.max, chart.unit))}</text>
      <text class="station-chart-label" x="${padding.left}" y="${height - 4}">${escapeHtml(formatChartValue(domain.min, chart.unit))}</text>
      ${body}
    </svg>
  `;
}

function lineSeries(points, baseline, color) {
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
  const area = `${path} L ${points[points.length - 1].x.toFixed(1)} ${baseline} L ${points[0].x.toFixed(1)} ${baseline} Z`;
  return `
    <path class="station-chart-area" d="${area}" fill="${escapeHtml(color)}"></path>
    <path class="station-chart-line" d="${path}" stroke="${escapeHtml(color)}"></path>
    ${points.slice(-24).map((point) => `<circle class="station-chart-dot" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="1.8" fill="${escapeHtml(color)}"></circle>`).join("")}
  `;
}

function barSeries(points, zeroY, color) {
  const barWidth = Math.max(2, Math.min(8, 220 / Math.max(1, points.length)));
  return points
    .map((point) => {
      const top = Math.min(point.y, zeroY);
      const height = Math.max(1, Math.abs(zeroY - point.y));
      return `<rect class="station-chart-bar" x="${(point.x - barWidth / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${height.toFixed(1)}" fill="${escapeHtml(color)}"></rect>`;
    })
    .join("");
}

function valueDomain(values) {
  const minimum = Math.min(...values, 0);
  const maximum = Math.max(...values, 0);
  if (minimum === maximum) {
    const padding = Math.max(Math.abs(minimum) * 0.2, 1);
    return { min: minimum - padding, max: maximum + padding };
  }
  const padding = (maximum - minimum) * 0.12;
  return { min: minimum - padding, max: maximum + padding };
}

function formatChartValue(value, unit) {
  return `${Number(value).toFixed(1)}${unit ? ` ${unit}` : ""}`;
}
