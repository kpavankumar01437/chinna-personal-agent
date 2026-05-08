const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

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
};
