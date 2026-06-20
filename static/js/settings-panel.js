export function settingsPayload(elements) {
  return {
    public_base_url: elements.publicBaseUrl.value.trim(),
    path_prefix: elements.pathPrefix.value.trim(),
    trusted_hosts: elements.trustedHosts.value.trim(),
    proxy_headers: elements.proxyHeaders.checked,
    ntfy_enabled: elements.ntfyEnabled.checked,
    ntfy_server_url: elements.ntfyServerUrl.value.trim(),
    ntfy_topic: elements.ntfyTopic.value.trim(),
    ntfy_token: elements.ntfyToken.value,
    ntfy_priority: elements.ntfyPriority.value,
  };
}

export function fillSettings(settings, elements) {
  elements.publicBaseUrl.value = settings.public_base_url || "";
  elements.pathPrefix.value = settings.path_prefix || "";
  elements.trustedHosts.value = settings.trusted_hosts || "";
  elements.proxyHeaders.checked = Boolean(settings.proxy_headers);
  elements.ntfyEnabled.checked = Boolean(settings.ntfy_enabled);
  elements.ntfyServerUrl.value = settings.ntfy_server_url || "";
  elements.ntfyTopic.value = settings.ntfy_topic || "";
  elements.ntfyToken.value = settings.ntfy_token || "";
  elements.ntfyPriority.value = settings.ntfy_priority || "default";
}

export function renderProxySnippet(settings, element) {
  const prefix = settings.path_prefix || "";
  const lines = [
    "ARGUS_PUBLIC_BASE_URL=" + (settings.public_base_url || ""),
    "ARGUS_ROOT_PATH=" + prefix,
    "ARGUS_TRUSTED_HOSTS=" + (settings.trusted_hosts || "*"),
    "ARGUS_PROXY_HEADERS=" + String(Boolean(settings.proxy_headers)),
    "ARGUS_NTFY_ENABLED=" + String(Boolean(settings.ntfy_enabled)),
    "ARGUS_NTFY_SERVER_URL=" + (settings.ntfy_server_url || ""),
    "ARGUS_NTFY_TOPIC=" + (settings.ntfy_topic || ""),
    "ARGUS_NTFY_TOKEN=" + (settings.ntfy_token ? "[configured]" : ""),
    "ARGUS_NTFY_PRIORITY=" + (settings.ntfy_priority || "default"),
  ];
  element.textContent = lines.join("\n");
}
