const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

export const api = {
  health: () => request("/api/health"),
  listIncidents: () => request("/api/incidents"),
  createSampleIncident: () =>
    request("/api/incidents", {
      method: "POST",
      body: JSON.stringify({
        source_type: "sample",
        title: "Sample repo failing tests",
        sample_key: "sample-suite",
        test_command: "python -m pytest",
      }),
    }),
  createIncident: (payload) =>
    request("/api/incidents", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  runIncident: (id) => request(`/api/incidents/${id}/run?background=true`, { method: "POST" }),
  getIncident: (id) => request(`/api/incidents/${id}`),
  approvePr: (id) => request(`/api/incidents/${id}/approve-pr`, { method: "POST" }),
  saveGithubSettings: (payload) =>
    request("/api/settings/github", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  searchMemory: (q) => request(`/api/memory/search?q=${encodeURIComponent(q)}`),
  operatorStatus: () => request("/api/operator/status"),
  operatorPolicy: () => request("/api/operator/policy"),
  saveOperatorPolicy: (payload) =>
    request("/api/operator/policy", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  operatorWake: () => request("/api/operator/session/wake", { method: "POST" }),
  operatorSleep: () => request("/api/operator/session/sleep", { method: "POST" }),
  operatorStop: () => request("/api/operator/session/stop", { method: "POST" }),
  operatorCommand: (text) =>
    request("/api/operator/command", {
      method: "POST",
      body: JSON.stringify({ text, source: "dashboard" }),
    }),
  operatorVoiceTranscribe: (payload) =>
    request("/api/operator/voice/transcribe", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  operatorObserve: () => request("/api/operator/observation"),
  operatorHistory: () => request("/api/operator/history"),
  operatorApprovals: () => request("/api/operator/approvals"),
  operatorApprove: (action_id, approved) =>
    request("/api/operator/action/approve", {
      method: "POST",
      body: JSON.stringify({ action_id, approved }),
    }),
  vaultStatus: () => request("/api/privacy/vault/status"),
  vaultSearch: (q = "") => request(`/api/privacy/memory/search?q=${encodeURIComponent(q)}`),
  vaultDelete: (kind = "all", value = null) =>
    request("/api/privacy/memory", {
      method: "DELETE",
      body: JSON.stringify({ kind, value }),
    }),
  vaultExport: () => request("/api/privacy/export", { method: "POST" }),
  operatorSpeak: (text) =>
    request("/api/operator/speak", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  voiceListenerStart: () => request("/api/operator/voice-listener/start", { method: "POST" }),
  voiceListenerStop: () => request("/api/operator/voice-listener/stop", { method: "POST" }),
  voiceListenerStatus: () => request("/api/operator/voice-listener/status"),
  getFolders: () => request("/api/privacy/folders"),
  saveFolders: (folders) =>
    request("/api/privacy/folders", {
      method: "POST",
      body: JSON.stringify({ folders }),
    }),
  saveFriendConsent: (payload) =>
    request("/api/friend-voice/consent", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  prepareMessage: (payload) =>
    request("/api/messages/prepare", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  prepareVoiceMessage: (payload) =>
    request("/api/voice-message", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  startCall: (payload) =>
    request("/api/calls/start", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  preparePayment: (payload) =>
    request("/api/payments/prepare", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
