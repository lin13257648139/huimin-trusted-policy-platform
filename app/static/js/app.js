const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  currentView: "overview",
  screeningId: null,
  screeningToken: null,
  selectedFiles: [],
  guidanceField: null,
  guidanceTimer: null,
  skippedGuidanceFields: [],
  adminToken: sessionStorage.getItem("huimin-admin-token") || "",
  compiledPolicyCandidate: null,
  metadata: null,
  readiness: null,
  careMode: false,
  speechActive: false,
};

const icons = {
  grid: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>',
  spark: '<svg viewBox="0 0 24 24"><path d="m12 3-1.3 4.2a5 5 0 0 1-3.3 3.3L3 12l4.4 1.5a5 5 0 0 1 3.2 3.2L12 21l1.4-4.3a5 5 0 0 1 3.2-3.2L21 12l-4.4-1.5a5 5 0 0 1-3.3-3.3L12 3Z"/></svg>',
  scan: '<svg viewBox="0 0 24 24"><path d="M3 8V5a2 2 0 0 1 2-2h3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3"/><path d="M7 12h10"/></svg>',
  book: '<svg viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4H6.5A2.5 2.5 0 0 0 4 6.5v13Z"/><path d="M4 6.5A2.5 2.5 0 0 1 6.5 9H20"/></svg>',
  shield: '<svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/></svg>',
  "shield-check": '<svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></svg>',
  menu: '<svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h16"/></svg>',
  type: '<svg viewBox="0 0 24 24"><path d="M4 7V4h16v3M9 20h6M12 4v16"/></svg>',
  volume: '<svg viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M15 9a4 4 0 0 1 0 6M18 6a8 8 0 0 1 0 12"/></svg>',
  arrow: '<svg viewBox="0 0 24 24"><path d="M5 12h14m-6-6 6 6-6 6"/></svg>',
  brain: '<svg viewBox="0 0 24 24"><path d="M9.5 4.5A3 3 0 0 0 6 7.4 3.5 3.5 0 0 0 5 14a3 3 0 0 0 4.5 3.8V5Z"/><path d="M14.5 4.5A3 3 0 0 1 18 7.4a3.5 3.5 0 0 1 1 6.6 3 3 0 0 1-4.5 3.8V5ZM9.5 9H7m7.5 3H17M9.5 15H7m7.5-7H17"/></svg>',
  clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  branch: '<svg viewBox="0 0 24 24"><circle cx="6" cy="5" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="18" cy="18" r="2"/><path d="M6 7v5a6 6 0 0 0 6 6h4M8 6h8"/></svg>',
  quote: '<svg viewBox="0 0 24 24"><path d="M9 11H5a4 4 0 0 1 4-4v8H5M19 11h-4a4 4 0 0 1 4-4v8h-4"/></svg>',
  lock: '<svg viewBox="0 0 24 24"><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>',
  database: '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/></svg>',
  layers: '<svg viewBox="0 0 24 24"><path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 17l9 5 9-5"/></svg>',
  alert: '<svg viewBox="0 0 24 24"><path d="M10.3 3.4 2.2 18a2 2 0 0 0 1.8 3h16a2 2 0 0 0 1.8-3L13.7 3.4a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4m0 4h.01"/></svg>',
  map: '<svg viewBox="0 0 24 24"><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3V6Z"/><path d="M9 3v15m6-12v15"/></svg>',
  message: '<svg viewBox="0 0 24 24"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v8Z"/><path d="M8 9h8M8 13h5"/></svg>',
  chevron: '<svg viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg>',
  eye: '<svg viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>',
  heart: '<svg viewBox="0 0 24 24"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8Z"/></svg>',
  wand: '<svg viewBox="0 0 24 24"><path d="m15 4 5 5L7 22l-5-5L15 4Z"/><path d="m6 15 5 5M19 2v3M22 5h-3M6 2v2M8 4H4"/></svg>',
  users: '<svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/></svg>',
  receipt: '<svg viewBox="0 0 24 24"><path d="M6 2h12v20l-3-2-3 2-3-2-3 2V2Z"/><path d="M9 7h6M9 11h6M9 15h4"/></svg>',
  info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8h.01"/></svg>',
  phone: '<svg viewBox="0 0 24 24"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.7 19.7 0 0 1-8.6-3.1 19.3 19.3 0 0 1-6-6A19.7 19.7 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.8 2.1Z"/></svg>',
  print: '<svg viewBox="0 0 24 24"><path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 14h12v8H6z"/></svg>',
  upload: '<svg viewBox="0 0 24 24"><path d="M12 16V4m-5 5 5-5 5 5M5 20h14"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18"/></svg>',
  help: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.8 9a2.4 2.4 0 1 1 4 1.8c-1.2.8-1.8 1.3-1.8 2.7M12 17h.01"/></svg>',
};

function injectIcons(root = document) {
  $$('[data-icon]', root).forEach((element) => {
    const name = element.dataset.icon;
    if (icons[name]) element.innerHTML = icons[name];
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (path.startsWith("/api/v1/admin") && state.adminToken) {
    headers.set("X-Admin-Token", state.adminToken);
  }
  const response = await fetch(path, { ...options, headers });
  let body;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) {
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join("；")
      : detail || `请求失败（${response.status}）`;
    throw new Error(message);
  }
  return body;
}

function toast(message, kind = "success") {
  const item = document.createElement("div");
  item.className = `toast ${kind === "error" ? "error" : ""}`;
  item.textContent = message;
  $("#toast-region").append(item);
  setTimeout(() => item.remove(), 3600);
}

function loading(show, text = "正在执行可信推理…") {
  $("#loading-text").textContent = text;
  $("#loading-overlay").classList.toggle("hidden", !show);
}

const pageInfo = {
  overview: ["可信民生 AI", "项目总览"],
  screening: ["INTELLIGENT GUIDANCE", "智能预筛"],
  documents: ["DOCUMENT ASSURANCE", "材料预检"],
  evidence: ["TRACEABLE POLICY", "政策证据"],
  worker: ["WORKER PROTOTYPE", "工作人员模式"],
  demo: ["JURY DEMONSTRATION", "评委演示中心"],
  admin: ["TRUST & GOVERNANCE", "可信治理"],
};

function navigate(view) {
  if (!pageInfo[view]) view = "overview";
  state.currentView = view;
  state.currentView = view;
  $$("[data-view]").forEach((section) => section.classList.toggle("active", section.dataset.view === view));
  $$("[data-nav]").forEach((item) => item.classList.toggle("active", item.dataset.nav === view));
  $("#page-eyebrow").textContent = pageInfo[view][0];
  $("#page-title").textContent = pageInfo[view][1];
  $(".sidebar").classList.remove("open");
  $("#mobile-menu").setAttribute("aria-expanded", "false");
  if (location.hash !== `#${view}`) history.replaceState(null, "", `#${view}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (view === "evidence") loadSources();
  if (view === "admin") loadAdmin();
}

function setupNavigation() {
  $$('[data-nav], [data-go]').forEach((element) => {
    element.addEventListener("click", (event) => {
      event.preventDefault();
      navigate(element.dataset.nav || element.dataset.go);
    });
  });
  $("#mobile-menu").addEventListener("click", () => {
    const open = $(".sidebar").classList.toggle("open");
    $("#mobile-menu").setAttribute("aria-expanded", String(open));
  });
  window.addEventListener("hashchange", () => navigate(location.hash.slice(1)));
  navigate(location.hash.slice(1) || "overview");
}

function valueOrNull(id) {
  const value = $(`#${id}`).value.trim();
  return value === "" ? null : value;
}

function boolOrNull(id) {
  const value = valueOrNull(id);
  return value === null ? null : value === "true";
}

function numberOrNull(id) {
  const value = valueOrNull(id);
  return value === null ? null : Number(value);
}

function setField(id, value) {
  const element = $(`#${id}`);
  if (!element || value === undefined || value === null) return;
  if (element.type === "checkbox") element.checked = Boolean(value);
  else element.value = String(value);
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function todayISO() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function setupForm() {
  setField("query_date", todayISO());
  const controls = $$("#screening-form input, #screening-form select");
  controls.forEach((control) => control.addEventListener("input", () => { state.skippedGuidanceFields = state.skippedGuidanceFields.filter((item) => item !== control.id); updateCompletion(); scheduleGuidance(); }));
  controls.forEach((control) => control.addEventListener("change", () => { state.skippedGuidanceFields = state.skippedGuidanceFields.filter((item) => item !== control.id); updateCompletion(); scheduleGuidance(); }));

  $("#urgent_event").addEventListener("change", (event) => {
    setUrgentFieldsEnabled(event.target.value === "true");
    updateCompletion();
  });
  $("#is_local_hukou").addEventListener("change", updateResidenceField);

  ["medical_expenses_12m", "education_expenses_12m"].forEach((id) => {
    $(`#${id}`).addEventListener("input", () => {
      const medical = numberOrNull("medical_expenses_12m") || 0;
      const education = numberOrNull("education_expenses_12m") || 0;
      if (medical || education) setField("rigid_expenses_12m", medical + education);
    });
  });

  $("#parse-narrative").addEventListener("click", parseNarrative);
  $("#focus-guidance-field").addEventListener("click", focusGuidanceField);
  $("#skip-guidance-field").addEventListener("click", skipGuidanceField);
  $("#load-demo").addEventListener("click", loadDemo);
  $("#screening-form").addEventListener("submit", submitScreening);
  $("#print-report").addEventListener("click", () => window.print());
  $("#new-screening").addEventListener("click", () => {
    $("#results-zone").classList.add("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  $("#feedback-card").addEventListener("click", submitFeedback);
  $("#send-feedback").addEventListener("click", sendDetailedFeedback);
  $("#delete-screening").addEventListener("click", deleteCurrentScreening);
  setUrgentFieldsEnabled(false);
  updateCompletion();
  scheduleGuidance();
}

function setUrgentFieldsEnabled(enabled) {
  const container = $("#urgent-fields");
  container.classList.toggle("muted", !enabled);
  container.setAttribute("aria-hidden", String(!enabled));
  $$("input, select", container).forEach((control) => { control.disabled = !enabled; });
  updateResidenceField();
}

function updateResidenceField() {
  const shouldAsk = boolOrNull("urgent_event") === true && boolOrNull("is_local_hukou") === false;
  const field = $("#residence-field");
  const control = $("#residence_proof");
  field.classList.toggle("hidden", !shouldAsk);
  control.disabled = !shouldAsk;
  if (!shouldAsk) control.value = "";
}

function updateCompletion() {
  const required = ["query_date", "district", "household_size", "monthly_income_total", "member_scope_confirmed", "assets_eligible", "urgent_event"];
  let completed = required.filter((id) => valueOrNull(id) !== null).length;
  let total = required.length;
  if (boolOrNull("urgent_event") === true) {
    const urgent = ["urgent_event_type", "urgent_event_date", "basic_life_interrupted"];
    total += urgent.length;
    completed += urgent.filter((id) => valueOrNull(id) !== null).length;
  }
  const percent = Math.round((completed / total) * 100);
  $("#completion-label").textContent = `已完成 ${percent}%`;
  $("#completion-bar").style.width = `${percent}%`;
}

function guidancePayload() {
  return {
    query_date: valueOrNull("query_date") || todayISO(),
    city: "广州市",
    district: valueOrNull("district"),
    household_size: numberOrNull("household_size"),
    is_local_hukou: boolOrNull("is_local_hukou"),
    member_scope_confirmed: boolOrNull("member_scope_confirmed"),
    monthly_income_total: numberOrNull("monthly_income_total"),
    assets_eligible: boolOrNull("assets_eligible"),
    rigid_expenses_12m: numberOrNull("rigid_expenses_12m"),
    urgent_event: boolOrNull("urgent_event"),
    urgent_event_date: boolOrNull("urgent_event") === true ? valueOrNull("urgent_event_date") : null,
    urgent_event_type: boolOrNull("urgent_event") === true ? valueOrNull("urgent_event_type") : null,
    basic_life_interrupted: boolOrNull("urgent_event") === true ? boolOrNull("basic_life_interrupted") : null,
    residence_proof: boolOrNull("is_local_hukou") === false ? boolOrNull("residence_proof") : null,
    skipped_fields: state.skippedGuidanceFields,
  };
}

function scheduleGuidance() {
  clearTimeout(state.guidanceTimer);
  state.guidanceTimer = setTimeout(updateGuidance, 180);
}

async function updateGuidance() {
  try {
    const result = await api("/api/v1/guidance/next-question", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(guidancePayload()),
    });
    const button = $("#focus-guidance-field");
    const skipButton = $("#skip-guidance-field");
    if (!result.next_question) {
      state.guidanceField = null;
      $("#guidance-question").textContent = "关键问题已基本确认，可以生成导办报告。";
      $("#guidance-reason").textContent = `已完成 ${result.completed_fields}/${result.total_relevant_fields} 项相关信息。`;
      button.classList.add("hidden");
      skipButton.classList.add("hidden");
    } else {
      const question = result.next_question;
      state.guidanceField = question.field_id;
      $("#guidance-question").textContent = question.plain_language;
      $("#guidance-reason").textContent = `${question.reason} 预计减少 ${question.expected_unknown_reduction} 个事项的不确定条件；敏感度：${question.sensitivity_level}。影响：${question.affects.join("、")}。`;
      button.classList.remove("hidden");
      skipButton.classList.remove("hidden");
    }
    $("#guidance-card").classList.toggle("urgent", Boolean(result.urgent_notice));
    if (result.urgent_notice) $("#guidance-reason").textContent = result.urgent_notice;
    updateCareFocus();
  } catch (error) {
    $("#guidance-reason").textContent = "主动补问暂时不可用，你仍可直接填写表单。";
    updateCareFocus();
  }
}

function setCareMode(enabled) {
  state.careMode = Boolean(enabled);
  const form = $("#screening-form");
  form.classList.toggle("care-mode-active", state.careMode);
  $("#care-flow-status").classList.toggle("hidden", !state.careMode);
  const toggle = $("#care-mode-toggle");
  toggle.setAttribute("aria-pressed", String(state.careMode));
  toggle.innerHTML = `${icons.heart}${state.careMode ? "退出一步一问" : "开启一步一问"}`;
  updateCareFocus();
  if (state.careMode) {
    $("#guidance-card").scrollIntoView({ behavior: "smooth", block: "center" });
    toast("已开启一步一问，只显示当前最关键的信息。" );
  } else {
    toast("已恢复完整表单。" );
  }
}

function updateCareFocus() {
  const form = $("#screening-form");
  $$(".guided-target, .guided-section", form).forEach((item) => {
    item.classList.remove("guided-target", "guided-section");
  });
  form.classList.remove("guidance-complete");
  if (!state.careMode) return;
  const target = state.guidanceField ? $(`#${state.guidanceField}`) : null;
  if (!target) {
    form.classList.add("guidance-complete");
    $("#care-flow-message").textContent = "关键问题已经确认完毕，请阅读说明、勾选同意后生成导办报告。";
    return;
  }
  const targetBlock = target.closest(".field, .toggle-line");
  const targetSection = target.closest(".form-section");
  if (targetBlock) targetBlock.classList.add("guided-target");
  if (targetSection) targetSection.classList.add("guided-section");
  $("#care-flow-message").textContent = `当前问题：${$("#guidance-question").textContent}`;
}

function focusGuidanceField() {
  if (!state.guidanceField) return;
  const target = $(`#${state.guidanceField}`);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  setTimeout(() => target.focus(), 320);
}

function skipGuidanceField() {
  if (!state.guidanceField) return;
  if (!state.skippedGuidanceFields.includes(state.guidanceField)) state.skippedGuidanceFields.push(state.guidanceField);
  toast("已暂时跳过；相关结论将保留为“还需确认”。");
  updateGuidance();
}

async function parseNarrative() {
  const text = $("#narrative").value.trim();
  if (text.length < 2) return toast("请先描述家庭情况。", "error");
  loading(true, "正在把描述转换为可确认的家庭画像…");
  try {
    const result = await api("/api/v1/profile/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, query_date: valueOrNull("query_date") || todayISO(), district: valueOrNull("district") }),
    });
    Object.entries(result.fields).forEach(([key, value]) => setField(key, value));
    const notice = $("#parse-notice");
    notice.classList.remove("hidden");
    const route = result.mode === "llm_assisted" ? `本地模型辅助 · Schema校验通过${result.latency_ms ? ` · ${result.latency_ms}ms` : ""}` : "确定性规则抽取";
    const intent = result.intent_predictions?.[0];
    const intentText = intent ? ` 可能关注：${intent.benefit_name}（仅用于导办排序，不是资格判断）。` : "";
    notice.innerHTML = `<strong>已生成草稿：</strong>${escapeHtml(Object.keys(result.fields).filter((key) => !["query_date", "city"].includes(key)).length)} 个字段已识别；${escapeHtml(result.missing_fields.length)} 个关键字段仍需确认。<br>${escapeHtml(route)}。${escapeHtml(intentText)} ${escapeHtml(result.warnings.join(" "))}`;
    toast(`画像草稿已生成（${result.provider}）`);
  } catch (error) { toast(error.message, "error"); }
  finally { loading(false); }
}

function loadDemo() {
  const demo = {
    query_date: "2026-09-30",
    district: "天河区",
    is_local_hukou: true,
    household_size: 3,
    monthly_income_total: 3200,
    deductible_monthly_total: 0,
    member_scope_confirmed: true,
    assets_eligible: true,
    financial_assets_per_capita: 4000,
    medical_expenses_12m: 30000,
    education_expenses_12m: 0,
    rigid_expenses_12m: 30000,
    urgent_event: true,
    urgent_event_type: "突发急病",
    urgent_event_date: "2026-09-15",
    basic_life_interrupted: true,
  };
  Object.entries(demo).forEach(([key, value]) => setField(key, value));
  $("#narrative").value = "广州天河区三口之家，家庭月收入约3200元，近期突发急病，医疗支出3万元，基本生活受到严重影响。";
  toast("演示家庭已载入，可直接生成报告。")
}

function formPayload() {
  return {
    query_date: valueOrNull("query_date"),
    city: "广州市",
    district: valueOrNull("district"),
    household_size: numberOrNull("household_size"),
    is_local_hukou: boolOrNull("is_local_hukou"),
    member_scope_confirmed: boolOrNull("member_scope_confirmed"),
    monthly_income_total: numberOrNull("monthly_income_total"),
    deductible_monthly_total: numberOrNull("deductible_monthly_total") || 0,
    assets_eligible: boolOrNull("assets_eligible"),
    financial_assets_per_capita: numberOrNull("financial_assets_per_capita"),
    rigid_expenses_12m: numberOrNull("rigid_expenses_12m"),
    medical_expenses_12m: numberOrNull("medical_expenses_12m"),
    education_expenses_12m: numberOrNull("education_expenses_12m"),
    urgent_event: boolOrNull("urgent_event"),
    urgent_event_date: boolOrNull("urgent_event") === true ? valueOrNull("urgent_event_date") : null,
    urgent_event_type: boolOrNull("urgent_event") === true ? valueOrNull("urgent_event_type") : null,
    basic_life_interrupted: boolOrNull("urgent_event") === true ? boolOrNull("basic_life_interrupted") : null,
    residence_proof: boolOrNull("is_local_hukou") === false ? boolOrNull("residence_proof") : null,
    user_statement: $("#narrative").value.trim() || null,
  };
}

async function submitScreening(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  loading(true);
  try {
    const report = await api("/api/v1/screenings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(formPayload()),
    });
    state.screeningId = report.screening_id;
    renderReport(report);
    $("#results-zone").classList.remove("hidden");
    $("#results-zone").scrollIntoView({ behavior: "smooth", block: "start" });
    toast("可信导办报告已生成。")
  } catch (error) { toast(error.message, "error"); }
  finally { loading(false); }
}

const statusLabels = {
  likely: "建议优先咨询",
  incomplete: "需要补充信息",
  unlikely: "目前可能不符合",
  manual_review: "需要人工核验",
};

const statusIcons = {
  likely: icons.check,
  incomplete: icons.help,
  unlikely: icons.x,
  manual_review: icons.alert,
};

const planRoleLabels = {
  primary: "主路径",
  linked: "联动事项",
  alternative: "分层备选",
  manual: "人工核验",
  not_recommended: "暂不推荐",
};

function renderReport(report) {
  state.screeningToken = report.screening_token;
  $("#retention-days").textContent = report.data_retention_days;
  $("#report-meta").textContent = `编号 ${report.screening_id} · ${report.district} · 政策快照 ${report.policy_snapshot}`;
  $("#global-warnings").innerHTML = report.global_warnings
    .map((warning) => `<div class="warning-item">${icons.alert}<span>${escapeHtml(warning)}</span></div>`).join("");
  const counts = report.results.reduce((acc, result) => {
    acc[result.plan_role] = (acc[result.plan_role] || 0) + 1;
    return acc;
  }, {});
  $("#result-summary").innerHTML = `
    <div class="summary-tile likely"><span>主办理路径</span><strong>${counts.primary || 0}</strong></div>
    <div class="summary-tile linked"><span>联动监测事项</span><strong>${counts.linked || 0}</strong></div>
    <div class="summary-tile incomplete"><span>分层备选 / 待补充</span><strong>${counts.alternative || 0}</strong></div>
    <div class="summary-tile manual"><span>人工核验 / 暂不推荐</span><strong>${(counts.manual || 0) + (counts.not_recommended || 0)}</strong></div>`;
  $("#result-list").innerHTML = report.results.map(renderResultCard).join("");
  const office = report.recommended_office;
  const safety = report.safety_validation || {};
  const safetyText = safety.safe
    ? `安全验证器已通过 ${safety.checks?.filter((item) => item.passed).length || 0} 项检查`
    : `安全验证器已阻断：${(safety.failed_check_ids || []).join("、") || "需要人工复核"}`;
  $("#next-step-panel").innerHTML = `
    <div class="panel-heading"><div><p class="eyebrow">ACTION PLAN</p><h3>接下来怎么做</h3><p>${escapeHtml(safetyText)}；验证器只阻断或提示，不改变规则结论。</p></div><span class="soft-tag">人工办理闭环</span></div>
    <div class="next-step-grid">
      <ol>${report.guidance_summary.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>
      ${office ? `<div class="office-card"><strong>${escapeHtml(office.office_name)}</strong><p>${escapeHtml(office.address)}</p><a href="tel:${escapeHtml(office.phone)}">${icons.phone} ${escapeHtml(office.phone)}</a><small>窗口信息最后核验：${escapeHtml(office.last_verified)}；出发前请电话确认。</small></div>` : '<div class="office-card"><strong>暂未匹配到属地窗口</strong><p>请拨打广州12345确认受理地点。</p></div>'}
    </div>`;
  $("#feedback-card").classList.remove("hidden");
  $("#feedback-detail").classList.add("hidden");
  $$("#feedback-card button").forEach((button) => { button.disabled = false; });
}

function renderResultCard(result) {
  const conditions = result.conditions.map((condition) => `
    <div class="condition ${condition.state}">
      <span>${condition.state === "true" ? icons.check : condition.state === "false" ? icons.x : icons.help}</span>
      <div><strong>${escapeHtml(condition.label)}</strong><p>${escapeHtml(condition.reason)}${condition.action_hint ? ` · ${escapeHtml(condition.action_hint)}` : ""}</p></div>
      <em>${escapeHtml(condition.actual || condition.expected || condition.state.toUpperCase())}</em>
    </div>`).join("");
  const evidence = result.evidence.map((item) => `
    <a class="evidence-chip" href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(item.verbatim_quote || item.excerpt)}">${icons.quote}${escapeHtml(item.source_id)} · ${escapeHtml(item.article || "依据")}</a>`).join("");
  const materials = result.materials.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const actions = result.next_actions.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const minimum = result.minimal_required_inputs?.length
    ? `<div class="minimum-inputs"><strong>最少还需确认</strong><p>${result.minimal_required_inputs.map(escapeHtml).join("、")}</p></div>`
    : `<div class="minimum-inputs complete"><strong>关键预筛信息已齐</strong><p>仍需由受理部门核验原件及家庭经济状况。</p></div>`;
  return `<article class="result-card">
    <div class="result-card-head">
      <span class="status-orb ${result.status}">${statusIcons[result.status]}</span>
      <div class="result-title"><strong>${escapeHtml(result.name)}</strong><p>${escapeHtml(result.plan_reason)} · ${escapeHtml(result.summary)}</p></div>
      <div class="result-status ${result.plan_role}"><strong>${escapeHtml(planRoleLabels[result.plan_role])}</strong><small>${escapeHtml(statusLabels[result.status])} · 非审批结论</small></div>
    </div>
    <div class="result-card-body">
      <div class="condition-list">${conditions}</div>
      ${minimum}
      <div class="result-columns"><div class="result-block"><h4>建议准备材料</h4><ul>${materials}</ul></div><div class="result-block"><h4>下一步</h4><ul>${actions}<li>${escapeHtml(result.deadline)}</li></ul></div></div>
      <div class="evidence-chips">${evidence}</div>
    </div>
  </article>`;
}

async function submitFeedback(event) {
  const button = event.target.closest("button[data-helpful]");
  if (!button || !state.screeningId) return;
  if (button.dataset.helpful === "false") {
    $("#feedback-detail").classList.remove("hidden");
    $("#feedback-type").focus();
    return;
  }
  try {
    await api("/api/v1/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Screening-Token": state.screeningToken },
      body: JSON.stringify({ screening_id: state.screeningId, helpful: true, issue_type: "none" }),
    });
    $$("#feedback-card button").forEach((item) => { item.disabled = true; });
    toast("反馈已记录，谢谢你的帮助。")
  } catch (error) { toast(error.message, "error"); }
}

async function sendDetailedFeedback() {
  if (!state.screeningId) return;
  try {
    await api("/api/v1/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Screening-Token": state.screeningToken },
      body: JSON.stringify({
        screening_id: state.screeningId,
        helpful: false,
        issue_type: $("#feedback-type").value,
        comment: $("#feedback-comment").value.trim() || null,
      }),
    });
    $$("#feedback-card button").forEach((item) => { item.disabled = true; });
    toast("改进意见已进入人工复核队列。")
  } catch (error) { toast(error.message, "error"); }
}

async function deleteCurrentScreening() {
  if (!state.screeningId || !state.screeningToken) return toast("当前没有可删除的预筛记录。", "error");
  if (!window.confirm("确定立即删除本次预筛记录及关联反馈吗？删除后无法恢复。")) return;
  try {
    await api(`/api/v1/screenings/${encodeURIComponent(state.screeningId)}`, {
      method: "DELETE",
      headers: { "X-Screening-Token": state.screeningToken },
    });
    state.screeningId = null;
    state.screeningToken = null;
    $("#results-zone").classList.add("hidden");
    toast("本次预筛记录已删除。")
  } catch (error) { toast(error.message, "error"); }
}

function setupDocuments() {
  const input = $("#document-file");
  const drop = $("#drop-zone");
  input.addEventListener("change", () => selectFiles(input.files));
  ["dragenter", "dragover"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.remove("dragging"); }));
  drop.addEventListener("drop", (event) => selectFiles(event.dataTransfer.files));
  $("#check-document").addEventListener("click", checkDocument);
}

function selectFiles(fileList) {
  state.selectedFiles = [...(fileList || [])];
  const total = state.selectedFiles.reduce((sum, file) => sum + file.size, 0);
  $("#selected-file").textContent = state.selectedFiles.length
    ? `已选择 ${state.selectedFiles.length} 份 · ${(total / 1024 / 1024).toFixed(2)} MB：${state.selectedFiles.map((file) => file.name).join("、")}`
    : "尚未选择文件";
}

async function checkDocument() {
  if (!state.selectedFiles.length) return toast("请先选择至少一份材料。", "error");
  if (!$("#document-consent").checked) return toast("请先确认本次处理同意。", "error");
  const data = new FormData();
  state.selectedFiles.forEach((file) => data.append("files", file));
  data.append("benefit_id", $("#document-benefit").value);
  data.append("consent", "true");
  loading(true, "正在执行本地OCR、内容分类与图像质量预检…");
  try {
    const result = await api("/api/v1/documents/package-precheck", { method: "POST", body: data });
    renderDocumentPackage(result);
    toast("材料包预检完成。")
  } catch (error) { toast(error.message, "error"); }
  finally { loading(false); }
}

function renderDocumentPackage(result) {
  const labels = {
    identity: "身份类证明", household_register: "户口簿", income: "收入证明",
    medical_expense: "医疗支出凭据", medical_diagnosis: "诊断材料", education_expense: "教育支出凭据",
    residence: "居住证明", verification_authorization: "经济状况核对授权书", unknown: "待人工分类",
  };
  const readiness = result.ready_for_manual_review ? "材料包已具备人工复核条件" : "建议补齐或重拍后再咨询";
  const detectionLabels = { ocr_content: "OCR内容", filename_hint: "文件名提示", user_declared: "人工指定", unknown: "未识别" };
  const documentCards = result.documents.map((document) => {
    const ocr = document.ocr || {};
    const fields = ocr.extracted_fields || {};
    const ocrDetail = ocr.enabled ? `<div class="ocr-summary"><div><strong>本地OCR</strong><span>${escapeHtml(ocr.line_count)} 行 · 平均行评分 ${ocr.average_line_score === null ? "—" : escapeHtml(ocr.average_line_score)}</span></div><p>内容分类依据：${document.classification_evidence.length ? document.classification_evidence.map(escapeHtml).join("、") : "未命中类型关键词"}</p><p>日期候选：${(fields.date_candidates || []).map(escapeHtml).join("、") || "无"}；金额候选：${(fields.amount_candidates || []).map(escapeHtml).join("、") || "无"}</p><small>OCR全文不返回，文字、日期和金额均需人工对照原件。</small></div>` : "";
    return `<article class="document-file-card">
    <div><strong>${escapeHtml(labels[document.detected_type] || document.detected_type)}</strong><span class="quality-badge ${document.quality_score >= 75 ? "good" : "warn"}">${document.quality_score} 分</span></div>
    <p>${escapeHtml(document.file_name)} · ${(document.file_size / 1024).toFixed(1)} KB · ${escapeHtml(detectionLabels[document.detection_source] || document.detection_source)}分类 · 指纹 ${escapeHtml(document.sha256_prefix)}</p>
    <div class="check-grid">${document.checks.map((check) => `<div class="check-item ${check.passed ? "passed" : "failed"}"><span>${escapeHtml(check.label)}</span><b>${check.passed ? "通过" : "需改进"} · ${escapeHtml(check.value)}</b></div>`).join("")}</div>
    ${ocrDetail}
    ${document.warnings.map((warning) => `<p class="document-warning">${escapeHtml(warning)}</p>`).join("")}
  </article>`; }).join("");
  const consistencyFlags = (result.consistency_flags || []).map((flag) => {
    const details = Object.entries(flag.values || {}).map(([value, names]) => `${escapeHtml(value)}（${names.map(escapeHtml).join("、")}）`).join("；");
    return `<p class="document-warning"><strong>跨材料一致性提示：</strong>${escapeHtml(flag.message)}${details ? `<br>${details}` : ""}</p>`;
  }).join("");
  $("#document-result").innerHTML = `<div class="document-report package-report">
    <div class="package-status ${result.ready_for_manual_review ? "ready" : "needs-work"}"><span>${result.ready_for_manual_review ? icons.check : icons.alert}</span><div><h3>${readiness}</h3><p>已检查 ${result.files_checked} 份材料；${escapeHtml(result.disclaimer)}</p></div></div>
    <div class="package-summary"><div><strong>建议材料</strong><p>${result.required_materials.map(escapeHtml).join("、") || "以窗口告知为准"}</p></div><div><strong>识别到</strong><p>${result.detected_materials.map(escapeHtml).join("、") || "文件名无法判断，请人工分类"}</p></div><div><strong>还建议补充</strong><p>${result.missing_recommended.map(escapeHtml).join("、") || "暂未发现明显缺项"}</p></div></div>
    ${result.duplicate_types.length ? `<p class="document-warning">发现可能重复的材料类型：${result.duplicate_types.map(escapeHtml).join("、")}</p>` : ""}
    ${result.exact_duplicate_files.length ? `<p class="document-warning">发现内容完全相同的重复文件：${result.exact_duplicate_files.map((names) => names.map(escapeHtml).join(" / ")).join("；")}</p>` : ""}
    ${consistencyFlags}
    ${documentCards}
  </div>`;
}

let sourcesLoaded = false;
async function loadSources() {
  if (sourcesLoaded) return;
  try {
    const sources = await api("/api/v1/policies");
    sourcesLoaded = true;
    $("#source-count").textContent = sources.length;
    $("#source-list").innerHTML = sources.map((source) => `<article class="source-item"><strong>${escapeHtml(source.title)}</strong><p>${escapeHtml(source.issuer)} · ${escapeHtml(source.document_no || "公开资料")}</p><div><span>${escapeHtml(source.priority)} · ${escapeHtml(source.status)}</span><a href="${escapeHtml(source.source_url)}" target="_blank" rel="noopener noreferrer">政府原文 ↗</a></div></article>`).join("");
  } catch (error) { toast(error.message, "error"); }
}

function setupEvidence() {
  setField("evidence-as-of", todayISO());
  $("#evidence-search").addEventListener("click", searchEvidence);
  $("#evidence-query").addEventListener("keydown", (event) => { if (event.key === "Enter") searchEvidence(); });
}

async function searchEvidence() {
  const query = $("#evidence-query").value.trim();
  if (query.length < 2) return toast("请至少输入两个字。", "error");
  const target = $("#evidence-results");
  target.innerHTML = '<div class="empty-state"><div class="loader"><span></span><span></span><span></span></div><p>正在检索已核验证据…</p></div>';
  try {
    const asOf = valueOrNull("evidence-as-of") || todayISO();
    const result = await api(`/api/v1/evidence/search?q=${encodeURIComponent(query)}&limit=6&as_of=${encodeURIComponent(asOf)}`);
    if (!result.items.length) {
      target.innerHTML = '<div class="empty-state"><span data-icon="search"></span><h3>没有找到直接证据</h3><p>尝试“低保”“临时救助”“收入”或“材料”。</p></div>';
      injectIcons(target);
      return;
    }
    const retriever = typeof result.retriever === "string" ? result.retriever : result.retriever.name;
    const degraded = typeof result.retriever === "object" && result.retriever.degraded ? ` · ${result.retriever.reason}` : "";
    target.innerHTML = `<p class="microcopy">查询日：${escapeHtml(result.as_of)} · 实际检索路径：${escapeHtml(retriever)}${escapeHtml(degraded)} · 已排除 ${escapeHtml(result.temporal_filter?.excluded_evidence || 0)} 条非有效期证据</p>` + result.items.map(({ score, evidence }) => {
      const quote = evidence.verbatim_quote || evidence.excerpt;
      const verified = evidence.quote_verified ? "逐字核验" : "待人工复核";
      const explanation = evidence.plain_language_explanation
        ? `<div class="evidence-explanation"><strong>通俗解释</strong><p>${escapeHtml(evidence.plain_language_explanation)}</p></div>`
        : "";
      return `<article class="evidence-card"><div class="evidence-card-head"><div><h3>${escapeHtml(evidence.title)}</h3><p class="source-meta">${escapeHtml(evidence.source_id)} · ${escapeHtml(evidence.document_no || "公开资料")} · ${escapeHtml(evidence.article || "相关内容")} · ${escapeHtml(evidence.locator || "定位待补充")}</p></div><span class="score-pill">相关度 ${escapeHtml(score)}</span></div><div class="evidence-quote"><strong>政策逐字原文 · ${escapeHtml(verified)}</strong><p>${escapeHtml(quote)}</p></div>${explanation}<a href="${escapeHtml(evidence.source_url)}" target="_blank" rel="noopener noreferrer">查看政府原文 ↗</a></article>`;
    }).join("");
  } catch (error) { target.innerHTML = `<div class="empty-state"><p>${escapeHtml(error.message)}</p></div>`; }
}

async function loadAdmin() {
  try {
    const result = await api("/api/v1/admin/dashboard");
    const cards = $$("#admin-metrics article strong");
    cards[0].textContent = result.screenings;
    cards[1].textContent = result.policy_health.total_sources;
    cards[2].textContent = result.privacy.raw_documents_stored ? "是" : "否";
    cards[3].textContent = `${result.privacy.retention_days} 天`;
    const registry = result.rule_registry;
    renderReadiness(result.system_readiness);
    const releaseLabels = { verified_for_demo: "演示核验版", draft: "草稿", production: "生产发布" };
    const ruleStatusLabels = { verified: "已核验", watch: "临期跟踪", manual_review: "人工核验" };
    $("#registry-version").textContent = `${registry.registry_version} · ${releaseLabels[registry.release_status] || registry.release_status}`;
    $("#rule-release").innerHTML = registry.rules.map((rule) => `<div class="rule-row">
      <span class="rule-state ${rule.status === "verified" ? "verified" : "review"}">${rule.status === "verified" ? icons.check : icons.alert}</span>
      <div><strong>${escapeHtml(rule.name)}</strong><p>${escapeHtml(rule.version)} · ${escapeHtml(rule.effective_from)} 至 ${escapeHtml(rule.effective_to || "长期")}</p></div>
      <em>${escapeHtml(ruleStatusLabels[rule.status] || rule.status)}</em>
    </div>`).join("");
    $("#control-enabled").textContent = registry.control_summary.enabled;
    $("#control-total").textContent = `/ ${registry.control_summary.total} 项`;
    $(".score-ring").style.setProperty(
      "--control-percent",
      String(Math.round(registry.control_summary.enabled / Math.max(registry.control_summary.total, 1) * 100)),
    );
    const controlLabels = {
      source_traceability: "官方来源可追溯", effective_date_guard: "政策有效期检查",
      three_value_logic: "三值不确定性推理", human_review_fallback: "不确定场景转人工",
      regression_tests: "边界回归测试", dual_reviewer_signoff: "双人规则复核签字",
      production_access_control: "生产访问控制",
    };
    $("#security-list").innerHTML = Object.entries(registry.controls).map(([key, enabled]) => `<div><span>${enabled ? icons.check : icons.alert}</span><strong>${escapeHtml(controlLabels[key] || key)}</strong><em>${enabled ? "已启用" : "待完善"}</em></div>`).join("") +
      `<div><span>${icons.database}</span><strong>规则登记表指纹</strong><em>${escapeHtml(registry.registry_sha256_prefix)}</em></div>`;
    const table = $("#audit-table");
    if (!result.recent.length) {
      table.innerHTML = '<div class="empty-state compact"><p>还没有预筛记录。</p></div>';
      return;
    }
    table.innerHTML = `<table><thead><tr><th>记录编号</th><th>地区</th><th>查询日期</th><th>政策快照</th><th>生成时间</th></tr></thead><tbody>${result.recent.map((row) => `<tr><td><code>${escapeHtml(row.id)}</code></td><td>${escapeHtml(row.district)}</td><td>${escapeHtml(row.query_date)}</td><td><code>${escapeHtml(row.policy_snapshot)}</code></td><td>${escapeHtml(row.created_at.slice(0, 19).replace("T", " "))}</td></tr>`).join("")}</tbody></table>`;
  } catch (error) { toast(error.message, "error"); }
}

function renderReadiness(readiness) {
  if (!readiness) return;
  state.readiness = readiness;
  const statusLabels = { ready: "全部就绪", ready_with_warnings: "核心就绪", blocked: "存在阻断" };
  const status = $("#readiness-status");
  status.textContent = statusLabels[readiness.status] || readiness.status;
  status.className = `soft-tag readiness-${escapeHtml(readiness.status)}`;
  $("#readiness-summary").innerHTML = `
    <div><strong>${escapeHtml(readiness.summary.passed)}</strong><span>通过</span></div>
    <div><strong>${escapeHtml(readiness.summary.warnings)}</strong><span>提醒</span></div>
    <div><strong>${escapeHtml(readiness.summary.failed)}</strong><span>阻断</span></div>
    <div><strong>${escapeHtml(readiness.summary.total)}</strong><span>核验项</span></div>`;
  const checkLabels = { pass: "通过", warn: "部署提醒", fail: "阻断" };
  $("#readiness-grid").innerHTML = readiness.checks.map((check) => `<div class="readiness-item ${escapeHtml(check.status)}"><span>${check.status === "pass" ? icons.check : icons.alert}</span><div><strong>${escapeHtml(check.label)}</strong><p>${escapeHtml(check.detail)}</p></div><em>${escapeHtml(checkLabels[check.status] || check.status)}</em></div>`).join("");
  $("#readiness-boundary").textContent = `${readiness.claim_boundary} · 数据核验至 ${readiness.policy_as_of}`;
}

const policySample = `广州市最低生活保障办法。共同生活家庭成员人均月收入低于本市最低生活保障标准，且家庭财产状况符合规定的，可以申请最低生活保障。2027年最低生活保障标准调整为1400元/人/月。本通知自2027年8月1日起施行，有效期为1年。`;

function setupPolicyCompiler() {
  $("#load-policy-sample").addEventListener("click", () => {
    $("#compiler-text").value = policySample;
    toast("已载入不含个人信息的合成演示条款");
  });
  $("#compile-policy").addEventListener("click", compilePolicyCandidate);
}

async function compilePolicyCandidate() {
  const sourceText = $("#compiler-text").value.trim();
  if (sourceText.length < 20) return toast("请粘贴至少20字的政策条款。", "error");
  const payload = {
    source_id: $("#compiler-source-id").value.trim(),
    title: $("#compiler-title").value.trim(),
    source_text: sourceText,
    region: $("#compiler-region").value.trim(),
    benefit_hint: $("#compiler-benefit").value,
    use_llm: $("#compiler-use-llm").checked,
  };
  loading(true, "正在编译候选规则并执行安全校验…");
  try {
    const result = await api("/api/v1/admin/policy/compile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.compiledPolicyCandidate = result.candidate;
    renderPolicyCandidate(result);
  } catch (error) {
    toast(error.message, "error");
  } finally { loading(false); }
}

function renderPolicyCandidate(result) {
  const candidate = result.candidate;
  const issues = result.validation.map((item) => `<li class="${escapeHtml(item.severity)}"><strong>${escapeHtml(item.severity.toUpperCase())}</strong><span>${escapeHtml(item.message)}</span></li>`).join("");
  const conditions = candidate.conditions.map((item) => `<li><code>${escapeHtml(item.field)} ${escapeHtml(item.operator)} ${escapeHtml(item.value)}</code><span>${escapeHtml(item.source_quote)}</span></li>`).join("") || "<li><span>没有抽取到可执行条件</span></li>";
  const changes = result.version_diff.changes.map((item) => `<li><strong>${escapeHtml(item.field)}</strong><span>${escapeHtml(item.before ?? "空")} → ${escapeHtml(item.after ?? "空")}</span></li>`).join("") || "<li><span>未发现参数或时间变化</span></li>";
  $("#compiler-output").innerHTML = `<div class="compiler-result-head"><div><span class="candidate-status">待双人复核</span><h4>${escapeHtml(candidate.benefit_name)}</h4><p>${escapeHtml(candidate.candidate_id)} · ${escapeHtml(candidate.provider)}</p></div><div><strong>${Math.round(candidate.extraction_completeness * 100)}%</strong><span>抽取完整度<br>不是准确率</span></div></div>
    <div class="compiler-facts"><div><span>生效区间</span><strong>${escapeHtml(candidate.effective_from || "待确认")} 至 ${escapeHtml(candidate.effective_to || "长期/待确认")}</strong></div><div><span>原文指纹</span><strong><code>${escapeHtml(candidate.source_sha256.slice(0, 16))}</code></strong></div></div>
    <div class="compiler-block"><h5>候选条件</h5><ul class="condition-code-list">${conditions}</ul></div>
    <div class="compiler-block"><h5>版本差异</h5><ul class="diff-list">${changes}</ul></div>
    <div class="compiler-block"><h5>发布校验</h5><ul class="validation-list">${issues}</ul></div>
    <button type="button" class="outline-button" id="analyze-policy-impact">运行240例影响分析</button>
    <div id="policy-impact-output"></div>`;
  document.getElementById("analyze-policy-impact").addEventListener("click", analyzePolicyImpact);
}

async function analyzePolicyImpact() {
  if (!state.compiledPolicyCandidate) return;
  const target = document.getElementById("policy-impact-output");
  target.innerHTML = '<p class="compiler-progress">正在对冻结合成回归集执行差异分析…</p>';
  try {
    const result = await api("/api/v1/admin/policy/impact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate: state.compiledPolicyCandidate }),
    });
    target.innerHTML = `<div class="impact-summary"><div><strong>${escapeHtml(result.total_cases)}</strong><span>总案例</span></div><div><strong>${escapeHtml(result.comparable_cases)}</strong><span>可比较</span></div><div><strong>${escapeHtml(result.changed_cases)}</strong><span>结论变化</span></div></div><p>${result.notes.map(escapeHtml).join(" ")}</p><p>新增纳入 ${escapeHtml(result.changes_by_direction.newly_included || 0)} 例；新增排除 ${escapeHtml(result.changes_by_direction.newly_excluded || 0)} 例。</p><small>示例编号：${escapeHtml(result.sample_case_ids.join("、") || "无")}</small>`;
  } catch (error) { target.innerHTML = `<p class="compiler-error">${escapeHtml(error.message)}</p>`; }
}

async function loadMetadata() {
  try {
    const [metadata, readiness] = await Promise.all([
      api("/api/v1/metadata"),
      api("/api/v1/system/readiness"),
    ]);
    state.metadata = metadata;
    state.readiness = readiness;
    const sourceCount = state.metadata.official_sources;
    $("#hero-sources").textContent = sourceCount;
    $("#metric-source-count").textContent = sourceCount;
    $("#metric-office-count").textContent = state.metadata.office_records;
    $("#metric-dibao").textContent = `¥${Number(state.metadata.parameters.dibao_standard).toLocaleString("zh-CN")}`;
    $("#metric-policy-watch").textContent = state.metadata.policy_watch.length;
    $("#source-count").textContent = sourceCount;
    $("#trust-policy-date").textContent = `核验至 ${state.metadata.policy_as_of}`;
    const modelActive = state.metadata.ai_runtime.active_provider.startsWith("ollama/");
    $("#parser-mode-tag").textContent = modelActive ? "本地模型辅助抽取" : "安全规则抽取";
    $("#retrieval-stack-label").textContent = state.metadata.ai_runtime.embedding_model
      ? "Rule · Hybrid Retrieve · Explain"
      : "Rule · BM25 · Explain";
    const asOf = new Date(`${state.metadata.policy_as_of}T00:00:00`);
    const watchItems = state.metadata.policy_watch
      .filter((item) => new Date(`${item.effective_to}T00:00:00`) >= asOf)
      .sort((a, b) => a.effective_to.localeCompare(b.effective_to))
      .slice(0, 3);
    $("#policy-watch-list").innerHTML = watchItems.map((item) => {
      const days = Math.round((new Date(`${item.effective_to}T00:00:00`) - asOf) / 86400000);
      const tone = days <= 180 ? "warning" : "active";
      return `<div class="time-item ${tone}"><span></span><div><small>${escapeHtml(item.effective_to)}</small><strong>${escapeHtml(item.source_id)} · ${escapeHtml(item.title)}</strong><p>${escapeHtml(item.status)}；到期前必须重新核验。</p></div></div>`;
    }).join("") || '<p class="microcopy">当前目录没有明确到期的政策来源。</p>';
    const status = $("#runtime-status");
    status.classList.toggle("warning", !readiness.ready);
    status.innerHTML = `<span></span>${readiness.ready ? "核心能力已核验" : "运行环境需检查"}`;
  } catch (error) { toast("后端未连接，请确认服务已启动。", "error"); }
}

function speakVisiblePage() {
  if (!("speechSynthesis" in window) || !("SpeechSynthesisUtterance" in window)) {
    return toast("当前浏览器不支持本地朗读。", "error");
  }
  const button = $("#read-page-aloud");
  if (state.speechActive || window.speechSynthesis.speaking) {
    window.speechSynthesis.cancel();
    state.speechActive = false;
    button.setAttribute("aria-pressed", "false");
    return toast("已停止朗读。" );
  }
  const activeView = $(".view.active");
  const reportVisible = !$("#results-zone").classList.contains("hidden");
  let source = activeView;
  if (state.currentView === "screening" && state.careMode) source = $("#guidance-card");
  else if (state.currentView === "screening" && reportVisible) source = $("#results-zone");
  const text = `${$("#page-title").textContent}。${source.innerText}`
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 5000);
  if (!text) return toast("当前页面没有可朗读的内容。", "error");
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 0.92;
  utterance.pitch = 1;
  utterance.onend = utterance.onerror = () => {
    state.speechActive = false;
    button.setAttribute("aria-pressed", "false");
  };
  state.speechActive = true;
  button.setAttribute("aria-pressed", "true");
  window.speechSynthesis.speak(utterance);
  toast("正在本机朗读当前重点内容。" );
}

function setupUtilities() {
  const largeType = localStorage.getItem("huimin-large-type") === "true";
  document.body.classList.toggle("large-type", largeType);
  $("#accessibility-toggle").setAttribute("aria-pressed", String(largeType));
  $("#accessibility-toggle").addEventListener("click", () => {
    document.body.classList.toggle("large-type");
    const enabled = document.body.classList.contains("large-type");
    $("#accessibility-toggle").setAttribute("aria-pressed", String(enabled));
    localStorage.setItem("huimin-large-type", String(enabled));
    toast(document.body.classList.contains("large-type") ? "已启用大字模式" : "已恢复标准字号");
  });
  const speechButton = $("#read-page-aloud");
  if ("speechSynthesis" in window && "SpeechSynthesisUtterance" in window) {
    speechButton.addEventListener("click", speakVisiblePage);
  } else {
    speechButton.disabled = true;
    speechButton.title = "当前浏览器不支持本地朗读，可使用系统读屏功能";
    speechButton.setAttribute("aria-label", speechButton.title);
  }
  $("#care-mode-toggle").addEventListener("click", () => setCareMode(!state.careMode));
  $("#admin-token").value = state.adminToken;
  $("#apply-admin-token").addEventListener("click", () => {
    state.adminToken = $("#admin-token").value.trim();
    if (state.adminToken) sessionStorage.setItem("huimin-admin-token", state.adminToken);
    else sessionStorage.removeItem("huimin-admin-token");
    loadAdmin();
  });
  $("#refresh-admin").addEventListener("click", () => loadAdmin());
}

function setupWorker() {
  setField("worker-query-date", todayISO());
  $("#worker-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const urgent = boolOrNull("worker-urgent") === true;
    const payload = {
      query_date: valueOrNull("worker-query-date"), city: "广州市",
      district: valueOrNull("worker-district"), household_size: numberOrNull("worker-household-size"),
      is_local_hukou: boolOrNull("worker-hukou"), member_scope_confirmed: boolOrNull("worker-member"),
      monthly_income_total: numberOrNull("worker-income"), deductible_monthly_total: 0,
      assets_eligible: boolOrNull("worker-assets"), rigid_expenses_12m: numberOrNull("worker-expenses"),
      urgent_event: urgent, urgent_event_date: urgent ? valueOrNull("worker-query-date") : null,
      basic_life_interrupted: urgent ? true : null,
    };
    loading(true, "正在生成匿名工作人员咨询摘要…");
    try {
      const result = await api("/api/v1/screenings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const rows = result.results.map((item) => {
        const unknown = item.conditions.filter((condition) => condition.state === "unknown");
        return `<div class="worker-row"><strong>${escapeHtml(item.name)}</strong><span class="soft-tag">${escapeHtml(statusLabels[item.status])}</span><small>${escapeHtml(unknown.length ? `还需确认：${unknown.map((condition) => condition.label).join("、")}` : item.plan_reason)}</small></div>`;
      }).join("");
      const office = result.recommended_office;
      $("#worker-output").innerHTML = `<div class="panel-heading"><div><p class="eyebrow">ANONYMOUS SUMMARY</p><h3>五事项并排摘要</h3><p>${escapeHtml(result.policy_snapshot)} · 安全验证${result.safety_validation.safe ? "通过" : "已阻断"}</p></div><button type="button" class="text-button" id="worker-print">打印</button></div><div class="worker-matrix">${rows}</div>${office ? `<div class="office-card"><strong>${escapeHtml(office.office_name)}</strong><p>${escapeHtml(office.address)} · ${escapeHtml(office.phone)}</p></div>` : ""}`;
      document.getElementById("worker-print").addEventListener("click", () => window.print());
      toast("工作人员咨询摘要已生成。")
    } catch (error) { toast(error.message, "error"); }
    finally { loading(false); }
  });
}

const demoProfiles = {
  A: { query_date: "2026-09-30", city: "广州市", district: "天河区", household_size: 3, is_local_hukou: true, member_scope_confirmed: true, monthly_income_total: 3981, deductible_monthly_total: 0, assets_eligible: true, rigid_expenses_12m: 0, urgent_event: false },
  B: { query_date: "2026-09-30", city: "广州市", district: "天河区", household_size: 3, is_local_hukou: true, member_scope_confirmed: null, monthly_income_total: 3000, deductible_monthly_total: 0, assets_eligible: true, rigid_expenses_12m: 0, urgent_event: false },
  C: { query_date: "2026-09-30", city: "广州市", district: "海珠区", household_size: 2, is_local_hukou: true, member_scope_confirmed: true, monthly_income_total: 4500, deductible_monthly_total: 0, assets_eligible: true, rigid_expenses_12m: 28000, urgent_event: true, urgent_event_date: "2026-09-20", urgent_event_type: "突发急病", basic_life_interrupted: true },
};

function renderDemoScreening(result, label) {
  const cards = result.results.slice(0, 3).map((item) => `<div><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(statusLabels[item.status])} · ${escapeHtml(item.plan_reason)}</p><small>证据 ${item.evidence.length} 条 · UNKNOWN ${item.conditions.filter((condition) => condition.state === "unknown").length} 项</small></div>`).join("");
  $("#demo-output").innerHTML = `<div class="panel-heading"><div><p class="eyebrow">SYNTHETIC CASE ${label}</p><h3>${escapeHtml(result.guidance_summary[0])}</h3><p>${escapeHtml(result.policy_snapshot)} · 安全验证${result.safety_validation.safe ? "通过" : "阻断"}</p></div><span class="soft-tag">合成案例</span></div><div class="demo-comparison">${cards}</div>`;
}

async function runDemoCase(label) {
  if (demoProfiles[label]) {
    loading(true, `正在运行合成案例 ${label}…`);
    try {
      const result = await api("/api/v1/screenings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(demoProfiles[label]) });
      renderDemoScreening(result, label);
    } catch (error) { toast(error.message, "error"); }
    finally { loading(false); }
    return;
  }
  if (label === "D") {
    loading(true, "正在比较新旧政策检索分区…");
    try {
      const [oldResult, newResult] = await Promise.all([
        api("/api/v1/evidence/search?q=最低生活保障辅助指标&limit=10&as_of=2026-07-31"),
        api("/api/v1/evidence/search?q=最低生活保障辅助指标&limit=10&as_of=2026-08-01"),
      ]);
      const ids = (result) => result.items.map((item) => item.evidence.evidence_id).join("、") || "无匹配";
      $("#demo-output").innerHTML = `<div class="panel-heading"><div><p class="eyebrow">TEMPORAL SWITCH</p><h3>查询日改变，政策版本随之切换</h3></div><span class="soft-tag">真实时态检索</span></div><div class="demo-comparison"><div><strong>2026-07-31</strong><p>${escapeHtml(ids(oldResult))}</p><small>排除 ${oldResult.temporal_filter.excluded_evidence} 条非有效期证据</small></div><div><strong>2026-08-01</strong><p>${escapeHtml(ids(newResult))}</p><small>排除 ${newResult.temporal_filter.excluded_evidence} 条非有效期证据</small></div></div>`;
    } catch (error) { toast(error.message, "error"); }
    finally { loading(false); }
    return;
  }
  if (label === "E") { navigate("admin"); setTimeout(() => $("#load-policy-sample").click(), 250); return; }
  if (label === "F") { navigate("documents"); toast("请分别选择页面提供的清晰与模糊合成样例进行预检。") }
}

function setupDemoCenter() {
  $("#demo-grid").addEventListener("click", (event) => {
    const button = event.target.closest("[data-demo-case]");
    if (button) runDemoCase(button.dataset.demoCase);
  });
}

function initialize() {
  injectIcons();
  setupNavigation();
  setupForm();
  setupDocuments();
  setupEvidence();
  setupWorker();
  setupDemoCenter();
  setupPolicyCompiler();
  setupUtilities();
  loadMetadata();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
  }
}

document.addEventListener("DOMContentLoaded", initialize);
