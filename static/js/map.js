import { severityColors } from "./utils.js";

const denmarkBounds = [
  [54.45, 7.75],
  [58.05, 15.35],
];

export function setupMap() {
  const map = L.map("map", {
    maxBounds: denmarkBounds,
    maxBoundsViscosity: 0.8,
    zoomControl: false,
  }).fitBounds(denmarkBounds);

  L.control.zoom({ position: "bottomright" }).addTo(map);
  map.createPane("weatherPane");
  map.getPane("weatherPane").style.zIndex = 450;
  map.createPane("eventPane");
  map.getPane("eventPane").style.zIndex = 500;

  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {
      attribution:
        "Tiles &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community",
      maxZoom: 18,
    },
  ).addTo(map);

  L.tileLayer(
    "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    {
      attribution: "Boundaries &copy; Esri",
      maxZoom: 18,
      opacity: 0.74,
    },
  ).addTo(map);

  return map;
}

export function createMarkerLayer(kind) {
  if (typeof L.markerClusterGroup !== "function") {
    return L.layerGroup();
  }
  return L.markerClusterGroup({
    chunkedLoading: true,
    disableClusteringAtZoom: 11,
    maxClusterRadius: kind === "event" ? 46 : 38,
    showCoverageOnHover: false,
    spiderfyDistanceMultiplier: 1.3,
    iconCreateFunction: (cluster) => clusterIcon(cluster, kind),
  });
}

function clusterIcon(cluster, kind) {
  const count = cluster.getChildCount();
  const size = count >= 100 ? 52 : count >= 25 ? 46 : 40;
  const severity = highestClusterSeverity(cluster);
  const color = kind === "observation" ? "#8fb8ff" : severityColors[severity] || severityColors.low;
  return L.divIcon({
    className: `argus-cluster argus-cluster-${kind}`,
    html: `
      <span
        class="argus-cluster-badge"
        style="--cluster-color: ${color}; width: ${size}px; height: ${size}px"
      >
        ${count}
      </span>
    `,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function highestClusterSeverity(cluster) {
  const ranks = { critical: 4, high: 3, medium: 2, low: 1 };
  return cluster
    .getAllChildMarkers()
    .map((marker) => marker.options.argusSeverity || "low")
    .sort((a, b) => (ranks[b] || 0) - (ranks[a] || 0))[0] || "low";
}
