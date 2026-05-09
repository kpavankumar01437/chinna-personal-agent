import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  Database,
  Eye,
  FileUp,
  GitPullRequest,
  History,
  Lock,
  Mic2,
  Moon,
  Play,
  RefreshCcw,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Sun,
  TestTube2,
  Volume2,
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
  const [operatorStatus, setOperatorStatus] = useState(null);
  const [operatorCommand, setOperatorCommand] = useState("Hey Chinna WakeUp run the DevPilot repair demo");
  const [operatorReply, setOperatorReply] = useState("");
  const [operatorPlan, setOperatorPlan] = useState([]);
  const [voiceRepliesEnabled, setVoiceRepliesEnabled] = useState(true);
  const [recording, setRecording] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState("Voice replies are on.");
  const [voiceListener, setVoiceListener] = useState(null);
  const [operatorHistory, setOperatorHistory] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [vault, setVault] = useState(null);
  const [vaultRecords, setVaultRecords] = useState([]);
  const [folders, setFolders] = useState([]);
  const [selectedFolders, setSelectedFolders] = useState({});
  const [operatorPolicyMode, setOperatorPolicyMode] = useState("hybrid");
  const [friendVoice, setFriendVoice] = useState({
    friend_name: "",
    consent_note: "",
    consent_clip_path: "",
    language: "English + Telugu",
  });
  const [messageRequest, setMessageRequest] = useState({
    app: "WhatsApp",
    recipient: "",
    message: "",
  });
  const [voiceMessage, setVoiceMessage] = useState({
    recipient: "",
    message: "",
    use_friend_voice: true,
  });
  const [callRequest, setCallRequest] = useState({
    app: "WhatsApp",
    contact_or_url: "",
    use_friend_voice: true,
    record_call: true,
  });
  const [paymentRequest, setPaymentRequest] = useState({
    app: "GPay",
    recipient: "",
    amount: "",
    upi_id: "",
    note: "",
  });

  const incident = detail.incident;
  const finalState = incident && ["Resolved", "Escalated"].includes(incident.status);
  const mediaRecorderRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const audioChunksRef = useRef([]);
  const autoStopTimerRef = useRef(null);

  useEffect(() => {
    loadInitial();
  }, []);

  useEffect(() => {
    const hotkeyHandler = () => handleOperatorWake();
    window.omnipilotDesktop?.onHotkey?.(hotkeyHandler);
  }, []);

  useEffect(() => {
    return () => {
      clearTimeout(autoStopTimerRef.current);
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      window.speechSynthesis?.cancel();
    };
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

  useEffect(() => {
    if (!voiceListener?.enabled) return;
    const timer = setInterval(async () => {
      const status = await api.voiceListenerStatus();
      setVoiceListener(status);
      if (status.last_transcript) setVoiceStatus(`Listener heard: "${status.last_transcript}"`);
      if (status.last_reply) setOperatorReply(status.last_reply);
    }, 2500);
    return () => clearInterval(timer);
  }, [voiceListener?.enabled]);

  async function loadInitial() {
    try {
      setHealth(await api.health());
      await loadOperator();
      const list = await api.listIncidents();
      setIncidents(list);
      if (list[0]) setDetail(await api.getIncident(list[0].id));
    } catch (err) {
      setError(err.message);
    }
  }

  async function loadOperator() {
    const [status, history, pending, vaultStatus, records, folderList, listenerStatus] = await Promise.all([
      api.operatorStatus(),
      api.operatorHistory(),
      api.operatorApprovals(),
      api.vaultStatus(),
      api.vaultSearch(""),
      api.getFolders(),
      api.voiceListenerStatus(),
    ]);
    setOperatorStatus(status);
    setOperatorHistory(history);
    setApprovals(pending);
    setVault(vaultStatus);
    setVaultRecords(records);
    setFolders(folderList);
    setSelectedFolders((current) => {
      const next = {};
      folderList.forEach((folder) => {
        next[folder.path] = current[folder.path] ?? (folder.status === "approved" || folder.status === "review-required");
      });
      return next;
    });
    setOperatorPolicyMode(status.policy?.reasoning_mode || "hybrid");
    setVoiceListener(listenerStatus);
  }

  function browserSpeakText(text) {
    if (!text || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.95;
    utterance.pitch = 1;
    const voices = window.speechSynthesis.getVoices();
    const preferredVoice = voices.find((voice) => /english|zira|natural/i.test(`${voice.name} ${voice.lang}`));
    if (preferredVoice) utterance.voice = preferredVoice;
    window.speechSynthesis.speak(utterance);
  }

  function speakText(text, force = false) {
    const clean = String(text || "").trim();
    if (!clean || (!voiceRepliesEnabled && !force)) return;
    api.operatorSpeak(clean).catch(() => browserSpeakText(clean));
  }

  async function runOperatorCommand(text, source = "text") {
    const cleanCommand = text.trim();
    if (!cleanCommand) return;
    setError("");
    const result = await api.operatorCommand(cleanCommand);
    setOperatorStatus(result.status);
    setOperatorReply(result.reply);
    setOperatorPlan(result.plan || []);
    if (source === "voice") {
      setVoiceStatus(`Heard: "${cleanCommand}"`);
    }
    speakText(result.reply);
    await loadOperator();
    const latest = await api.listIncidents();
    setIncidents(latest);
    if (latest[0]) setDetail(await api.getIncident(latest[0].id));
  }

  async function handleOperatorWake() {
    const status = await api.operatorWake();
    setOperatorStatus(status);
    setNotice("Chinna is awake.");
    speakText("Chinna is awake and listening.");
  }

  async function handleOperatorSleep() {
    const status = await api.operatorSleep();
    setOperatorStatus(status);
    setNotice("Chinna is sleeping.");
    speakText("Going to sleep now.");
  }

  async function handleOperatorStop() {
    const status = await api.operatorStop();
    setOperatorStatus(status);
    setNotice("Emergency stop activated.");
    speakText("Emergency stop activated. I have halted pending actions.");
    await loadOperator();
  }

  async function sendOperatorCommand(event) {
    event.preventDefault();
    await runOperatorCommand(operatorCommand);
  }

  async function runQuickCommand(text) {
    setOperatorCommand(text);
    await runOperatorCommand(text);
  }

  async function observeScreen() {
    const result = await api.operatorObserve();
    setOperatorReply(result.message);
    speakText(result.message);
    await loadOperator();
  }

  async function startVoiceCommand() {
    setError("");
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setError("Microphone recording is not available in this browser. Use the Electron app or type the command.");
      return;
    }
    window.speechSynthesis?.cancel();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      audioChunksRef.current = [];
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm")
          ? "audio/webm"
          : "";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };
      recorder.onstop = async () => {
        clearTimeout(autoStopTimerRef.current);
        setRecording(false);
        mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
        mediaStreamRef.current = null;
        const audioBlob = new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        if (!audioBlob.size) {
          setVoiceStatus("No audio was captured.");
          speakText("I did not hear anything clearly.");
          return;
        }
        try {
          setVoiceStatus("Transcribing locally with Whisper...");
          const audioBase64 = await blobToBase64(audioBlob);
          const transcript = await api.operatorVoiceTranscribe({
            audio_base64: audioBase64,
            mime_type: audioBlob.type || "audio/webm",
            language_hint: "auto",
          });
          if (!transcript.text) {
            const message = transcript.error || "I could not detect speech clearly.";
            setVoiceStatus(message);
            speakText("I could not hear the command clearly. Please try again.");
            return;
          }
          setOperatorCommand(transcript.text);
          await runOperatorCommand(transcript.text, "voice");
        } catch (err) {
          setError(err.message);
          setVoiceStatus("Voice command failed safely.");
        }
      };
      recorder.start();
      setRecording(true);
      setVoiceStatus("Listening now. Speak naturally.");
      autoStopTimerRef.current = setTimeout(() => stopVoiceCommand(), 8000);
    } catch (err) {
      setError(`Microphone permission failed: ${err.message}`);
      setVoiceStatus("Microphone permission was blocked.");
    }
  }

  function stopVoiceCommand() {
    clearTimeout(autoStopTimerRef.current);
    if (mediaRecorderRef.current?.state === "recording") {
      setVoiceStatus("Processing your voice command...");
      mediaRecorderRef.current.stop();
    }
  }

  async function startWakeListener() {
    const status = await api.voiceListenerStart();
    setVoiceListener(status);
    setVoiceStatus("Always-on local wake listener started.");
    setNotice("Wake listener is running locally. Say Hey Chinna WakeUp.");
  }

  async function stopWakeListener() {
    const status = await api.voiceListenerStop();
    setVoiceListener(status);
    setVoiceStatus("Wake listener stopped.");
    setNotice("Wake listener stopped.");
  }

  async function approveAction(actionId, approved) {
    const result = await api.operatorApprove(actionId, approved);
    setNotice(result.message);
    await loadOperator();
  }

  async function wipeVault(kind = "all") {
    const result = await api.vaultDelete(kind);
    setNotice(`Deleted ${result.deleted} private vault file(s).`);
    await loadOperator();
  }

  async function exportVault() {
    const result = await api.vaultExport();
    setNotice(`Private vault exported to ${result.export_path}`);
    await loadOperator();
  }

  async function approveFolders() {
    const approved = folders.filter((folder) => selectedFolders[folder.path]).map((folder) => folder.path);
    setFolders(await api.saveFolders(approved));
    setNotice("Folder indexing choices saved.");
    await loadOperator();
  }

  function toggleFolder(path) {
    setSelectedFolders((current) => ({
      ...current,
      [path]: !current[path],
    }));
  }

  async function saveOperatorPolicy() {
    const policy = await api.saveOperatorPolicy({ reasoning_mode: operatorPolicyMode });
    setOperatorStatus((current) => (current ? { ...current, policy } : current));
    setNotice(`Operator routing set to ${policy.reasoning_mode}.`);
    await loadOperator();
  }

  async function saveFriendVoiceConsent(event) {
    event.preventDefault();
    const result = await api.saveFriendConsent(friendVoice);
    setNotice(`Friend voice consent saved: ${result.status}`);
    await loadOperator();
  }

  async function prepareMessage(event) {
    event.preventDefault();
    const result = await api.prepareMessage(messageRequest);
    setNotice(result.message || `Message ${result.status}.`);
    await loadOperator();
  }

  async function prepareVoiceMessage(event) {
    event.preventDefault();
    const result = await api.prepareVoiceMessage(voiceMessage);
    setNotice(result.message || `Voice message ${result.status}. Disclosure: ${result.disclosure || "none"}`);
    await loadOperator();
  }

  async function prepareCall(event) {
    event.preventDefault();
    const result = await api.startCall(callRequest);
    setNotice(result.message || `Call ${result.status}. ${result.disclosure}`);
    await loadOperator();
  }

  async function preparePayment(event) {
    event.preventDefault();
    const payload = {
      ...paymentRequest,
      amount: Number(paymentRequest.amount || 0),
      upi_id: paymentRequest.upi_id || null,
    };
    const result = await api.preparePayment(payload);
    setNotice(result.message || `Payment ${result.status}.`);
    await loadOperator();
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
    speakText(detail.voice_briefing, true);
  }

  const latestAttempt = detail.attempts.at(-1);
  const changedFiles = useMemo(() => detail.rollback_plan?.affected_files || [], [detail.rollback_plan]);
  const lastObservation = operatorHistory.find((item) => item.kind === "observation");
  const latestOperatorEvent = operatorHistory[0];
  const readinessChecks = [
    {
      label: "Wake listener",
      ready: !!voiceListener?.enabled,
      note: voiceListener?.enabled ? "Always-on local wake phrase is active" : "Start listener for desktop wake phrase",
    },
    {
      label: "Local brain",
      ready: !!operatorStatus?.local_ai?.ollama,
      note: operatorStatus?.local_ai?.primary_model || "qwen3:8b",
    },
    {
      label: "Private vault",
      ready: !!vault?.vault_path && vault?.onedrive_safe !== false,
      note: vault?.vault_path || "Vault initializing",
    },
    {
      label: "Safety approvals",
      ready: approvals.length === 0,
      note: approvals.length ? `${approvals.length} pending approval(s)` : "No blocked sensitive actions",
    },
  ];
  const readyCount = readinessChecks.filter((check) => check.ready).length;

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark">C</div>
          <div>
            <p className="eyebrow">OmniPilot Private desktop agent</p>
            <h1>Chinna Command Center</h1>
            <p className="hero-copy">
              Voice-first Windows control, local privacy vault, supervised screen actions, and DevPilot repair in one operational dashboard.
            </p>
          </div>
        </div>
        <div className="toolbar">
          <span className={`status-pill ${voiceListener?.enabled ? "online" : "offline"}`}>
            <span />
            {voiceListener?.enabled ? "Wake listener on" : "Wake listener off"}
          </span>
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

      <nav className="dashboard-nav" aria-label="Dashboard sections">
        <a href="#command-center">Command Center</a>
        <a href="#devpilot">DevPilot Repair</a>
        <a href="#privacy">Privacy Vault</a>
        <a href="#approvals">Approvals</a>
        <a href="#communications">Calls & Messages</a>
      </nav>

      <section className="mission-grid">
        <article className="mission-card">
          <span>01 Perception</span>
          <strong>Sees only when awake</strong>
          <p>Wake phrase, screen observation, OCR readiness, local transcripts, and reviewed-folder access show exactly how Chinna perceives the computer.</p>
        </article>
        <article className="mission-card">
          <span>02 Reasoning</span>
          <strong>Plans before acting</strong>
          <p>Commands are classified into safe, uncertain, approval-required, and blocked actions before any desktop or DevPilot workflow executes.</p>
        </article>
        <article className="mission-card">
          <span>03 Action</span>
          <strong>Acts with guardrails</strong>
          <p>Chinna can observe, open apps, prepare messages/calls/payments, run DevPilot repair, and pause for approval when risk is detected.</p>
        </article>
        <article className="readiness-card">
          <div>
            <span>Readiness</span>
            <strong>{readyCount}/{readinessChecks.length}</strong>
          </div>
          {readinessChecks.map((check) => (
            <p className={check.ready ? "ready" : "not-ready"} key={check.label}>
              <CheckCircle2 size={15} />
              <span>{check.label}</span>
              <small>{check.note}</small>
            </p>
          ))}
        </article>
      </section>

      <section className="operator-band" id="command-center">
        <Panel className="wide" icon={<Mic2 />} title="Chinna Console">
          <div className="operator-layout">
            <div className="operator-status">
              <Metric icon={operatorStatus?.mode === "Sleeping" ? <Moon /> : <Sun />} label="Mode" value={operatorStatus?.mode || "Loading"} note={`Wake: ${operatorStatus?.wake_phrase || "Hey Chinna WakeUp"}`} />
              <Metric icon={<Lock />} label="Private Vault" value={vault?.onedrive_safe === false ? "Check path" : "Local only"} note={vault?.vault_path || "Preparing vault"} />
              <Metric icon={<Bot />} label="Local AI" value={operatorStatus?.local_ai?.ollama ? "Ollama ready" : "Limited mode"} note={`${operatorStatus?.local_ai?.primary_model || "qwen3:8b"} + OCR ${operatorStatus?.local_ai?.ocr ? "ready" : "limited"}`} />
            </div>
            <form className="operator-command" onSubmit={sendOperatorCommand}>
              <label>
                <span>Talk or type naturally</span>
                <textarea value={operatorCommand} onChange={(event) => setOperatorCommand(event.target.value)} />
              </label>
              <div className="quick-command-row">
                <button type="button" onClick={() => runQuickCommand("Hey Chinna WakeUp observe my screen")}>Observe screen</button>
                <button type="button" onClick={() => runQuickCommand("Hey Chinna WakeUp run the DevPilot repair demo")}>Run repair demo</button>
                <button type="button" onClick={() => runQuickCommand("Hey Chinna WakeUp open Google")}>Open Google</button>
                <button type="button" onClick={() => runQuickCommand("sleep")}>Sleep now</button>
              </div>
              <div className="operator-actions">
                <button type="button" className={recording ? "danger" : "voice-live"} onClick={recording ? stopVoiceCommand : startVoiceCommand}>
                  <Mic2 size={17} /> {recording ? "Stop & Send" : "Talk"}
                </button>
                <button type="button" className={voiceRepliesEnabled ? "voice-live" : "ghost"} onClick={() => setVoiceRepliesEnabled((enabled) => !enabled)}>
                  <Volume2 size={17} /> {voiceRepliesEnabled ? "Voice On" : "Voice Off"}
                </button>
                <button type="button" className={voiceListener?.enabled ? "voice-live" : "ghost"} onClick={voiceListener?.enabled ? stopWakeListener : startWakeListener}>
                  <Mic2 size={17} /> {voiceListener?.enabled ? "Stop Wake Listener" : "Start Wake Listener"}
                </button>
                <button type="button" onClick={handleOperatorWake}>
                  <Sun size={17} /> Wake
                </button>
                <button type="button" onClick={handleOperatorSleep}>
                  <Moon size={17} /> Sleep
                </button>
                <button type="button" onClick={observeScreen}>
                  <Eye size={17} /> Observe
                </button>
                <button type="button" className="danger" onClick={handleOperatorStop}>
                  <Square size={17} /> Stop
                </button>
                <button type="submit" className="primary">
                  <Play size={17} /> Send
                </button>
              </div>
            </form>
            <div className="operator-reply">
              <strong>Agent reply</strong>
              <p>{operatorReply || operatorStatus?.last_message || "Chinna is ready."}</p>
              <div className="chips">
                <span>{voiceStatus}</span>
                <span>Hotkey: Alt+Space</span>
                <span>Local STT: {operatorStatus?.local_ai?.local_stt ? "ready" : "limited"}</span>
                <span>Wake listener: {voiceListener?.enabled ? "on" : "off"}</span>
                <span>Sleep: sleep</span>
                <span>Cloud: {operatorStatus?.policy?.cloud_enabled ? "hybrid on" : "local only"}</span>
              </div>
              <div className="diagnostic-grid">
                <span>Chunks heard: {voiceListener?.processed_chunks ?? 0}</span>
                <span>Latest event: {latestOperatorEvent?.kind || "none"}</span>
                <span>Risk: {latestOperatorEvent?.risk_level || "none"}</span>
              </div>
            </div>
            <div className="operator-plan">
              <strong>Current plan</strong>
              {operatorPlan.length === 0 && <p className="muted">No active plan yet.</p>}
              {operatorPlan.map((step) => (
                <p key={step}>{step}</p>
              ))}
              <div className="screen-snapshot">
                <strong>Latest screen observation</strong>
                <p>{lastObservation?.content || "No observation yet. Click Observe or say: Hey Chinna WakeUp observe my screen."}</p>
              </div>
            </div>
          </div>
        </Panel>
      </section>

      <section className="overview" id="devpilot">
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

          <Panel className="wide" icon={<Database />} title="Privacy Center" id="privacy">
            <div className="privacy-grid">
              <div>
                <strong>Vault</strong>
                <p>{vault?.vault_path || "Not initialized"}</p>
                <small>Desktop entry: {vault?.desktop_entry || "pending"}</small>
                <div className="operator-actions">
                  <button onClick={() => wipeVault("screenshots")}>Delete Screenshots</button>
                  <button onClick={() => wipeVault("calls")}>Delete Calls</button>
                  <button onClick={exportVault}>Export Vault</button>
                  <button className="danger" onClick={() => wipeVault("all")}>Wipe Vault</button>
                </div>
              </div>
              <div>
                <strong>Folders to review</strong>
                {folders.map((folder) => (
                  <label key={folder.id} className="folder-choice">
                    <input type="checkbox" checked={!!selectedFolders[folder.path]} onChange={() => toggleFolder(folder.path)} />
                    <span>{folder.path}</span>
                    <small>{folder.status}</small>
                  </label>
                ))}
                <button onClick={approveFolders}>Save Folder Review</button>
              </div>
              <div>
                <strong>Recent private records</strong>
                {vaultRecords.slice(0, 5).map((record) => (
                  <p key={record.path}>{record.payload?.user || record.payload?.error || record.payload?.friend_name || record.path}</p>
                ))}
              </div>
            </div>
          </Panel>

          <Panel icon={<Settings />} title="Operator Policy">
            <div className="settings-form">
              <label>
                <span>Supervision mode</span>
                <input value={operatorStatus?.policy?.supervision_mode || "supervised"} disabled />
              </label>
              <label>
                <span>Reasoning mode</span>
                <select value={operatorPolicyMode} onChange={(event) => setOperatorPolicyMode(event.target.value)}>
                  <option value="hybrid">Hybrid</option>
                  <option value="local-only">Local only</option>
                </select>
              </label>
              <label>
                <span>Approval policy</span>
                <textarea
                  disabled
                  value={(operatorStatus?.policy?.approval_required_for || []).join(", ")}
                />
              </label>
              <label>
                <span>Indexing rule</span>
                <textarea disabled value={operatorStatus?.policy?.indexing_notes || "Reviewed folders only."} />
              </label>
              <button onClick={saveOperatorPolicy}>
                <Settings size={17} /> Save Policy
              </button>
            </div>
          </Panel>

          <Panel className="wide" icon={<ShieldCheck />} title="Approvals" id="approvals">
            {approvals.length === 0 && <p className="muted">No pending sensitive actions.</p>}
            {approvals.map((approval) => (
              <div className="approval" key={approval.id}>
                <strong>{approval.reason}</strong>
                <pre>{approval.action_json}</pre>
                <div className="operator-actions">
                  <button onClick={() => approveAction(approval.id, true)}>Approve</button>
                  <button className="danger" onClick={() => approveAction(approval.id, false)}>Deny</button>
                </div>
              </div>
            ))}
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

          <Panel className="wide" icon={<Volume2 />} title="Messages, Payments, Friend Voice + Calls" id="communications">
            <div className="voice-grid">
              <form className="settings-form" onSubmit={saveFriendVoiceConsent}>
                <strong>Friend voice consent</strong>
                <p className="muted">
                  {operatorStatus?.friend_voice?.clone_ready
                    ? `Clone ready with ${operatorStatus.friend_voice.clone_engine}.`
                    : `Clone engine: ${operatorStatus?.friend_voice?.clone_engine || "not-installed"}. Fallback: ${operatorStatus?.friend_voice?.fallback_voice || "generic-local-tts"}.`}
                </p>
                <label>
                  <span>Friend name</span>
                  <input value={friendVoice.friend_name} onChange={(event) => setFriendVoice((current) => ({ ...current, friend_name: event.target.value }))} />
                </label>
                <label>
                  <span>Consent note</span>
                  <textarea value={friendVoice.consent_note} onChange={(event) => setFriendVoice((current) => ({ ...current, consent_note: event.target.value }))} />
                </label>
                <label>
                  <span>Consent clip path</span>
                  <input value={friendVoice.consent_clip_path} onChange={(event) => setFriendVoice((current) => ({ ...current, consent_clip_path: event.target.value }))} />
                </label>
                <button type="submit">Save Consent</button>
              </form>
              <form className="settings-form" onSubmit={prepareMessage}>
                <strong>WhatsApp message</strong>
                <label>
                  <span>Recipient</span>
                  <input value={messageRequest.recipient} onChange={(event) => setMessageRequest((current) => ({ ...current, recipient: event.target.value }))} />
                </label>
                <label>
                  <span>Message</span>
                  <textarea value={messageRequest.message} onChange={(event) => setMessageRequest((current) => ({ ...current, message: event.target.value }))} />
                </label>
                <button type="submit">Prepare WhatsApp Send</button>
              </form>
              <form className="settings-form" onSubmit={prepareVoiceMessage}>
                <strong>Voice message</strong>
                <label>
                  <span>Recipient</span>
                  <input value={voiceMessage.recipient} onChange={(event) => setVoiceMessage((current) => ({ ...current, recipient: event.target.value }))} />
                </label>
                <label>
                  <span>Message</span>
                  <textarea value={voiceMessage.message} onChange={(event) => setVoiceMessage((current) => ({ ...current, message: event.target.value }))} />
                </label>
                <button type="submit">Prepare Voice Send</button>
              </form>
              <form className="settings-form" onSubmit={prepareCall}>
                <strong>WhatsApp / Meet call</strong>
                <label>
                  <span>App</span>
                  <input value={callRequest.app} onChange={(event) => setCallRequest((current) => ({ ...current, app: event.target.value }))} />
                </label>
                <label>
                  <span>Contact or URL</span>
                  <input value={callRequest.contact_or_url} onChange={(event) => setCallRequest((current) => ({ ...current, contact_or_url: event.target.value }))} />
                </label>
                <button type="submit">Prepare Call</button>
              </form>
              <form className="settings-form" onSubmit={preparePayment}>
                <strong>Supervised payment</strong>
                <label>
                  <span>App</span>
                  <input value={paymentRequest.app} onChange={(event) => setPaymentRequest((current) => ({ ...current, app: event.target.value }))} />
                </label>
                <label>
                  <span>Recipient</span>
                  <input value={paymentRequest.recipient} onChange={(event) => setPaymentRequest((current) => ({ ...current, recipient: event.target.value }))} />
                </label>
                <label>
                  <span>Amount</span>
                  <input value={paymentRequest.amount} onChange={(event) => setPaymentRequest((current) => ({ ...current, amount: event.target.value }))} />
                </label>
                <label>
                  <span>UPI ID</span>
                  <input value={paymentRequest.upi_id} onChange={(event) => setPaymentRequest((current) => ({ ...current, upi_id: event.target.value }))} />
                </label>
                <label>
                  <span>Note</span>
                  <input value={paymentRequest.note} onChange={(event) => setPaymentRequest((current) => ({ ...current, note: event.target.value }))} />
                </label>
                <button type="submit">Prepare Payment</button>
              </form>
            </div>
          </Panel>

          <Panel className="wide" icon={<History />} title="Chinna Action Log">
            <div className="timeline">
              {operatorHistory.slice(0, 12).map((item) => (
                <div className={`timeline-row ${item.status}`} key={item.id}>
                  <strong>{item.kind}</strong>
                  <span>{item.risk_level} | {formatTime(item.created_at)}</span>
                  <p>{item.content}</p>
                </div>
              ))}
            </div>
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

function Panel({ icon, title, children, className = "", ...props }) {
  return (
    <section className={`panel ${className}`} {...props}>
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

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(String(reader.result || "").split(",")[1] || "");
    reader.onerror = () => reject(reader.error || new Error("Unable to read recorded audio."));
    reader.readAsDataURL(blob);
  });
}

export default App;
