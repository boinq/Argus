import { escapeHtml, formatDate } from "./utils.js";

const RULE_GROUPS = ["category", "severity", "event", "promote", "maritime", "noise"];
const CATEGORIES = ["", "weather", "hybrid", "electrical", "food", "health", "transport", "maritime", "emergency", "other"];
const SEVERITIES = ["", "low", "medium", "high", "critical"];

export function renderMlOverview(overview, element) {
  const items = [
    ["Events", overview.events ?? 0],
    ["Candidates", overview.candidate_terms ?? 0],
    ["Active Rules", overview.active_terms ?? 0],
    ["Learned Rules", overview.learned_terms ?? 0],
  ];
  element.innerHTML = items
    .map(
      ([label, count]) => `
        <div class="summary-item">
          <strong>${count}</strong>
          <span>${escapeHtml(label)}</span>
        </div>
      `,
    )
    .join("");
}

export function renderMlSources(sources, select) {
  const current = select.value;
  select.innerHTML = [
    '<option value="">All sources</option>',
    ...sources.map(
      (source) =>
        `<option value="${escapeHtml(source.id)}">${escapeHtml(source.name)}</option>`,
    ),
  ].join("");
  select.value = [...select.options].some((option) => option.value === current) ? current : "";
}

export function renderMlScore(score, element) {
  if (!score || (!score.category && !score.severity)) {
    element.innerHTML = '<p class="empty">No confident classification.</p>';
    return;
  }
  element.innerHTML = `
    ${score.category ? scoreBlock("Category", score.category) : ""}
    ${score.severity ? scoreBlock("Severity", score.severity) : ""}
  `;
}

export function renderMlCandidates(candidates, element) {
  if (!candidates.length) {
    element.innerHTML = '<p class="empty">No candidate terms yet.</p>';
    return;
  }
  element.innerHTML = candidates.map(candidateCard).join("");
}

export function renderMlTerms(terms, element) {
  if (!terms.length) {
    element.innerHTML = '<p class="empty">No active rules yet.</p>';
    return;
  }
  element.innerHTML = terms
    .map(
      (term) => `
        <article class="ml-card">
          <div class="ml-card-header">
            <div>
              <h3>${escapeHtml(term.term)}</h3>
              <p>${escapeHtml(term.source_id)} / ${escapeHtml(term.rule_group)}</p>
            </div>
            <span class="source-status connected">${escapeHtml(term.source)}</span>
          </div>
          <dl class="source-details">
            <div><dt>Category</dt><dd>${escapeHtml(term.category || "-")}</dd></div>
            <div><dt>Severity</dt><dd>${escapeHtml(term.severity || "-")}</dd></div>
            <div><dt>Score</dt><dd>${escapeHtml(String(term.score))}</dd></div>
            <div><dt>Updated</dt><dd>${formatDate(term.updated_at)}</dd></div>
          </dl>
        </article>
      `,
    )
    .join("");
}

function scoreBlock(label, item) {
  const confidence = Math.round((item.confidence || 0) * 100);
  const reasons = (item.reasons || []).map((reason) => `<span>${escapeHtml(reason)}</span>`).join("");
  return `
    <article class="ml-card">
      <div class="ml-card-header">
        <div>
          <h3>${escapeHtml(label)}: ${escapeHtml(item.label)}</h3>
          <p>${confidence}% confidence</p>
        </div>
      </div>
      <div class="ml-reasons">${reasons || "<span>No evidence tokens</span>"}</div>
    </article>
  `;
}

function candidateCard(candidate) {
  return `
    <article class="ml-card" data-ml-candidate>
      <div class="ml-card-header">
        <div>
          <h3>${escapeHtml(candidate.term)}</h3>
          <p>${escapeHtml(candidate.source_id)} · seen ${escapeHtml(String(candidate.seen_count))} times</p>
        </div>
      </div>
      <p class="ml-sample">${escapeHtml(candidate.sample_title || "")}</p>
      <div class="ml-promote-grid">
        ${selectHtml("rule-group", RULE_GROUPS, defaultRuleGroup(candidate.source_id))}
        ${selectHtml("category", CATEGORIES, "")}
        ${selectHtml("severity", SEVERITIES, "")}
        <input data-ml-field="score" type="number" min="0" max="20" value="1" />
      </div>
      <button
        type="button"
        class="save-button"
        data-ml-action="promote"
        data-source-id="${escapeHtml(candidate.source_id)}"
        data-term="${escapeHtml(candidate.term)}"
      >
        Promote
      </button>
    </article>
  `;
}

function selectHtml(field, values, selected) {
  return `
    <select data-ml-field="${escapeHtml(field)}">
      ${values
        .map(
          (value) =>
            `<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>${escapeHtml(value || "-")}</option>`,
        )
        .join("")}
    </select>
  `;
}

function defaultRuleGroup(sourceId) {
  if (sourceId === "dr-news") {
    return "category";
  }
  if (sourceId === "dma-news") {
    return "maritime";
  }
  if (sourceId === "police-ritzau-short-messages") {
    return "event";
  }
  if (sourceId === "health-alerts") {
    return "promote";
  }
  return "severity";
}
