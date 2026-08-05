"use strict";

const THEME_STORAGE_KEY = "ai-popline-theme";

applyTheme(readInitialTheme(), false);

const STATUS_LABELS = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已成功",
  failed: "失败",
  blocked: "已阻止",
  partial: "部分成功",
};

const STEP_LABELS = {
  route: "路由",
  source_scan: "素材",
  image: "图像",
  video: "视频",
  archive: "归档",
  upload: "发布",
  complete: "完成",
};

const EVENT_LABELS = {
  job_created: "任务已创建",
  step_started: "步骤已开始",
  route_resolved: "流水线已确定",
  upload_skipped: "已跳过发布",
  job_finished: "任务已结束",
};

const state = {
  bootstrap: null,
  jobs: [],
  selectedTaskId: null,
  pendingPublish: null,
  pollTimer: null,
  validationResult: null,
  resumeTaskDialog: false,
};

const elements = {};

class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  bindEvents();
  window.ContentStudio?.initialize({
    request: apiRequest,
    toast: showToast,
    onTaskCreated: async (taskId) => {
      window.ContentStudio.switchView("jobs");
      await loadJobs();
      await selectTask(taskId);
    },
  });
  initialize();
});

function cacheElements() {
  const ids = [
    "login-view", "login-form", "admin-token", "toggle-token", "login-error", "login-button",
    "app-shell", "service-chip", "refresh-button", "logout-button", "readiness-strip",
    "stat-all", "stat-running", "stat-succeeded", "stat-attention", "last-updated",
    "status-filter", "pipeline-filter", "job-search", "jobs-body", "jobs-empty",
    "detail-panel", "detail-empty", "detail-content", "create-task-button", "task-dialog",
    "task-form", "pipeline-cards", "task-description", "task-topic", "pipeline-help",
    "dynamic-fields", "publish-toggle", "publish-help", "publish-targets-wrap",
    "publish-targets", "add-target-button", "advanced-params", "validation-badge",
    "validation-messages", "task-json-preview", "validate-task-button", "submit-task-button",
    "publish-dialog", "publish-confirm-input", "cancel-publish-button", "confirm-publish-button",
    "toast-region",
  ];
  ids.forEach((id) => { elements[id] = document.getElementById(id); });
}

function bindEvents() {
  document.querySelectorAll(".theme-toggle").forEach((button) => {
    button.addEventListener("click", toggleTheme);
  });
  updateThemeControls();
  elements["login-form"].addEventListener("submit", handleLogin);
  elements["toggle-token"].addEventListener("click", toggleTokenVisibility);
  elements["logout-button"].addEventListener("click", handleLogout);
  elements["refresh-button"].addEventListener("click", () => refreshWorkspace(true));
  elements["create-task-button"].addEventListener("click", openTaskDialog);
  document.querySelectorAll(".close-dialog").forEach((button) => {
    button.addEventListener("click", () => elements["task-dialog"].close());
  });
  elements["task-dialog"].addEventListener("click", closeDialogFromBackdrop);
  elements["publish-dialog"].addEventListener("click", closeDialogFromBackdrop);
  elements["task-form"].addEventListener("submit", handleTaskSubmit);
  elements["task-form"].addEventListener("input", invalidatePreview);
  elements["validate-task-button"].addEventListener("click", () => preflightTask(true));
  elements["publish-toggle"].addEventListener("change", handlePublishToggle);
  elements["add-target-button"].addEventListener("click", () => addTargetRow());
  elements["status-filter"].addEventListener("change", renderJobs);
  elements["pipeline-filter"].addEventListener("change", renderJobs);
  elements["job-search"].addEventListener("input", renderJobs);
  elements["cancel-publish-button"].addEventListener("click", cancelPublish);
  elements["publish-confirm-input"].addEventListener("input", updatePublishConfirmation);
  elements["confirm-publish-button"].addEventListener("click", confirmPublish);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshWorkspace(false);
  });
}

function readInitialTheme() {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch (error) {
    // Storage can be unavailable in hardened or private browser contexts.
  }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyTheme(theme, persist = true) {
  const resolved = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = resolved;
  updateThemeControls();
  if (!persist) return;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, resolved);
  } catch (error) {
    // The active theme still works for this page when storage is unavailable.
  }
}

function toggleTheme() {
  applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
}

function updateThemeControls() {
  const light = document.documentElement.dataset.theme === "light";
  document.querySelectorAll(".theme-toggle").forEach((button) => {
    const label = light ? "深色模式" : "浅色模式";
    button.setAttribute("aria-label", `切换到${label}`);
    button.setAttribute("title", `切换到${label}`);
    button.setAttribute("aria-pressed", String(light));
    const icon = button.querySelector(".theme-icon");
    const text = button.querySelector(".theme-label");
    if (icon) icon.textContent = light ? "☾" : "☀";
    if (text) text.textContent = label;
  });
}

async function initialize() {
  try {
    await loadBootstrap();
    showApplication();
    await refreshWorkspace(false);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      return;
    }
    showLogin("无法连接服务，请确认服务地址和访问策略。", false);
    setServiceState(false, "连接失败");
  }
}

async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (options.body && typeof options.body !== "string") {
    headers.set("Content-Type", "application/json");
    options.body = JSON.stringify(options.body);
  }
  const method = (options.method || "GET").toUpperCase();
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrf = getCookie("ai_popline_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  let response;
  try {
    response = await fetch(path, { ...options, method, headers, credentials: "same-origin" });
  } catch (error) {
    throw new ApiError("网络连接失败", 0, null);
  }

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = extractErrorMessage(payload, response.status);
    if (response.status === 401 && path !== "/auth/login") showLogin("会话已过期，请重新登录。");
    throw new ApiError(message, response.status, payload);
  }
  return payload;
}

function extractErrorMessage(payload, status) {
  if (payload && typeof payload === "object") {
    if (payload.error?.message) return payload.error.message;
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail?.message) return payload.detail.message;
    if (payload.detail?.code) return payload.detail.code;
  }
  return `请求失败（HTTP ${status}）`;
}

function getCookie(name) {
  const prefix = `${encodeURIComponent(name)}=`;
  const item = document.cookie.split("; ").find((part) => part.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : "";
}

async function loadBootstrap() {
  state.bootstrap = await apiRequest("/ui/bootstrap");
  populateFilters();
  if (!state.resumeTaskDialog) renderPipelineCards();
  setServiceState(true, "服务在线");
}

function showLogin(message = "", focus = true) {
  clearTimeout(state.pollTimer);
  if (elements["task-dialog"].open) {
    state.resumeTaskDialog = true;
    elements["task-dialog"].close();
  }
  if (elements["publish-dialog"].open) elements["publish-dialog"].close();
  elements["app-shell"].hidden = true;
  elements["login-view"].hidden = false;
  elements["login-error"].hidden = !message;
  elements["login-error"].textContent = message;
  if (focus) setTimeout(() => elements["admin-token"].focus(), 50);
}

function showApplication() {
  elements["login-view"].hidden = true;
  elements["app-shell"].hidden = false;
  elements["logout-button"].hidden = !state.bootstrap.auth_required;
  window.ContentStudio?.load();
  if (state.resumeTaskDialog) {
    state.resumeTaskDialog = false;
    elements["task-dialog"].showModal();
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const token = elements["admin-token"].value;
  elements["login-button"].disabled = true;
  elements["login-button"].textContent = "正在验证…";
  elements["login-error"].hidden = true;
  try {
    await apiRequest("/auth/login", { method: "POST", body: { token } });
    elements["admin-token"].value = "";
    await loadBootstrap();
    showApplication();
    await refreshWorkspace(false);
    showToast("登录成功", "success");
  } catch (error) {
    elements["login-error"].textContent = error.message;
    elements["login-error"].hidden = false;
  } finally {
    elements["login-button"].disabled = false;
    elements["login-button"].textContent = "安全登录";
  }
}

function toggleTokenVisibility() {
  const input = elements["admin-token"];
  const visible = input.type === "text";
  input.type = visible ? "password" : "text";
  elements["toggle-token"].textContent = visible ? "显示" : "隐藏";
  elements["toggle-token"].setAttribute("aria-label", visible ? "显示令牌" : "隐藏令牌");
}

async function handleLogout() {
  try {
    await apiRequest("/auth/logout", { method: "POST" });
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    showLogin();
  }
}

function setServiceState(online, text) {
  const dot = elements["service-chip"].querySelector(".status-dot");
  dot.classList.toggle("offline", !online);
  elements["service-chip"].lastElementChild.textContent = text;
}

async function refreshWorkspace(showFeedback) {
  try {
    await Promise.all([loadReadiness(), loadJobs()]);
    if (state.selectedTaskId) await loadTaskDetail(state.selectedTaskId, false);
    setServiceState(true, "服务在线");
    if (showFeedback) showToast("数据已刷新", "success");
  } catch (error) {
    setServiceState(false, "刷新失败");
    if (!(error instanceof ApiError && error.status === 401)) showToast(error.message, "error");
  } finally {
    schedulePolling();
  }
}

async function loadReadiness() {
  const ready = await apiRequest("/ready");
  const dataReady = ready.data_dir_available;
  const profilesReady = ready.profiles_available;
  elements["readiness-strip"].innerHTML = `
    <span class="ready-item"><span class="status-dot ${dataReady ? "" : "offline"}"></span>任务存储 ${dataReady ? "可用" : "不可用"}</span>
    <span class="ready-divider"></span>
    <span class="ready-item"><span class="status-dot ${profilesReady ? "" : "offline"}"></span>内容配置 ${profilesReady ? "可用" : "不可用"}</span>
    <span class="ready-divider"></span>
    <span class="ready-item">发布控制 ${state.bootstrap.publish_enabled ? "已启用" : "安全关闭"}</span>`;
}

async function loadJobs() {
  const response = await apiRequest("/jobs?limit=100");
  state.jobs = response.jobs || [];
  renderStats();
  renderJobs();
  elements["last-updated"].textContent = `更新于 ${new Intl.DateTimeFormat("zh-CN", { timeStyle: "short" }).format(new Date())}`;
}

function populateFilters() {
  elements["status-filter"].innerHTML = `<option value="">全部状态</option>${state.bootstrap.statuses
    .map((status) => `<option value="${escapeHtml(status)}">${escapeHtml(STATUS_LABELS[status] || status)}</option>`).join("")}`;
  elements["pipeline-filter"].innerHTML = `<option value="">全部流水线</option>${state.bootstrap.pipelines
    .map((pipeline) => `<option value="${escapeHtml(pipeline.content_type)}">${escapeHtml(pipeline.label)}</option>`).join("")}`;
}

function renderStats() {
  const running = state.jobs.filter((job) => ["queued", "running"].includes(job.status)).length;
  const succeeded = state.jobs.filter((job) => ["succeeded", "partial"].includes(job.status)).length;
  const attention = state.jobs.filter((job) => ["failed", "blocked"].includes(job.status)).length;
  elements["stat-all"].textContent = state.jobs.length;
  elements["stat-running"].textContent = running;
  elements["stat-succeeded"].textContent = succeeded;
  elements["stat-attention"].textContent = attention;
}

function filteredJobs() {
  const status = elements["status-filter"].value;
  const pipeline = elements["pipeline-filter"].value;
  const query = elements["job-search"].value.trim().toLowerCase();
  return state.jobs.filter((job) => {
    const contentType = job.route?.content_type || job.task?.content_type || "";
    const text = `${job.task_id} ${job.task?.description || ""}`.toLowerCase();
    return (!status || job.status === status) && (!pipeline || contentType === pipeline) && (!query || text.includes(query));
  });
}

function renderJobs() {
  const jobs = filteredJobs();
  elements["jobs-empty"].hidden = jobs.length > 0;
  elements["jobs-body"].innerHTML = jobs.map((job) => {
    const contentType = job.route?.content_type || job.task?.content_type || "unknown";
    const pipeline = pipelineByType(contentType);
    const selected = job.task_id === state.selectedTaskId ? "selected" : "";
    return `<tr class="${selected}" data-task-id="${escapeHtml(job.task_id)}" tabindex="0" aria-label="查看任务 ${escapeHtml(job.task?.description || job.task_id)}">
      <td><span class="job-title">${escapeHtml(job.task?.description || "未命名任务")}</span><span class="job-id">${escapeHtml(job.task_id.slice(0, 12))}</span></td>
      <td><span class="pipeline-label">${escapeHtml(pipeline?.label || contentType)}</span></td>
      <td>${statusBadge(job.status)}</td>
      <td>${escapeHtml(formatRelativeTime(job.updated_at || job.created_at))}</td>
      <td class="row-arrow">›</td>
    </tr>`;
  }).join("");
  elements["jobs-body"].querySelectorAll("tr").forEach((row) => {
    const select = () => selectTask(row.dataset.taskId);
    row.addEventListener("click", select);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select();
      }
    });
  });
}

async function selectTask(taskId) {
  state.selectedTaskId = taskId;
  renderJobs();
  await loadTaskDetail(taskId, true);
}

async function loadTaskDetail(taskId, showLoading) {
  if (showLoading) {
    elements["detail-empty"].hidden = true;
    elements["detail-content"].hidden = false;
    elements["detail-content"].innerHTML = `<div class="detail-content"><div class="skeleton-line"></div></div>`;
  }
  try {
    const [snapshot, eventResponse, artifactResponse] = await Promise.all([
      apiRequest(`/status/${taskId}`),
      apiRequest(`/jobs/${taskId}/events?limit=100`),
      apiRequest(`/jobs/${taskId}/artifacts`),
    ]);
    if (state.selectedTaskId !== taskId) return;
    renderTaskDetail(snapshot, eventResponse.events || [], artifactResponse.artifacts || []);
  } catch (error) {
    if (state.selectedTaskId !== taskId) return;
    elements["detail-content"].innerHTML = `<div class="detail-content"><div class="error-box">${escapeHtml(error.message)}</div></div>`;
  }
}

function renderTaskDetail(snapshot, events, artifacts) {
  const contentType = snapshot.route?.content_type || snapshot.task?.content_type || "unknown";
  const pipeline = pipelineByType(contentType);
  const steps = state.bootstrap.steps || Object.keys(STEP_LABELS);
  const currentIndex = steps.indexOf(snapshot.current_step);
  const terminal = ["succeeded", "partial"].includes(snapshot.status);
  const stepMarkup = steps.map((step, index) => {
    const className = terminal || index < currentIndex ? "done" : index === currentIndex ? "current" : "";
    return `<span class="step ${className}">${escapeHtml(STEP_LABELS[step] || step)}</span>`;
  }).join("");
  const eventMarkup = events.length ? events.slice().reverse().map((event) => `
    <div class="timeline-item"><span class="timeline-dot"></span><div class="timeline-copy">
      <strong>${escapeHtml(EVENT_LABELS[event.event] || event.event)}</strong>
      <time>${escapeHtml(formatDateTime(event.timestamp))}</time>
    </div></div>`).join("") : `<p class="muted">暂无事件记录。</p>`;
  const artifactMarkup = renderArtifacts(artifacts);
  const validation = snapshot.artifacts?.validation || {};
  const publishResults = snapshot.artifacts?.publish_results || {};

  elements["detail-empty"].hidden = true;
  elements["detail-content"].hidden = false;
  elements["detail-content"].className = "detail-content";
  elements["detail-content"].innerHTML = `
    <div class="detail-head"><div><p class="eyebrow">${escapeHtml(pipeline?.label || contentType)}</p><h2>${escapeHtml(snapshot.task?.description || "未命名任务")}</h2><p>${escapeHtml(snapshot.task_id)}</p></div>${statusBadge(snapshot.status)}</div>
    <div class="step-track" aria-label="任务步骤">${stepMarkup}</div>
    ${snapshot.error ? `<div class="error-box">${escapeHtml(snapshot.error)}</div>` : ""}
    <section class="detail-section"><h3>运行信息</h3><div class="meta-grid">
      ${metaItem("当前步骤", STEP_LABELS[snapshot.current_step] || snapshot.current_step || "等待中")}
      ${metaItem("发布模式", snapshot.task?.publish ? "生成并发布" : "仅本地生成")}
      ${metaItem("开始时间", formatDateTime(snapshot.started_at || snapshot.created_at))}
      ${metaItem("结束时间", snapshot.finished_at ? formatDateTime(snapshot.finished_at) : "尚未结束")}
    </div></section>
    <section class="detail-section"><h3>验证结果</h3>${renderObjectSummary(validation, "暂无媒体验证数据。")}</section>
    ${Object.keys(publishResults).length ? `<section class="detail-section"><h3>发布结果</h3>${renderObjectSummary(publishResults, "暂无发布结果。")}</section>` : ""}
    <section class="detail-section"><h3>安全产物 · ${artifacts.length}</h3>${artifactMarkup}</section>
    <section class="detail-section"><h3>事件时间线</h3><div class="timeline">${eventMarkup}</div></section>
    <section class="detail-section"><details class="raw-details"><summary>查看原始任务快照</summary><pre>${escapeHtml(JSON.stringify(snapshot, null, 2))}</pre></details></section>`;
}

function renderObjectSummary(value, emptyText) {
  if (!value || Object.keys(value).length === 0) return `<p class="muted">${escapeHtml(emptyText)}</p>`;
  return `<pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
}

function renderArtifacts(artifacts) {
  if (!artifacts.length) return `<p class="muted">当前没有可预览的任务内产物。</p>`;
  return `<div class="artifact-grid">${artifacts.map((artifact) => {
    const url = escapeHtml(artifact.url);
    const name = escapeHtml(artifact.name);
    let preview = `<span aria-hidden="true">FILE</span>`;
    if (artifact.media_type.startsWith("image/")) preview = `<img src="${url}" alt="${name}" loading="lazy">`;
    if (artifact.media_type.startsWith("video/")) preview = `<video src="${url}" controls preload="metadata" aria-label="${name}"></video>`;
    return `<a class="artifact-card" href="${url}" target="_blank" rel="noopener">
      <div class="artifact-preview">${preview}</div><div class="artifact-info"><strong>${name}</strong><small>${escapeHtml(formatBytes(artifact.size))} · ${escapeHtml(artifact.media_type)}</small></div>
    </a>`;
  }).join("")}</div>`;
}

function schedulePolling() {
  clearTimeout(state.pollTimer);
  if (document.hidden || !state.bootstrap || elements["app-shell"].hidden) return;
  const hasActiveJobs = state.jobs.some((job) => ["queued", "running"].includes(job.status));
  const delay = hasActiveJobs ? state.bootstrap.active_refresh_ms : state.bootstrap.idle_refresh_ms;
  state.pollTimer = setTimeout(() => refreshWorkspace(false), delay);
}

function renderPipelineCards() {
  elements["pipeline-cards"].innerHTML = state.bootstrap.pipelines.map((pipeline, index) => `
    <button class="pipeline-card ${index === 0 ? "selected" : ""}" type="button" role="radio" aria-checked="${index === 0}" data-content-type="${escapeHtml(pipeline.content_type)}">
      <span class="pipeline-icon" aria-hidden="true">${escapeHtml(pipeline.icon)}</span><span><strong>${escapeHtml(pipeline.label)}</strong><small>${escapeHtml(pipeline.external_tools.join(" + ") || "本地处理")}</small></span>
    </button>`).join("");
  elements["pipeline-cards"].querySelectorAll(".pipeline-card").forEach((card) => {
    card.addEventListener("click", () => selectPipeline(card.dataset.contentType));
  });
  if (state.bootstrap.pipelines.length) selectPipeline(state.bootstrap.pipelines[0].content_type);
}

function selectPipeline(contentType) {
  elements["pipeline-cards"].querySelectorAll(".pipeline-card").forEach((card) => {
    const selected = card.dataset.contentType === contentType;
    card.classList.toggle("selected", selected);
    card.setAttribute("aria-checked", String(selected));
  });
  const pipeline = pipelineByType(contentType);
  renderDynamicFields(pipeline);
  elements["pipeline-help"].textContent = pipeline?.description || "填写流水线参数。";
  configurePublishing(pipeline);
  invalidatePreview();
}

function selectedPipeline() {
  return elements["pipeline-cards"].querySelector(".pipeline-card.selected")?.dataset.contentType || "";
}

function pipelineByType(contentType) {
  return state.bootstrap?.pipelines.find((item) => item.content_type === contentType);
}

function renderDynamicFields(pipeline) {
  if (!pipeline) {
    elements["dynamic-fields"].innerHTML = "";
    return;
  }
  elements["dynamic-fields"].innerHTML = pipeline.fields.map((field) => renderField(field)).join("");
}

function renderField(field) {
  const id = `param-${field.name}`;
  const required = field.required ? "required" : "";
  const requiredLabel = field.required ? `<span class="required">*</span>` : "";
  const help = field.help ? `<small>${escapeHtml(field.help)}</small>` : "";
  const value = Array.isArray(field.default) ? field.default.join(", ") : field.default ?? "";
  if (field.type === "checkbox") {
    return `<div class="checkbox-field"><input id="${id}" data-param-name="${escapeHtml(field.name)}" data-param-type="checkbox" type="checkbox" ${field.default ? "checked" : ""}><label for="${id}">${escapeHtml(field.label)}${requiredLabel}</label></div>`;
  }
  if (field.type === "select") {
    const options = field.options.map((option) => `<option value="${escapeHtml(option.value)}" ${option.value === field.default ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("");
    return `<label class="field">${escapeHtml(field.label)}${requiredLabel}<select id="${id}" data-param-name="${escapeHtml(field.name)}" data-param-type="select" ${required}>${options}</select>${help}</label>`;
  }
  if (field.type === "textarea") {
    return `<label class="field span-two">${escapeHtml(field.label)}${requiredLabel}<textarea id="${id}" data-param-name="${escapeHtml(field.name)}" data-param-type="textarea" rows="${field.rows || 4}" placeholder="${escapeHtml(field.placeholder || "")}" ${required}>${escapeHtml(String(value))}</textarea>${help}</label>`;
  }
  const htmlType = field.type === "number" ? "number" : field.type === "url" ? "url" : "text";
  const constraints = `${field.minimum !== null ? `min="${field.minimum}"` : ""} ${field.maximum !== null ? `max="${field.maximum}"` : ""}`;
  return `<label class="field">${escapeHtml(field.label)}${requiredLabel}<input id="${id}" data-param-name="${escapeHtml(field.name)}" data-param-type="${escapeHtml(field.type)}" type="${htmlType}" value="${escapeHtml(String(value))}" placeholder="${escapeHtml(field.placeholder || "")}" ${constraints} ${required}>${help}</label>`;
}

function configurePublishing(pipeline) {
  const available = Boolean(state.bootstrap.publish_enabled && pipeline?.publish_targets.length);
  elements["publish-toggle"].disabled = !available;
  elements["publish-toggle"].checked = false;
  elements["publish-targets-wrap"].hidden = true;
  elements["publish-targets"].innerHTML = "";
  elements["publish-help"].textContent = available
    ? `支持 ${pipeline.publish_targets.join("、")}；开启后需要二次确认。`
    : state.bootstrap.publish_enabled ? "该流水线不支持发布。" : "服务端 Web 发布当前安全关闭。";
}

function handlePublishToggle() {
  const enabled = elements["publish-toggle"].checked;
  elements["publish-targets-wrap"].hidden = !enabled;
  if (enabled && !elements["publish-targets"].children.length) addTargetRow();
  invalidatePreview();
}

function addTargetRow(target = {}) {
  const pipeline = pipelineByType(selectedPipeline());
  const platforms = pipeline?.publish_targets || [];
  if (!platforms.length) return;
  const row = document.createElement("div");
  row.className = "target-row";
  row.innerHTML = `
    <label class="field">平台<select class="target-platform">${platforms.map((platform) => `<option value="${escapeHtml(platform)}" ${platform === target.platform ? "selected" : ""}>${escapeHtml(platform)}</option>`).join("")}</select></label>
    <label class="field">账号<input class="target-account" value="${escapeHtml(target.account || "")}" required></label>
    <label class="field target-tid-wrap">分区 tid<input class="target-tid" type="number" min="1" value="${escapeHtml(target.tid || "")}"></label>
    <button class="icon-button remove-target" type="button" aria-label="删除发布目标">×</button>`;
  const platform = row.querySelector(".target-platform");
  const updateTid = () => { row.querySelector(".target-tid-wrap").hidden = platform.value !== "bilibili"; };
  platform.addEventListener("change", () => { updateTid(); invalidatePreview(); });
  row.querySelector(".remove-target").addEventListener("click", () => { row.remove(); invalidatePreview(); });
  row.querySelectorAll("input").forEach((input) => input.addEventListener("input", invalidatePreview));
  updateTid();
  elements["publish-targets"].appendChild(row);
}

function openTaskDialog() {
  elements["task-form"].reset();
  elements["advanced-params"].value = "{}";
  elements["publish-targets"].innerHTML = "";
  state.validationResult = null;
  const first = state.bootstrap.pipelines[0];
  if (first) selectPipeline(first.content_type);
  updateTaskPreview();
  elements["task-dialog"].showModal();
  setTimeout(() => elements["task-description"].focus(), 50);
}

function closeDialogFromBackdrop(event) {
  if (event.target === event.currentTarget) event.currentTarget.close();
}

function collectTask(checkValidity = true) {
  if (checkValidity && !elements["task-form"].reportValidity()) throw new Error("请先填写所有必填字段。");
  const params = {};
  elements["dynamic-fields"].querySelectorAll("[data-param-name]").forEach((input) => {
    const name = input.dataset.paramName;
    const type = input.dataset.paramType;
    if (type === "checkbox") {
      params[name] = input.checked;
      return;
    }
    const raw = input.value.trim();
    if (!raw) return;
    if (type === "number") params[name] = Number(raw);
    else if (type === "tags") params[name] = raw.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
    else params[name] = raw;
  });

  let advanced;
  try {
    advanced = JSON.parse(elements["advanced-params"].value || "{}");
  } catch (error) {
    throw new Error("高级参数不是有效的 JSON。");
  }
  if (!advanced || Array.isArray(advanced) || typeof advanced !== "object") throw new Error("高级参数必须是 JSON 对象。");

  const publish = elements["publish-toggle"].checked;
  const publishTargets = publish ? [...elements["publish-targets"].querySelectorAll(".target-row")].map((row) => {
    const platform = row.querySelector(".target-platform").value;
    const account = row.querySelector(".target-account").value.trim();
    const tidValue = row.querySelector(".target-tid").value;
    if (!account) throw new Error("每个发布目标都必须填写账号。");
    const target = { platform, account };
    if (platform === "bilibili") {
      if (!tidValue) throw new Error("Bilibili 发布目标必须填写分区 tid。");
      target.tid = Number(tidValue);
    }
    return target;
  }) : [];

  return {
    description: elements["task-description"].value.trim(),
    content_type: selectedPipeline(),
    topic: elements["task-topic"].value.trim() || null,
    publish,
    publish_targets: publishTargets,
    params: { ...params, ...advanced },
  };
}

function invalidatePreview() {
  state.validationResult = null;
  elements["validation-badge"].className = "badge neutral";
  elements["validation-badge"].textContent = "尚未预检";
  elements["validation-messages"].innerHTML = "";
  updateTaskPreview();
}

function updateTaskPreview() {
  try {
    const task = collectTaskWithoutValidity();
    elements["task-json-preview"].textContent = JSON.stringify(task, null, 2);
  } catch (error) {
    elements["task-json-preview"].textContent = `// ${error.message}`;
  }
}

function collectTaskWithoutValidity() {
  return collectTask(false);
}

async function preflightTask(showFeedback) {
  let task;
  try {
    task = collectTask();
  } catch (error) {
    setValidation(false, [error.message]);
    if (showFeedback) showToast(error.message, "error");
    return null;
  }
  elements["validate-task-button"].disabled = true;
  elements["validate-task-button"].textContent = "正在预检…";
  try {
    const result = await apiRequest("/validate-task", { method: "POST", body: task });
    state.validationResult = result;
    elements["task-json-preview"].textContent = JSON.stringify(result.task, null, 2);
    setValidation(true, result.warnings || []);
    if (showFeedback) showToast("任务预检通过", "success");
    return result;
  } catch (error) {
    const errors = error.payload?.detail?.errors?.map((item) => `${item.field || "参数"}：${item.message}`) || [error.message];
    setValidation(false, errors);
    if (showFeedback) showToast("任务预检未通过", "error");
    return null;
  } finally {
    elements["validate-task-button"].disabled = false;
    elements["validate-task-button"].textContent = "预检任务";
  }
}

function setValidation(valid, messages) {
  elements["validation-badge"].className = `badge ${valid ? "succeeded" : "invalid"}`;
  elements["validation-badge"].textContent = valid ? "预检通过" : "需要修正";
  elements["validation-messages"].innerHTML = messages.map((message) => `<div class="validation-message ${valid ? "warning" : "error"}">${escapeHtml(message)}</div>`).join("");
}

async function handleTaskSubmit(event) {
  event.preventDefault();
  const result = await preflightTask(false);
  if (!result) return;
  if (result.task.publish) {
    state.pendingPublish = result;
    elements["publish-confirm-input"].value = "";
    elements["confirm-publish-button"].disabled = true;
    elements["publish-dialog"].showModal();
    setTimeout(() => elements["publish-confirm-input"].focus(), 50);
    return;
  }
  await submitValidatedTask(result);
}

function updatePublishConfirmation() {
  elements["confirm-publish-button"].disabled = elements["publish-confirm-input"].value.trim() !== "确认发布";
}

function cancelPublish() {
  state.pendingPublish = null;
  elements["publish-dialog"].close();
}

async function confirmPublish() {
  if (!state.pendingPublish || elements["publish-confirm-input"].value.trim() !== "确认发布") return;
  const result = state.pendingPublish;
  state.pendingPublish = null;
  elements["publish-dialog"].close();
  await submitValidatedTask(result, `PUBLISH:${result.task_fingerprint}`);
}

async function submitValidatedTask(result, confirmation = "") {
  elements["submit-task-button"].disabled = true;
  elements["submit-task-button"].textContent = "正在提交…";
  try {
    const headers = confirmation ? { "X-AI-Popline-Publish-Confirmation": confirmation } : {};
    const response = await apiRequest("/run", { method: "POST", headers, body: result.task });
    elements["task-dialog"].close();
    showToast("任务已进入队列", "success");
    await loadJobs();
    await selectTask(response.task_id);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    elements["submit-task-button"].disabled = false;
    elements["submit-task-button"].textContent = "开始运行";
  }
}

function statusBadge(status) {
  return `<span class="badge ${escapeHtml(status || "neutral")}">${escapeHtml(STATUS_LABELS[status] || status || "未知")}</span>`;
}

function metaItem(label, value) {
  return `<div class="meta-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value ?? "—"))}</strong></div>`;
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "medium" }).format(date);
}

function formatRelativeTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  if (Number.isNaN(seconds)) return value;
  const formatter = new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" });
  if (Math.abs(seconds) < 60) return formatter.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
  return formatter.format(Math.round(hours / 24), "day");
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && value >= 1024; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${unit}`;
}

function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  elements["toast-region"].appendChild(toast);
  setTimeout(() => toast.remove(), 4200);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
