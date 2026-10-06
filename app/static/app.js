(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));

  const elements = {
    question: $("#question"),
    questionCount: $("#question-count"),
    guidance: $("#system-prompt"),
    responseLength: $("#response-length"),
    temperature: $("#temperature"),
    temperatureValue: $("#temperature-value"),
    ask: $("#ask-council"),
    cancel: $("#cancel-council"),
    clear: $("#clear-session"),
    memberCount: $("#member-count"),
    results: $("#results-section"),
    memberResults: $("#member-results"),
    memberTemplate: $("#member-template"),
    roundTime: $("#round-time"),
    synthesis: $("#synthesis-section"),
    moderator: $("#moderator"),
    synthesize: $("#synthesize"),
    selectionNote: $("#selection-note"),
    finalAnswer: $("#final-answer"),
    finalTitle: $("#final-title"),
    finalMeta: $("#final-meta"),
    finalText: $("#final-text"),
    copyFinal: $("#copy-final"),
    toast: $("#toast"),
    openaiModel: $("#openai-model"),
    openaiKey: $("#openai-key"),
    anthropicModel: $("#anthropic-model"),
    anthropicKey: $("#anthropic-key"),
    ollamaRefresh: $("#refresh-ollama"),
    ollamaStatus: $("#ollama-status"),
    ollamaModel: $("#ollama-model"),
    ollamaBaseUrl: $("#ollama-base-url"),
    ollamaOptions: $("#ollama-model-options"),
    customMode: $("#custom-mode"),
    customStatus: $("#custom-status"),
    customJson: $("#custom-json"),
    applyCustomJson: $("#apply-custom-json"),
    customLabel: $("#custom-label"),
    customModel: $("#custom-model"),
    customEndpoint: $("#custom-endpoint"),
    customAuthType: $("#custom-auth-type"),
    customKey: $("#custom-key"),
    customApiVersion: $("#custom-api-version"),
    customEnabled: $("#custom-enabled"),
    enabledInputs: {
      openai: $("#openai-enabled"),
      custom: $("#custom-enabled"),
      anthropic: $("#anthropic-enabled"),
      ollama: $("#ollama-enabled"),
    },
    // Memory elements
    memoryEnabled: $("#memory-enabled"),
    memoryBadge: $("#memory-badge"),
    newSessionBtn: $("#new-session-btn"),
    clearMemoryBtn: $("#clear-memory-btn"),
    memoryHistory: $("#memory-history"),
    // Modal elements
    expandFinal: $("#expand-final"),
    modal: $("#expand-modal"),
    modalTitle: $("#modal-title"),
    modalKicker: $("#modal-kicker"),
    modalMeta: $("#modal-meta"),
    modalText: $("#modal-text"),
    modalClose: $("#modal-close"),
    modalCopy: $("#modal-copy"),
    // Workspace / code agent elements
    modeCouncil: $("#mode-council"),
    modeWorkspace: $("#mode-workspace"),
    councilMode: $("#council-mode"),
    workspaceMode: $("#workspace-mode"),
    workspaceRootSelect: $("#workspace-root-select"),
    loadTree: $("#load-tree"),
    workspaceSearch: $("#workspace-search"),
    runSearch: $("#run-search"),
    workspaceTree: $("#workspace-tree"),
    fileViewer: $("#file-viewer"),
    fileViewerPath: $("#file-viewer-path"),
    fileViewerMeta: $("#file-viewer-meta"),
    fileViewerCode: $("#file-viewer-code"),
    codeTask: $("#code-task"),
    agentMaxSteps: $("#agent-max-steps"),
    runAgent: $("#run-agent"),
    cancelAgent: $("#cancel-agent"),
    agentActivity: $("#agent-activity"),
    agentRunTitle: $("#agent-run-title"),
    agentStatus: $("#agent-status"),
    agentStream: $("#agent-stream"),
    agentStreamText: $("#agent-stream-text"),
    agentFeed: $("#agent-feed"),
    agentSummaryCard: $("#agent-summary-card"),
    agentSummaryText: $("#agent-summary-text"),
  };

  const providers = ["openai", "custom", "anthropic", "ollama"];
  const providerLabels = { openai: "OpenAI", custom: "Azure / custom", anthropic: "Claude", ollama: "Ollama" };

  // Streaming deltas re-render the whole accumulated answer (O(text length)
  // each time), so coalesce them to at most one markdown render per interval.
  const RENDER_INTERVAL_MS = 150;
  const OLLAMA_LIST_CACHE_MS = 5_000;

  const state = {
    members: [],
    question: "",
    finalAnswer: "",
    toastTimer: null,
    asking: false,
    councilStopped: false,
    synthesizing: false,
    streamSocket: null,
    customHeaders: {},
    customQueryParams: {},
    memberViews: new Map(),
    pendingMemberProviders: new Set(),
    memberRenderTimer: null,
    lastMemberRender: 0,
    finalRenderTimer: null,
    lastFinalRender: 0,
    ollamaListCache: null,
    ollamaRpcController: null,
    // Memory state
    sessionId: getSessionId(),
    currentRoundId: "",
    // Workspace / code agent state
    agentRunning: false,
    agentStopped: false,
    agentRoundId: "",
    agentStepRows: new Map(),
    pendingDiffCard: null,
    workspaceRoot: "",
  };

  // ── Memory & Session Helpers ──────────────────────────────────────────────

  function getSessionId() {
    let id = localStorage.getItem("model_council_session_id");
    if (!id) {
      id = crypto.randomUUID().replace(/-/g, "").slice(0, 24);
      localStorage.setItem("model_council_session_id", id);
    }
    return id;
  }

  function newSession() {
    localStorage.removeItem("model_council_session_id");
    state.sessionId = getSessionId();
    state.currentRoundId = "";
    loadMemoryHistory();
    showToast("Started a new conversation session.");
  }

  function isMemoryEnabled() {
    return elements.memoryEnabled ? elements.memoryEnabled.checked : true;
  }

  function enrichPayload(payload) {
    return {
      ...payload,
      session_id: state.sessionId,
      memory_enabled: isMemoryEnabled(),
    };
  }

  async function loadMemoryHistory() {
    if (!state.sessionId) return;
    try {
      const resp = await fetch(`/api/memory/${state.sessionId}`);
      if (!resp.ok) return;
      const data = await resp.json();
      renderMemoryHistory(data.rounds || []);
      updateMemoryBadge(data.available, data.round_count);
    } catch (e) {
      console.warn("Memory history unavailable:", e);
    }
  }

  function updateMemoryBadge(available, count) {
    if (!elements.memoryBadge) return;
    if (!available) {
      elements.memoryBadge.textContent = "Memory: off (Redis unavailable)";
      elements.memoryBadge.style.color = "#f87171";
    } else if (count > 0) {
      elements.memoryBadge.textContent = `Memory: ${count} round${count > 1 ? "s" : ""}`;
      elements.memoryBadge.style.color = "#10b981";
    } else {
      elements.memoryBadge.textContent = "Memory: empty";
      elements.memoryBadge.style.color = "#9ca3af";
    }
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function renderMemoryHistory(rounds) {
    if (!elements.memoryHistory) return;
    if (!rounds.length) {
      elements.memoryHistory.innerHTML = '<p class="muted">No prior conversation.</p>';
      return;
    }
    elements.memoryHistory.innerHTML = rounds
      .map((r) => {
        const synth = r.synthesis
          ? `<div class="memory-synthesis"><strong>${escapeHtml(r.synthesis.label)}</strong>: ${escapeHtml(r.synthesis.answer.slice(0, 150))}${r.synthesis.answer.length > 150 ? "…" : ""}</div>`
          : '<div class="muted" style="margin-top: 0.5rem;">No synthesis yet</div>';
        const ts = new Date(r.timestamp * 1000).toLocaleString();
        const question = r.question;
        return `<details class="memory-round">
          <summary>${ts} — ${escapeHtml(question.slice(0, 60))}${question.length > 60 ? "…" : ""}</summary>
          <div class="memory-round-body">
            <div class="memory-question">${escapeHtml(question)}</div>
            ${synth}
          </div>
        </details>`;
      })
      .join("");
  }

  async function clearMemory() {
    if (!state.sessionId) return;
    if (!confirm("Clear all conversation memory for this session?")) return;
    try {
      await fetch(`/api/memory/${state.sessionId}`, { method: "DELETE" });
      loadMemoryHistory();
      showToast("Conversation memory cleared.");
    } catch (e) {
      showToast("Failed to clear memory.", "error");
    }
  }

  // ── Core App Logic ────────────────────────────────────────────────────────

  function formatDuration(milliseconds) {
    if (!Number.isFinite(milliseconds)) return "";
    if (milliseconds < 1_000) return `${milliseconds} ms`;
    return `${(milliseconds / 1_000).toFixed(milliseconds < 10_000 ? 1 : 0)} s`;
  }

  function showToast(message, kind = "info") {
    window.clearTimeout(state.toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.toggle("is-error", kind === "error");
    elements.toast.hidden = false;
    state.toastTimer = window.setTimeout(() => {
      elements.toast.hidden = true;
    }, 5_200);
  }

  async function request(path, payload) {
    let response;
    try {
      response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });
    } catch (_) {
      throw new Error("Could not reach the local Model Council server. Keep the terminal running and try again.");
    }

    let body = {};
    try {
      body = await response.json();
    } catch (_) {
      throw new Error("The local server returned an invalid response.");
    }
    if (!response.ok) {
      throw new Error(typeof body.error === "string" ? body.error : "The request could not be completed.");
    }
    return body;
  }
  async function handleOllamaRpc(socket, message) {
    const base_url = elements.ollamaBaseUrl.value.trim() || "http://127.0.0.1:11434";
    const payload = {
      model: message.model,
      stream: true,
      think: false,
      messages: message.messages,
      options: message.options,
      keep_alive: message.keep_alive || "5m"
    };

    const controller = new AbortController();
    state.ollamaRpcController = controller;
    socket.addEventListener("close", () => controller.abort());

    try {
      const response = await fetch(`${base_url}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      if (!response.ok) {
        socket.send(JSON.stringify({ rpc: "ollama_error", error: `Ollama HTTP ${response.status}` }));
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let final_usage = {};

      while (true) {
        if (socket.readyState !== WebSocket.OPEN) break;
        const { done, value } = await reader.read();
        if (done) break;

        const lines = decoder.decode(value).split("\n").filter(l => l.trim());
        for (const line of lines) {
          try {
            const event = JSON.parse(line);
            if (event.message && event.message.content) {
              socket.send(JSON.stringify({ rpc: "ollama_chunk", content: event.message.content }));
            }
            if (event.done) {
              final_usage = {
                prompt_eval_count: event.prompt_eval_count,
                eval_count: event.eval_count,
                prompt_eval_duration: event.prompt_eval_duration,
                eval_duration: event.eval_duration
              };
            }
          } catch (e) {
            // Ignore partial JSON parse errors
          }
        }
      }
      socket.send(JSON.stringify({ rpc: "ollama_done", usage: final_usage }));

    } catch (err) {
      if (err.name === "AbortError") return;   // expected after a stop or socket close
      socket.send(JSON.stringify({
        rpc: "ollama_error",
        error: "Cannot reach local Ollama from browser. Is it running? (Check OLLAMA_ORIGINS)"
      }));
    } finally {
      if (state.ollamaRpcController === controller) state.ollamaRpcController = null;
    }
  }
    function streamRequest(payload, onEvent) {
    return new Promise((resolve, reject) => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      let settled = false;
      let completed = false;
      let socket;
      try {
        socket = new WebSocket(`${protocol}//${window.location.host}/api/council/stream`);
      } catch (_) {
        reject(new Error("This browser could not open the local streaming connection."));
        return;
      }
      state.streamSocket = socket;

      const fail = (message) => {
        if (settled) return;
        settled = true;
        reject(new Error(message));
      };

      socket.addEventListener("open", () => socket.send(JSON.stringify(enrichPayload(payload))));
      
      socket.addEventListener("message", (event) => {
        let message;
        try {
          message = JSON.parse(event.data);
        } catch (_) {
          fail("The local server sent an invalid streaming response.");
          socket.close();
          return;
        }
        if (!message || typeof message.type !== "string") return;

        if (message.type === "rpc_ollama_chat") {
          handleOllamaRpc(socket, message);
          return;
        }

        if (message.type === "error") {
          fail(typeof message.message === "string" ? message.message : "The streaming request could not be completed.");
          socket.close();
          return;
        }
        onEvent(message);
        if (message.type === "round_complete" || message.type === "synthesis_complete" ||
            (message.type === "agent_complete" && message.result)) {
          completed = true;
          if (!settled) {
            settled = true;
            resolve(message.result || {});
          }
        }
      });
      
      socket.addEventListener("error", () => fail("Could not open the local streaming connection. Keep the server running and try again."));
      socket.addEventListener("close", () => {
        if (!completed) fail("The local streaming connection closed before the response finished.");
        if (state.streamSocket === socket) state.streamSocket = null;
      });
    });
  }

  function isEnabled(provider) {
    const input = elements.enabledInputs[provider];
    return Boolean(input && input.checked);
  }

  function buildProviderSettings() {
    const openaiEnabled = isEnabled("openai");
    const anthropicEnabled = isEnabled("anthropic");
    const ollamaEnabled = isEnabled("ollama");
    const customEnabled = isEnabled("custom");
    const customMode = elements.customMode.value;
    const queryParams = { ...state.customQueryParams };
    if (customMode === "azure") {
      const apiVersion = elements.customApiVersion.value.trim();
      if (apiVersion) queryParams["api-version"] = apiVersion;
    }
    return {
      openai: {
        enabled: openaiEnabled,
        model: elements.openaiModel.value.trim(),
        api_key: openaiEnabled ? elements.openaiKey.value : "",
      },
      anthropic: {
        enabled: anthropicEnabled,
        model: elements.anthropicModel.value.trim(),
        api_key: anthropicEnabled ? elements.anthropicKey.value : "",
      },
      ollama: {
        enabled: ollamaEnabled,
        model: elements.ollamaModel.value.trim(),
        base_url: elements.ollamaBaseUrl.value.trim(),
      },
      custom: {
        enabled: customEnabled,
        mode: customMode,
        label: elements.customLabel.value.trim(),
        model: elements.customModel.value.trim(),
        endpoint: elements.customEndpoint.value.trim(),
        auth_type: elements.customAuthType.value,
        api_key: customEnabled ? elements.customKey.value : "",
        headers: { ...state.customHeaders },
        query_params: queryParams,
      },
    };
  }

  function objectOfSimpleValues(value, field) {
    if (!value || Array.isArray(value) || typeof value !== "object") {
      throw new Error(`${field} must be a JSON object.`);
    }
    return value;
  }

  function applyCustomJson() {
    let config;
    try {
      config = JSON.parse(elements.customJson.value);
    } catch (_) {
      showToast("Custom configuration must be valid JSON.", "error");
      return;
    }
    if (!config || Array.isArray(config) || typeof config !== "object") {
      showToast("Custom configuration must be a JSON object.", "error");
      return;
    }
    const stringFields = ["label", "mode", "model", "endpoint", "auth_type", "api_key"];
    for (const field of stringFields) {
      if (field in config && typeof config[field] !== "string") {
        showToast(`Custom JSON field \`${field}\` must be text.`, "error");
        return;
      }
    }
    if (config.mode && !["azure", "responses"].includes(config.mode)) {
      showToast("Custom JSON mode must be \"azure\" or \"responses\".", "error");
      return;
    }
    if (config.auth_type && !["api-key", "bearer", "none"].includes(config.auth_type)) {
      showToast("Custom JSON auth_type must be \"api-key\", \"bearer\", or \"none\".", "error");
      return;
    }
    try {
      if ("headers" in config) state.customHeaders = objectOfSimpleValues(config.headers, "headers");
      if ("query_params" in config) state.customQueryParams = objectOfSimpleValues(config.query_params, "query_params");
    } catch (error) {
      showToast(error.message, "error");
      return;
    }

    if (typeof config.mode === "string") elements.customMode.value = config.mode;
    if (typeof config.label === "string") elements.customLabel.value = config.label;
    if (typeof config.model === "string") elements.customModel.value = config.model;
    if (typeof config.endpoint === "string") elements.customEndpoint.value = config.endpoint;
    if (typeof config.auth_type === "string") elements.customAuthType.value = config.auth_type;
    if (typeof config.api_key === "string") elements.customKey.value = config.api_key;
    if (config.query_params && typeof config.query_params["api-version"] !== "undefined") {
      elements.customApiVersion.value = String(config.query_params["api-version"]);
    }
    elements.customEnabled.checked = true;
    syncProviderCard("custom");
    syncCustomMode();
    showToast("Custom provider configuration applied for this tab only.");
  }

  function syncCustomMode() {
    const isAzure = elements.customMode.value === "azure";
    elements.customApiVersion.disabled = !isAzure || !isEnabled("custom");
    elements.customApiVersion.closest("div").classList.toggle("is-visually-muted", !isAzure);
    elements.customStatus.textContent = isAzure
      ? "Azure calls use your deployment name and the Responses API. Keys remain request-scoped."
      : "Use the provider's complete OpenAI-compatible /responses URL. Add gateway headers through JSON if needed.";
  }

  function syncProviderCard(provider) {
    const card = document.querySelector(`[data-provider-card="${provider}"]`);
    const enabled = isEnabled(provider);
    card.classList.toggle("is-disabled", !enabled);
    card.querySelectorAll('input:not([type="checkbox"]), button').forEach((control) => {
      control.disabled = !enabled;
    });
    if (provider === "custom") syncCustomMode();
    updateMemberCount();
  }

  function updateMemberCount() {
    const enabled = providers.filter(isEnabled).length;
    elements.memberCount.textContent = `${enabled} ${enabled === 1 ? "seat" : "seats"}`;
  }

  function updateQuestionCount() {
    elements.questionCount.textContent = `${elements.question.value.length.toLocaleString()} / 14,000`;
  }

  function setAskBusy(busy) {
    state.asking = busy;
    elements.ask.disabled = busy;
    elements.ask.classList.toggle("is-loading", busy);
    elements.ask.querySelector(".button-label").textContent = busy ? "Council deliberating" : "Convene council";
    setCancelButton(busy);
    if (!busy) state.councilStopped = false;
  }

  function setSynthesisBusy(busy) {
    state.synthesizing = busy;
    elements.synthesize.disabled = busy || getSelectedMembers().length === 0;
    elements.synthesize.textContent = busy ? "Synthesizing…" : "Synthesize";
  }
    // ── Council cancellation ──────────────────────────────────────────────────
  function setCancelButton(visible, label = "Stop council") {
    if (!elements.cancel) return;
    elements.cancel.hidden = !visible;
    elements.cancel.disabled = false;
    const labelEl = elements.cancel.querySelector(".button-label");
    if (labelEl) labelEl.textContent = label;
  }

  async function cancelCouncil() {
    if (!state.asking) return;
    if (!state.currentRoundId) return;   // round_start hasn't arrived yet
    elements.cancel.disabled = true;
    const labelEl = elements.cancel.querySelector(".button-label");
    if (labelEl) labelEl.textContent = "Stopping…";
    try {
      await fetch(`/api/council/cancel/${encodeURIComponent(state.currentRoundId)}`, {
        method: "POST",
        credentials: "same-origin",
      });
    } catch (_) {
      /* the stream still delivers council_cancelled even if this fails */
    }
  }

  window.addEventListener("pagehide", () => {
    if (state.asking && state.currentRoundId) {
      navigator.sendBeacon(`/api/council/cancel/${encodeURIComponent(state.currentRoundId)}`);
    }
    if (state.agentRunning && state.agentRoundId) {
      navigator.sendBeacon(`/api/council/cancel/${encodeURIComponent(state.agentRoundId)}`);
    }
  });

  function getSelectedMembers() {
    return state.members.filter((member) => member.status === "complete" && member.included !== false);
  }
  function statusLabel(status) {
    return {
      pending: "Thinking",
      complete: "Ready",
      cancelled: "Stopped",
      error: "Unavailable",
      skipped: "Skipped",
    }[status] || "Unknown";
  }

  function memberSummary(member) {
    if (member.status === "complete") {
      const parts = [];
      if (Number.isFinite(member.latency_ms)) parts.push(`Answered in ${formatDuration(member.latency_ms)}`);
      if (member.truncated) parts.push("output limited for display");
      return parts.join(" · ") || "Response received";
    }
    if (member.status === "cancelled") return member.text ? "Stopped mid-answer — partial answer kept." : "Stopped before this member finished.";
    if (member.status === "pending") return member.text ? "Streaming response…" : "This member is considering the question…";
    return "";
  }

  function safeUrl(value) {
    try {
      const url = new URL(value, window.location.href);
      return ["http:", "https:", "mailto:"].includes(url.protocol) ? url.href : null;
    } catch (_) {
      return null;
    }
  }

  function appendInlineMarkdown(target, source) {
    const tokenPattern = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\[[^\]]+\]\((?:https?:\/\/|mailto:)[^)]+\)|\*[^*]+\*|_[^_]+_)/g;
    let cursor = 0;
    let match;
    while ((match = tokenPattern.exec(source)) !== null) {
      target.append(document.createTextNode(source.slice(cursor, match.index)));
      const token = match[0];
      let node;
      if (token.startsWith("`")) {
        node = document.createElement("code");
        node.textContent = token.slice(1, -1);
      } else if (token.startsWith("**") || token.startsWith("__")) {
        node = document.createElement("strong");
        node.textContent = token.slice(2, -2);
      } else if (token.startsWith("*") || token.startsWith("_")) {
        node = document.createElement("em");
        node.textContent = token.slice(1, -1);
      } else {
        const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
        const href = link && safeUrl(link[2]);
        if (link && href) {
          node = document.createElement("a");
          node.href = href;
          node.target = "_blank";
          node.rel = "noreferrer noopener";
          node.textContent = link[1];
        } else {
          node = document.createTextNode(token);
        }
      }
      target.append(node);
      cursor = tokenPattern.lastIndex;
    }
    target.append(document.createTextNode(source.slice(cursor)));
  }

  function renderMarkdown(container, value) {
    const text = typeof value === "string" ? value.replace(/\r\n?/g, "\n") : "";
    const lines = text.split("\n");
    const fragment = document.createDocumentFragment();
    let index = 0;

    const isBlockStart = (line) => /^(#{1,3}\s+|```|>\s?|\s*[-*+]\s+|\s*\d+[.)]\s+|---+\s*$)/.test(line);
    const addParagraph = (paragraphLines) => {
      const paragraph = document.createElement("p");
      appendInlineMarkdown(paragraph, paragraphLines.join(" "));
      fragment.append(paragraph);
    };

    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
        continue;
      }
      const heading = /^(#{1,3})\s+(.+?)\s*$/.exec(line);
      if (heading) {
        const node = document.createElement(`h${heading[1].length}`);
        appendInlineMarkdown(node, heading[2]);
        fragment.append(node);
        index += 1;
        continue;
      }
      if (/^```/.test(line)) {
        const language = line.slice(3).trim();
        const codeLines = [];
        index += 1;
        while (index < lines.length && !/^```/.test(lines[index])) codeLines.push(lines[index++]);
        if (index < lines.length) index += 1;
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        if (language) code.dataset.language = language;
        code.textContent = codeLines.join("\n");
        pre.append(code);
        fragment.append(pre);
        continue;
      }
      if (/^---+\s*$/.test(line)) {
        fragment.append(document.createElement("hr"));
        index += 1;
        continue;
      }
      if (/^>\s?/.test(line)) {
        const quoteLines = [];
        while (index < lines.length && /^>\s?/.test(lines[index])) quoteLines.push(lines[index++].replace(/^>\s?/, ""));
        const quote = document.createElement("blockquote");
        appendInlineMarkdown(quote, quoteLines.join(" "));
        fragment.append(quote);
        continue;
      }
      const listMatch = /^\s*([-*+]|\d+[.)])\s+(.+)$/.exec(line);
      if (listMatch) {
        const ordered = /^\d/.test(listMatch[1]);
        const list = document.createElement(ordered ? "ol" : "ul");
        while (index < lines.length) {
          const item = /^\s*([-*+]|\d+[.)])\s+(.+)$/.exec(lines[index]);
          if (!item || /^\d/.test(item[1]) !== ordered) break;
          const listItem = document.createElement("li");
          appendInlineMarkdown(listItem, item[2]);
          list.append(listItem);
          index += 1;
        }
        fragment.append(list);
        continue;
      }
      const paragraphLines = [line];
      index += 1;
      while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index])) paragraphLines.push(lines[index++]);
      addParagraph(paragraphLines);
    }
    container.replaceChildren(fragment);
  }

  function createMemberView(member) {
    const fragment = elements.memberTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".member-result");
    const view = {
      card,
      name: fragment.querySelector(".member-name"),
      model: fragment.querySelector(".member-model"),
      status: fragment.querySelector(".result-status"),
      meta: fragment.querySelector(".result-meta"),
      answer: fragment.querySelector(".answer-text"),
      detail: fragment.querySelector(".result-detail"),
      includeControl: fragment.querySelector(".include-control"),
      include: fragment.querySelector(".include-member"),
      copy: fragment.querySelector(".copy-button"),
      expand: fragment.querySelector(".expand-button"),
    };
    view.include.addEventListener("change", () => {
      const current = state.members.find((item) => item.provider === member.provider);
      if (current) current.included = view.include.checked;
      updateSynthesisControls();
    });
    view.copy.addEventListener("click", () => {
      const current = state.members.find((item) => item.provider === member.provider);
      copyText(current?.text || "", view.copy);
    });
    view.expand.addEventListener("click", () => {
      const current = state.members.find((item) => item.provider === member.provider);
      openModal(current?.label || "Member", current?.model || "", current?.text || "", "TESTIMONY");
    });
    elements.memberResults.append(fragment);
    state.memberViews.set(member.provider, view);
    return view;
  }

  function renderMembers() {
    state.memberViews.clear();
    elements.memberResults.replaceChildren();
    state.members.forEach(patchMember);
  }
    function patchMember(member) {
    if (member.status === "skipped") {
      const view = state.memberViews.get(member.provider);
      if (view) view.card.hidden = true;
      return;
    }

    const view = state.memberViews.get(member.provider) || createMemberView(member);
    view.card.hidden = false;

    view.card.dataset.provider = member.provider;
    view.card.classList.remove("is-pending", "is-complete", "is-error", "is-skipped", "is-cancelled");
    view.card.classList.add(`is-${member.status}`);
    view.name.textContent = member.label || providerLabels[member.provider] || "Member";
    view.model.textContent = member.model || "No model selected";
    view.status.textContent = statusLabel(member.status);
    view.status.className = `result-status status-${member.status}`;
    view.meta.textContent = memberSummary(member);

    if (member.status === "complete") {
      renderMarkdown(view.answer, member.text || "This member did not return any displayable text.");
      view.detail.textContent = member.truncated ? "The displayed answer was truncated to keep the council context manageable." : "";
      if (typeof member.included !== "boolean") member.included = true;
      view.include.checked = member.included;
      view.includeControl.classList.remove("is-hidden");
      view.include.disabled = false;
      view.copy.disabled = false;
      view.expand.disabled = false;
    } else if (member.status === "cancelled") {
      renderMarkdown(view.answer, member.text || "");
      view.detail.textContent = member.text
        ? "Stopped by user — partial answer kept below."
        : "Stopped by user before this member finished.";
      view.includeControl.classList.add("is-hidden");
      view.include.disabled = true;
      view.copy.disabled = !member.text;
      view.expand.disabled = !member.text;
    } else if (member.status === "pending") {
      renderMarkdown(view.answer, member.text || "");
      view.detail.textContent = member.text ? "Receiving a streamed response…" : "Waiting for the local server to collect the council's responses.";
      view.includeControl.classList.add("is-hidden");
      view.include.disabled = true;
      view.copy.disabled = true;
      view.expand.disabled = true;
    } else {
      view.answer.replaceChildren();
      view.detail.textContent = member.detail || "This member was not included in this round.";
      view.includeControl.classList.add("is-hidden");
      view.include.disabled = true;
      view.copy.disabled = true;
      view.expand.disabled = true;
    }
  }

  function flushMemberPatches() {
    const pending = [...state.pendingMemberProviders];
    state.pendingMemberProviders.clear();
    state.memberRenderTimer = null;
    state.lastMemberRender = performance.now();
    pending.forEach((name) => {
      const member = state.members.find((item) => item.provider === name);
      if (member) patchMember(member);
    });
  }

  function scheduleMemberPatch(provider) {
    state.pendingMemberProviders.add(provider);
    if (state.memberRenderTimer !== null) return;
    const wait = Math.max(0, RENDER_INTERVAL_MS - (performance.now() - state.lastMemberRender));
    state.memberRenderTimer = window.setTimeout(flushMemberPatches, wait);
  }

  function flushFinalRender() {
    state.finalRenderTimer = null;
    state.lastFinalRender = performance.now();
    renderMarkdown(elements.finalText, state.finalAnswer);
  }

  function scheduleFinalRender() {
    if (state.finalRenderTimer !== null) return;
    const wait = Math.max(0, RENDER_INTERVAL_MS - (performance.now() - state.lastFinalRender));
    state.finalRenderTimer = window.setTimeout(flushFinalRender, wait);
  }

  function updateSynthesisControls(resetChair = false) {
    const completed = state.members.filter((member) => member.status === "complete");
    const selected = getSelectedMembers();
    elements.synthesis.hidden = completed.length === 0;
    if (completed.length === 0) return;

    const prior = elements.moderator.value;
    if (resetChair || !Array.from(elements.moderator.options).some((option) => option.value === prior)) {
      elements.moderator.replaceChildren();
      for (const member of completed) {
        const option = document.createElement("option");
        option.value = member.provider;
        option.textContent = `${member.label} · ${member.model}`;
        elements.moderator.append(option);
      }
      if (prior && Array.from(elements.moderator.options).some((option) => option.value === prior)) {
        elements.moderator.value = prior;
      }
    }
    elements.selectionNote.textContent = `${selected.length} of ${completed.length} completed ${completed.length === 1 ? "answer" : "answers"} selected for the chair.`;
    elements.synthesize.disabled = state.synthesizing || selected.length === 0;
  }

  function showPendingRound() {
    const settings = buildProviderSettings();
    state.members = providers.map((provider) => ({
      provider,
      label: providerLabels[provider],
      model: settings[provider].model || "Not selected",
      status: settings[provider].enabled ? "pending" : "skipped",
      detail: settings[provider].enabled ? "" : "Disabled",
    }));
    state.finalAnswer = "";
    elements.finalAnswer.hidden = true;
    elements.results.hidden = false;
    elements.synthesis.hidden = true;
    elements.roundTime.textContent = "Council is deliberating…";
    renderMembers();
  }
  async function askCouncil() {
    if (state.asking) return;
    const question = elements.question.value.trim();
    if (!question) {
      showToast("Write a question before convening the council.", "error");
      elements.question.focus();
      return;
    }

    state.question = question;
    showPendingRound();
    setAskBusy(true);
    try {
      const data = await streamRequest({
        action: "ask",
        question,
        system_prompt: elements.guidance.value.trim(),
        providers: buildProviderSettings(),
        max_tokens: Number(elements.responseLength.value),
        temperature: Number(elements.temperature.value),
      }, (event) => {
        if (event.type === "round_start") {
          state.currentRoundId = event.round_id || "";
        } else if (event.type === "council_cancelled") {
          state.councilStopped = true;
          if (state.ollamaRpcController) {
            state.ollamaRpcController.abort();   // stop pulling chunks from local Ollama
            state.ollamaRpcController = null;
          }
          state.members.forEach((member) => {
            if (member.status === "pending") member.status = "cancelled";
          });
          renderMembers();
          showToast("Stopping the council — completed answers are kept.");
        } else if (event.type === "member" || event.type === "member_complete") {
          const member = event.member;
          if (!member || typeof member.provider !== "string") return;
          const index = state.members.findIndex((item) => item.provider === member.provider);
          if (index >= 0) state.members[index] = member;
          else state.members.push(member);
          scheduleMemberPatch(member.provider);
        } else if (event.type === "member_delta") {
          if (state.councilStopped) return;
          const member = state.members.find((item) => item.provider === event.provider);
          if (!member || typeof event.delta !== "string") return;
          member.text = `${member.text || ""}${event.delta}`;
          scheduleMemberPatch(member.provider);
        }
      });

      const streamedBeforeStop = new Map(
        state.members.filter((m) => m.text).map((m) => [m.provider, m]),
      );
      state.members = Array.isArray(data.members) ? data.members : [];
      if (data.cancelled) {
        // The server keeps no text for stopped members; restore what the
        // browser streamed so "partial results kept" is actually true.
        state.members.forEach((member) => {
          const local = streamedBeforeStop.get(member.provider);
          if (local && !member.text) {
            member.text = local.text;
            if (member.status !== "complete" && member.status !== "error") member.status = "cancelled";
          }
        });
      }
      state.members.forEach((member) => {
        if (member.status === "complete") member.included = true;
      });
      state.question = typeof data.question === "string" ? data.question : question;
      state.currentRoundId = data.round_id || "";
      elements.roundTime.textContent = data.cancelled
        ? "Council stopped — partial results kept"
        : `Round completed in ${formatDuration(data.elapsed_ms)}`;
      renderMembers();
      updateSynthesisControls(true);
      loadMemoryHistory();

      if (!state.members.some((member) => member.status === "complete") && !data.cancelled) {
        showToast("No council member completed this round. Check each card for the reason.", "error");
      }
    } catch (error) {
      elements.results.hidden = true;
      state.members = [];
      showToast(error.message || "The council could not be convened.", "error");
    } finally {
      setAskBusy(false);
    }
  }
  async function synthesizeCouncil() {
    if (state.synthesizing) return;
    const selected = getSelectedMembers();
    if (selected.length === 0) {
      showToast("Select at least one completed answer for the chair.", "error");
      return;
    }
    const moderator = elements.moderator.value;
    if (!moderator) {
      showToast("Choose a chair for the synthesis.", "error");
      return;
    }

    setSynthesisBusy(true);
    elements.finalAnswer.hidden = true;
    try {
      const data = await streamRequest({
        action: "synthesize",
        question: state.question || elements.question.value.trim(),
        moderator,
        providers: buildProviderSettings(),
        submissions: selected.map((member) => ({
          provider: member.provider,
          label: member.label,
          model: member.model,
          text: member.text,
        })),
        round_id: state.currentRoundId, // Send round_id to update memory
        max_tokens: Number(elements.responseLength.value),
        temperature: Math.min(0.8, Number(elements.temperature.value)),
      }, (event) => {
        if (event.type === "synthesis_start") {
          state.finalAnswer = "";
          elements.finalTitle.textContent = `${event.label || "Council"} synthesis`;
          elements.finalMeta.textContent = `${event.model || "Selected model"} · streaming`;
          elements.finalText.replaceChildren();
          elements.finalAnswer.hidden = false;
        } else if (event.type === "synthesis_delta" && typeof event.delta === "string") {
          state.finalAnswer += event.delta;
          scheduleFinalRender();
        }
      });
      state.finalAnswer = data.answer || "";
      elements.finalTitle.textContent = `${data.label || "Council"} synthesis`;
      elements.finalMeta.textContent = `${data.model || "Selected model"} · ${data.submission_count || selected.length} ${data.submission_count === 1 ? "submission" : "submissions"} · ${formatDuration(data.latency_ms)}`;
      renderMarkdown(elements.finalText, state.finalAnswer || "The chair did not return any displayable text.");
      elements.finalAnswer.hidden = false;
      elements.finalAnswer.scrollIntoView({ behavior: "smooth", block: "nearest" });
      loadMemoryHistory(); // Refresh memory UI
    } catch (error) {
      showToast(error.message || "The chair could not complete the synthesis.", "error");
    } finally {
      setSynthesisBusy(false);
    }
  }

  async function refreshOllama() {
    if (elements.ollamaRefresh.disabled) return;
    elements.ollamaRefresh.disabled = true;
    elements.ollamaRefresh.textContent = "Checking…";
    elements.ollamaStatus.textContent = "Checking local Ollama…";
    elements.ollamaStatus.className = "connection-note";

    const base_url = elements.ollamaBaseUrl.value.trim();
    const isLocal = base_url.includes("127.0.0.1") || base_url.includes("localhost");

    try {
      let data;
      const cached = state.ollamaListCache;
      if (cached && cached.base_url === base_url && performance.now() - cached.at < OLLAMA_LIST_CACHE_MS) {
        data = cached.data;
      } else if (isLocal) {
        // Bypass FastAPI and fetch directly from the browser!
        const res = await fetch(`${base_url}/api/tags`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        data = { models: json.models || [] };
      } else {
        // Use FastAPI for remote URLs (like Ngrok)
        data = await request("/api/ollama/models", { base_url: base_url });
      }
      state.ollamaListCache = { base_url, at: performance.now(), data };

      const models = Array.isArray(data.models) ? data.models : [];
      const installedModelNames = new Set();
      const options = document.createDocumentFragment();
      for (const model of models) {
        if (!model || typeof model.name !== "string") continue;
        installedModelNames.add(model.name);
        const option = document.createElement("option");
        option.value = model.name;
        options.append(option);
      }
      elements.ollamaOptions.replaceChildren(options);
      if (!elements.ollamaModel.value && models[0] && models[0].name) {
        elements.ollamaModel.value = models[0].name;
      }
      const count = models.length;
      const selectedModel = elements.ollamaModel.value.trim();
      const gemma4Installed = [...installedModelNames].some((name) => name === "gemma4" || name.startsWith("gemma4:"));
      if (gemma4Installed) {
        elements.ollamaStatus.textContent = `Gemma 4 is available · ${count} local ${count === 1 ? "model" : "models"} found`;
      } else if (selectedModel === "gemma4") {
        elements.ollamaStatus.textContent = count
          ? `Gemma 4 is not installed · ${count} other local ${count === 1 ? "model" : "models"} found. Run \`ollama pull gemma4\` to add it.`
          : "Ollama is reachable, but Gemma 4 is not installed. Pull it with `ollama pull gemma4`.";
      } else {
        elements.ollamaStatus.textContent = count ? `${count} local ${count === 1 ? "model" : "models"} available` : "Ollama is reachable, but no local models were found.";
      }
      elements.ollamaStatus.className = "connection-note is-ready";
      if (!count) showToast("Ollama is running, but it has no models yet. Pull one with `ollama pull <model>`.");
    } catch (error) {
      elements.ollamaStatus.textContent = error.message || "Could not reach local Ollama.";
      elements.ollamaStatus.className = "connection-note is-error";
    } finally {
      elements.ollamaRefresh.disabled = false;
      elements.ollamaRefresh.textContent = "Refresh";
    }
  }

  async function copyText(text, button) {
    if (!text) return;
    const original = button.textContent;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const temporary = document.createElement("textarea");
        temporary.value = text;
        temporary.style.position = "fixed";
        temporary.style.opacity = "0";
        document.body.append(temporary);
        temporary.select();
        const copied = document.execCommand("copy");
        temporary.remove();
        if (!copied) throw new Error("Copy was unavailable.");
      }
      button.textContent = "Copied";
      window.setTimeout(() => { button.textContent = original; }, 1_300);
    } catch (_) {
      showToast("Copy was unavailable in this browser. Select the text to copy it.", "error");
    }
  }

  function clearSession() {
    if (state.asking && state.currentRoundId) {
      navigator.sendBeacon(`/api/council/cancel/${encodeURIComponent(state.currentRoundId)}`);
    }
    if (state.streamSocket) state.streamSocket.close();
    if (state.memberRenderTimer !== null) window.clearTimeout(state.memberRenderTimer);
    if (state.finalRenderTimer !== null) window.clearTimeout(state.finalRenderTimer);
    state.memberRenderTimer = null;
    state.finalRenderTimer = null;
    state.pendingMemberProviders.clear();
    elements.openaiKey.value = "";
    elements.anthropicKey.value = "";
    elements.customKey.value = "";
    elements.customJson.value = "";
    state.customHeaders = {};
    state.customQueryParams = {};
    elements.question.value = "";
    elements.guidance.value = "";
    updateQuestionCount();
    state.members = [];
    state.question = "";
    state.finalAnswer = "";
    state.currentRoundId = "";
    elements.results.hidden = true;
    elements.synthesis.hidden = true;
    elements.finalAnswer.hidden = true;
    elements.memberResults.replaceChildren();
    state.memberViews.clear();
    elements.ollamaStatus.textContent = "Not checked yet";
    elements.ollamaStatus.className = "connection-note";
    showToast("Keys, prompt, and council results cleared from this page.");
  }

  // ── Workspace / Code Agent ────────────────────────────────────────────────

  function switchMode(mode) {
    const isWorkspace = mode === "workspace";
    elements.councilMode.hidden = isWorkspace;
    elements.workspaceMode.hidden = !isWorkspace;
    elements.modeCouncil.classList.toggle("is-active", !isWorkspace);
    elements.modeWorkspace.classList.toggle("is-active", isWorkspace);
    elements.modeCouncil.setAttribute("aria-selected", String(!isWorkspace));
    elements.modeWorkspace.setAttribute("aria-selected", String(isWorkspace));
    if (isWorkspace) loadWorkspaceRoots();
  }

  function shortenPath(path) {
    const segments = String(path).split("/").filter(Boolean);
    return segments.length > 2 ? `…/${segments.slice(-2).join("/")}` : path;
  }

  async function loadWorkspaceRoots() {
    try {
      const resp = await fetch("/api/workspace/roots", { cache: "no-store", credentials: "same-origin" });
      const data = await resp.json();
      const roots = Array.isArray(data.roots) ? data.roots : [];
      elements.workspaceRootSelect.replaceChildren();
      if (!roots.length) {
        state.workspaceRoot = "";
        elements.workspaceRootSelect.disabled = true;
        const option = document.createElement("option");
        option.textContent = data.error || "No workspace configured";
        elements.workspaceRootSelect.append(option);
        return;
      }
      elements.workspaceRootSelect.disabled = false;
      for (const entry of roots) {
        const option = document.createElement("option");
        option.value = entry.path;
        option.textContent = shortenPath(entry.path) + (entry.exists ? "" : " (missing)");
        elements.workspaceRootSelect.append(option);
      }
      if (!roots.some((entry) => entry.path === state.workspaceRoot)) {
        state.workspaceRoot = roots[0].path;
      }
      elements.workspaceRootSelect.value = state.workspaceRoot;
      elements.workspaceRootSelect.title = state.workspaceRoot;
    } catch (_) {
      state.workspaceRoot = "";
      elements.workspaceRootSelect.disabled = true;
      elements.workspaceRootSelect.replaceChildren();
      const option = document.createElement("option");
      option.textContent = "Workspace unavailable";
      elements.workspaceRootSelect.append(option);
    }
  }

  function onRootChange() {
    state.workspaceRoot = elements.workspaceRootSelect.value;
    elements.workspaceRootSelect.title = state.workspaceRoot;
    elements.workspaceTree.replaceChildren();
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No file tree loaded yet.";
    elements.workspaceTree.append(empty);
    elements.fileViewer.hidden = true;
  }

  async function loadTree() {
    if (elements.loadTree.disabled) return;
    elements.loadTree.disabled = true;
    elements.loadTree.textContent = "Loading…";
    try {
      const data = await request("/api/workspace/tree", { root: state.workspaceRoot });
      renderTree(data);
    } catch (error) {
      showToast(error.message || "Could not load the file tree.", "error");
    } finally {
      elements.loadTree.disabled = false;
      elements.loadTree.textContent = "Load file tree";
    }
  }

  function buildTreeModel(entries) {
    const root = { name: "", dirs: new Map(), files: [] };
    for (const entry of entries) {
      const parts = entry.path.split("/");
      let node = root;
      for (let i = 0; i < parts.length - 1; i += 1) {
        const key = parts[i];
        if (!node.dirs.has(key)) node.dirs.set(key, { name: key, dirs: new Map(), files: [] });
        node = node.dirs.get(key);
      }
      const name = parts[parts.length - 1];
      if (entry.type === "dir") {
        if (!node.dirs.has(name)) node.dirs.set(name, { name, dirs: new Map(), files: [] });
      } else {
        node.files.push({ name, path: entry.path, size: entry.size || 0 });
      }
    }
    return root;
  }

  function renderTreeNode(node, depth) {
    const wrap = document.createElement("div");
    const dirs = [...node.dirs.values()].sort((a, b) => a.name.localeCompare(b.name));
    const files = [...node.files].sort((a, b) => a.name.localeCompare(b.name));
    for (const dir of dirs) {
      const details = document.createElement("details");
      details.className = "tree-dir";
      if (depth < 1) details.open = true;
      const summary = document.createElement("summary");
      summary.textContent = `${dir.name}/`;
      details.append(summary);
      details.append(renderTreeNode(dir, depth + 1));
      wrap.append(details);
    }
    for (const file of files) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "tree-file";
      button.textContent = file.name;
      button.title = `${file.path} · ${file.size.toLocaleString()} bytes`;
      button.addEventListener("click", () => openWorkspaceFile(file.path));
      wrap.append(button);
    }
    return wrap;
  }

  function renderTree(data) {
    const entries = Array.isArray(data.entries) ? data.entries : [];
    if (!entries.length) {
      elements.workspaceTree.replaceChildren();
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "The workspace folder is empty.";
      elements.workspaceTree.append(empty);
      return;
    }
    const container = document.createElement("div");
    container.className = "tree-body";
    container.append(renderTreeNode(buildTreeModel(entries), 0));
    if (data.truncated) {
      const note = document.createElement("p");
      note.className = "tree-note";
      note.textContent = "Tree truncated — narrow with a subfolder search or raise the entry cap.";
      container.append(note);
    }
    elements.workspaceTree.replaceChildren(container);
  }

  async function openWorkspaceFile(path, offset) {
    try {
      const blob = await request("/api/workspace/read", { path, offset: offset || 1, root: state.workspaceRoot });
      renderFileViewer(blob);
    } catch (error) {
      showToast(error.message || "Could not open the file.", "error");
    }
  }

  function renderFileViewer(blob) {
    elements.fileViewer.hidden = false;
    elements.fileViewerPath.textContent = blob.path;
    elements.fileViewerMeta.textContent =
      `lines ${blob.start_line}–${blob.end_line} of ${blob.total_lines}` +
      (blob.truncated ? " · truncated" : "");
    const lines = blob.content.split("\n");
    const gutterWidth = String(blob.end_line).length;
    elements.fileViewerCode.textContent = lines
      .map((line, i) => `${String(blob.start_line + i).padStart(gutterWidth, " ")} │ ${line}`)
      .join("\n");
  }

  async function runWorkspaceSearch() {
    const query = elements.workspaceSearch.value.trim();
    if (!query) return;
    try {
      const data = await request("/api/workspace/search", { query, root: state.workspaceRoot });
      const container = document.createElement("div");
      container.className = "tree-body";
      const heading = document.createElement("p");
      heading.className = "tree-note";
      heading.textContent = `${data.matches.length} match${data.matches.length === 1 ? "" : "es"} for “${query}”` +
        (data.truncated ? " (truncated)" : "");
      container.append(heading);
      for (const match of data.matches) {
        const hit = document.createElement("button");
        hit.type = "button";
        hit.className = "search-hit";
        const place = document.createElement("span");
        place.className = "search-hit-path";
        place.textContent = `${match.path}:${match.line}`;
        const text = document.createElement("span");
        text.className = "search-hit-text";
        text.textContent = match.text;
        hit.append(place, text);
        hit.addEventListener("click", () => openWorkspaceFile(match.path, Math.max(1, match.line - 8)));
        container.append(hit);
      }
      const back = document.createElement("button");
      back.type = "button";
      back.className = "quiet-button";
      back.textContent = "← Back to file tree";
      back.addEventListener("click", loadTree);
      container.append(back);
      elements.workspaceTree.replaceChildren(container);
      elements.fileViewer.hidden = true;
    } catch (error) {
      showToast(error.message || "Search failed.", "error");
    }
  }

  function setAgentStatus(status, text) {
    elements.agentStatus.className = `result-status status-${status}`;
    elements.agentStatus.textContent = text;
  }

  function setAgentBusy(busy) {
    state.agentRunning = busy;
    elements.runAgent.disabled = busy;
    elements.runAgent.classList.toggle("is-loading", busy);
    elements.runAgent.querySelector(".button-label").textContent = busy ? "Agent working" : "Run coder agent";
    elements.cancelAgent.hidden = !busy;
    elements.cancelAgent.disabled = false;
    const labelEl = elements.cancelAgent.querySelector(".button-label");
    if (labelEl) labelEl.textContent = "Stop agent";
    if (!busy) state.agentStopped = false;
  }

  function upsertAgentStep(event) {
    const key = String(event.index);
    let row = state.agentStepRows.get(key);
    if (!row) {
      row = document.createElement("div");
      row.className = "agent-step";
      const index = document.createElement("span");
      index.className = "step-index";
      index.textContent = key;
      const body = document.createElement("div");
      body.className = "step-body";
      const top = document.createElement("div");
      top.className = "step-top";
      const label = document.createElement("span");
      label.className = "step-label";
      const chip = document.createElement("span");
      chip.className = "result-status";
      top.append(label, chip);
      const detail = document.createElement("p");
      detail.className = "step-detail";
      body.append(top, detail);
      row.append(index, body);
      state.agentStepRows.set(key, row);
      elements.agentFeed.append(row);
    }
    row.classList.remove("is-running", "is-complete", "is-error", "is-rejected");
    row.classList.add(`is-${event.status}`);
    row.querySelector(".step-label").textContent = event.label || event.action || "Step";
    const chip = row.querySelector(".result-status");
    chip.className = `result-status status-${event.status === "running" ? "pending" : event.status}`;
    chip.textContent = { running: "Working", complete: "Done", error: "Failed", rejected: "Rejected" }[event.status] || event.status;
    row.querySelector(".step-detail").textContent = event.detail || "";
    row.scrollIntoView({ block: "nearest" });
  }

  function appendDiffCard(event) {
    const card = document.createElement("div");
    card.className = "agent-diff-card is-pending";
    const head = document.createElement("div");
    head.className = "agent-diff-head";
    const path = document.createElement("strong");
    path.textContent = event.path;
    const kind = document.createElement("span");
    kind.className = "diff-kind";
    kind.textContent = event.is_new ? "new file" : event.action === "edit_file" ? "edit" : "rewrite";
    head.append(path, kind);
    const body = document.createElement("pre");
    body.className = "diff-body";
    for (const line of String(event.diff || "(no textual changes)").split("\n")) {
      const span = document.createElement("span");
      const isAdd = line.startsWith("+") && !line.startsWith("+++");
      const isDel = line.startsWith("-") && !line.startsWith("---");
      span.className = `diff-line ${isAdd ? "add" : isDel ? "del" : line.startsWith("@@") ? "hunk" : ""}`;
      span.textContent = line.length ? line : " ";
      body.append(span, document.createTextNode("\n"));
    }
    card.append(head, body);
    elements.agentFeed.append(card);
    state.pendingDiffCard = card;
    card.scrollIntoView({ block: "nearest" });
  }

  function attachConfirm(event) {
    const { confirm_id: confirmId, kind } = event;
    let card;
    if (kind === "write" && state.pendingDiffCard) {
      card = state.pendingDiffCard;
      state.pendingDiffCard = null;
    } else {
      card = document.createElement("div");
      card.className = "agent-diff-card is-pending";
      const head = document.createElement("div");
      head.className = "agent-diff-head";
      const strong = document.createElement("strong");
      strong.textContent = "Command";
      const command = document.createElement("code");
      command.textContent = Array.isArray(event.command) ? event.command.join(" ") : "";
      head.append(strong, command);
      card.append(head);
      elements.agentFeed.append(card);
    }
    card.dataset.confirmId = confirmId;
    const row = document.createElement("div");
    row.className = "confirm-row";
    const approve = document.createElement("button");
    approve.type = "button";
    approve.className = "confirm-approve";
    approve.textContent = kind === "command" ? "Approve & run" : "Approve & apply";
    const reject = document.createElement("button");
    reject.type = "button";
    reject.className = "confirm-reject";
    reject.textContent = "Reject";
    const note = document.createElement("span");
    note.className = "confirm-note";
    note.textContent = "Waiting for your decision…";
    approve.addEventListener("click", () => answerConfirm(confirmId, true, card));
    reject.addEventListener("click", () => answerConfirm(confirmId, false, card));
    row.append(approve, reject, note);
    card.append(row);
    card.scrollIntoView({ block: "nearest" });
  }

  function answerConfirm(confirmId, approved, card) {
    if (state.streamSocket && state.streamSocket.readyState === WebSocket.OPEN) {
      state.streamSocket.send(JSON.stringify({ rpc: "agent_confirm", confirm_id: confirmId, approved }));
    }
    markConfirm(card, approved);
  }

  function markConfirm(card, approved, noteText) {
    if (!card) return;
    card.classList.remove("is-pending");
    card.classList.add(approved ? "is-approved" : "is-rejected");
    const approve = card.querySelector(".confirm-approve");
    const reject = card.querySelector(".confirm-reject");
    if (approve) approve.disabled = true;
    if (reject) reject.disabled = true;
    const note = card.querySelector(".confirm-note");
    if (note) note.textContent = noteText || (approved ? "Approved" : "Rejected");
  }

  function closeOpenConfirms() {
    elements.agentFeed.querySelectorAll(".agent-diff-card.is-pending").forEach((card) => {
      markConfirm(card, false, "Closed");
    });
    state.pendingDiffCard = null;
  }

  function appendTerminal(event) {
    const wrap = document.createElement("div");
    wrap.className = `agent-terminal ${event.returncode === 0 ? "is-ok" : "is-fail"}`;
    const head = document.createElement("div");
    head.className = "terminal-head";
    const command = document.createElement("code");
    command.textContent = `$ ${(event.command || []).join(" ")}`;
    const exit = document.createElement("span");
    exit.className = "terminal-exit";
    exit.textContent = `exit ${event.returncode} · ${formatDuration(event.duration_ms)}`;
    head.append(command, exit);
    const pre = document.createElement("pre");
    pre.className = "terminal-body";
    pre.textContent = [event.stdout, event.stderr].filter(Boolean).join("\n") || "(no output)";
    wrap.append(head, pre);
    elements.agentFeed.append(wrap);
    wrap.scrollIntoView({ block: "nearest" });
  }

  async function runAgent() {
    if (state.agentRunning) return;
    const task = elements.codeTask.value.trim();
    if (!task) {
      showToast("Describe the coding task first.", "error");
      elements.codeTask.focus();
      return;
    }
    if (!state.workspaceRoot) {
      await loadWorkspaceRoots();
      if (!state.workspaceRoot) {
        showToast("No workspace folder. Set MODEL_COUNCIL_WORKSPACE_ROOT or create the default workspace/ folder.", "error");
        return;
      }
    }
    const providerSettings = buildProviderSettings();
    if (!providerSettings.ollama.enabled || !providerSettings.ollama.model) {
      showToast("Enable Ollama and choose a local model (e.g. qwen3-coder:30b).", "error");
      return;
    }

    state.agentStopped = false;
    state.agentStepRows = new Map();
    state.pendingDiffCard = null;
    elements.agentFeed.replaceChildren();
    elements.agentSummaryCard.hidden = true;
    elements.agentStreamText.replaceChildren();
    elements.agentStream.open = false;
    elements.agentActivity.hidden = false;
    elements.agentRunTitle.textContent = "Agent run";
    setAgentStatus("pending", "Working");
    setAgentBusy(true);
    try {
      const data = await streamRequest({
        action: "code_task",
        task,
        root: state.workspaceRoot,
        max_steps: Number(elements.agentMaxSteps.value),
        providers: { ollama: providerSettings.ollama },
      }, (event) => {
        if (event.type === "agent_start") {
          state.agentRoundId = event.round_id || "";
          state.workspaceRoot = event.root || state.workspaceRoot;
          if (elements.workspaceRootSelect.value !== state.workspaceRoot) {
            elements.workspaceRootSelect.value = state.workspaceRoot;
          }
          elements.workspaceRootSelect.title = state.workspaceRoot;
          elements.agentRunTitle.textContent = `Agent · ${event.model || "local model"}`;
        } else if (event.type === "agent_delta") {
          if (!state.agentStopped) elements.agentStreamText.append(document.createTextNode(event.delta || ""));
        } else if (event.type === "agent_step") {
          upsertAgentStep(event);
        } else if (event.type === "agent_diff") {
          appendDiffCard(event);
        } else if (event.type === "agent_confirm") {
          attachConfirm(event);
        } else if (event.type === "agent_confirm_done") {
          const card = elements.agentFeed.querySelector(`[data-confirm-id="${event.confirm_id}"]`);
          markConfirm(card, event.approved);
        } else if (event.type === "agent_output") {
          appendTerminal(event);
        } else if (event.type === "agent_cancelled") {
          state.agentStopped = true;
          setAgentStatus("cancelled", "Stopped");
          showToast("Stopping the code agent — approved changes are kept.");
        }
      });
      finishAgentRun(data);
    } catch (error) {
      setAgentStatus("error", "Failed");
      elements.agentSummaryCard.hidden = false;
      renderMarkdown(elements.agentSummaryText, error.message || "The code agent could not be started.");
      showToast(error.message || "The code agent could not be started.", "error");
    } finally {
      setAgentBusy(false);
      closeOpenConfirms();
    }
  }

  function finishAgentRun(data) {
    const status = data.cancelled ? "cancelled" : data.ok ? "complete" : "error";
    setAgentStatus(status, data.cancelled ? "Stopped" : data.ok ? "Completed" : "Ended");
    const meta = [];
    if (Array.isArray(data.steps)) meta.push(`${data.steps.length} step${data.steps.length === 1 ? "" : "s"}`);
    if (Array.isArray(data.applied_changes) && data.applied_changes.length) {
      meta.push(`applied: ${data.applied_changes.join(", ")}`);
    }
    if (data.usage && Number.isFinite(data.usage.eval_count)) {
      meta.push(`${data.usage.eval_count.toLocaleString()} output tokens`);
    }
    if (Number.isFinite(data.elapsed_ms)) meta.push(formatDuration(data.elapsed_ms));
    elements.agentSummaryCard.hidden = false;
    const body = [data.summary || "The agent ended without a summary.", meta.join(" · ")]
      .filter(Boolean)
      .join("\n\n");
    renderMarkdown(elements.agentSummaryText, body);
    if (Array.isArray(data.applied_changes) && data.applied_changes.length) loadTree();
  }

  async function cancelAgent() {
    if (!state.agentRunning || !state.agentRoundId) return;
    elements.cancelAgent.disabled = true;
    const labelEl = elements.cancelAgent.querySelector(".button-label");
    if (labelEl) labelEl.textContent = "Stopping…";
    try {
      await fetch(`/api/council/cancel/${encodeURIComponent(state.agentRoundId)}`, {
        method: "POST",
        credentials: "same-origin",
      });
    } catch (_) {
      /* the stream still delivers agent_cancelled even if this fails */
    }
  }

  // ── Modal Logic ───────────────────────────────────────────────────────────

  function openModal(title, model, text, kicker) {
    elements.modalTitle.textContent = title;
    elements.modalKicker.textContent = kicker;
    elements.modalMeta.textContent = model;
    renderMarkdown(elements.modalText, text || "");
    elements.modal.hidden = false;
  }

  function closeModal() {
    elements.modal.hidden = true;
  }

  function wireEvents() {
    providers.forEach((provider) => {
      elements.enabledInputs[provider].addEventListener("change", () => syncProviderCard(provider));
      syncProviderCard(provider);
    });
    elements.customMode.addEventListener("change", syncCustomMode);
    elements.applyCustomJson.addEventListener("click", applyCustomJson);

    elements.question.addEventListener("input", updateQuestionCount);
    elements.temperature.addEventListener("input", () => {
      elements.temperatureValue.textContent = Number(elements.temperature.value).toFixed(1);
    });
    $$(".idea-chip").forEach((button) => {
      button.addEventListener("click", () => {
        elements.question.value = button.dataset.prompt || "";
        updateQuestionCount();
        elements.question.focus();
      });
    });
    $$(".reveal-secret").forEach((button) => {
      button.addEventListener("click", () => {
        const input = document.getElementById(button.dataset.reveal);
        const showing = input.type === "text";
        input.type = showing ? "password" : "text";
        button.textContent = showing ? "Show" : "Hide";
        button.setAttribute("aria-label", `${showing ? "Show" : "Hide"} API key`);
      });
    });
    elements.ask.addEventListener("click", askCouncil);
    elements.cancel.addEventListener("click", cancelCouncil);
    elements.synthesize.addEventListener("click", synthesizeCouncil);
    elements.copyFinal.addEventListener("click", () => copyText(state.finalAnswer, elements.copyFinal));
    elements.clear.addEventListener("click", clearSession);
    elements.ollamaRefresh.addEventListener("click", refreshOllama);

    // Workspace / code agent listeners
    elements.modeCouncil.addEventListener("click", () => switchMode("council"));
    elements.modeWorkspace.addEventListener("click", () => switchMode("workspace"));
    elements.workspaceRootSelect.addEventListener("change", onRootChange);
    elements.loadTree.addEventListener("click", loadTree);
    elements.runSearch.addEventListener("click", runWorkspaceSearch);
    elements.workspaceSearch.addEventListener("keydown", (event) => {
      if (event.key === "Enter") runWorkspaceSearch();
    });
    elements.runAgent.addEventListener("click", runAgent);
    elements.cancelAgent.addEventListener("click", cancelAgent);

    // Memory event listeners
    if (elements.newSessionBtn) elements.newSessionBtn.addEventListener("click", newSession);
    if (elements.clearMemoryBtn) elements.clearMemoryBtn.addEventListener("click", clearMemory);

    // Expand & Modal Listeners
    if (elements.expandFinal) {
      elements.expandFinal.addEventListener("click", () => {
        openModal(elements.finalTitle.textContent, elements.finalMeta.textContent, state.finalAnswer, "COUNCIL FINDING");
      });
    }
    if (elements.modalClose) elements.modalClose.addEventListener("click", closeModal);
    if (elements.modalCopy) {
      elements.modalCopy.addEventListener("click", () => {
        copyText(elements.modalText.innerText, elements.modalCopy);
      });
    }
    // Close modal if user clicks outside the content box
    if (elements.modal) {
      elements.modal.addEventListener("click", (e) => {
        if (e.target === elements.modal) closeModal();
      });
    }
  }

  // Initialize
  wireEvents();
  updateQuestionCount();
  loadMemoryHistory();
  loadWorkspaceRoots();
})();