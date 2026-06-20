export const severityColors = {
  critical: "#e03131",
  high: "#ff8f1f",
  medium: "#f2c94c",
  low: "#3fb950",
};

export function formatDate(value) {
  return new Intl.DateTimeFormat("en-DK", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatOptionalDate(value) {
  return value ? formatDate(value) : "Not set";
}

export function escapeHtml(value) {
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

export function eventColor(event) {
  return severityColors[event.severity] || severityColors.low;
}

export function categoryLabel(category) {
  return category.charAt(0).toUpperCase() + category.slice(1);
}

export function severityRank(severity) {
  const ranks = { critical: 4, high: 3, medium: 2, low: 1 };
  return ranks[severity] || 0;
}

export function mostCommon(values) {
  const counts = values.reduce((result, value) => {
    result[value] = (result[value] || 0) + 1;
    return result;
  }, {});
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || "none";
}
