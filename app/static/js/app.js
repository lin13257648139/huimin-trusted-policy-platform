"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const todayISO = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const valueOrNull = (id) => { const value = $(`#${id}`)?.value?.trim(); return value === "" || value === undefined ? null : value; };
const numberOrNull = (id) => { const value = valueOrNull(id); return value === null ? null : Number(value); };
const boolOrNull = (id) => { const value = valueOrNull(id); return value === null ? null : value === "true"; };
const formatMoney = (value) => value === null || value === undefined || value === "" ? "尚未提供" : `${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}元`;

const state = {
  route: "home",
  step: 0,
  metadata: null,
  readiness: null,
  lastParse: null,
  assistiveParse: null,
  supplementAnalysis: null,
  supplementDecisions: {},
  analyzedSupplementText: "",
  report: null,
  screeningId: null,
  screeningToken: null,
  selectedFiles: [],
  reportSafetyPassed: false,
  workerSafetyPassed: false,
  adminToken: sessionStorage.getItem("huimin-admin-token") || "",
};

const fieldLabels = {
  district: "地区", household_size: "共同生活人数", is_local_hukou: "广州户籍成员",
  residence_proof: "有效居住证明", member_scope_confirmed: "成员范围", monthly_income_total: "家庭月总收入",
  deductible_monthly_total: "允许扣除的月支出", assets_eligible: "财产情况",
  financial_assets_per_capita: "人均金融资产", rigid_expenses_12m: "刚性支出",
  medical_expenses_12m: "医疗支出", education_expenses_12m: "教育支出",
  urgent_event: "急难事件", urgent_event_date: "事件日期", urgent_event_type: "事件类型",
  basic_life_interrupted: "基本生活受影响",
  special_person_category_confirmed: "特困供养对象线索", no_labor_capacity: "劳动能力",
  no_livelihood_source: "生活来源", has_capable_legal_supporter: "法定赡养抚养扶养支持",
};

const inputSteps = {
  district: 0, household_size: 0, is_local_hukou: 0, residence_proof: 0, member_scope_confirmed: 0,
  monthly_income_total: 1, deductible_monthly_total: 1, assets_eligible: 1, financial_assets_per_capita: 1,
  rigid_expenses_12m: 2, medical_expenses_12m: 2, education_expenses_12m: 2,
  urgent_event: 2, urgent_event_date: 2, urgent_event_type: 2, basic_life_interrupted: 2,
  special_person_category_confirmed: 2, no_labor_capacity: 2,
  no_livelihood_source: 2, has_capable_legal_supporter: 2,
};

const draftFieldIds = [
  "query_date", "district", "household_size", "is_local_hukou", "residence_proof",
  "member_scope_confirmed", "monthly_income_total", "deductible_monthly_total",
  "assets_eligible", "financial_assets_per_capita", "medical_expenses_12m",
  "education_expenses_12m", "rigid_expenses_12m", "urgent_event_type",
  "urgent_event_date", "basic_life_interrupted", "special_person_category_confirmed",
  "no_labor_capacity", "no_livelihood_source", "has_capable_legal_supporter",
  "narrative", "assistive-narrative",
];

const booleanText = (value, yes = "是", no = "否") => value === true ? yes : value === false ? no : "不清楚";

function toast(message, tone = "success") {
  const item = document.createElement("div");
  item.className = `toast ${tone}`;
  item.textContent = message;
  $("#toast-region").append(item);
  setTimeout(() => item.remove(), 4200);
}

function loading(show, message = "正在处理") {
  $("#loading-text").textContent = message;
  $("#loading-overlay").classList.toggle("hidden", !show);
}

async function api(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.adminToken && url.startsWith("/api/v1/admin/")) headers.set("X-Admin-Token", state.adminToken);
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    const detail = payload?.detail;
    const error = new Error(typeof detail === "string" ? detail : detail?.message || `请求失败（${response.status}）`);
    error.status = response.status;
    error.code = detail?.code;
    error.details = detail;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

function closeMobileNav() {
  $("#site-navigation").classList.remove("open");
  $("#nav-scrim").classList.remove("open");
  $("#mobile-menu").setAttribute("aria-expanded", "false");
}

function navigate(route, { focus = true } = {}) {
  if (!$(`[data-page="${route}"]`)) route = "home";
  state.route = route;
  $$(".page").forEach((page) => page.classList.toggle("active", page.dataset.page === route));
  $$(".site-nav [data-route]").forEach((button) => button.classList.toggle("active", button.dataset.route === route));
  closeMobileNav();
  if (route === "trust") loadSources();
  if (route === "professional") setProfessionalTab("worker");
  history.replaceState(null, "", `#${route}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (focus) setTimeout(() => $("#main-content").focus({ preventScroll: true }), 50);
}

function setField(id, value) {
  if (value === undefined || value === null) return;
  if (id === "urgent_event") {
    const radio = $(`input[name="urgent_event_choice"][value="${String(value)}"]`);
    if (radio) radio.checked = true;
    toggleUrgentFields();
    return;
  }
  const target = $(`#${id}`);
  if (!target) return;
  if (typeof value === "boolean") target.value = String(value);
  else target.value = value;
}

function urgentValue() {
  const checked = $('input[name="urgent_event_choice"]:checked');
  if (!checked || checked.value === "") return null;
  return checked.value === "true";
}

function formPayload() {
  const medical = numberOrNull("medical_expenses_12m");
  const education = numberOrNull("education_expenses_12m");
  let rigid = numberOrNull("rigid_expenses_12m");
  if (rigid === null && (medical !== null || education !== null)) rigid = (medical || 0) + (education || 0);
  const urgent = urgentValue();
  return {
    query_date: valueOrNull("query_date") || todayISO(), city: "广州市", district: valueOrNull("district") || "天河区",
    household_size: numberOrNull("household_size"), is_local_hukou: boolOrNull("is_local_hukou"),
    member_scope_confirmed: boolOrNull("member_scope_confirmed"), monthly_income_total: numberOrNull("monthly_income_total"),
    deductible_monthly_total: numberOrNull("deductible_monthly_total") || 0, assets_eligible: boolOrNull("assets_eligible"),
    financial_assets_per_capita: numberOrNull("financial_assets_per_capita"), rigid_expenses_12m: rigid,
    medical_expenses_12m: medical, education_expenses_12m: education, urgent_event: urgent,
    urgent_event_date: urgent === true ? valueOrNull("urgent_event_date") : null,
    urgent_event_type: urgent === true ? valueOrNull("urgent_event_type") : null,
    basic_life_interrupted: urgent === true ? boolOrNull("basic_life_interrupted") : null,
    special_person_category_confirmed: boolOrNull("special_person_category_confirmed"),
    no_labor_capacity: boolOrNull("special_person_category_confirmed") === true ? boolOrNull("no_labor_capacity") : null,
    no_livelihood_source: boolOrNull("special_person_category_confirmed") === true ? boolOrNull("no_livelihood_source") : null,
    has_capable_legal_supporter: boolOrNull("special_person_category_confirmed") === true ? boolOrNull("has_capable_legal_supporter") : null,
    residence_proof: boolOrNull("residence_proof"), user_statement: valueOrNull("narrative"),
    confirmed_supplement_fields: confirmedSupplementFields(),
  };
}

function profileDraftPayload() {
  const payload = formPayload();
  return {
    query_date: payload.query_date, city: payload.city, district: valueOrNull("district"),
    household_size: payload.household_size, is_local_hukou: payload.is_local_hukou,
    residence_proof: payload.residence_proof, member_scope_confirmed: payload.member_scope_confirmed,
    monthly_income_total: payload.monthly_income_total, deductible_monthly_total: payload.deductible_monthly_total,
    assets_eligible: payload.assets_eligible, financial_assets_per_capita: payload.financial_assets_per_capita,
    rigid_expenses_12m: payload.rigid_expenses_12m, medical_expenses_12m: payload.medical_expenses_12m,
    education_expenses_12m: payload.education_expenses_12m, urgent_event: payload.urgent_event,
    urgent_event_date: payload.urgent_event_date, urgent_event_type: payload.urgent_event_type,
    basic_life_interrupted: payload.basic_life_interrupted,
    special_person_category_confirmed: payload.special_person_category_confirmed,
    no_labor_capacity: payload.no_labor_capacity, no_livelihood_source: payload.no_livelihood_source,
    has_capable_legal_supporter: payload.has_capable_legal_supporter, skipped_fields: [],
  };
}

function confirmedSupplementFields() {
  if (!state.supplementAnalysis) return [];
  return state.supplementAnalysis.candidates
    .filter((candidate) => state.supplementDecisions[candidate.candidate_id] === "confirmed")
    .map((candidate) => candidate.field);
}

function toggleUrgentFields() {
  $("#urgent-fields").classList.toggle("hidden", urgentValue() !== true);
}

function toggleSpecialHardshipFields() {
  const enabled = boolOrNull("special_person_category_confirmed") === true;
  $("#special-hardship-fields").classList.toggle("hidden", !enabled);
  $("#special-hardship-note").textContent = enabled
    ? "下面三项只记录自述线索，正式认定仍由主管部门调查核实。"
    : "选择“是”后再核对劳动能力、生活来源和法定支持情况。";
}

function updateIncomePreview() {
  const members = numberOrNull("household_size");
  const income = numberOrNull("monthly_income_total");
  const deduction = numberOrNull("deductible_monthly_total") || 0;
  const target = $("#income-preview strong");
  if (!members || income === null) target.textContent = "等待填写收入和人数";
  else target.textContent = `${Math.max(income - deduction, 0) / members < 0 ? 0 : ((Math.max(income - deduction, 0) / members).toFixed(2))}元 / 人 / 月`;
}

function updateReview() {
  const payload = formPayload();
  const rows = [
    ["准备咨询地区", payload.district, "district"], ["查询日期", payload.query_date, "query_date"], ["共同生活人数", payload.household_size ? `${payload.household_size}人` : null, "household_size"],
    ["广州户籍成员", booleanText(payload.is_local_hukou, "有", "没有"), "is_local_hukou"], ["有效居住证明", booleanText(payload.residence_proof, "有", "没有"), "residence_proof"], ["家庭月总收入", formatMoney(payload.monthly_income_total), "monthly_income_total"],
    ["成员范围", booleanText(payload.member_scope_confirmed, "已确认", "可能有遗漏"), "member_scope_confirmed"], ["财产情况", booleanText(payload.assets_eligible, "未发现超限", "可能超限"), "assets_eligible"],
    ["近12月刚性支出", formatMoney(payload.rigid_expenses_12m), "rigid_expenses_12m"], ["近期急难事件", booleanText(payload.urgent_event, "有", "没有"), "urgent_event"],
    ["基本生活受严重影响", payload.urgent_event === true ? booleanText(payload.basic_life_interrupted) : "不适用", "basic_life_interrupted"],
    ["特困供养对象线索", booleanText(payload.special_person_category_confirmed, "有，继续核对", "没有"), "special_person_category_confirmed"],
    ["劳动能力", payload.special_person_category_confirmed === true ? booleanText(payload.no_labor_capacity, "无劳动能力", "有劳动能力") : "不适用", "no_labor_capacity"],
    ["生活来源", payload.special_person_category_confirmed === true ? booleanText(payload.no_livelihood_source, "没有", "有") : "不适用", "no_livelihood_source"],
    ["有履行能力的法定义务人", payload.special_person_category_confirmed === true ? booleanText(payload.has_capable_legal_supporter, "有", "没有或无履行能力") : "不适用", "has_capable_legal_supporter"],
  ];
  $("#profile-review").innerHTML = rows.map(([label, value, field]) => `<div class="review-item ${!value || value === "尚未提供" || value === "不清楚" ? "missing" : ""}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "尚未提供")}</strong><button type="button" data-edit-field="${escapeHtml(field)}">修改</button></div>`).join("");
}

function validateStep(step) {
  const requiredByStep = { 0: ["query_date", "district", "household_size"] };
  for (const id of requiredByStep[step] || []) {
    const field = $(`#${id}`);
    if (!field.reportValidity()) return false;
  }
  if (step === 2 && !$('input[name="urgent_event_choice"]:checked')) {
    toast("请选择是否发生急难事件；不确定可以选择“不清楚”。", "error");
    $("#urgent-choice-group").scrollIntoView({ behavior: "smooth", block: "center" });
    return false;
  }
  if (step === 2 && valueOrNull("special_person_category_confirmed") === null) {
    toast("请选择是否存在特困供养对象线索；不确定可以选择“不清楚”。", "error");
    $("#special_person_category_confirmed").focus();
    return false;
  }
  return true;
}

function showStep(step, { scroll = false, focus = false } = {}) {
  state.step = Math.max(0, Math.min(3, step));
  $$("[data-wizard-step]").forEach((panel) => panel.classList.toggle("active", Number(panel.dataset.wizardStep) === state.step));
  $$("[data-step-indicator]").forEach((item) => {
    const index = Number(item.dataset.stepIndicator);
    item.classList.toggle("active", index === state.step);
    item.classList.toggle("done", index < state.step);
  });
  $("#wizard-progress-bar").style.width = `${(state.step + 1) * 25}%`;
  $("#wizard-back").disabled = state.step === 0;
  $("#wizard-next").classList.toggle("hidden", state.step === 3);
  $("#screen-submit").classList.toggle("hidden", state.step !== 3);
  if (state.step === 3) updateReview();
  const activePanel = $(`[data-wizard-step="${state.step}"]`);
  if (scroll) activePanel?.scrollIntoView({ behavior: "smooth", block: "start" });
  if (focus) setTimeout(() => activePanel?.querySelector("input, select, button")?.focus({ preventScroll: true }), 350);
  requestGuidance();
}

function inputForField(field) {
  if (field === "urgent_event") return $('input[name="urgent_event_choice"]');
  return $(`#${field}`);
}

function openCorrection(field, message = "请核对这项信息后重新生成结果。") {
  const step = inputSteps[field] ?? 0;
  $("#results-zone").classList.add("hidden");
  $(".screening-shell").classList.remove("hidden");
  showStep(step, { scroll: true });
  const input = inputForField(field);
  const container = input?.closest(".field, .choice-block") || input;
  container?.classList.add("attention-field");
  setTimeout(() => {
    input?.focus({ preventScroll: true });
    setTimeout(() => container?.classList.remove("attention-field"), 2600);
  }, 420);
  toast(message, "success");
}

function saveDraft() {
  const fields = Object.fromEntries(draftFieldIds.map((id) => [id, $(`#${id}`)?.value ?? ""]));
  fields.urgent_event = urgentValue();
  try {
    sessionStorage.setItem("huimin-screening-draft-v2", JSON.stringify(fields));
    $("#draft-status span").textContent = "已在本标签页临时保存";
  } catch { /* private browsing may disable storage */ }
}

function restoreDraft() {
  let draft = null;
  try { draft = JSON.parse(sessionStorage.getItem("huimin-screening-draft-v2") || "null"); } catch { draft = null; }
  if (!draft) return false;
  Object.entries(draft).forEach(([key, value]) => setField(key, value));
  toggleUrgentFields();
  toggleSpecialHardshipFields();
  updateIncomePreview();
  $("#draft-status span").textContent = "已恢复本标签页中的未完成内容";
  return true;
}

function clearDraft({ announce = true } = {}) {
  try { sessionStorage.removeItem("huimin-screening-draft-v2"); } catch { /* no-op */ }
  $("#screening-form").reset();
  setField("query_date", todayISO());
  setField("deductible_monthly_total", 0);
  $("#narrative").value = "";
  $("#story-count").textContent = "0";
  $("#assistive-narrative").value = "";
  $("#assistive-story-count").textContent = "0";
  $("#assistive-extraction").classList.add("hidden");
  $("#supplement-result").classList.add("hidden");
  state.lastParse = null;
  state.assistiveParse = null;
  state.supplementAnalysis = null;
  state.supplementDecisions = {};
  state.analyzedSupplementText = "";
  toggleUrgentFields();
  toggleSpecialHardshipFields();
  updateIncomePreview();
  showStep(0, { scroll: true });
  $("#draft-status span").textContent = "本页填写内容会临时保留，关闭标签页后自动清除";
  if (announce) toast("已清空本次预筛内容。", "success");
}

let guidanceTimer = null;
function requestGuidance() {
  clearTimeout(guidanceTimer);
  guidanceTimer = setTimeout(async () => {
    const payload = formPayload();
    if (!payload.household_size) return;
    try {
      const result = await api("/api/v1/guidance/next-question", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (result.next_question) {
        const question = result.next_question.plain_language || result.next_question.label;
        $("#smart-question").textContent = `还建议确认：${question}`;
        $("#smart-question-reason").textContent = result.next_question.reason || "这项信息会影响预筛结果。";
      } else {
        $("#smart-question").textContent = "关键问题已完成";
        $("#smart-question-reason").textContent = "当前信息已经能够执行预筛；仍会保留无法确认的政策条件。";
      }
    } catch { /* guidance is progressive enhancement */ }
  }, 280);
}

async function parseAssistiveNarrative() {
  const text = $("#assistive-narrative").value.trim();
  if (text.length < 2) return toast("请先写一句已经知道的基本情况。", "error");
  loading(true, "本地AI正在生成待核对草稿");
  const coldStartNotice = setTimeout(() => {
    $("#loading-text").textContent = "本地模型首次启动可能需要1—2分钟，之后会明显加快";
  }, 12000);
  try {
    const result = await api("/api/v1/profile/parse", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, query_date: valueOrNull("query_date") || todayISO(), district: valueOrNull("district") }) });
    state.assistiveParse = result;
    const facts = Object.entries(result.fields || {}).filter(([key, value]) => !["query_date", "city"].includes(key) && value !== null && value !== undefined);
    const latency = result.latency_ms ? ` · ${(result.latency_ms / 1000).toFixed(1)}秒` : "";
    const provider = result.mode === "llm_assisted" ? `本地大模型 · ${result.model_id || result.provider}${latency}` : `安全规则抽取${latency}`;
    const missing = (result.missing_fields || []).map((key) => fieldLabels[key] || key);
    $("#assistive-extraction").classList.remove("hidden");
    $("#assistive-extraction").innerHTML = `<div class="ai-result-head"><div><h3>${facts.length ? `识别到 ${facts.length} 项待核对信息` : "没有识别出可直接使用的事实"}</h3><p>${facts.length ? "尚未写入表单。采用草稿后仍需逐项核对，尤其是金额和成员范围。" : "像“家庭条件很好”这样的模糊描述不会被擅自换算成收入或资产。"}</p></div><span class="ai-provider">${escapeHtml(provider)}</span></div><div class="extracted-facts">${facts.map(([key, value]) => `<span>${escapeHtml(fieldLabels[key] || key)}：${escapeHtml(typeof value === "boolean" ? booleanText(value) : value)}</span>`).join("") || "<span>请逐项填写可量化信息</span>"}</div>${missing.length ? `<p>仍需你确认：${escapeHtml(missing.slice(0, 5).join("、"))}</p>` : ""}${(result.warnings || []).map((warning) => `<p>${escapeHtml(warning)}</p>`).join("")}${facts.length ? '<button class="continue-after-ai" type="button" data-continue-assistive>采用草稿并逐项核对</button>' : ""}`;
    toast(result.mode === "llm_assisted" ? "本地大模型已生成待核对草稿。" : "已使用安全规则生成待核对草稿。", "success");
  } catch (error) { toast(error.message, "error"); }
  finally { clearTimeout(coldStartNotice); loading(false); }
}

function applyAssistiveDraft() {
  const result = state.assistiveParse;
  if (!result) return;
  Object.entries(result.fields || {}).forEach(([key, value]) => setField(key, value));
  state.lastParse = result;
  updateIncomePreview();
  saveDraft();
  $("#ai-helper").open = false;
  const nextField = result.missing_fields?.find((field) => inputSteps[field] !== undefined) || "district";
  openCorrection(nextField, "辅助草稿已采用，请逐项核对后继续。");
}

function clearField(field) {
  if (field === "urgent_event") {
    $$('input[name="urgent_event_choice"]').forEach((radio) => { radio.checked = radio.value === ""; });
    toggleUrgentFields();
    return;
  }
  const target = $(`#${field}`);
  if (target) target.value = "";
}

function supplementCandidate(candidateId) {
  return state.supplementAnalysis?.candidates?.find((item) => item.candidate_id === candidateId) || null;
}

function pendingSupplementCandidates() {
  if (!state.supplementAnalysis) return [];
  return state.supplementAnalysis.candidates.filter((candidate) => (
    candidate.requires_confirmation && !state.supplementDecisions[candidate.candidate_id]
  ));
}

function setSupplementDecision(candidateId, action) {
  const candidate = supplementCandidate(candidateId);
  if (!candidate) return;
  if (action === "confirmed") {
    setField(candidate.field, candidate.proposed_value);
    state.supplementDecisions[candidateId] = "confirmed";
    toast(`已采用“${candidate.label}”，并写入待提交表单。`, "success");
  } else if (action === "rejected") {
    state.supplementDecisions[candidateId] = "rejected";
    toast(candidate.comparison === "conflict" ? "已保留原表单内容。" : "已标记为不采用。", "success");
  } else if (action === "reset") {
    if (state.supplementDecisions[candidateId] === "confirmed") {
      if (candidate.existing_value === null || candidate.existing_value === undefined) clearField(candidate.field);
      else setField(candidate.field, candidate.existing_value);
    }
    delete state.supplementDecisions[candidateId];
  }
  updateIncomePreview();
  updateReview();
  toggleUrgentFields();
  saveDraft();
  requestGuidance();
  renderSupplementResult();
}

function renderSupplementCandidate(candidate) {
  const decision = state.supplementDecisions[candidate.candidate_id];
  const comparisonLabel = {
    new: "表单未填写",
    consistent: "与表单一致",
    conflict: "与表单冲突",
  }[candidate.comparison];
  let actions = '<span class="candidate-resolved consistent">无需改动</span>';
  if (candidate.requires_confirmation && !decision) {
    const confirmLabel = candidate.comparison === "conflict" ? "以补充说明为准" : "确认并采用";
    const rejectLabel = candidate.comparison === "conflict" ? "保留原填写" : "不采用";
    actions = `<div class="candidate-actions"><button type="button" data-candidate-action="confirmed" data-candidate-id="${escapeHtml(candidate.candidate_id)}">${confirmLabel}</button><button type="button" data-candidate-action="rejected" data-candidate-id="${escapeHtml(candidate.candidate_id)}">${rejectLabel}</button></div>`;
  } else if (decision) {
    actions = `<div class="candidate-resolved ${decision}"><span>${decision === "confirmed" ? "✓ 已由你确认并写入表单" : "— 已由你选择不采用"}</span><button type="button" data-candidate-action="reset" data-candidate-id="${escapeHtml(candidate.candidate_id)}">重新选择</button></div>`;
  }
  const comparison = candidate.comparison === "conflict"
    ? `<div class="candidate-comparison"><span>原表单<strong>${escapeHtml(candidate.existing_display || "尚未填写")}</strong></span><b aria-hidden="true">↔</b><span>补充说明<strong>${escapeHtml(candidate.display_value)}</strong></span></div>`
    : `<div class="candidate-value"><span>识别结果</span><strong>${escapeHtml(candidate.display_value)}</strong></div>`;
  return `<article class="supplement-candidate ${escapeHtml(candidate.comparison)} ${decision ? `decided ${decision}` : ""}"><div class="candidate-head"><div><span>${escapeHtml(comparisonLabel)}</span><h4>${escapeHtml(candidate.label)}</h4></div><em>${Math.round(candidate.extraction_score * 100)} · 抽取排序分</em></div>${comparison}<blockquote><span>原句依据</span>${escapeHtml(candidate.source_quote)}</blockquote><p>${escapeHtml(candidate.reason)}</p>${actions}</article>`;
}

function renderSupplementResult() {
  const result = state.supplementAnalysis;
  const target = $("#supplement-result");
  if (!result) {
    target.classList.add("hidden");
    target.innerHTML = "";
    return;
  }
  target.classList.remove("hidden");
  if (["blocked_sensitive_data", "blocked_instruction", "out_of_scope"].includes(result.status)) {
    const title = result.status === "blocked_sensitive_data" ? "请先删除敏感信息" : result.status === "blocked_instruction" ? "本次分析已安全阻断" : "没有识别到社会救助相关内容";
    target.innerHTML = `<div class="supplement-refusal"><span aria-hidden="true">!</span><div><h3>${title}</h3><p>${escapeHtml(result.warnings?.[0] || "请修改补充说明后重试。")}</p><small>模型未参与资格判断，表单内容没有变化。</small></div></div>`;
    return;
  }
  const pending = pendingSupplementCandidates().length;
  const confirmed = confirmedSupplementFields().length;
  const provider = result.mode === "llm_assisted" ? `本地大模型 · ${result.model_id || result.provider}` : "安全规则与受控抽取";
  const candidates = result.candidates?.length
    ? `<section class="supplement-block"><div class="supplement-block-title"><div><span>01 · 候选事实</span><h3>逐条确认后才能进入规则计算</h3></div><b>${pending ? `${pending}项待处理` : "已处理"}</b></div><div class="candidate-grid">${result.candidates.map(renderSupplementCandidate).join("")}</div></section>`
    : '<section class="supplement-empty"><strong>没有发现可直接写入表单的明确事实</strong><p>系统不会把模糊描述强行转换成金额或资格条件。</p></section>';
  const clues = result.clues?.length
    ? `<section class="supplement-block"><div class="supplement-block-title"><div><span>02 · 特殊情况线索</span><h3>这些内容值得继续核对</h3></div><b>${result.clues.length}类</b></div><div class="clue-list">${result.clues.map((clue) => `<article><strong>${escapeHtml(clue.label)}</strong><blockquote>${escapeHtml(clue.source_quote)}</blockquote><p>${escapeHtml(clue.implication)}</p></article>`).join("")}</div></section>`
    : "";
  const questions = result.follow_up_questions?.length
    ? `<section class="supplement-block"><div class="supplement-block-title"><div><span>03 · 最少追问</span><h3>补充这些信息，判断会更明确</h3></div><b>${result.follow_up_questions.length}问</b></div><div class="follow-up-list">${result.follow_up_questions.map((question) => `<article><div><strong>${escapeHtml(question.question)}</strong><p>${escapeHtml(question.reason)}</p></div>${question.field_id ? `<button type="button" data-supplement-field="${escapeHtml(question.field_id)}">去补充</button>` : ""}</article>`).join("")}</div></section>`
    : "";
  const impacts = result.impact_directions?.length
    ? `<details class="impact-directions"><summary>查看可能受影响的政策方向（${result.impact_directions.length}项）</summary><div>${result.impact_directions.map((item) => `<article><strong>${escapeHtml(item.benefit_name)}</strong><p>${escapeHtml(item.reason)}</p></article>`).join("")}</div></details>`
    : "";
  const ambiguity = result.ambiguities?.length
    ? `<div class="ambiguity-panel"><strong>AI没有替你猜的内容</strong><ul>${result.ambiguities.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`
    : "";
  target.innerHTML = `<div class="supplement-summary"><div><span>分析完成 · ${escapeHtml(provider)}</span><h3>${pending ? `还有 ${pending} 项需要你决定` : confirmed ? `已确认 ${confirmed} 项补充事实` : "没有待确认的候选事实"}</h3><p>${escapeHtml(result.disclaimer)}</p></div><div class="supplement-audit"><span>敏感信息门 ✓</span><span>指令攻击门 ✓</span><span>领域门 ✓</span><span>原句锚定 ✓</span></div></div>${candidates}${ambiguity}${clues}${questions}${impacts}`;
}

async function analyzeSupplement() {
  const text = $("#narrative").value.trim();
  if (text.length < 2) return toast("没有其他情况可以直接跳过；需要补充时请先写一句说明。", "error");
  loading(true, "本地AI正在检查特殊情况、矛盾与信息缺口");
  const coldStartNotice = setTimeout(() => {
    $("#loading-text").textContent = "本地模型首次启动可能需要1—2分钟，分析期间不会自动修改表单";
  }, 12000);
  try {
    const result = await api("/api/v1/profile/analyze-supplement", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, profile: profileDraftPayload() }),
    });
    state.supplementAnalysis = result;
    state.supplementDecisions = {};
    state.analyzedSupplementText = text;
    renderSupplementResult();
    saveDraft();
    if (result.status.startsWith("blocked") || result.status === "out_of_scope") toast(result.warnings?.[0] || "本次分析未执行。", "error");
    else toast("补充情况分析完成，请逐条确认候选事实。", "success");
  } catch (error) { toast(error.message, "error"); }
  finally { clearTimeout(coldStartNotice); loading(false); }
}

function invalidateSupplementIfChanged() {
  if (!state.supplementAnalysis) return;
  if ($("#narrative").value.trim() === state.analyzedSupplementText) return;
  state.supplementAnalysis = null;
  state.supplementDecisions = {};
  state.analyzedSupplementText = "";
  renderSupplementResult();
  toast("补充说明已修改，请重新分析。", "success");
}

function safetyGateAllowsReport(report) {
  const enforcement = report?.safety_validation?.enforcement;
  return report?.safety_validation?.safe === true && report?.safety_validation?.blocked === false && ["api_publish", "persistence", "presentation", "print_export"].every((key) => enforcement?.[key] === true);
}

function renderCondition(condition) {
  const symbols = { true: "✓", false: "×", unknown: "?" };
  const fallback = condition.state === "true" ? "满足" : condition.state === "false" ? "不满足" : "尚未确认";
  const value = condition.actual ?? condition.expected ?? fallback;
  const fix = condition.state === "unknown" && condition.input_field ? `<button class="condition-fix" type="button" data-fix-field="${escapeHtml(condition.input_field)}">去确认</button>` : "";
  return `<div class="condition-row ${escapeHtml(condition.state)}"><span class="condition-state">${symbols[condition.state] || "?"}</span><div><strong>${escapeHtml(condition.label)}</strong><p>${escapeHtml(condition.reason)}${condition.action_hint ? ` ${escapeHtml(condition.action_hint)}` : ""}</p></div><span class="condition-value">${escapeHtml(value)}</span>${fix}</div>`;
}

function unresolvedInputs(report) {
  const unique = new Map();
  report.results.forEach((item) => item.conditions
    .filter((condition) => condition.state === "unknown" && condition.input_field)
    .forEach((condition) => {
      if (!unique.has(condition.input_field)) unique.set(condition.input_field, {
        field: condition.input_field,
        label: condition.label,
        hint: condition.action_hint || condition.reason,
      });
    }));
  return [...unique.values()];
}

function renderResolutionPanel(report) {
  const unresolved = unresolvedInputs(report);
  $("#resolution-panel").classList.toggle("hidden", unresolved.length === 0);
  $("#resolution-actions").innerHTML = unresolved.map((item) => `<button type="button" data-fix-field="${escapeHtml(item.field)}"><span>待确认</span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.hint)}</small><b aria-hidden="true">→</b></button>`).join("");
}

function renderBenefitCard(item, { lead = false, category = "match" } = {}) {
  const badges = { match: lead ? "优先核对" : "可能匹配", related: item.plan_role === "linked" ? "关联服务" : "后续核对", review: "还需确认", no: "当前未匹配" };
  const reasonTitle = category === "no" ? "为什么当前未匹配" : category === "review" ? "还缺什么" : "为什么值得核对";
  const evidence = item.evidence.map((entry) => `<a href="${escapeHtml(entry.source_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(entry.title)} · ${escapeHtml(entry.article || "相关条款")} ↗</a>`).join("");
  const open = lead ? " open" : "";
  return `<details class="benefit-card ${lead ? "lead" : ""}"${open}><summary><div><div class="benefit-title-row"><h4>${escapeHtml(item.name)}</h4><span class="result-badge ${category}">${badges[category]}</span></div><p>${escapeHtml(item.plan_reason || item.summary)}</p></div><span class="expand-label">查看依据</span></summary><div class="benefit-body"><div class="plain-reason"><strong>${reasonTitle}</strong><p>${escapeHtml(item.summary)}</p></div><div class="condition-table">${item.conditions.map(renderCondition).join("")}</div><div class="benefit-columns"><div><h5>下一步</h5><ul>${item.next_actions.map((action) => `<li>${escapeHtml(action)}</li>`).join("")}</ul></div><div><h5>可能需要的材料</h5><ul>${item.materials.map((material) => `<li>${escapeHtml(material)}</li>`).join("")}</ul></div></div><details class="evidence-fold"><summary>查看政策原文依据（${item.evidence.length}条）</summary><div class="evidence-links">${evidence}</div></details></div></details>`;
}

function computeOutcomeFallback(report) {
  const matched = report.results.filter((item) => item.status === "likely");
  const primary = matched.filter((item) => item.plan_role === "primary");
  const related = matched.filter((item) => item.plan_role !== "primary");
  const review = report.results.filter((item) => ["incomplete", "manual_review"].includes(item.status));
  if (matched.length) return { code: "possible_match", title: primary.length ? `发现${primary.length}个需要优先核对的救助方向` : `发现${matched.length}个可能方向，但应先核对前置条件`, detail: `这是申请前预筛，不代表已经取得资格。${related.length ? `另有${related.length}个关联或后续方向。` : ""}`, lead_benefit_id: primary[0]?.benefit_id || matched[0].benefit_id };
  if (review.length) return { code: "needs_information", title: "现有信息不足，暂时不能判断", detail: "系统保留了未知项，没有用猜测填补信息。", lead_benefit_id: review[0].benefit_id };
  return { code: "no_current_match", title: "根据目前信息，暂未发现匹配的救助方向", detail: "系统没有强行推荐任何事项；你可以补充或修改信息后重新预筛。", lead_benefit_id: null };
}

function renderReport(report) {
  if (!safetyGateAllowsReport(report)) return renderSafetyBlock({ message: "本次结果没有取得完整的安全发布凭据。" });
  state.report = report;
  state.reportSafetyPassed = true;
  state.screeningId = report.screening_id;
  state.screeningToken = report.screening_token || null;
  document.body.dataset.reportSafety = "passed";
  const outcome = report.outcome?.code ? report.outcome : computeOutcomeFallback(report);
  const banner = $("#outcome-banner");
  banner.className = `outcome-banner ${outcome.code === "no_current_match" ? "no-match" : outcome.code === "needs_information" ? "needs-information" : ""}`;
  $("#result-title").textContent = outcome.title;
  $("#outcome-detail").textContent = outcome.detail;
  const profile = report.profile_summary || {};
  $("#calculation-summary").innerHTML = `<div><span>共同生活人数</span><strong>${escapeHtml(profile.household_size)}人</strong></div><div><span>计算后人均月收入</span><strong>${profile.per_capita_monthly_income === null ? "尚未提供" : `${escapeHtml(profile.per_capita_monthly_income)}元`}</strong></div><div><span>适用政策快照</span><strong>${escapeHtml(report.query_date)} · ${escapeHtml(report.district)}</strong></div>`;
  const likely = report.results.filter((item) => item.status === "likely");
  const matched = likely.filter((item) => item.plan_role === "primary");
  const related = likely.filter((item) => item.plan_role !== "primary");
  const review = report.results.filter((item) => ["incomplete", "manual_review"].includes(item.status));
  const unmatched = report.results.filter((item) => item.status === "unlikely");
  $("#matched-section").classList.toggle("hidden", matched.length === 0);
  $("#related-section").classList.toggle("hidden", related.length === 0);
  $("#review-section").classList.toggle("hidden", review.length === 0);
  $("#unmatched-section").classList.toggle("hidden", unmatched.length === 0);
  $("#matched-results").innerHTML = matched.map((item) => renderBenefitCard(item, { lead: item.benefit_id === outcome.lead_benefit_id, category: "match" })).join("");
  $("#related-results").innerHTML = related.map((item) => renderBenefitCard(item, { lead: matched.length === 0 && item.benefit_id === outcome.lead_benefit_id, category: "related" })).join("");
  $("#review-results").innerHTML = review.map((item, index) => renderBenefitCard(item, { lead: matched.length === 0 && index === 0, category: "review" })).join("");
  $("#unmatched-count").textContent = `${unmatched.length}项`;
  $("#unmatched-results").innerHTML = unmatched.map((item) => renderBenefitCard(item, { category: "no" })).join("");
  renderResolutionPanel(report);
  const payload = formPayload();
  const urgent = payload.urgent_event === true && payload.basic_life_interrupted === true;
  $("#urgent-result").classList.toggle("hidden", !urgent);
  if (urgent) $("#urgent-result").innerHTML = "<strong>请优先处理眼前困难：</strong>基本生活已经受到严重影响，请先联系所在街道或广州12345，不必等待材料全部备齐。";
  const office = report.recommended_office;
  const lead = report.results.find((item) => item.benefit_id === outcome.lead_benefit_id);
  const heading = outcome.code === "no_current_match" ? "接下来可以这样做" : lead ? `先核对：${lead.name}` : "先补齐关键信息";
  $("#next-action-card").innerHTML = `<span>行动建议</span><h3>${escapeHtml(heading)}</h3><div class="action-list">${report.guidance_summary.map((action, index) => `<p><span class="action-number" aria-hidden="true">${index + 1}</span><span>${escapeHtml(action)}</span></p>`).join("")}</div>${office ? `<div class="office-box"><span>属地咨询窗口</span><strong>${escapeHtml(office.office_name)}</strong><p>${escapeHtml(office.address)}</p><a href="tel:${escapeHtml(office.phone)}">${escapeHtml(office.phone)}</a><p>出发前请电话确认地址、时间和材料。</p></div>` : ""}`;
  const runtime = state.metadata?.ai_runtime || {};
  const supplementConfirmed = report.profile_summary?.confirmed_supplement_count || 0;
  const parseText = state.supplementAnalysis
    ? `${state.supplementAnalysis.mode === "llm_assisted" ? "本地大模型" : "受控解析"}分析补充情况，${supplementConfirmed}项经用户确认，${state.supplementAnalysis.candidates.filter((item) => item.comparison === "conflict").length}项冲突由用户处理`
    : state.lastParse
      ? `${state.lastParse.mode === "llm_assisted" ? "本地大模型" : "确定性解析"}辅助录入，识别${Object.keys(state.lastParse.fields || {}).length}项，Schema${state.lastParse.schema_validated ? "通过" : "未通过"}`
      : "本次使用逐项表单，无自然语言推断";
  const passed = report.safety_validation?.checks?.filter((check) => check.passed).length || 0;
  $("#audit-trail-content").innerHTML = `<div class="audit-step"><span>1 · 信息整理</span><strong>${escapeHtml(parseText)}</strong></div><div class="audit-step"><span>2 · 政策规则</span><strong>${escapeHtml(report.engine_version)} · 三态求值</strong></div><div class="audit-step"><span>3 · 证据与时态</span><strong>${escapeHtml(report.policy_snapshot)}</strong></div><div class="audit-step"><span>4 · 发布安全门</span><strong>${escapeHtml(passed)}项检查通过 · ${escapeHtml(runtime.mode || "unknown")}</strong></div>`;
  $("#report-boundary").textContent = report.disclaimer;
  $("#print-report").disabled = false;
  $("#data-actions").classList.toggle("hidden", !report.persisted || !report.screening_token);
  $("#results-zone").classList.remove("hidden");
  $(".screening-shell").classList.add("hidden");
  $("#results-zone").scrollIntoView({ behavior: "smooth", block: "start" });
  return true;
}

function handleResultAction(action) {
  if (action === "edit") {
    $("#results-zone").classList.add("hidden");
    $(".screening-shell").classList.remove("hidden");
    showStep(3, { scroll: true });
    return;
  }
  const outcome = state.report?.outcome?.code ? state.report.outcome : computeOutcomeFallback(state.report || { results: [] });
  const lead = state.report?.results?.find((item) => item.benefit_id === outcome.lead_benefit_id)
    || state.report?.results?.find((item) => item.status !== "unlikely");
  if (action === "documents") {
    if (lead?.benefit_id && $("#document-benefit option[value=\"" + lead.benefit_id + "\"]")) $("#document-benefit").value = lead.benefit_id;
    navigate("documents");
    toast(lead ? `已带入“${lead.name}”材料清单。` : "请先选择准备咨询的事项。", "success");
  }
  if (action === "evidence") {
    if (lead) $("#evidence-query").value = `${lead.name}的申请条件、材料和办理流程是什么`;
    navigate("evidence");
    $("#evidence-query").focus({ preventScroll: true });
  }
}

function renderSafetyBlock(details = {}) {
  state.reportSafetyPassed = false;
  $("#print-report").disabled = true;
  $("#print-safety-block").classList.remove("hidden");
  $("#print-safety-block").innerHTML = `<strong>结果已被安全门阻断</strong><p>${escapeHtml(details.message || "输入、政策证据或判断边界未通过校验，本次结果没有展示、保存或开放打印。")}</p>`;
  toast(details.message || "安全校验未通过。", "error");
  return false;
}

async function submitScreening(event) {
  event.preventDefault();
  if (!$("#screening-consent").checked) return toast("请先确认你已理解申请前预筛的使用边界。", "error");
  const pendingSupplement = pendingSupplementCandidates();
  if (pendingSupplement.length) {
    $("#supplement-result").scrollIntoView({ behavior: "smooth", block: "start" });
    return toast(`请先处理AI提出的${pendingSupplement.length}项候选事实；可以采用，也可以明确选择不采用。`, "error");
  }
  const payload = formPayload();
  if (!payload.household_size) return toast("请填写共同生活家庭成员人数。", "error");
  state.reportSafetyPassed = false;
  loading(true, "正在对照有效政策并执行安全检查");
  try {
    const persist = $("#persist-screening").checked;
    const report = await api(`/api/v1/screenings?persist=${persist}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (renderReport(report)) toast("预筛完成：结果已按匹配程度分层。", "success");
  } catch (error) {
    if (error.code === "SAFETY_GATE_BLOCKED") renderSafetyBlock(error.details);
    else toast(error.message, "error");
  } finally { loading(false); }
}

function resetScreening({ clear = true } = {}) {
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  $("#results-zone").classList.add("hidden");
  $(".screening-shell").classList.remove("hidden");
  $("#print-safety-block").classList.add("hidden");
  if (clear) {
    clearDraft({ announce: false });
  }
  showStep(clear ? 0 : 3, { scroll: true });
}

function readCurrentReport() {
  if (!state.reportSafetyPassed || !state.report) return toast("安全门未放行，不能朗读结果。", "error");
  if (!("speechSynthesis" in window) || typeof SpeechSynthesisUtterance === "undefined") return toast("当前浏览器不支持本地朗读。", "error");
  const outcome = state.report.outcome?.title || computeOutcomeFallback(state.report).title;
  const directions = state.report.results
    .filter((item) => item.status !== "unlikely")
    .slice(0, 3)
    .map((item) => `${item.name}：${item.status === "likely" ? "可能匹配" : "需要补充信息"}。${item.plan_reason || ""}`);
  const actions = (state.report.guidance_summary || []).slice(0, 3);
  const text = ["惠民智导预筛结果。", outcome, ...directions, "下一步建议。", ...actions, state.report.disclaimer].filter(Boolean).join(" ");
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 0.92;
  utterance.onerror = () => toast("本地朗读未能启动，请检查系统语音设置。", "error");
  window.speechSynthesis.speak(utterance);
  toast("正在使用浏览器本地语音朗读结果。", "success");
}

async function deleteScreening() {
  if (!state.screeningId || !state.screeningToken) return;
  if (!window.confirm("确定立即删除这次保存的结构化结果吗？删除后无法恢复。")) return;
  try {
    await api(`/api/v1/screenings/${encodeURIComponent(state.screeningId)}`, { method: "DELETE", headers: { "X-Screening-Token": state.screeningToken } });
    state.screeningId = null; state.screeningToken = null;
    $("#data-actions").classList.add("hidden");
    toast("已删除这次保存的结构化结果。", "success");
  } catch (error) { toast(error.message, "error"); }
}

function loadDemo() {
  const values = { query_date: "2026-09-30", district: "天河区", household_size: 3, is_local_hukou: true, residence_proof: null, member_scope_confirmed: true, monthly_income_total: 3200, deductible_monthly_total: 0, assets_eligible: true, financial_assets_per_capita: 4000, medical_expenses_12m: 30000, education_expenses_12m: 0, rigid_expenses_12m: 30000, urgent_event: true, urgent_event_type: "突发急病", urgent_event_date: "2026-09-15", basic_life_interrupted: true, special_person_category_confirmed: false };
  Object.entries(values).forEach(([key, value]) => setField(key, value));
  $("#narrative").value = "";
  $("#story-count").textContent = "0";
  toggleSpecialHardshipFields();
  updateIncomePreview();
  saveDraft();
  showStep(3, { scroll: true });
  toast("示例信息已载入，请核对后生成结果。", "success");
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function selectFiles(files) {
  state.selectedFiles = [...(files || [])];
  const count = state.selectedFiles.length;
  const total = state.selectedFiles.reduce((sum, file) => sum + file.size, 0);
  $("#upload-selection").classList.toggle("empty", count === 0);
  $("#drop-zone").classList.toggle("has-files", count > 0);
  $("#selected-file-title").textContent = count ? `已选择 ${count} 份材料` : "尚未选择材料";
  $("#selected-file-count").textContent = count ? formatFileSize(total) : "0份";
  $("#selected-file-list").replaceChildren(...state.selectedFiles.map((file) => { const li = document.createElement("li"); const name = document.createElement("strong"); const size = document.createElement("span"); name.textContent = file.name; size.textContent = formatFileSize(file.size); li.append(name, size); return li; }));
  $("#clear-selected-files").disabled = count === 0;
  $("#check-document").disabled = count === 0;
}

function renderDocumentPackage(result) {
  const labels = { identity: "身份类证明", household_register: "户口簿", income: "收入证明", medical_expense: "医疗支出凭据", medical_diagnosis: "诊断材料", education_expense: "教育支出凭据", residence: "居住证明", verification_authorization: "经济状况核对授权书", unknown: "待人工分类" };
  const cards = result.documents.map((doc) => `<article class="document-file-card"><div><strong>${escapeHtml(labels[doc.detected_type] || doc.detected_type)}</strong><span class="quality-badge ${doc.quality_score >= 75 ? "" : "warn"}">${escapeHtml(doc.quality_score)}分</span></div><p>${escapeHtml(doc.file_name)} · ${formatFileSize(doc.file_size)} · 指纹 ${escapeHtml(doc.sha256_prefix)}</p><div class="check-grid">${doc.checks.map((check) => `<div class="check-item ${check.passed ? "passed" : "failed"}"><span>${escapeHtml(check.label)}</span><b>${check.passed ? "通过" : "需改进"} · ${escapeHtml(check.value)}</b></div>`).join("")}</div>${doc.ocr?.enabled ? `<div class="ocr-summary"><strong>本地OCR已运行</strong><p>识别${escapeHtml(doc.ocr.line_count)}行；日期候选：${escapeHtml((doc.ocr.extracted_fields?.date_candidates || []).join("、") || "无")}；金额候选：${escapeHtml((doc.ocr.extracted_fields?.amount_candidates || []).join("、") || "无")}</p></div>` : ""}${doc.warnings.map((warning) => `<p class="document-warning">${escapeHtml(warning)}</p>`).join("")}</article>`).join("");
  $("#document-result").innerHTML = `<div class="package-status ${result.ready_for_manual_review ? "ready" : "needs-work"}"><span>${result.ready_for_manual_review ? "✓" : "!"}</span><div><h3>${result.ready_for_manual_review ? "材料包已具备人工复核条件" : "建议补齐或重拍后再咨询"}</h3><p>已检查${escapeHtml(result.files_checked)}份材料；${escapeHtml(result.disclaimer)}</p></div></div><div class="package-summary"><div><strong>建议材料</strong><p>${result.required_materials.map(escapeHtml).join("、") || "以窗口告知为准"}</p></div><div><strong>识别到</strong><p>${result.detected_materials.map(escapeHtml).join("、") || "尚未识别"}</p></div><div><strong>还建议补充</strong><p>${result.missing_recommended.map(escapeHtml).join("、") || "暂未发现明显缺项"}</p></div></div>${cards}`;
}

async function checkDocuments() {
  if (!state.selectedFiles.length) return toast("请先选择材料。", "error");
  if (!$("#document-consent").checked) return toast("请先确认本次本地处理同意。", "error");
  const data = new FormData();
  state.selectedFiles.forEach((file) => data.append("files", file));
  data.append("benefit_id", $("#document-benefit").value); data.append("consent", "true");
  loading(true, "正在执行本地OCR和质量检查");
  try { renderDocumentPackage(await api("/api/v1/documents/package-precheck", { method: "POST", body: data })); toast("材料检查完成。", "success"); }
  catch (error) { toast(error.message, "error"); }
  finally { loading(false); }
}

async function searchEvidence() {
  const query = $("#evidence-query").value.trim();
  if (query.length < 2) return toast("请至少输入两个字。", "error");
  const target = $("#evidence-results");
  target.innerHTML = '<div class="empty-illustration compact"><span class="spinner"></span><h2>正在检索并核验答案</h2><p>本地模型首次启动可能需要更长时间</p></div>';
  try {
    const asOf = valueOrNull("evidence-as-of") || todayISO();
    const result = await api("/api/v1/policy/answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: query, as_of: asOf, max_evidence: 6 }) });
    if (result.status !== "answered") {
      const statusLabel = result.status === "blocked_sensitive_data" ? "隐私保护已阻断" : result.status === "blocked_instruction" ? "安全规则已阻断" : result.status === "out_of_scope" ? "超出当前知识范围" : "证据不足";
      target.innerHTML = `<section class="answer-refusal" role="status"><span>${escapeHtml(statusLabel)}</span><h2>${escapeHtml(result.answer_title)}</h2>${(result.unanswered || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("")}<small>本次没有调用大模型生成政策答案，也没有把域外问题强行匹配到政策。</small></section>`;
      return;
    }
    const retriever = result.retrieval?.retriever?.name || "已核验证据检索";
    const generation = result.generation?.mode === "grounded_local_llm" ? `本地模型 ${result.generation.model_id || ""}` : "逐字证据安全回退";
    const claims = result.claims.map((claim, index) => `<article class="answer-claim"><span>${String(index + 1).padStart(2, "0")}</span><div><p>${escapeHtml(claim.text)}</p><div>${claim.evidence_ids.map((id) => `<a href="#evidence-${escapeHtml(id)}">依据 ${escapeHtml(id)}</a>`).join("")}</div></div></article>`).join("");
    const evidenceCards = result.evidence.map((evidence) => `<article class="evidence-card" id="evidence-${escapeHtml(evidence.evidence_id)}"><div class="evidence-card-head"><div><h3>${escapeHtml(evidence.title)}</h3><p class="source-meta">${escapeHtml(evidence.document_no || "公开资料")} · ${escapeHtml(evidence.article || "相关内容")} · ${escapeHtml(evidence.locator || "已登记定位")}</p></div><span class="score-pill">${escapeHtml(evidence.evidence_id)}</span></div><div class="evidence-quote"><strong>政策逐字原文 · ${evidence.quote_verified ? "已核验" : "待复核"}</strong><p>${escapeHtml(evidence.verbatim_quote || evidence.excerpt)}</p></div>${evidence.plain_language_explanation ? `<div class="evidence-explanation"><strong>通俗解释</strong><p>${escapeHtml(evidence.plain_language_explanation)}</p></div>` : ""}<a href="${escapeHtml(evidence.source_url)}" target="_blank" rel="noopener noreferrer">查看政府原文 ↗</a></article>`).join("");
    target.innerHTML = `<section class="policy-answer"><div class="policy-answer-head"><div><span>查询日 ${escapeHtml(result.as_of)}</span><h2>${escapeHtml(result.answer_title)}</h2></div><b>${escapeHtml(generation)}</b></div><div class="answer-claims">${claims}</div>${result.unanswered?.length ? `<div class="answer-uncertainty"><strong>仍不能由本系统确定</strong>${result.unanswered.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}</div>` : ""}<details class="answer-audit"><summary>查看本次AI如何受控</summary><div><p><b>领域门：</b>${result.retrieval?.domain_gate?.passed ? "通过" : "未通过"}</p><p><b>检索：</b>${escapeHtml(retriever)}；候选${escapeHtml(result.retrieval?.candidate_evidence_count || 0)}条，最终引用${escapeHtml(result.retrieval?.cited_evidence_count || 0)}条；已排除${escapeHtml(result.retrieval?.temporal_filter?.excluded_evidence || 0)}条非有效期证据</p><p><b>生成：</b>${escapeHtml(generation)}${result.generation?.latency_ms ? `，${escapeHtml(result.generation.latency_ms)}ms` : ""}</p><p><b>发布校验：</b>引用白名单、数值来源、越权表达、逐字核验均通过</p></div></details><p class="answer-boundary">${escapeHtml(result.disclaimer)}</p></section><div class="evidence-divider"><span>引用原文</span><p>只展示上方结论实际引用的证据</p></div>${evidenceCards}`;
  } catch (error) { target.innerHTML = `<div class="empty-illustration compact"><span>!</span><h2>检索未完成</h2><p>${escapeHtml(error.message)}</p></div>`; }
}

let sourcesLoaded = false;
async function loadSources() {
  if (sourcesLoaded) return;
  try {
    const sources = await api("/api/v1/policies"); sourcesLoaded = true;
    $("#source-count").textContent = sources.length;
    $("#source-list").innerHTML = sources.map((source) => `<article class="source-item"><strong>${escapeHtml(source.title)}</strong><p>${escapeHtml(source.issuer)} · ${escapeHtml(source.document_no || "公开资料")} · ${escapeHtml(source.status)}</p><a href="${escapeHtml(source.source_url)}" target="_blank" rel="noopener noreferrer">政府原文 ↗</a></article>`).join("");
  } catch (error) { toast(error.message, "error"); }
}

function renderTrust(metadata, readiness) {
  const ai = metadata.ai_runtime || {};
  const active = ai.active_provider?.startsWith("ollama/");
  $("#home-source-count").textContent = metadata.official_sources;
  $("#trust-policy-date").textContent = `政策核验至 ${metadata.policy_as_of}`;
  $("#trust-runtime-title").textContent = active ? "本地大模型与规则引擎协同运行" : "确定性安全底座运行中";
  $("#runtime-grid").innerHTML = [
    ["自然语言理解", active ? ai.active_provider : "确定性安全解析"], ["模型摘要校验", ai.model_digest_verified ? "通过" : "未启用/待核验"],
    ["向量检索模型", ai.embedding_model || "未启用"], ["资格判断", "确定性三态规则引擎"],
    ["运行边界", "仅本机回环地址"], ["原始材料保存", "不保存"],
  ].map(([label, value]) => `<div class="runtime-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
  const statusText = { ready: "全部就绪", ready_with_warnings: "核心就绪", blocked: "存在阻断" };
  $("#readiness-title").textContent = readiness.claim_boundary;
  $("#readiness-status").textContent = statusText[readiness.status] || readiness.status;
  $("#readiness-grid").innerHTML = readiness.checks.map((check) => `<div class="readiness-item ${escapeHtml(check.status)}"><div><strong>${escapeHtml(check.label)}</strong><p>${escapeHtml(check.detail)}</p></div><b>${check.status === "pass" ? "通过" : check.status === "warn" ? "提醒" : "阻断"}</b></div>`).join("");
  const runtimeStatus = $("#runtime-status");
  runtimeStatus.className = `runtime-pill ${readiness.status === "blocked" ? "warning" : "ready"}`;
  runtimeStatus.innerHTML = `<i></i><span>${active ? "本地AI已连接" : "规则引擎已就绪"}</span>`;
}

async function loadMetadata() {
  try {
    const metadata = await api("/api/v1/metadata");
    state.metadata = metadata;
    const ai = metadata.ai_runtime || {};
    const active = ai.active_provider?.startsWith("ollama/");
    $("#home-source-count").textContent = metadata.official_sources;
    $("#trust-policy-date").textContent = `政策核验至 ${metadata.policy_as_of}`;
    $("#runtime-status").className = "runtime-pill ready";
    $("#runtime-status").innerHTML = `<i></i><span>${active ? "本地AI已连接" : "规则引擎已就绪"}</span>`;
  } catch {
    $("#runtime-status").className = "runtime-pill warning";
    $("#runtime-status").innerHTML = "<i></i><span>服务未连接</span>";
    return;
  }
  try {
    const readiness = await api("/api/v1/system/readiness");
    state.readiness = readiness;
    renderTrust(state.metadata, readiness);
  } catch {
    $("#readiness-title").textContent = "服务已连接，就绪度检查暂未完成";
    $("#readiness-status").textContent = "稍后可重试";
  }
}

function setProfessionalTab(tab) {
  $$("[data-pro-tab]").forEach((button) => { const active = button.dataset.proTab === tab; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); });
  $$("[data-pro-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.proPanel === tab));
  if (tab === "governance") loadAdmin();
}

async function runWorker(event) {
  event.preventDefault(); state.workerSafetyPassed = false;
  const urgent = boolOrNull("worker-urgent");
  const specialGateway = boolOrNull("worker-special-category");
  const payload = { query_date: valueOrNull("worker-query-date"), city: "广州市", district: valueOrNull("worker-district"), household_size: numberOrNull("worker-household-size"), is_local_hukou: boolOrNull("worker-hukou"), member_scope_confirmed: boolOrNull("worker-member"), monthly_income_total: numberOrNull("worker-income"), deductible_monthly_total: 0, assets_eligible: boolOrNull("worker-assets"), rigid_expenses_12m: numberOrNull("worker-expenses"), urgent_event: urgent, urgent_event_date: urgent === true ? valueOrNull("worker-query-date") : null, basic_life_interrupted: urgent === true ? true : null, special_person_category_confirmed: specialGateway, no_labor_capacity: specialGateway === true ? boolOrNull("worker-no-labor") : null, no_livelihood_source: specialGateway === true ? boolOrNull("worker-no-livelihood") : null, has_capable_legal_supporter: specialGateway === true ? boolOrNull("worker-supporter") : null };
  loading(true, "正在生成匿名咨询摘要");
  try {
    const result = await api("/api/v1/screenings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!safetyGateAllowsReport(result)) throw new Error("安全发布门未放行");
    state.workerSafetyPassed = true;
    $("#worker-output").innerHTML = `<div class="panel-title"><div><span>匿名咨询结果</span><h2>${escapeHtml(result.outcome?.title || "六事项判断")}</h2></div><b>${escapeHtml(result.policy_snapshot)}</b></div>${result.results.map((item) => `<article class="worker-result-row"><div><strong>${escapeHtml(item.name)}</strong><span class="result-badge ${item.status === "likely" ? "match" : item.status === "unlikely" ? "no" : "review"}">${item.status === "likely" ? "可能匹配" : item.status === "unlikely" ? "当前未匹配" : "需要确认"}</span></div><p>${escapeHtml(item.plan_reason)}</p><small>UNKNOWN ${item.conditions.filter((condition) => condition.state === "unknown").length}项 · 证据${item.evidence.length}条</small></article>`).join("")}`;
  } catch (error) { toast(error.message, "error"); }
  finally { loading(false); }
}

const policySample = "广州市最低生活保障办法。共同生活家庭成员人均月收入低于本市最低生活保障标准，且家庭财产状况符合规定的，可以申请最低生活保障。2027年最低生活保障标准调整为1400元/人/月。本通知自2027年8月1日起施行，有效期为1年。";

async function compilePolicy() {
  const text = $("#compiler-text").value.trim();
  if (text.length < 20) return toast("请粘贴至少20字的政策条款。", "error");
  const payload = { source_id: $("#compiler-source-id").value.trim(), title: $("#compiler-title").value.trim(), source_text: text, region: $("#compiler-region").value.trim(), benefit_hint: valueOrNull("compiler-benefit"), use_llm: $("#compiler-use-llm").checked };
  loading(true, "正在抽取候选规则并运行合成案例影响分析");
  try {
    const result = await api("/api/v1/admin/policy/compile", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const candidate = result.candidate;
    const impact = await api("/api/v1/admin/policy/impact", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ candidate }) });
    $("#compiler-output").innerHTML = `<div class="compiler-result"><div class="panel-title"><div><span>待双人复核 · 不可自动发布</span><h3>${escapeHtml(candidate.benefit_name)}</h3></div><b>完整度 ${Math.round(candidate.extraction_completeness * 100)}%</b></div><p class="compiler-meta">${escapeHtml(candidate.provider)} · 指纹 ${escapeHtml(candidate.source_sha256.slice(0, 16))} · ${escapeHtml(candidate.effective_from || "生效日待确认")} 至 ${escapeHtml(candidate.effective_to || "长期/待确认")}</p><div class="impact-summary"><div><span>合成案例</span><strong>${escapeHtml(impact.total_cases)}</strong></div><div><span>可比较</span><strong>${escapeHtml(impact.comparable_cases)}</strong></div><div><span>结果变化</span><strong>${escapeHtml(impact.changed_cases)}</strong></div></div><p class="compiler-meta">${impact.notes.map(escapeHtml).join(" ")}</p><div class="compiler-block"><h4>候选条件</h4><ul>${candidate.conditions.map((item) => `<li><code>${escapeHtml(item.field)} ${escapeHtml(item.operator)} ${escapeHtml(item.value)}</code><br>${escapeHtml(item.source_quote)}</li>`).join("") || "<li>未抽取到可执行条件</li>"}</ul></div><div class="compiler-block"><h4>版本差异</h4><ul>${result.version_diff.changes.map((item) => `<li>${escapeHtml(item.field)}：${escapeHtml(item.before ?? "空")} → ${escapeHtml(item.after ?? "空")}</li>`).join("") || "<li>未发现参数或时间变化</li>"}</ul></div><div class="compiler-block"><h4>发布阻断</h4><ul>${result.publish_blockers.map((item) => `<li class="validation-error">${escapeHtml(item)}</li>`).join("")}</ul></div><div class="compiler-block"><h4>全部校验记录</h4><ul>${result.validation.map((item) => `<li class="validation-${escapeHtml(item.severity)}"><strong>${escapeHtml(item.severity.toUpperCase())}</strong> ${escapeHtml(item.message)}</li>`).join("")}</ul></div></div>`;
    toast("候选规则与影响分析已生成，仍禁止自动发布。", "success");
  } catch (error) { toast(error.message, "error"); }
  finally { loading(false); }
}

async function loadAdmin() {
  try {
    const result = await api("/api/v1/admin/dashboard");
    const values = [result.screenings, result.policy_health.total_sources, result.privacy.raw_documents_stored ? "是" : "否", `${result.privacy.retention_days}天`];
    $$("#admin-metrics article strong").forEach((element, index) => { element.textContent = values[index]; });
    const readiness = result.system_readiness;
    $("#governance-readiness").textContent = readiness.status;
    $("#governance-checks").innerHTML = readiness.checks.map((check) => `<div class="readiness-item ${escapeHtml(check.status)}"><div><strong>${escapeHtml(check.label)}</strong><p>${escapeHtml(check.detail)}</p></div><b>${escapeHtml(check.status)}</b></div>`).join("");
    const registry = result.rule_registry;
    $("#registry-version").textContent = registry.registry_version;
    $("#rule-release").innerHTML = registry.rules.map((rule) => `<div class="rule-row"><div><strong>${escapeHtml(rule.name)}</strong><p>${escapeHtml(rule.version)} · ${escapeHtml(rule.effective_from)} 至 ${escapeHtml(rule.effective_to || "长期")}</p></div><em>${escapeHtml(rule.status)}</em></div>`).join("");
  } catch (error) { if (error.status === 401 || error.status === 403) toast("请输入有效的管理员令牌。", "error"); else toast(error.message, "error"); }
}

function setupEvents() {
  document.addEventListener("click", (event) => {
    const route = event.target.closest("[data-route]");
    if (route) {
      event.preventDefault();
      navigate(route.dataset.route);
      if (route.dataset.screenStart === "manual") setTimeout(() => showStep(0), 100);
      else if (route.dataset.screenStart === "ai") setTimeout(() => { showStep(0); $("#ai-helper").open = true; $("#assistive-narrative").focus({ preventScroll: true }); }, 100);
    }
    if (event.target.closest("[data-continue-assistive]")) applyAssistiveDraft();
    const candidateAction = event.target.closest("[data-candidate-action]");
    if (candidateAction) setSupplementDecision(candidateAction.dataset.candidateId, candidateAction.dataset.candidateAction);
    const supplementField = event.target.closest("[data-supplement-field]");
    if (supplementField) openCorrection(supplementField.dataset.supplementField, "请补充这项信息；返回核对页后可继续生成结果。");
    const fix = event.target.closest("[data-fix-field]"); if (fix) openCorrection(fix.dataset.fixField);
    const edit = event.target.closest("[data-edit-field]"); if (edit) openCorrection(edit.dataset.editField, "请修改后继续核对。");
    const resultAction = event.target.closest("[data-result-action]"); if (resultAction) handleResultAction(resultAction.dataset.resultAction);
    const tab = event.target.closest("[data-pro-tab]"); if (tab) setProfessionalTab(tab.dataset.proTab);
    const suggestion = event.target.closest("[data-evidence-query]"); if (suggestion) { $("#evidence-query").value = suggestion.dataset.evidenceQuery; searchEvidence(); }
  });
  $("#mobile-menu").addEventListener("click", () => { const open = !$("#site-navigation").classList.contains("open"); $("#site-navigation").classList.toggle("open", open); $("#nav-scrim").classList.toggle("open", open); $("#mobile-menu").setAttribute("aria-expanded", String(open)); });
  $("#nav-scrim").addEventListener("click", closeMobileNav);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeMobileNav(); });
  $("#accessibility-toggle").addEventListener("click", () => { document.body.classList.toggle("large-type"); const active = document.body.classList.contains("large-type"); $("#accessibility-toggle").setAttribute("aria-pressed", String(active)); localStorage.setItem("huimin-large-type", String(active)); });
  $("#narrative").addEventListener("input", (event) => { $("#story-count").textContent = event.target.value.length; invalidateSupplementIfChanged(); });
  $("#assistive-narrative").addEventListener("input", (event) => { $("#assistive-story-count").textContent = event.target.value.length; });
  $("#parse-assistive").addEventListener("click", parseAssistiveNarrative);
  $("#analyze-supplement").addEventListener("click", analyzeSupplement);
  $("#wizard-back").addEventListener("click", () => showStep(state.step - 1, { scroll: true }));
  $("#wizard-next").addEventListener("click", () => { if (validateStep(state.step)) { saveDraft(); showStep(state.step + 1, { scroll: true }); } });
  $("#screening-form").addEventListener("submit", submitScreening);
  $("#load-demo").addEventListener("click", loadDemo);
  $("#new-screening").addEventListener("click", () => resetScreening({ clear: true }));
  $("#clear-draft").addEventListener("click", () => clearDraft());
  $("#delete-screening").addEventListener("click", deleteScreening);
  $("#print-report").addEventListener("click", () => { if (!state.reportSafetyPassed) return toast("安全门未放行，不能打印。", "error"); document.body.dataset.printAuthorized = "true"; window.print(); });
  $("#read-report").addEventListener("click", readCurrentReport);
  ["household_size", "monthly_income_total", "deductible_monthly_total"].forEach((id) => $(`#${id}`).addEventListener("input", updateIncomePreview));
  $$("#screening-form input, #screening-form select, #screening-form textarea").forEach((field) => field.addEventListener("change", () => { requestGuidance(); saveDraft(); }));
  $$('input[name="urgent_event_choice"]').forEach((radio) => radio.addEventListener("change", toggleUrgentFields));
  $("#special_person_category_confirmed").addEventListener("change", toggleSpecialHardshipFields);
  const upload = $("#document-file"), drop = $("#drop-zone");
  upload.addEventListener("change", () => selectFiles(upload.files));
  ["dragenter", "dragover"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.remove("dragging"); }));
  drop.addEventListener("drop", (event) => selectFiles(event.dataTransfer.files));
  $("#clear-selected-files").addEventListener("click", () => { upload.value = ""; selectFiles([]); });
  $("#check-document").addEventListener("click", checkDocuments);
  $("#evidence-search").addEventListener("click", searchEvidence);
  $("#evidence-query").addEventListener("keydown", (event) => { if (event.key === "Enter") searchEvidence(); });
  $("#worker-form").addEventListener("submit", runWorker);
  $("#load-policy-sample").addEventListener("click", () => { $("#compiler-text").value = policySample; toast("已载入不含个人信息的合成政策条款。", "success"); });
  $("#compile-policy").addEventListener("click", compilePolicy);
  $("#apply-admin-token").addEventListener("click", () => { state.adminToken = $("#admin-token").value.trim(); if (state.adminToken) sessionStorage.setItem("huimin-admin-token", state.adminToken); else sessionStorage.removeItem("huimin-admin-token"); loadAdmin(); });
  window.addEventListener("beforeprint", () => { document.body.dataset.printAuthorized = state.reportSafetyPassed || state.workerSafetyPassed ? "true" : "false"; });
}

function initialize() {
  document.body.classList.toggle("large-type", localStorage.getItem("huimin-large-type") === "true");
  $("#accessibility-toggle").setAttribute("aria-pressed", String(document.body.classList.contains("large-type")));
  setField("query_date", todayISO()); setField("evidence-as-of", todayISO()); setField("worker-query-date", todayISO());
  $("#admin-token").value = state.adminToken;
  setupEvents(); restoreDraft(); showStep(0); loadMetadata();
  const initialRoute = location.hash.slice(1); navigate(initialRoute || "home", { focus: false });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
}

document.addEventListener("DOMContentLoaded", initialize);
