(() => {
  const $ = (id) => document.getElementById(id);

  const modeSelect = $("modeSelect");
  const levelSelect = $("levelSelect");
  const connectBtn = $("connectBtn");
  const statusPill = $("statusPill");
  const sessionIdText = $("sessionIdText");
  const runIdText = $("runIdText");
  const chatLog = $("chatLog");
  const latestEvent = $("latestEvent");
  const eventsLog = $("eventsLog");
  const evidenceBox = $("evidenceBox");
  const workflowTree = $("workflowTree");
  const toggleLeftBtn = $("toggleLeftBtn");

  let es = null;
  let sessionId = null;
  let runId = null;
  let recent = [];
  let pathCounts = new Map();

  function setStatus(text, kind) {
    statusPill.textContent = text;
    statusPill.classList.remove("pill--ok", "pill--bad");
    if (kind === "ok") statusPill.classList.add("pill--ok");
    if (kind === "bad") statusPill.classList.add("pill--bad");
  }

  function appendChat(text, meta) {
    const div = document.createElement("div");
    div.className = "msg";
    const metaDiv = document.createElement("div");
    metaDiv.className = "msg__meta";
    metaDiv.textContent = meta || "event";
    const body = document.createElement("div");
    body.textContent = text;
    div.appendChild(metaDiv);
    div.appendChild(body);
    chatLog.appendChild(div);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function renderWorkflowTree() {
    const items = Array.from(pathCounts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 50)
      .map(([k, v]) => `${String(v).padStart(3, " ")}  ${k}`);
    workflowTree.textContent = items.join("\n") || "(no events yet)";
  }

  function renderEvidence(ev) {
    const evidence = ev && ev.evidence ? ev.evidence : null;
    if (!evidence) {
      evidenceBox.textContent = "(none)";
      return;
    }
    const lines = [];
    if (evidence.events_path) lines.push(`events_path: ${evidence.events_path}`);
    if (evidence.node_report_schema) lines.push(`node_report_schema: ${evidence.node_report_schema}`);
    if (evidence.call_id) lines.push(`call_id: ${evidence.call_id}`);
    if (evidence.artifact_path) lines.push(`artifact_path: ${evidence.artifact_path}`);
    evidenceBox.textContent = lines.join("\n") || "(none)";
  }

  function onRuntimeEvent(ev) {
    recent.push(ev);
    if (recent.length > 200) recent = recent.slice(-200);

    const pathKey =
      Array.isArray(ev.path) && ev.path.length
        ? ev.path.map((p) => `${p.kind}:${p.id}`).join(" / ")
        : "(no path)";
    pathCounts.set(pathKey, (pathCounts.get(pathKey) || 0) + 1);

    latestEvent.textContent = JSON.stringify(ev, null, 2);
    eventsLog.textContent = recent.map((x) => JSON.stringify(x)).join("\n");
    renderEvidence(ev);
    renderWorkflowTree();

    if (ev.type === "item_delta" && ev.data && typeof ev.data.text === "string") {
      appendChat(ev.data.text, "item_delta");
    }
    if (ev.type === "run.status" && ev.data && ev.data.status) {
      setStatus(`run.status: ${ev.data.status}`, ev.data.status === "completed" ? "ok" : "ok");
    }
  }

  async function startSession() {
    const mode = modeSelect.value;
    const level = levelSelect.value;
    const url = `/api/start?mode=${encodeURIComponent(mode)}&level=${encodeURIComponent(level)}`;
    setStatus("连接中…", "ok");
    const resp = await fetch(url, { method: "POST" });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      setStatus(`启动失败: ${resp.status}`, "bad");
      appendChat(String(data.error || "start failed"), "error");
      return null;
    }
    sessionId = data.session_id;
    runId = data.run_id;
    sessionIdText.textContent = sessionId || "-";
    runIdText.textContent = runId || "-";
    return data;
  }

  function connectEvents() {
    if (!sessionId) return;
    if (es) {
      es.close();
      es = null;
    }
    recent = [];
    pathCounts = new Map();
    chatLog.innerHTML = "";
    latestEvent.textContent = "";
    eventsLog.textContent = "";
    evidenceBox.textContent = "(none)";
    renderWorkflowTree();

    const url = `/api/events?session_id=${encodeURIComponent(sessionId)}&transport=sse`;
    es = new EventSource(url);
    es.onmessage = (msg) => {
      if (!msg.data) return;
      try {
        const ev = JSON.parse(msg.data);
        onRuntimeEvent(ev);
      } catch (e) {
        appendChat(`invalid JSON: ${String(e)}`, "warn");
      }
    };
    es.onerror = () => {
      setStatus("SSE 断开/错误", "bad");
      try {
        es.close();
      } catch (_) {}
      es = null;
    };
    setStatus("已连接（SSE）", "ok");
  }

  connectBtn.addEventListener("click", async () => {
    const started = await startSession();
    if (started) connectEvents();
  });

  toggleLeftBtn.addEventListener("click", () => {
    const left = document.querySelector(".panel--left");
    const isHidden = left.style.display === "none";
    if (isHidden) {
      left.style.display = "";
      toggleLeftBtn.textContent = "折叠";
    } else {
      left.style.display = "none";
      toggleLeftBtn.textContent = "展开";
    }
  });

  // auto-connect offline for convenience
  window.addEventListener("load", () => {
    connectBtn.click();
  });
})();

