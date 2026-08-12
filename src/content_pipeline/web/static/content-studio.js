"use strict";

window.ContentStudio = (() => {
  const STUDIO_FORM_MEMORY_STORAGE_KEY = "ai-popline-studio-form-memory-v1";

  const studio = {
    request: null,
    toast: null,
    featureEnabled: null,
    onTaskCreated: null,
    bootstrap: null,
    drafts: [],
    current: null,
    selectedDraftIds: new Set(),
    pollTimer: null,
    initialized: false,
    loading: false,
  };

  const byId = (id) => document.getElementById(id);

  function readStudioFormMemory() {
    try {
      const stored = localStorage.getItem(STUDIO_FORM_MEMORY_STORAGE_KEY);
      const parsed = stored ? JSON.parse(stored) : {};
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (error) {
      return {};
    }
  }

  function writeStudioFormMemory(memory) {
    try {
      localStorage.setItem(STUDIO_FORM_MEMORY_STORAGE_KEY, JSON.stringify(memory));
    } catch (error) {
      // Studio form memory is optional; the editor works without storage.
    }
  }

  function rememberedVoiceRate() {
    return readStudioFormMemory().voice_rate || "1.0";
  }

  function rememberVoiceRate(value = byId("content-voice-rate").value) {
    const memory = readStudioFormMemory();
    memory.voice_rate = String(value || "1.0");
    writeStudioFormMemory(memory);
  }

  function initialize(dependencies) {
    if (studio.initialized) return;
    studio.initialized = true;
    studio.request = dependencies.request;
    studio.toast = dependencies.toast;
    studio.featureEnabled = dependencies.featureEnabled;
    studio.onTaskCreated = dependencies.onTaskCreated;
    document.querySelectorAll("[data-console-view]").forEach((button) => {
      button.addEventListener("click", () => switchView(button.dataset.consoleView));
    });
    byId("template-cards").addEventListener("click", (event) => {
      const button = event.target.closest("[data-template-id]");
      if (button) startNewDraft(button.dataset.templateId);
    });
    byId("content-template").addEventListener("change", () => applyTemplateAppearance(true));
    byId("save-content-draft").addEventListener("click", () => saveDraft(true));
    byId("refresh-research").addEventListener("click", refreshResearch);
    byId("generate-content-video").addEventListener("click", generateVideo);
    byId("delete-selected-drafts").addEventListener("click", deleteSelectedDrafts);
    byId("content-script").addEventListener("input", () => {
      updateScriptChecks();
      markUnsaved();
    });
    byId("content-title").addEventListener("input", markUnsaved);
    byId("content-focus-assets").addEventListener("input", markUnsaved);
    byId("content-voice-rate").addEventListener("input", () => {
      rememberVoiceRate();
      markUnsaved();
    });
  }

  async function load() {
    if (!studio.request || studio.loading) return;
    studio.loading = true;
    try {
      const [bootstrap, response] = await Promise.all([
        studio.request("/content/bootstrap"),
        studio.request("/content/drafts?limit=30"),
      ]);
      studio.bootstrap = bootstrap;
      studio.drafts = response.drafts || [];
      renderReadiness();
      renderTemplates();
      renderTemplateCards();
      renderDraftList();
      if (studio.current) await selectDraft(studio.current.draft_id, false);
    } catch (error) {
      if (error.status !== 401) {
        byId("studio-status").innerHTML = `<span class="ready-item"><span class="status-dot offline"></span>${escapeHtml(error.message)}</span>`;
      }
    } finally {
      studio.loading = false;
    }
  }

  function switchView(view) {
    const selected = view === "jobs" ? "jobs" : "studio";
    byId("studio-view").hidden = selected !== "studio";
    byId("jobs-view").hidden = selected !== "jobs";
    document.querySelectorAll("[data-console-view]").forEach((button) => {
      const active = button.dataset.consoleView === selected;
      button.classList.toggle("active", active);
      button.setAttribute("aria-current", active ? "page" : "false");
    });
  }

  function renderReadiness() {
    const ready = studio.bootstrap?.ttskill || {};
    byId("studio-status").innerHTML = `
      <span class="ready-item"><span class="status-dot ${ready.available ? "" : "offline"}"></span>ttskill ${ready.available ? "已安装" : "不可用"}</span>
      <span class="ready-divider"></span>
      <span class="ready-item"><span class="status-dot ${ready.authenticated ? "" : "offline"}"></span>${ready.authenticated ? "登录有效" : "需要登录"}</span>
      <span class="ready-divider"></span>
      <span class="ready-item">已安装 ${escapeHtml(String(ready.installed_count || 0))} 个 Skill · 内容工作台仅开放 4 个只读 Skill</span>`;
  }

  function renderTemplates() {
    const select = byId("content-template");
    select.innerHTML = (studio.bootstrap?.templates || []).map((item) =>
      `<option value="${escapeHtml(item.template_id)}">${escapeHtml(item.label)}</option>`
    ).join("");
    applyTemplateAppearance(false);
  }

  function renderTemplateCards() {
    const templates = studio.bootstrap?.templates || [];
    const container = byId("template-cards");
    if (!templates.length) {
      container.innerHTML = `<div class="empty-inline">还没有可用的内容模板。</div>`;
      return;
    }
    container.innerHTML = templates.map((template) => {
      const sourceList = (template.sources || []).slice(0, 4).map((source) =>
        `<span>${escapeHtml(source)}</span>`
      ).join("");
      const chars = template.target_chars || {};
      return `<article class="template-card template-${escapeHtml(template.template_id)}">
        <div class="template-card-top"><span class="template-icon" aria-hidden="true">${templateIcon(template.template_id)}</span><span class="template-number">${escapeHtml(String(templates.indexOf(template) + 1).padStart(2, "0"))}</span></div>
        <div class="template-card-copy">
          <h3>${escapeHtml(template.label)}</h3>
          <p>${escapeHtml(template.description || "创建一份可核对的口播草稿。")}</p>
        </div>
        <div class="template-meta">
          <span>${escapeHtml(String(chars.minimum || 350))}-${escapeHtml(String(chars.maximum || 500))} 字</span>
          ${template.supports_focus_assets ? "<span>支持关注股票</span>" : "<span>无需额外参数</span>"}
        </div>
        <div class="template-sources">${sourceList}</div>
        <button class="button secondary compact" type="button" data-template-id="${escapeHtml(template.template_id)}">${escapeHtml(createDraftLabel(template))}</button>
      </article>`;
    }).join("");
  }

  function startNewDraft(templateId) {
    clearTimeout(studio.pollTimer);
    studio.current = null;
    byId("studio-empty").hidden = true;
    byId("studio-editor").hidden = false;
    byId("content-template").disabled = false;
    byId("content-template").value = templateId || byId("content-template").value || "finance_90s";
    byId("content-focus-assets").value = "";
    byId("content-focus-assets").disabled = false;
    byId("content-script").value = "";
    byId("content-script").disabled = true;
    byId("content-voice-rate").value = rememberedVoiceRate();
    applyTemplateAppearance(true);
    byId("research-grid").innerHTML = `<div class="empty-inline">创建草稿后将自动获取资料并写入口播稿。</div>`;
    byId("research-alert").hidden = true;
    byId("research-updated").textContent = "尚未采集";
    byId("draft-status-badge").className = "badge neutral";
    byId("draft-status-badge").textContent = "新草稿";
    byId("save-content-draft").textContent = createDraftLabel(selectedTemplate());
    byId("generate-content-video").disabled = true;
    byId("refresh-research").disabled = true;
    byId("draft-save-state").textContent = "尚未创建";
    updateScriptChecks();
    byId("content-title").focus();
  }

  function renderDraftList() {
    const list = byId("draft-list");
    studio.selectedDraftIds.forEach((draftId) => {
      if (!studio.drafts.some((draft) => draft.draft_id === draftId)) studio.selectedDraftIds.delete(draftId);
    });
    updateDraftDeleteButton();
    if (!studio.drafts.length) {
      list.innerHTML = `<div class="empty-inline">还没有内容草稿。</div>`;
      return;
    }
    const deleteSupported = studio.featureEnabled?.("content_draft_crud") === true;
    list.innerHTML = studio.drafts.map((draft) => {
      const selected = studio.current?.draft_id === draft.draft_id ? "selected" : "";
      const checked = studio.selectedDraftIds.has(draft.draft_id) ? "checked" : "";
      const counts = draft.source_counts || {};
      return `<div class="draft-list-row ${selected}" data-draft-row="${escapeHtml(draft.draft_id)}">
        <label class="select-cell" title="${deleteSupported ? "选择草稿" : "后端版本较旧，请重启服务"}"><input type="checkbox" data-draft-check="${escapeHtml(draft.draft_id)}" ${checked} ${deleteSupported ? "" : "disabled"}><span class="sr-only">选择 ${escapeHtml(draft.title)}</span></label>
        <button class="draft-list-item" type="button" data-draft-id="${escapeHtml(draft.draft_id)}">
          <span class="draft-list-copy"><strong>${escapeHtml(draft.title)}</strong><small>${escapeHtml(formatDateTime(draft.updated_at))}</small></span>
        </button>
        <div class="draft-row-actions"><span class="draft-source-count">${escapeHtml(String(counts.succeeded || 0))}/${escapeHtml(String(counts.total || 0))}</span><button class="row-delete-button icon-only" type="button" data-delete-draft="${escapeHtml(draft.draft_id)}" title="${deleteSupported ? "删除草稿" : "后端版本较旧，请重启服务"}" aria-label="删除草稿 ${escapeHtml(draft.title)}" ${deleteSupported ? "" : "disabled"}>×</button></div>
      </div>`;
    }).join("");
    list.querySelectorAll("[data-draft-id]").forEach((button) => {
      button.addEventListener("click", () => selectDraft(button.dataset.draftId));
    });
    list.querySelectorAll("[data-draft-check]").forEach((checkbox) => {
      checkbox.addEventListener("click", (event) => event.stopPropagation());
      checkbox.addEventListener("change", () => toggleDraftSelection(checkbox.dataset.draftCheck, checkbox.checked));
    });
    list.querySelectorAll("[data-delete-draft]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        deleteDraft(button.dataset.deleteDraft);
      });
    });
  }

  function toggleDraftSelection(draftId, checked) {
    if (!draftId) return;
    if (checked) studio.selectedDraftIds.add(draftId);
    else studio.selectedDraftIds.delete(draftId);
    updateDraftDeleteButton();
  }

  function updateDraftDeleteButton() {
    const button = byId("delete-selected-drafts");
    if (!button) return;
    const supported = studio.featureEnabled?.("content_draft_bulk_delete") === true;
    const count = studio.selectedDraftIds.size;
    button.disabled = !supported || count === 0;
    button.title = supported ? "" : "后端版本较旧，请重启 AI Popline 服务";
    button.textContent = count ? `删除选中（${count}）` : "删除选中";
  }

  function showDraftEmptyState() {
    studio.current = null;
    byId("studio-empty").hidden = false;
    byId("studio-editor").hidden = true;
    byId("draft-status-badge").className = "badge neutral";
    byId("draft-status-badge").textContent = "等待创建";
  }

  async function deleteDraft(draftId) {
    const draft = studio.drafts.find((item) => item.draft_id === draftId);
    const label = draft?.title || draftId;
    if (!window.confirm(`确定删除内容草稿“${label}”？此操作不能撤销。`)) return;
    const button = byId("draft-list").querySelector(`[data-delete-draft="${draftId}"]`);
    if (button) button.disabled = true;
    try {
      await studio.request(`/content/drafts/${draftId}`, { method: "DELETE" });
      studio.selectedDraftIds.delete(draftId);
      if (studio.current?.draft_id === draftId) showDraftEmptyState();
      await reloadDraftList();
      studio.toast("内容草稿已删除", "success");
    } catch (error) {
      if (button) button.disabled = false;
      studio.toast(error.message, "error");
    }
  }

  async function deleteSelectedDrafts() {
    const draftIds = Array.from(studio.selectedDraftIds);
    if (!draftIds.length) return;
    if (!window.confirm(`确定删除选中的 ${draftIds.length} 个内容草稿？此操作不能撤销。`)) return;
    const button = byId("delete-selected-drafts");
    button.disabled = true;
    try {
      const result = await studio.request("/content/drafts/batch-delete", { method: "POST", body: { draft_ids: draftIds } });
      if (studio.current && (result.deleted || []).includes(studio.current.draft_id)) showDraftEmptyState();
      studio.selectedDraftIds = new Set([...(result.blocked || []), ...(result.failed || [])]);
      await reloadDraftList();
      const blocked = [...(result.blocked || []), ...(result.not_found || []), ...(result.failed || [])].length;
      studio.toast(blocked ? `已删除 ${result.deleted?.length || 0} 个草稿，${blocked} 个未删除` : `已删除 ${result.deleted?.length || 0} 个草稿`, blocked ? "warning" : "success");
    } catch (error) {
      updateDraftDeleteButton();
      studio.toast(error.message, "error");
    }
  }

  async function selectDraft(draftId, showFeedback = true) {
    try {
      const draft = await studio.request(`/content/drafts/${draftId}`);
      studio.current = draft;
      renderDraft();
      renderDraftList();
      if (showFeedback) switchView("studio");
      schedulePoll();
    } catch (error) {
      studio.toast(error.message, "error");
    }
  }

  function renderDraft() {
    const draft = studio.current;
    if (!draft) return;
    byId("studio-empty").hidden = true;
    byId("studio-editor").hidden = false;
    byId("content-template").value = draft.template_id;
    byId("content-template").disabled = true;
    applyTemplateAppearance(false);
    byId("content-title").value = draft.title;
    const template = selectedTemplate();
    byId("studio-editor-kicker").textContent = template?.template_id === "ai_briefing_90s" ? "90-SECOND AI BRIEFING" : "90-SECOND FINANCE";
    byId("studio-editor-title").textContent = template?.label || "资讯口播";
    byId("content-focus-assets").value = (draft.focus_assets || []).join(", ");
    byId("content-focus-assets").disabled = true;
    byId("content-script").value = draft.script || "";
    byId("content-script").disabled = false;
    byId("content-voice-rate").value = rememberedVoiceRate();
    byId("save-content-draft").textContent = "保存口播稿";
    byId("generate-content-video").disabled = draft.status === "collecting";
    byId("refresh-research").disabled = draft.status === "collecting";
    byId("draft-save-state").textContent = `版本 ${draft.revision} · 已保存于 ${formatDateTime(draft.updated_at)}`;
    renderDraftStatus(draft);
    renderResearch(draft);
    updateScriptChecks();
  }

  function renderDraftStatus(draft) {
    const labels = { collecting: "正在采集", ready: "资料就绪", partial: "部分就绪", failed: "采集失败" };
    const classes = { collecting: "running", ready: "succeeded", partial: "partial", failed: "failed" };
    byId("draft-status-badge").className = `badge ${classes[draft.status] || "neutral"}`;
    byId("draft-status-badge").textContent = labels[draft.status] || draft.status;
  }

  function renderResearch(draft) {
    const sources = draft.research || [];
    const fetched = sources.map((item) => item.fetched_at).filter(Boolean).sort().at(-1);
    byId("research-updated").textContent = fetched ? `最近采集 ${formatDateTime(fetched)}` : "等待资料返回";
    byId("research-alert").hidden = !draft.research_error;
    byId("research-alert").textContent = draft.research_error || "";
    byId("research-grid").innerHTML = sources.map((source) => {
      const stateClass = source.status === "succeeded" ? "succeeded" : source.status === "failed" ? "failed" : "running";
      const stateLabel = source.status === "succeeded" ? "已获取" : source.status === "failed" ? "失败" : "采集中";
      const details = source.status === "succeeded"
        ? `<p>${escapeHtml(source.summary || "已获取最新资料")}</p>
           <div class="source-meta">数据时间：${escapeHtml(source.data_as_of || "以来源字段为准")} · 采集：${escapeHtml(formatDateTime(source.fetched_at))}</div>
           <details><summary>查看结构化资料</summary><pre>${escapeHtml(JSON.stringify(source.payload || {}, null, 2))}</pre></details>`
        : source.status === "failed"
          ? `<div class="error-box">${escapeHtml(source.error || "资料获取失败")}</div>`
          : `<div class="skeleton-line"></div>`;
      return `<article class="research-card"><header><div><span class="source-skill">${escapeHtml(source.skill_id)}</span><h4>${escapeHtml(source.label)}</h4></div><span class="badge ${stateClass}">${stateLabel}</span></header>${details}</article>`;
    }).join("");
  }

  function parseFocusAssets() {
    return byId("content-focus-assets").value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean).slice(0, 5);
  }

  async function saveDraft(showFeedback) {
    const title = byId("content-title").value.trim();
    if (!title) {
      studio.toast("请填写视频标题。", "error");
      return null;
    }
    byId("save-content-draft").disabled = true;
    try {
      let draft;
      if (!studio.current) {
        draft = await studio.request("/content/drafts", {
          method: "POST",
          body: {
            template_id: byId("content-template").value || "finance_90s",
            title,
            focus_assets: parseFocusAssets(),
          },
        });
      } else {
        draft = await studio.request(`/content/drafts/${studio.current.draft_id}`, {
          method: "PATCH",
          body: { revision: studio.current.revision, title, script: byId("content-script").value },
        });
      }
      studio.current = draft;
      await reloadDraftList();
      renderDraft();
      schedulePoll();
      if (showFeedback) studio.toast("草稿已保存", "success");
      return draft;
    } catch (error) {
      studio.toast(error.message, "error");
      if (error.status === 409 && studio.current) await selectDraft(studio.current.draft_id, false);
      return null;
    } finally {
      byId("save-content-draft").disabled = false;
    }
  }

  async function refreshResearch() {
    if (!studio.current) return;
    byId("refresh-research").disabled = true;
    try {
      studio.current = await studio.request(`/content/drafts/${studio.current.draft_id}/refresh`, {
        method: "POST",
        body: { revision: studio.current.revision },
      });
      renderDraft();
      schedulePoll();
      studio.toast("正在重新获取资料", "success");
    } catch (error) {
      studio.toast(error.message, "error");
    }
  }

  async function generateVideo() {
    const draft = await saveDraft(false);
    if (!draft) return;
    const voiceRate = parseVoiceRate();
    if (voiceRate === null) {
      studio.toast("朗读速度需要在 0.55–1.2 之间。", "error");
      return;
    }
    rememberVoiceRate(voiceRate);
    const generateButton = byId("generate-content-video");
    const originalLabel = generateButton.textContent;
    generateButton.disabled = true;
    generateButton.textContent = "正在拉取资料并生成视频…";
    try {
      const response = await studio.request(`/content/drafts/${draft.draft_id}/video`, {
        method: "POST",
        body: { revision: draft.revision, dry_run: false, voice_rate: voiceRate },
      });
      studio.toast("视频任务已进入队列，请在任务中心审查后设置发布", "success");
      await studio.onTaskCreated(response.task_id);
    } catch (error) {
      const messages = error.payload?.detail?.errors?.map((item) => item.message).filter(Boolean);
      studio.toast(messages?.[0] || error.message, "error");
      updateScriptChecks();
    } finally {
      generateButton.disabled = false;
      generateButton.textContent = originalLabel;
    }
  }

  async function reloadDraftList() {
    const response = await studio.request("/content/drafts?limit=30");
    studio.drafts = response.drafts || [];
    renderDraftList();
  }

  function schedulePoll() {
    clearTimeout(studio.pollTimer);
    if (!studio.current || studio.current.status !== "collecting") return;
    studio.pollTimer = setTimeout(async () => {
      await selectDraft(studio.current.draft_id, false);
      await reloadDraftList();
    }, 2000);
  }

  function updateScriptChecks() {
    const script = byId("content-script").value.trim();
    const lengthOkay = script.length >= 350 && script.length <= 500;
    const requiresDisclaimer = selectedTemplate()?.requires_finance_disclaimer === true;
    const disclaimerOkay = !requiresDisclaimer || script.includes("不构成投资建议");
    const complete = !["请根据左侧", "待补充", "TODO", "{{", "}}"].some((marker) => script.includes(marker));
    byId("script-counter").textContent = `${script.length} / 350–500`;
    byId("script-counter").classList.toggle("valid", lengthOkay);
    const checks = [
      checkItem(lengthOkay, "字数在 350–500 之间"),
      checkItem(complete, "没有未完成占位内容"),
    ];
    if (requiresDisclaimer) checks.splice(1, 0, checkItem(disclaimerOkay, "包含“不构成投资建议”风险提示"));
    byId("script-checks").innerHTML = checks.join("");
    if (studio.current && studio.current.status !== "collecting") {
      byId("generate-content-video").disabled = !(lengthOkay && disclaimerOkay && complete);
    }
  }

  function parseVoiceRate() {
    const raw = byId("content-voice-rate").value.trim();
    const value = Number(raw || "1.0");
    if (!Number.isFinite(value) || value < 0.55 || value > 1.2) return null;
    return Math.round(value * 100) / 100;
  }

  function selectedTemplate() {
    const templateId = studio.current?.template_id || byId("content-template").value;
    return studio.bootstrap?.templates?.find((item) => item.template_id === templateId) || null;
  }

  function applyTemplateAppearance(resetTitle) {
    const template = selectedTemplate();
    if (!template) return;
    byId("content-focus-field").hidden = !template.supports_focus_assets;
    byId("studio-editor-kicker").textContent = template.template_id === "ai_briefing_90s" ? "90-SECOND AI BRIEFING" : "90-SECOND FINANCE";
    byId("studio-editor-title").textContent = template.label || "资讯口播";
    if (resetTitle) byId("content-title").value = template.default_title || "内容口播";
    byId("content-script").placeholder = template.requires_finance_disclaimer
      ? "系统会根据上方资料自动生成 350–500 字口播初稿，请核对后保留“不构成投资建议”的风险提示。"
      : "系统会根据最新 AI 简报资料自动生成 350–500 字口播初稿，请核对日期、产品名称和事实。";
    byId("save-content-draft").textContent = studio.current ? "保存口播稿" : createDraftLabel(template);
    updateScriptChecks();
  }

  function templateIcon(templateId) {
    if (templateId === "finance_90s") return "¥";
    if (templateId === "ai_briefing_90s") return "AI";
    return "✦";
  }

  function createDraftLabel(template) {
    if (!template) return "创建口播初稿";
    if (template.template_id === "finance_90s") return "创建金融口播初稿";
    if (template.template_id === "ai_briefing_90s") return "创建 AI 简报口播初稿";
    return `创建${template.label}`;
  }

  function checkItem(valid, label) {
    return `<span class="script-check ${valid ? "valid" : ""}">${valid ? "✓" : "○"} ${escapeHtml(label)}</span>`;
  }

  function markUnsaved() {
    if (studio.current) byId("draft-save-state").textContent = "有未保存的修改";
  }

  function formatDateTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(date);
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
    })[character]);
  }

  return { initialize, load, switchView };
})();
