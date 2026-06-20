import { escapeHtml, eventColor, formatDate, mostCommon, severityRank } from "./utils.js";

export function reportEvents(events, { scope, category }) {
  return events.filter((event) => {
    const matchesScope = scope === "all" || event.status === scope;
    const matchesCategory = category === "all" || event.category === category;
    return matchesScope && matchesCategory;
  });
}

export function renderReports(events, elements) {
  if (!elements.summary || !elements.brief || !elements.list) {
    return;
  }

  const items = reportEvents(events, {
    scope: elements.scope.value,
    category: elements.category.value,
  });
  const highRisk = items.filter((event) => ["critical", "high"].includes(event.severity));
  const current = items.filter((event) => event.status === "current");
  const upcoming = items.filter((event) => event.status === "upcoming");
  const monitoring = items.filter((event) => event.status === "monitoring");
  const categories = new Set(items.map((event) => event.category));

  elements.summary.innerHTML = [
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
    elements.brief.innerHTML = '<p class="empty">No events match this report scope.</p>';
    elements.list.innerHTML = "";
    return;
  }

  const leadingCategory = mostCommon(items.map((event) => event.category));
  const priority = [...items].sort(
    (a, b) => severityRank(b.severity) - severityRank(a.severity),
  )[0];

  elements.brief.innerHTML = `
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

  elements.list.innerHTML = [...items]
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
