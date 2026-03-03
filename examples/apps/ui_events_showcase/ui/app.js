(() => {
  const $ = (id) => document.getElementById(id);

  const modeSelect = $("modeSelect");
  const levelSelect = $("levelSelect");
  const transportSelect = $("transportSelect");
  const connectBtn = $("connectBtn");
  const disconnectBtn = $("disconnectBtn");
  const breakBtn = $("breakBtn");
  const drawerBtn = $("drawerBtn");
  const drawer = $("drawer");
  const drawerCloseBtn = $("drawerCloseBtn");
  const themeBtn = $("themeBtn");
  const modePill = $("modePill");
  const statusPill = $("statusPill");
  const sessionIdText = $("sessionIdText");
  const runIdText = $("runIdText");
  const levelText = $("levelText");
  const lastRidText = $("lastRidText");
  const copyLocatorBtn = $("copyLocatorBtn");
  const chatLog = $("chatLog");
  const workflowTree = $("workflowTree");
  const toggleLeftBtn = $("toggleLeftBtn");

  const tabTools = $("tabTools");
  const tabTimeline = $("tabTimeline");
  const tabEvidence = $("tabEvidence");
  const panelTools = $("panelTools");
  const panelTimeline = $("panelTimeline");
  const panelEvidence = $("panelEvidence");
  const toolsList = $("toolsList");
  const timelineList = $("timelineList");
  const filterInput = $("filterInput");
  const pauseBtn = $("pauseBtn");

  const eventsPathText = $("eventsPathText");
  const walLocatorText = $("walLocatorText");
  const callIdText = $("callIdText");
  const nodeReportSchemaText = $("nodeReportSchemaText");
  const copyEventsPathBtn = $("copyEventsPathBtn");
  const copyWalLocatorBtn = $("copyWalLocatorBtn");
  const copyCallIdBtn = $("copyCallIdBtn");
  const copyNodeReportSchemaBtn = $("copyNodeReportSchemaBtn");
  const rawEvent = $("rawEvent");

	  const layout = $("main");

	  let abort = null;
	  let eventSource = null;
	  let sessionId = null;
	  let runId = null;
	  let level = "ui";
	  let transport = "sse";
	  let lastRid = null;
  let selectedPathPrefix = null;
  let selectedCallId = null;
  let selectedRid = null;
  let paused = false;
  let done = false;
  let userDisconnected = false;
  let resumeExpired = false;
  let reconnectTimer = null;
  let sawItemDelta = false;
  let appendedFinalSummary = false;

	  let events = [];
	  let ridSeen = new Set();
	  let seqSeen = new Set();
	  let diagnostics = { invalidJson: 0 };
	  let themeMode = "auto"; // auto | dark | light
	  let themeAutoMql = null;

	  const THEME_STORAGE_KEY = "ui_events_theme";

	  function setStatus(text, kind) {
	    statusPill.textContent = text;
	    statusPill.classList.remove("pill--ok", "pill--bad");
    if (kind === "ok") statusPill.classList.add("pill--ok");
    if (kind === "bad") statusPill.classList.add("pill--bad");
  }

  function setModePill(modeValue) {
    const isReal = modeValue === "real";
    modePill.textContent = isReal ? "REAL" : "OFFLINE";
    modePill.classList.remove("pill--ok", "pill--bad");
    modePill.classList.add(isReal ? "pill--bad" : "pill--ok");
    modePill.setAttribute("aria-label", isReal ? "mode real" : "mode offline");
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

	  async function copyText(s) {
	    const text = String(s || "");
	    if (!text) return false;
	    try {
	      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      return false;
    }
  }

  function pathToKey(path) {
    if (!Array.isArray(path) || !path.length) return "(no path)";
    return path.map((p) => `${p.kind}:${p.id}`).join(" / ");
  }

  function pathPrefixMatches(pathKey, prefixKey) {
    if (!prefixKey) return true;
    return String(pathKey).startsWith(String(prefixKey));
  }

	  function getCallId(ev) {
	    if (ev && ev.evidence && ev.evidence.call_id) return String(ev.evidence.call_id);
	    if (Array.isArray(ev.path)) {
	      const seg = ev.path.find((p) => p && p.kind === "call");
      if (seg && seg.id) return String(seg.id);
    }
    if (ev && ev.data && ev.data.call_id) return String(ev.data.call_id);
	    return null;
	  }

	  function getCurrentLocator() {
	    const wal = walLocatorText.textContent && walLocatorText.textContent !== "-" ? String(walLocatorText.textContent) : "";
	    const ep = eventsPathText.textContent && eventsPathText.textContent !== "-" ? String(eventsPathText.textContent) : "";
	    return wal || ep || "";
	  }

	  function refreshCopyLocatorState() {
	    const locator = getCurrentLocator();
	    const ok = Boolean(locator);
	    copyLocatorBtn.disabled = !ok;
	    copyLocatorBtn.setAttribute("aria-disabled", ok ? "false" : "true");
	  }

	  function updateThemeButton() {
	    const label =
	      themeMode === "auto" ? "主题：自动" : themeMode === "dark" ? "主题：深色" : themeMode === "light" ? "主题：浅色" : "主题";
	    themeBtn.textContent = label;
	    themeBtn.setAttribute("aria-label", `切换主题（当前：${label.replace("主题：", "")}）`);
	  }

	  function applyTheme() {
	    const root = document.documentElement;
	    const resolved =
	      themeMode === "auto"
	        ? themeAutoMql && themeAutoMql.matches
	          ? "dark"
	          : "light"
	        : themeMode === "dark"
	          ? "dark"
	          : "light";
	    root.setAttribute("data-theme", resolved);
	  }

	  function setThemeMode(nextMode, { persist }) {
	    const m = String(nextMode || "").trim();
	    if (!["auto", "dark", "light"].includes(m)) return;
	    themeMode = m;
	    if (persist) {
	      try {
	        localStorage.setItem(THEME_STORAGE_KEY, themeMode);
	      } catch (_) {}
	    }
	    applyTheme();
	    updateThemeButton();
	  }

	  function initTheme() {
	    try {
	      themeAutoMql = window.matchMedia("(prefers-color-scheme: dark)");
	    } catch (_) {
	      themeAutoMql = null;
	    }
	    let stored = "auto";
	    try {
	      stored = localStorage.getItem(THEME_STORAGE_KEY) || "auto";
	    } catch (_) {}
	    setThemeMode(stored, { persist: false });

	    if (themeAutoMql) {
	      const onChange = () => {
	        if (themeMode === "auto") applyTheme();
	      };
	      try {
	        themeAutoMql.addEventListener("change", onChange);
	      } catch (_) {
	        try {
	          themeAutoMql.addListener(onChange);
	        } catch (_) {}
	      }
	    }
	  }

	  function cycleThemeMode() {
	    const order = ["auto", "dark", "light"];
	    const idx = order.indexOf(themeMode);
	    const next = order[(idx >= 0 ? idx + 1 : 0) % order.length];
	    setThemeMode(next, { persist: true });
	  }

	  function setSelectedEvidenceFromEvent(ev) {
	    const evidence = ev && ev.evidence ? ev.evidence : null;
	    const eventsPath = evidence && evidence.events_path ? String(evidence.events_path) : "";
	    const walLocator =
      evidence && evidence.wal_locator
        ? String(evidence.wal_locator)
        : eventsPath
          ? String(eventsPath)
          : "";

	    eventsPathText.textContent = eventsPath || "-";
	    walLocatorText.textContent = walLocator || "-";
	    callIdText.textContent = evidence && evidence.call_id ? String(evidence.call_id) : "-";
	    nodeReportSchemaText.textContent = evidence && evidence.node_report_schema ? String(evidence.node_report_schema) : "-";
	    rawEvent.textContent = ev ? JSON.stringify(ev, null, 2) : "";
	    refreshCopyLocatorState();
	  }

  function renderWorkflowTree() {
    // Build unique path keys and counts
    const counts = new Map();
    for (const ev of events) {
      const k = pathToKey(ev.path);
      counts.set(k, (counts.get(k) || 0) + 1);
    }

    const items = Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 60)
      .map(([k, v]) => ({ key: k, count: v }));

    workflowTree.innerHTML = "";
    if (!items.length) {
      const div = document.createElement("div");
      div.className = "hint";
      div.textContent = "(no events yet)";
      workflowTree.appendChild(div);
      return;
    }

    for (const it of items) {
      const div = document.createElement("div");
      div.className = "tree-item" + (selectedPathPrefix === it.key ? " is-active" : "");
      div.setAttribute("role", "treeitem");
      div.tabIndex = 0;
      const label = document.createElement("div");
      label.className = "tree-item__label";
      label.textContent = it.key;
      const count = document.createElement("div");
      count.className = "tree-item__count";
      count.textContent = String(it.count);
      div.appendChild(label);
      div.appendChild(count);
      const onSelect = () => {
        selectedPathPrefix = selectedPathPrefix === it.key ? null : it.key;
        selectedRid = null;
        renderAll();
      };
      div.addEventListener("click", onSelect);
      div.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      });
      workflowTree.appendChild(div);
    }
  }

  async function startSession() {
    const mode = modeSelect.value;
    level = levelSelect.value;
    transport = transportSelect.value;
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
    levelText.textContent = level || "-";
    lastRidText.textContent = "-";
    lastRid = null;
    done = false;
    userDisconnected = false;
    resumeExpired = false;
    sawItemDelta = false;
    appendedFinalSummary = false;
    setModePill(mode);
    if (mode === "real") {
      appendChat("REAL 模式已开启：可能产生费用/依赖外网/存在敏感信息风险。", "risk");
    }
    return data;
  }

	  function resetStateForNewRun() {
	    closeTransport();
	    if (reconnectTimer) {
	      clearTimeout(reconnectTimer);
	      reconnectTimer = null;
	    }
    events = [];
    ridSeen = new Set();
    seqSeen = new Set();
    diagnostics = { invalidJson: 0 };
    selectedPathPrefix = null;
    selectedCallId = null;
    selectedRid = null;
    paused = false;
    pauseBtn.textContent = "暂停";
    done = false;
    userDisconnected = false;
    resumeExpired = false;
    sawItemDelta = false;
    appendedFinalSummary = false;
    chatLog.innerHTML = "";
    toolsList.innerHTML = "";
    timelineList.innerHTML = "";
    workflowTree.innerHTML = "";
    setSelectedEvidenceFromEvent(null);
    if (layout) layout.classList.remove("drawer-hidden");
  }

  function activateTab(which) {
    const tabs = [
      { id: "tools", tab: tabTools, panel: panelTools },
      { id: "timeline", tab: tabTimeline, panel: panelTimeline },
      { id: "evidence", tab: tabEvidence, panel: panelEvidence },
    ];
    for (const t of tabs) {
      const active = t.id === which;
      t.tab.classList.toggle("is-active", active);
      t.tab.setAttribute("aria-selected", active ? "true" : "false");
      t.panel.classList.toggle("is-hidden", !active);
    }
  }

  function renderToolsAndApprovals() {
    const groups = new Map();
    for (const ev of events) {
      if (!(String(ev.type || "").startsWith("tool.") || String(ev.type || "").startsWith("approval."))) continue;
      const cid = getCallId(ev) || "(no call_id)";
      if (!groups.has(cid)) groups.set(cid, []);
      groups.get(cid).push(ev);
    }

    const items = Array.from(groups.entries()).map(([cid, evs]) => {
      const last = evs[evs.length - 1];
      return { callId: cid, count: evs.length, lastType: String(last.type || ""), lastSeq: Number(last.seq || 0), lastEv: last };
    });
    items.sort((a, b) => b.lastSeq - a.lastSeq);

    toolsList.innerHTML = "";
    if (!items.length) {
      const div = document.createElement("div");
      div.className = "hint";
      div.textContent = "(no tool/approval events)";
      toolsList.appendChild(div);
      return;
    }
    for (const it of items) {
      const div = document.createElement("div");
      div.className = "item" + (selectedCallId === it.callId ? " is-active" : "");
      div.tabIndex = 0;
      const title = document.createElement("div");
      title.className = "item__title";
      title.textContent = `call_id=${it.callId}`;
      const sub = document.createElement("div");
      sub.className = "item__sub";
      sub.textContent = `last=${it.lastType} · events=${it.count}`;
      div.appendChild(title);
      div.appendChild(sub);
      const onSelect = () => {
        selectedCallId = selectedCallId === it.callId ? null : it.callId;
        setSelectedEvidenceFromEvent(it.lastEv);
        activateTab("evidence");
        renderAll();
      };
      div.addEventListener("click", onSelect);
      div.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      });
      toolsList.appendChild(div);
    }
  }

  function renderTimeline() {
    const q = String(filterInput.value || "").trim().toLowerCase();
    const out = [];
    for (const ev of events) {
      if (selectedCallId) {
        const cid = getCallId(ev);
        if (cid !== selectedCallId) continue;
      }
      const pk = pathToKey(ev.path);
      if (!pathPrefixMatches(pk, selectedPathPrefix)) continue;

      const hay = `${ev.type || ""} ${pk} ${getCallId(ev) || ""} ${ev.rid || ""} ${ev.level || ""}`.toLowerCase();
      if (q && !hay.includes(q)) continue;
      out.push(ev);
    }

    out.sort((a, b) => Number(a.seq || 0) - Number(b.seq || 0));

    timelineList.innerHTML = "";
    if (!out.length) {
      const div = document.createElement("div");
      div.className = "hint";
      div.textContent = "(no matching events)";
      timelineList.appendChild(div);
      return;
    }
    for (const ev of out.slice(-240)) {
      const pk = pathToKey(ev.path);
      const div = document.createElement("div");
      div.className = "item" + (selectedRid && String(ev.rid) === String(selectedRid) ? " is-active" : "");
      div.tabIndex = 0;
      const title = document.createElement("div");
      title.className = "item__title";
      title.textContent = `#${ev.seq} ${ev.type} rid=${ev.rid || "-"}`;
      const sub = document.createElement("div");
      sub.className = "item__sub";
      sub.textContent = `${pk}${getCallId(ev) ? " · call_id=" + getCallId(ev) : ""}`;
      div.appendChild(title);
      div.appendChild(sub);
      const onSelect = () => {
        selectedRid = ev.rid || null;
        setSelectedEvidenceFromEvent(ev);
        activateTab("evidence");
        renderAll();
      };
      div.addEventListener("click", onSelect);
      div.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      });
      timelineList.appendChild(div);
    }
  }

	  function renderAll() {
	    renderWorkflowTree();
	    renderToolsAndApprovals();
	    renderTimeline();
	  }

	  function buildEventsUrl({ afterId }) {
	    const qs = new URLSearchParams();
	    qs.set("session_id", sessionId);
	    qs.set("transport", transport);
	    if (afterId) qs.set("after_id", String(afterId));
	    return `/api/events?${qs.toString()}`;
	  }

	  function closeTransport() {
	    if (eventSource) {
	      try {
	        eventSource.close();
	      } catch (_) {}
	      eventSource = null;
	    }
	    if (abort) {
	      try {
	        abort.abort();
	      } catch (_) {}
	      abort = null;
	    }
	  }

	  function maybeAutoStopTransportOnDone(ev) {
	    if (!ev || typeof ev !== "object") return;
	    if (ev.type !== "run.status") return;
	    const st = ev.data && ev.data.status ? String(ev.data.status) : "";
	    if (st && st !== "running") {
	      // 终态后服务端通常会关闭连接；这里主动关闭 transport，避免 SSE/EventSource 将“正常关闭”误当作断线并触发重连。
	      closeTransport();
	    }
	  }

	  function onRuntimeEvent(ev) {
	    if (!ev || typeof ev !== "object") return;
	    if (ev.schema !== "capability-runtime.runtime_event.v1") return;
	    if (ev.rid && ridSeen.has(String(ev.rid))) return;
	    if (ev.rid) ridSeen.add(String(ev.rid));
    if (!ev.rid && ev.seq != null) {
      const s = String(ev.seq);
      if (seqSeen.has(s)) return;
      seqSeen.add(s);
    }

    if (!paused) {
      events.push(ev);
      if (events.length > 2000) events = events.slice(-2000);
    }

    if (ev.rid) {
      lastRid = String(ev.rid);
      lastRidText.textContent = lastRid;
    }

    if (ev.type === "item_delta" && ev.data && typeof ev.data.text === "string") {
      sawItemDelta = true;
      appendChat(ev.data.text, "item_delta");
    }
    if (ev.type === "error") {
      appendChat(String((ev.data && ev.data.message) || "error"), "error");
      if (ev.data && ev.data.kind === "after_id_expired") {
        resumeExpired = true;
        done = true;
        setStatus("续传游标已过期：请重新连接（不要自动重连）", "bad");
        if (!appendedFinalSummary) {
          appendedFinalSummary = true;
          appendChat("提示：after_id 续传已失效（可能是裁剪/重启/游标错误）。请点击“连接”重新开始一轮会话。", "final");
        }
      }
    }
	    if (ev.type === "run.status" && ev.data && ev.data.status) {
	      const st = String(ev.data.status);
	      setStatus(`run.status: ${st}`, st === "completed" ? "ok" : st === "failed" ? "bad" : "ok");
	      if (st !== "running") {
	        done = true;
	        if (!sawItemDelta && !appendedFinalSummary) {
          appendedFinalSummary = true;
          const ep = (ev.evidence && ev.evidence.events_path) || "";
          appendChat(
            `终态：${st}。你可以在右侧 Evidence 中复制 locator（events_path / wal_locator）去追溯 NodeReport/WAL。${ep ? ` events_path=${ep}` : ""}`,
            "final"
          );
	        }
	      }
	    }

	    // Evidence: prefer terminal or selected; keep last event for evidence panel
	    if (!selectedRid) {
	      setSelectedEvidenceFromEvent(ev);
	    }
	    maybeAutoStopTransportOnDone(ev);
	    renderAll();
	  }

	  async function streamEventsJsonlFetch({ afterId, attempt }) {
	    if (!sessionId) return;
	    const url = buildEventsUrl({ afterId });
	    abort = new AbortController();

	    if (attempt > 0) {
	      setStatus(`重连中… (after_id=${afterId || "-"})`, "ok");
	    } else {
      setStatus(`已连接（${transport}）`, "ok");
    }

    let resp;
    try {
      resp = await fetch(url, { method: "GET", signal: abort.signal });
    } catch (e) {
      if (done) return;
      setStatus("连接失败（网络/中断）", "bad");
      scheduleReconnect();
      return;
    }

    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      appendChat(`events HTTP ${resp.status}: ${text || "(no body)"}`, "error");
      if (done) return;
      scheduleReconnect();
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buf = "";
    while (true) {
      let r;
      try {
        r = await reader.read();
      } catch (_) {
        break;
      }
      if (r.done) break;
      buf += decoder.decode(r.value, { stream: true });
      while (true) {
        const idx = buf.indexOf("\n");
        if (idx < 0) break;
        const line = buf.slice(0, idx);
        buf = buf.slice(idx + 1);
        const s = line.trim();
        if (!s) continue;
        const payload = s.startsWith("data:") ? s.slice("data:".length).trim() : s;
        try {
          const ev = JSON.parse(payload);
          onRuntimeEvent(ev);
        } catch (e) {
          diagnostics.invalidJson += 1;
          appendChat(`invalid JSON line (#${diagnostics.invalidJson}): ${String(e)}`, "warn");
        }
      }
      if (done) break;
    }

	    if (!done && !userDisconnected && !resumeExpired) {
	      scheduleReconnect();
	    }
	  }

	  function streamEventsSseEventSource({ afterId, attempt }) {
	    if (!sessionId) return;
	    const url = buildEventsUrl({ afterId });

	    // EventSource 必须重建以携带新的 after_id（其内建重连 URL 不会变）
	    if (eventSource) {
	      try {
	        eventSource.close();
	      } catch (_) {}
	      eventSource = null;
	    }
	    if (abort) {
	      try {
	        abort.abort();
	      } catch (_) {}
	      abort = null;
	    }

	    if (attempt > 0) {
	      setStatus(`重连中… (after_id=${afterId || "-"})`, "ok");
	    } else {
	      setStatus(`已连接（${transport}）`, "ok");
	    }

	    eventSource = new EventSource(url);
	    eventSource.onmessage = (e) => {
	      const payload = e && typeof e.data === "string" ? e.data : "";
	      if (!payload) return;
	      try {
	        const ev = JSON.parse(payload);
	        onRuntimeEvent(ev);
	      } catch (err) {
	        diagnostics.invalidJson += 1;
	        appendChat(`invalid SSE data (#${diagnostics.invalidJson}): ${String(err)}`, "warn");
	      }
	    };
	    eventSource.onerror = () => {
	      if (done || userDisconnected || resumeExpired) {
	        closeTransport();
	        return;
	      }
	      setStatus("连接失败（网络/中断）", "bad");
	      closeTransport();
	      scheduleReconnect();
	    };
	  }

	  async function streamEvents({ afterId, attempt }) {
	    if (transport === "sse") {
	      streamEventsSseEventSource({ afterId, attempt });
	      return;
	    }
	    await streamEventsJsonlFetch({ afterId, attempt });
	  }

	  function scheduleReconnect() {
	    if (reconnectTimer) return;
	    if (userDisconnected) return;
	    if (resumeExpired) return;
    const delay = 400;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (done) return;
      if (userDisconnected) return;
      if (resumeExpired) return;
      streamEvents({ afterId: lastRid, attempt: 1 });
    }, delay);
  }

	  function disconnect() {
	    userDisconnected = true;
	    closeTransport();
	    setStatus("已断开（用户）", "bad");
	  }

	  function simulateBreak() {
	    if (!sessionId) return;
	    setStatus("模拟断线：准备重连…", "bad");
	    if (transport === "sse") {
	      if (eventSource) {
	        try {
	          eventSource.close();
	        } catch (_) {}
	        eventSource = null;
	        scheduleReconnect();
	      }
	      return;
	    }
	    if (!abort) return;
	    try {
	      abort.abort();
	    } catch (_) {}
	  }

  connectBtn.addEventListener("click", async () => {
    resetStateForNewRun();
    const started = await startSession();
    if (started) {
      activateTab("tools");
      drawer.classList.remove("is-hidden");
      if (layout) layout.classList.remove("drawer-hidden");
      drawerBtn.setAttribute("aria-expanded", "true");
      streamEvents({ afterId: null, attempt: 0 });
    }
  });

  disconnectBtn.addEventListener("click", () => {
    disconnect();
  });
  breakBtn.addEventListener("click", () => {
    simulateBreak();
  });

  toggleLeftBtn.addEventListener("click", () => {
    const left = document.querySelector(".panel--left");
    const isHidden = left.style.display === "none";
    if (isHidden) {
      left.style.display = "";
      toggleLeftBtn.textContent = "折叠";
      toggleLeftBtn.setAttribute("aria-expanded", "true");
    } else {
      left.style.display = "none";
      toggleLeftBtn.textContent = "展开";
      toggleLeftBtn.setAttribute("aria-expanded", "false");
    }
  });

  drawerBtn.addEventListener("click", () => {
    const hidden = drawer.classList.toggle("is-hidden");
    drawerBtn.setAttribute("aria-expanded", hidden ? "false" : "true");
    if (layout && window.matchMedia("(min-width: 1101px)").matches) {
      layout.classList.toggle("drawer-hidden", hidden);
    }
  });
  drawerCloseBtn.addEventListener("click", () => {
    drawer.classList.add("is-hidden");
    drawerBtn.setAttribute("aria-expanded", "false");
    if (layout && window.matchMedia("(min-width: 1101px)").matches) {
      layout.classList.add("drawer-hidden");
    }
  });

  tabTools.addEventListener("click", () => activateTab("tools"));
  tabTimeline.addEventListener("click", () => activateTab("timeline"));
  tabEvidence.addEventListener("click", () => activateTab("evidence"));

  const tabs = [
    { id: "tools", tab: tabTools },
    { id: "timeline", tab: tabTimeline },
    { id: "evidence", tab: tabEvidence },
  ];
  for (const t of tabs) {
    t.tab.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const idx = tabs.findIndex((x) => x.id === t.id);
      const next = e.key === "ArrowRight" ? (idx + 1) % tabs.length : (idx - 1 + tabs.length) % tabs.length;
      tabs[next].tab.focus();
      activateTab(tabs[next].id);
    });
  }

  filterInput.addEventListener("input", () => renderTimeline());
  pauseBtn.addEventListener("click", () => {
    paused = !paused;
    pauseBtn.textContent = paused ? "继续" : "暂停";
  });

	  copyLocatorBtn.addEventListener("click", async () => {
	    const locator = getCurrentLocator();
	    if (!locator) return;
	    const ok = await copyText(locator);
	    appendChat(ok ? "已复制 locator" : "复制失败（浏览器权限）", ok ? "info" : "warn");
	  });
  copyEventsPathBtn.addEventListener("click", async () => {
    const ok = await copyText(eventsPathText.textContent);
    appendChat(ok ? "已复制 events_path" : "复制失败（浏览器权限）", ok ? "info" : "warn");
  });
  copyWalLocatorBtn.addEventListener("click", async () => {
    const ok = await copyText(walLocatorText.textContent);
    appendChat(ok ? "已复制 wal_locator" : "复制失败（浏览器权限）", ok ? "info" : "warn");
  });
  copyCallIdBtn.addEventListener("click", async () => {
    const ok = await copyText(callIdText.textContent);
    appendChat(ok ? "已复制 call_id" : "复制失败（浏览器权限）", ok ? "info" : "warn");
  });
  copyNodeReportSchemaBtn.addEventListener("click", async () => {
    const ok = await copyText(nodeReportSchemaText.textContent);
    appendChat(ok ? "已复制 node_report_schema" : "复制失败（浏览器权限）", ok ? "info" : "warn");
  });

	  themeBtn.addEventListener("click", () => {
	    cycleThemeMode();
	  });

	  // auto-connect offline for convenience
	  window.addEventListener("load", () => {
	    initTheme();
	    setModePill("offline");
	    levelText.textContent = levelSelect.value;
	    connectBtn.click();
	  });
})();
