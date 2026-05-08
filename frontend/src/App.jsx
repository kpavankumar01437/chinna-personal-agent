import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  FileUp,
  GitPullRequest,
  History,
  Mic2,
  Play,
  RefreshCcw,
  Settings,
  ShieldCheck,
  Sparkles,
  TestTube2,
} from "lucide-react";
import { api } from "./lib/api";

const emptyDetail = {
  incident: null,
  events: [],
  attempts: [],
  mistakes: [],
  security_reviews: [],
  rollback_plan: null,
  memory: [],
  pr_draft: null,
  diff: "",
  voice_briefing: "",
};

function App() {
  const [health, setHealth] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [detail, setDetail] = useState(emptyDetail);
  const [running, setRunning] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [intake, setIntake] = useState({
    title: "Uploaded incident",
    logs: "",
    repoPath: "",
    testCommand: "python -m pytest",
    fileName: "",
  });
  const [githubSettings, setGithubSettings] = useState({
    owner: "",
    repo: "",
    base_branch: "main",
    token: "",
  });

  const incident = detail.incident;
  const finalState = incident && ["Resolved", "Escalated"].includes(incident.status);

  useEffect(() => {
    loadInitial();
  }, []);

  useEffect(() => {
    if (!incident?.id || !running) return;
    const timer = setInterval(async () => {
      const next = await api.getIncident(incident.id);
      setDetail(next);
      if (["Resolved", "Escalated"].includes(next.incident.status)) {
        setRunning(false);
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [incident?.id, running, finalState]);

  async function loadInitial() {
    try {
      setHealth(await api.health());
      const list = await api.listIncidents();
      setIncidents(list);
      if (list[0]) setDetail(await api.getIncident(list[0].id));
    } catch (err) {
      setError(err.message);
    }
  }

  async function triggerSample() {
    setError("");
    setNotice("");
    const created = await api.createSampleIncident();
    setDetail(created);
    setIncidents(await api.listIncidents());
    setNotice("Sample incident detected.");
  }

  async function handleFileInput(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    setIntake((current) => ({
      ...current,
      title: current.title === "Uploaded incident" ? file.name : current.title,
      logs: text,
      fileName: file.name,
    }));
    setNotice(`Loaded ${file.name}. Create the incident when ready.`);
  }

  async function createCustomIncident(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    if (!intake.logs.trim() && !intake.repoPath.trim()) {
      setError("Upload a log file, paste logs, or provide a repo path before creating an incident.");
      return;
    }
    const created = await api.createIncident({
      source_type: intake.fileName ? "file-upload" : "manual",
      title: intake.title.trim() || intake.fileName || "Manual incident",
      logs: intake.logs,
      repo_path: intake.repoPath.trim() || null,
      test_command: intake.testCommand.trim() || "python -m pytest",
    });
    setDetail(created);
    setIncidents(await api.listIncidents());
    setNotice("Incident created from your input.");
  }

  async function runAgents() {
    if (!incident) return;
    setError("");
    setNotice("");
    setRunning(true);
    await api.runIncident(incident.id);
    setNotice("Agents started.");
  }

  async function approvePr() {
    if (!incident) return;
    const result = await api.approvePr(incident.id);
    setNotice(result.pr_url ? `Pull request created: ${result.pr_url}` : result.message);
    setDetail(await api.getIncident(incident.id));
  }

  async function saveGithubSettings(event) {
    event.preventDefault();
    setError("");
    const result = await api.saveGithubSettings(githubSettings);
    setNotice(result.token_present ? "GitHub settings saved with token." : "GitHub settings saved. PR preview will be used until a token is added.");
  }

  function speakBriefing() {
    if (!detail.voice_briefing || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(detail.voice_briefing);
    utterance.rate = 0.95;
    window.speechSynthesis.speak(utterance);
  }

  const latestAttempt = detail.attempts.at(-1);
  const changedFiles = useMemo(() => detail.rollback_plan?.affected_files || [], [detail.rollback_plan]);

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Autonomous DevOps Repair Platform</p>
          <h1>DevPilot AI</h1>
        </div>
        <div className="toolbar">
          <button className="ghost" onClick={loadInitial}>
            <RefreshCcw size={17} /> Refresh
          </button>
          <button onClick={triggerSample}>
            <Sparkles size={17} /> Trigger Sample Incident
          </button>
          <button className="primary" disabled={!incident || running} onClick={runAgents}>
            <Play size={17} /> Run Agents
          </button>
        </div>
      </header>

      {(notice || error) && <div className={error ? "banner error" : "banner"}>{error || notice}</div>}

      <section className="overview">
        <Metric icon={<Bot />} label="AI Routing" value={health?.remote_ai_configured ? "OpenAI live" : "Local fallback"} note={`${health?.reasoning_model || "gpt-5.5"} + ${health?.coding_model || "gpt-5.1-codex-max"}`} />
        <Metric icon={<AlertTriangle />} label="Severity" value={incident?.severity || "Waiting"} note={incident?.status || "No incident selected"} tone="warn" />
        <Metric icon={<CheckCircle2 />} label="Confidence" value={`${incident?.confidence || 0}%`} note={latestAttempt ? `Latest tests ${latestAttempt.test_result}` : "No verification yet"} tone="good" />
        <Metric icon={<Clock3 />} label="Time Saved" value={`${incident?.time_saved_minutes || 0} min`} note="Estimated manual debugging time" tone="time" />
      </section>

      <section className="workspace">
        <aside className="incident-list panel">
          <PanelTitle icon={<FileUp />} title="Incident Intake" />
          <form className="intake-form" onSubmit={createCustomIncident}>
            <label>
              <span>Log or error file</span>
              <input type="file" accept=".log,.txt,.json,.out,.err,.xml" onChange={handleFileInput} />
            </label>
            {intake.fileName && <small>Loaded file: {intake.fileName}</small>}
            <label>
              <span>Incident title</span>
              <input
                value={intake.title}
                onChange={(event) => setIntake((current) => ({ ...current, title: event.target.value }))}
                placeholder="CI failure from uploaded log"
              />
            </label>
            <label>
              <span>Paste logs</span>
              <textarea
                value={intake.logs}
                onChange={(event) => setIntake((current) => ({ ...current, logs: event.target.value }))}
                placeholder="Paste stack trace, failed test output, or GitHub Actions logs"
              />
            </label>
            <label>
              <span>Repo path</span>
              <input
                value={intake.repoPath}
                onChange={(event) => setIntake((current) => ({ ...current, repoPath: event.target.value }))}
                placeholder="Optional local repo path"
              />
            </label>
            <label>
              <span>Test command</span>
              <input
                value={intake.testCommand}
                onChange={(event) => setIntake((current) => ({ ...current, testCommand: event.target.value }))}
              />
            </label>
            <button type="submit">
              <FileUp size={17} /> Create Incident
            </button>
          </form>

          <PanelTitle icon={<History />} title="Incidents" />
          {incidents.length === 0 && <p className="muted">No incidents yet.</p>}
          {incidents.map((item) => (
            <button
              className={`incident-row ${incident?.id === item.id ? "active" : ""}`}
              key={item.id}
              onClick={async () => setDetail(await api.getIncident(item.id))}
            >
              <span>{item.title}</span>
              <small>{item.status}</small>
            </button>
          ))}
        </aside>

        <section className="main-grid">
          <Panel className="wide" icon={<BrainCircuit />} title="Live Agent Timeline">
            <div className="timeline">
              {detail.events.map((event) => (
                <div className={`timeline-row ${event.status}`} key={event.id}>
                  <strong>{event.agent_name}</strong>
                  <span>{event.step_type}</span>
                  <p>{event.message}</p>
                </div>
              ))}
              {detail.events.length === 0 && <p className="muted">Create an incident to start the workflow.</p>}
            </div>
          </Panel>

          <Panel icon={<AlertTriangle />} title="Root Cause">
            <p className="big-text">{incident?.root_cause || "No root cause yet."}</p>
            <div className="chips">
              <span>{incident?.source_type || "source"}</span>
              <span>{incident?.test_command || "test command"}</span>
              {changedFiles.map((file) => (
                <span key={file}>{file}</span>
              ))}
            </div>
          </Panel>

          <Panel icon={<TestTube2 />} title="Test Evidence">
            {detail.attempts.map((attempt) => (
                <div className="attempt" key={attempt.id}>
                  <div>
                  <strong>{attempt.attempt_number === 0 ? "Baseline" : `Attempt ${attempt.attempt_number}`}</strong>
                  <span className={attempt.test_result === "passed" ? "pass" : "fail"}>{attempt.test_result}</span>
                </div>
                <p>{attempt.patch_summary}</p>
                <pre>{attempt.logs.slice(-900)}</pre>
              </div>
            ))}
            {detail.attempts.length === 0 && <p className="muted">Tests have not run yet.</p>}
          </Panel>

          <Panel className="wide" icon={<AlertTriangle />} title="Mistakes & Resolutions">
            <div className="table">
              <div className="table-head">
                <span>Time</span>
                <span>Agent</span>
                <span>Mistake / Error</span>
                <span>Action Taken</span>
                <span>Result</span>
                <span>Status</span>
              </div>
              {detail.mistakes.map((mistake) => (
                <div className="table-row" key={mistake.id}>
                  <span>{formatTime(mistake.created_at)}</span>
                  <span>{mistake.agent_name}</span>
                  <span>{mistake.mistake}</span>
                  <span>{mistake.attempted_action}</span>
                  <span>{mistake.result}</span>
                  <span>{mistake.status}</span>
                </div>
              ))}
            </div>
            {detail.mistakes.length === 0 && <p className="muted">Self-correction records will appear here.</p>}
          </Panel>

          <Panel className="wide" icon={<GitPullRequest />} title="Code Diff">
            <div className="file-strip">
              {changedFiles.map((file) => (
                <span key={file}>{file}</span>
              ))}
            </div>
            <pre className="diff">{detail.diff || "No patch generated yet."}</pre>
          </Panel>

          <Panel icon={<ShieldCheck />} title="Security Review">
            {detail.security_reviews.map((review) => (
              <div className="review" key={review.id}>
                <strong>{review.risk_level} risk</strong>
                <p>{review.blocked_reason}</p>
                <small>{review.approval_required ? "Approval required" : "No sensitive patterns detected"}</small>
              </div>
            ))}
            {detail.security_reviews.length === 0 && <p className="muted">No review yet.</p>}
          </Panel>

          <Panel icon={<RefreshCcw />} title="Rollback Plan">
            {detail.rollback_plan ? (
              <>
                <p className="command">{detail.rollback_plan.rollback_command}</p>
                {detail.rollback_plan.revert_steps.map((step) => (
                  <p key={step}>{step}</p>
                ))}
              </>
            ) : (
              <p className="muted">Rollback plan will be generated after repair.</p>
            )}
          </Panel>

          <Panel icon={<History />} title="Memory">
            {detail.memory.map((entry) => (
              <div className="memory" key={entry.id}>
                <strong>{entry.error_signature}</strong>
                <p>{entry.fix_summary}</p>
                <small>Reused {entry.reuse_count} time(s)</small>
              </div>
            ))}
            {detail.memory.length === 0 && <p className="muted">No memory entries yet.</p>}
          </Panel>

          <Panel icon={<GitPullRequest />} title="PR Approval">
            {detail.pr_draft ? (
              <>
                <strong>{detail.pr_draft.title}</strong>
                <p>{detail.pr_draft.diff_summary}</p>
                <p className="command">{detail.pr_draft.status}</p>
                <button onClick={approvePr}>
                  <GitPullRequest size={17} /> Approve PR
                </button>
              </>
            ) : (
              <p className="muted">PR draft appears after a repair run.</p>
            )}
          </Panel>

          <Panel icon={<Settings />} title="GitHub Settings">
            <form className="settings-form" onSubmit={saveGithubSettings}>
              <label>
                <span>Owner</span>
                <input
                  value={githubSettings.owner}
                  onChange={(event) => setGithubSettings((current) => ({ ...current, owner: event.target.value }))}
                  placeholder="github-user-or-org"
                />
              </label>
              <label>
                <span>Repository</span>
                <input
                  value={githubSettings.repo}
                  onChange={(event) => setGithubSettings((current) => ({ ...current, repo: event.target.value }))}
                  placeholder="repo-name"
                />
              </label>
              <label>
                <span>Base branch</span>
                <input
                  value={githubSettings.base_branch}
                  onChange={(event) => setGithubSettings((current) => ({ ...current, base_branch: event.target.value }))}
                />
              </label>
              <label>
                <span>GitHub token</span>
                <input
                  type="password"
                  value={githubSettings.token}
                  onChange={(event) => setGithubSettings((current) => ({ ...current, token: event.target.value }))}
                  placeholder="Optional for real PR creation"
                />
              </label>
              <button type="submit">
                <Settings size={17} /> Save Settings
              </button>
            </form>
          </Panel>

          <Panel className="wide" icon={<Mic2 />} title="Voice Briefing">
            <p>{detail.voice_briefing || "Briefing appears after the workflow runs."}</p>
            <button disabled={!detail.voice_briefing} onClick={speakBriefing}>
              <Mic2 size={17} /> Play Briefing
            </button>
          </Panel>
        </section>
      </section>
    </main>
  );
}

function Metric({ icon, label, value, note, tone = "" }) {
  return (
    <article className={`metric ${tone}`}>
      <div>{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function Panel({ icon, title, children, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      <PanelTitle icon={icon} title={title} />
      {children}
    </section>
  );
}

function PanelTitle({ icon, title }) {
  return (
    <div className="panel-title">
      {icon}
      <h2>{title}</h2>
    </div>
  );
}

function formatTime(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

export default App;
