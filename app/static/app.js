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
    ollamaRefresh: $("#refresh-ollama"),
    ollamaStatus: $("#ollama-status"),
    ollamaOptions: $("#ollama-model-options"),
    customMode: $("#custom-mode"),
    customStatus: $("#custom-status"),
    customJson: $("#custom-json"),
    applyCustomJson: $("#apply-custom-json"),
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
  };

  const providers = ["openai", "custom", "anthropic", "ollama"];
  const providerLabels = { openai: "OpenAI", custom: "Azure / custom", anthropic: "Claude", ollama: "Ollama" };

  const state = {
    members: [],
    question: "",
    finalAnswer: "",
    toastTimer: null,
    asking: false,
    synthesizing: false,
    streamSocket: null,
    customHeaders: {},
    customQueryParams: {},
    memberViews: new Map(),
    pendingMemberProviders: new Set(),
    memberRenderFrame: null,
    finalRenderFrame: null,
    // Memory state
    sessionId: getSessionId(),
    currentRoundId: "",
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

  function renderMemoryHistory(rounds) {
    if (!elements.memoryHistory) return;
    if (!rounds.length) {
      elements.memoryHistory.innerHTML = '<p class="muted">No prior conversation.</p>';
      return;
    }
    elements.memoryHistory.innerHTML = rounds
      .map((r) => {
        const synth = r.synthesis
          ? `<div class="memory-synthesis"><strong>${r.synthesis.label}</strong>: ${r.synthesis.answer.slice(0, 150)}${r.synthesis.answer.length > 150 ? "…" : ""}</div>`
          : '<div class="muted" style="margin-top: 0.5rem;">No synthesis yet</div>';
        const ts = new Date(r.timestamp * 1000).toLocaleString();
        return `<details class="memory-round">
          <summary>${ts} — ${r.question.slice(0, 60)}${r.question.length > 60 ? "…" : ""}</summary>
          <div class="memory-round-body">
            <div class="memory-question">${r.question}</div>
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
    // Add this new function to handle Ollama fetches
  async function handleOllamaRpc(socket, message) {
    console.log("✅ Received RPC from FastAPI. Browser is now fetching Ollama directly...");
    const base_url = $("#ollama-base-url").value.trim() || "http://127.0.0.1:11434";
    const payload = {
      model: message.model,
      stream: true,
      think: false,
      messages: message.messages,
      options: message.options,
      keep_alive: message.keep_alive || "5m"
    };

    try {
      const response = await fetch(`${base_url}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        socket.send(JSON.stringify({ rpc: "ollama_error", error: `Ollama HTTP ${response.status}` }));
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let final_usage = {};

      while (true) {
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
      socket.send(JSON.stringify({ 
        rpc: "ollama_error", 
        error: "Cannot reach local Ollama from browser. Is it running? (Check OLLAMA_ORIGINS)" 
      }));
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

        // --- NEW: Intercept RPC requests from the server ---
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
        if (message.type === "round_complete" || message.type === "synthesis_complete") {
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
    return $(`#${provider}-enabled`).checked;
  }

  function buildProviderSettings() {
    const openaiEnabled = isEnabled("openai");
    const anthropicEnabled = isEnabled("anthropic");
    const ollamaEnabled = isEnabled("ollama");
    const customEnabled = isEnabled("custom");
    const customMode = elements.customMode.value;
    const queryParams = { ...state.customQueryParams };
    if (customMode === "azure") {
      const apiVersion = $("#custom-api-version").value.trim();
      if (apiVersion) queryParams["api-version"] = apiVersion;
    }
    return {
      openai: {
        enabled: openaiEnabled,
        model: $("#openai-model").value.trim(),
        api_key: openaiEnabled ? $("#openai-key").value : "",
      },
      anthropic: {
        enabled: anthropicEnabled,
        model: $("#anthropic-model").value.trim(),
        api_key: anthropicEnabled ? $("#anthropic-key").value : "",
      },
      ollama: {
        enabled: ollamaEnabled,
        model: $("#ollama-model").value.trim(),
        base_url: $("#ollama-base-url").value.trim(),
      },
      custom: {
        enabled: customEnabled,
        mode: customMode,
        label: $("#custom-label").value.trim(),
        model: $("#custom-model").value.trim(),
        endpoint: $("#custom-endpoint").value.trim(),
        auth_type: $("#custom-auth-type").value,
        api_key: customEnabled ? $("#custom-key").value : "",
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
    if (typeof config.label === "string") $("#custom-label").value = config.label;
    if (typeof config.model === "string") $("#custom-model").value = config.model;
    if (typeof config.endpoint === "string") $("#custom-endpoint").value = config.endpoint;
    if (typeof config.auth_type === "string") $("#custom-auth-type").value = config.auth_type;
    if (typeof config.api_key === "string") $("#custom-key").value = config.api_key;
    if (config.query_params && typeof config.query_params["api-version"] !== "undefined") {
      $("#custom-api-version").value = String(config.query_params["api-version"]);
    }
    $("#custom-enabled").checked = true;
    syncProviderCard("custom");
    syncCustomMode();
    showToast("Custom provider configuration applied for this tab only.");
  }

  function syncCustomMode() {
    const isAzure = elements.customMode.value === "azure";
    $("#custom-api-version").disabled = !isAzure || !isEnabled("custom");
    $("#custom-api-version").closest("div").classList.toggle("is-visually-muted", !isAzure);
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
  }

  function setSynthesisBusy(busy) {
    state.synthesizing = busy;
    elements.synthesize.disabled = busy || getSelectedMembers().length === 0;
    elements.synthesize.textContent = busy ? "Synthesizing…" : "Synthesize";
  }

  function getSelectedMembers() {
    return state.members.filter((member) => member.status === "complete" && member.included !== false);
  }

  function statusLabel(status) {
    return {
      pending: "Thinking",
      complete: "Ready",
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

  function patchMember(member) {
    // If the model is skipped, hide it from the results area completely
    if (member.status === "skipped") {
      const view = state.memberViews.get(member.provider);
      if (view) view.card.hidden = true;
      return;
    }

    const view = state.memberViews.get(member.provider) || createMemberView(member);
    view.card.hidden = false; // Ensure it's visible if it was previously hidden

    view.card.dataset.provider = member.provider;
    view.card.classList.remove("is-pending", "is-complete", "is-error", "is-skipped");
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

  function renderMembers() {
    state.memberViews.clear();
    elements.memberResults.replaceChildren();
    state.members.forEach(patchMember);
  }

  function scheduleMemberPatch(provider) {
    state.pendingMemberProviders.add(provider);
    if (state.memberRenderFrame !== null) return;
    state.memberRenderFrame = window.requestAnimationFrame(() => {
      const pending = [...state.pendingMemberProviders];
      state.pendingMemberProviders.clear();
      state.memberRenderFrame = null;
      pending.forEach((name) => {
        const member = state.members.find((item) => item.provider === name);
        if (member) patchMember(member);
      });
    });
  }

  function scheduleFinalRender() {
    if (state.finalRenderFrame !== null) return;
    state.finalRenderFrame = window.requestAnimationFrame(() => {
      state.finalRenderFrame = null;
      renderMarkdown(elements.finalText, state.finalAnswer);
    });
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
        if (event.type === "member" || event.type === "member_complete") {
          const member = event.member;
          if (!member || typeof member.provider !== "string") return;
          const index = state.members.findIndex((item) => item.provider === member.provider);
          if (index >= 0) state.members[index] = member;
          else state.members.push(member);
          scheduleMemberPatch(member.provider);
        } else if (event.type === "member_delta") {
          const member = state.members.find((item) => item.provider === event.provider);
          if (!member || typeof event.delta !== "string") return;
          member.text = `${member.text || ""}${event.delta}`;
          scheduleMemberPatch(member.provider);
        }
      });

      state.members = Array.isArray(data.members) ? data.members : [];
      state.members.forEach((member) => {
        if (member.status === "complete") member.included = true;
      });
      state.question = typeof data.question === "string" ? data.question : question;
      state.currentRoundId = data.round_id || ""; // Store round_id for synthesis
      elements.roundTime.textContent = `Round completed in ${formatDuration(data.elapsed_ms)}`;
      renderMembers();
      updateSynthesisControls(true);
      loadMemoryHistory(); // Refresh memory UI

      if (!state.members.some((member) => member.status === "complete")) {
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
    
    const base_url = $("#ollama-base-url").value.trim();
    const isLocal = base_url.includes("127.0.0.1") || base_url.includes("localhost");

    try {
      let data;
      if (isLocal) {
        // Bypass FastAPI and fetch directly from the browser!
        const res = await fetch(`${base_url}/api/tags`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        data = { models: json.models || [] };
      } else {
        // Use FastAPI for remote URLs (like Ngrok)
        data = await request("/api/ollama/models", { base_url: base_url });
      }

      elements.ollamaOptions.replaceChildren();
      const models = Array.isArray(data.models) ? data.models : [];
      const installedModelNames = new Set();
      for (const model of models) {
        if (!model || typeof model.name !== "string") continue;
        installedModelNames.add(model.name);
        const option = document.createElement("option");
        option.value = model.name;
        elements.ollamaOptions.append(option);
      }
      if (!$("#ollama-model").value && models[0] && models[0].name) {
        $("#ollama-model").value = models[0].name;
      }
      const count = models.length;
      const selectedModel = $("#ollama-model").value.trim();
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
    if (state.streamSocket) state.streamSocket.close();
    if (state.memberRenderFrame !== null) window.cancelAnimationFrame(state.memberRenderFrame);
    if (state.finalRenderFrame !== null) window.cancelAnimationFrame(state.finalRenderFrame);
    state.memberRenderFrame = null;
    state.finalRenderFrame = null;
    state.pendingMemberProviders.clear();
    $("#openai-key").value = "";
    $("#anthropic-key").value = "";
    $("#custom-key").value = "";
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
      $(`#${provider}-enabled`).addEventListener("change", () => syncProviderCard(provider));
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
    elements.synthesize.addEventListener("click", synthesizeCouncil);
    elements.copyFinal.addEventListener("click", () => copyText(state.finalAnswer, elements.copyFinal));
    elements.clear.addEventListener("click", clearSession);
    elements.ollamaRefresh.addEventListener("click", refreshOllama);

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
})();