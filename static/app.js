"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

let STATE = null;
let LLM_SETTINGS_CACHE = null;
let llmSettingsDirty = false;

async function get(path) {
  const r = await fetch(path);
  return r.json();
}
async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const text = await r.text();
  let result;
  try {
    result = JSON.parse(text);
  } catch (_) {
    throw new Error(`서버가 JSON 응답을 보내지 않았습니다 (HTTP ${r.status}). 배포 서버 로그를 확인해 주세요.`);
  }
  if (!r.ok && !result.message) {
    result.message = `요청이 거부되었습니다 (HTTP ${r.status}). APP_TRUSTED_ORIGINS 설정을 확인해 주세요.`;
  }
  return result;
}

/* ── 탭 ─────────────────────────────────────────────── */
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => { b.classList.remove("on"); b.removeAttribute("aria-current"); });
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("on"));
    btn.classList.add("on");
    btn.setAttribute("aria-current", "page");
    const panel = document.querySelector(`.panel[data-panel="${btn.dataset.tab}"]`);
    panel.classList.add("on");
  });
});

/* ── Context Window ───────────────────────────────── */
const tokenText = (n) => Number(n).toLocaleString("ko-KR");
const percentText = (n) => n > 0 && n < 0.01 ? "<0.01" : n.toFixed(2);
const contextParts = [
  ["instructions", "Instructions", "contextInstructions", "legendInstructions", "시스템 프롬프트 / 역할 지침"],
  ["tools", "Tools", "contextTools", "legendTools", "도구 name · description · parameters 명세 (연결된 MCP 포함)"],
  ["context", "Context", "contextHistory", "legendContext", "저장된 앞선 대화 + 이번 요청의 메시지 · 응답 · 도구 호출 · 실행 결과"],
];
function drawContext(c) {
  if (!c) return;
  const ratio = c.limit > 0 ? c.total / c.limit * 100 : 0;
  const totalLabel = `${tokenText(c.total)} / ${tokenText(c.limit)} tokens · ${percentText(ratio)}%`;
  const providerName = c.provider === "ollama" ? "Ollama" : "OpenRouter";
  $("contextModel").textContent = `${providerName} · ${c.model}`;
  $("contextTotal").textContent = `${c.basis === "api" ? "" : "약 "}${totalLabel}`;
  $("contextUsed").style.width = `${Math.min(100, Math.max(0, ratio))}%`;
  const capacity = $("contextCapacity");
  capacity.setAttribute("aria-valuenow", Math.min(100, Math.max(0, ratio)).toFixed(4));
  capacity.setAttribute("aria-valuetext", totalLabel);
  capacity.classList.toggle("near-limit", ratio >= 80);
  capacity.classList.toggle("over-limit", ratio >= 100);
  capacity.dataset.tooltip = `전체 사용량: ${tokenText(c.total)} tokens (${percentText(ratio)}%)\n최대 용량: ${tokenText(c.limit)} tokens\n${c.total > c.limit ? "초과" : "남은 용량"}: ${tokenText(Math.abs(c.limit - c.total))} tokens\n${c.basis === "api" ? "마지막 API 호출의 입력 + 출력 실측 합계" : "호출 전 / 도구 실행 후 로컬 추정치"}`;
  for (const [key, label, barId, legendId, detail] of contextParts) {
    const count = c.parts[key];
    const share = c.total ? count / c.total * 100 : 0;
    const tip = `${label} · 추정 ${tokenText(count)} tokens\n사용량 내 ${percentText(share)}% · 최대 용량 대비 ${percentText(c.limit ? count / c.limit * 100 : 0)}%\n${detail}`;
    const bar = $(barId), legend = $(legendId);
    bar.style.width = `${share}%`;
    bar.textContent = share >= 15 ? `${label} ${share.toFixed(1)}%` : "";
    for (const el of [bar, legend]) {
      el.dataset.tooltip = tip;
      el.setAttribute("aria-label", tip.replace(/\n/g, ", "));
    }
    legend.querySelector("b").textContent = `${tokenText(count)} · ${share.toFixed(1)}%`;
  }
  const phase = {ready:"대기", request:"API 응답 대기", response:"응답 수신", tool:"도구 결과 반영", done:"완료", error:"요청 실패 · 마지막 확인값"}[c.phase] || c.phase;
  const basis = c.basis === "api" ? "전체: 마지막 호출 입력 + 출력 실측 · 항목별: 입력 비중 추정, 출력은 Context에 포함" : "전체·항목별: 텍스트 길이 기반 추정 (실제 토큰과 차이 있음)";
  $("contextNote").textContent = `${phase}${c.step ? ` · API ${c.step}회차` : ""} — ${basis}${ratio > 100 ? " · 최대 용량 초과" : ""}`;
}
for (const el of $("contextCard").querySelectorAll("[tabindex]")) {
  const hide = () => { $("contextTooltip").hidden = true; el.removeAttribute("aria-describedby"); };
  const show = () => {
    const tip = $("contextTooltip");
    if (!el.dataset.tooltip) return;
    tip.textContent = el.dataset.tooltip;
    tip.hidden = false;
    const rect = el.getBoundingClientRect();
    tip.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - tip.offsetWidth - 12))}px`;
    tip.style.top = `${Math.max(12, rect.bottom + tip.offsetHeight + 16 > window.innerHeight ? rect.top - tip.offsetHeight - 8 : rect.bottom + 8)}px`;
    el.setAttribute("aria-describedby", "contextTooltip");
  };
  el.addEventListener("mouseenter", show);
  el.addEventListener("mouseleave", hide);
  el.addEventListener("focus", show);
  el.addEventListener("blur", hide);
  el.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
}
window.addEventListener("scroll", () => { $("contextTooltip").hidden = true; }, {passive:true});
let contextPollVersion = 0;
function pollContext() {
  const version = ++contextPollVersion;
  const poll = async () => {
    try {
      const c = await get("/api/context");
      if (version === contextPollVersion) drawContext(c);
    } catch { /* 채팅 응답 오류와 별도로 처리한다. 다음 주기에 재시도. */ }
    if (version === contextPollVersion) setTimeout(poll, 500);
  };
  poll();
}

/* ── 그리기 ─────────────────────────────────────────── */
function drawMcp() {
  const list = $("mcpList");
  const book = (STATE.mcp && STATE.mcp.catalog) || [];
  list.innerHTML = "";
  book.forEach((s) => {
    const el = document.createElement("div");
    el.className = "server";
    el.innerHTML = `
      <div class="body"><b>${esc(s.label)}</b><span>${esc(s.detail)}</span>
      <span class="connection-status ${s.on ? "connected" : ""}">${s.on ? "연결됨" : "연결 안 됨"}</span></div>
      <button class="${s.on ? "ghost" : "primary"}">${s.on ? "연결 끊기" : "연결"}</button>
      ${s.custom ? '<button class="ghost remove">삭제</button>' : ""}`;
    if (s.custom) {
      el.querySelector(".remove").addEventListener("click", async (ev) => {
        ev.target.disabled = true;
        try {
          const result = await post("/api/mcp/remove", { name: s.name });
          $("mcpNote").textContent = result.ok ? `${s.label} 서버를 삭제했습니다.` : result.message || "삭제하지 못했습니다.";
          await refresh();
        } catch (error) {
          $("mcpNote").textContent = "서버에 연결하지 못했습니다. 다시 시도하세요.";
          ev.target.disabled = false;
        }
      });
    }
    el.querySelector("button").addEventListener("click", async (ev) => {
      ev.target.disabled = true;
      ev.target.textContent = s.on ? "끊는 중…" : "연결 중…";
      try {
        const result = await post("/api/mcp/toggle", { name: s.name, on: !s.on });
        $("mcpNote").textContent = result.ok ? (s.on ? "연결을 해제했습니다." : "연결 결과를 확인했습니다.") : result.message || "연결 설정을 변경하지 못했습니다.";
        await refresh();
      } catch (error) {
        $("mcpNote").textContent = "서버에 연결하지 못했습니다. 다시 시도하세요.";
        ev.target.disabled = false;
        ev.target.textContent = s.on ? "연결 끊기" : "연결";
      }
    });
    list.appendChild(el);
  });

  $("mergedTools").innerHTML = STATE.tools.map((t, index) =>
    `<div class="merged-tool"><div class="merged-head"><code>${esc(t.name)}</code><span class="tool-source">${esc(t.source)}</span>${t.source !== "내장" ? `<button class="ghost remove-tool" data-index="${index}" aria-label="${esc(t.name)} 도구 제외">제외</button>` : `<span class="builtin-tag">내장</span>`}</div></div>`).join("")
    || '<div class="empty">사용 가능한 도구가 없습니다.</div>';
  $("mergedTools").querySelectorAll(".remove-tool").forEach((button) => {
    button.addEventListener("click", async () => {
      const tool = STATE.tools[Number(button.dataset.index)];
      if (!confirm(`${tool.source} 서버의 '${tool.name}' 도구를 Common Agent에서 제외할까요?`)) return;
      button.disabled = true;
      const result = await post("/api/mcp/tool/remove", { source: tool.source, name: tool.name });
      if (!result.ok) {
        button.disabled = false;
        $("mcpNote").textContent = result.message || "도구를 삭제하지 못했습니다.";
        return;
      }
      $("mcpNote").textContent = `'${tool.name}' 도구를 제외했습니다.`;
      await refresh();
    });
  });
  const disabled = STATE.disabled_tools || [];
  $("excludedTools").innerHTML = disabled.length ? disabled.map((tool, index) =>
    `<div class="excluded-tool"><div><code>${esc(tool.name)}</code><span>${esc(tool.source)}</span></div><button class="restore-tool" data-index="${index}">복원</button></div>`).join("")
    : '<div class="empty excluded-empty">제외된 도구가 없습니다.</div>';
  $("excludedTools").querySelectorAll(".restore-tool").forEach((button) => {
    button.addEventListener("click", async () => {
      const tool = disabled[Number(button.dataset.index)];
      button.disabled = true;
      const result = await post("/api/mcp/tool/restore", { source: tool.source, name: tool.name });
      if (!result.ok) {
        button.disabled = false;
        $("mcpNote").textContent = result.message || "도구를 복원하지 못했습니다.";
        return;
      }
      $("mcpNote").textContent = `'${tool.name}' 도구를 복원했습니다.`;
      await refresh();
    });
  });
  $("mergedCount").textContent = `${STATE.tools.length}개`;
}

$("mcpAddForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const button = $("mcpAdd");
  const name = $("mcpName").value.trim();
  button.disabled = true;
  button.textContent = "연결 중…";
  $("mcpAddNote").textContent = "";
  try {
    const result = await post("/api/mcp/add", { name, url: $("mcpUrl").value.trim(), headers: $("mcpHeaders").value, fixed_args: $("mcpFixedArgs").value });
    if (!result.ok) {
      $("mcpAddNote").textContent = result.message || "추가하지 못했습니다.";
    } else {
      $("mcpAddNote").textContent = result.tools
        ? `${name} 서버를 추가하고 도구 ${result.tools}개를 연결했습니다.`
        : `${name} 서버를 목록에 추가했지만 도구를 받지 못했습니다. 화면 위쪽의 오류 문구를 확인하세요. 주소를 고치려면 삭제 후 다시 추가하세요.`;
      $("mcpName").value = "";
      $("mcpUrl").value = "";
      $("mcpHeaders").value = "";
      $("mcpFixedArgs").value = "";
      await refresh();
    }
  } catch (error) {
    $("mcpAddNote").textContent = "서버에 연결하지 못했습니다. 다시 시도하세요.";
  }
  button.disabled = false;
  button.textContent = "추가하고 연결";
});

$("mcpJsonForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const button = $("mcpJsonAdd");
  button.disabled = true;
  button.textContent = "연결 중…";
  $("mcpAddNote").textContent = "";
  try {
    const result = await post("/api/mcp/add_json", { json: $("mcpJson").value });
    if (!result.ok) {
      $("mcpAddNote").textContent = result.message || "추가하지 못했습니다.";
    } else {
      const skipped = result.problems && result.problems.length ? ` 건너뜀: ${result.problems.join(" / ")}` : "";
      $("mcpAddNote").textContent = `${result.added.join(", ")} 서버를 추가하고 도구 ${result.tools}개를 연결했습니다.${skipped}`;
      $("mcpJson").value = "";
      await refresh();
    }
  } catch (error) {
    $("mcpAddNote").textContent = "서버에 연결하지 못했습니다. 다시 시도하세요.";
  }
  button.disabled = false;
  button.textContent = "JSON으로 추가";
});

function drawErrors() {
  const box = $("errors");
  const list = STATE.errors || [];
  box.hidden = list.length === 0;
  box.innerHTML = list.map((e) => `<div>${esc(e)}</div>`).join("");
}

/* ── 연구 자료 파일 ──────────────────────────────────── */
function sizeText(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function drawFiles(files) {
  const box = $("fileList");
  const list = files || [];
  if (!list.length) {
    box.innerHTML = '<div class="empty">올린 파일이 없습니다.</div>';
    return;
  }
  box.innerHTML = "";
  list.forEach((f) => {
    const el = document.createElement("div");
    el.className = "file";
    el.innerHTML = `<span class="nm">${esc(f.name)}</span>
      <span class="sz">${sizeText(f.bytes)}</span>
      <button class="del" title="파일 삭제" aria-label="파일 삭제">✕</button>`;
    el.querySelector("button").addEventListener("click", async () => {
      if (!confirm(`${f.name}을(를) 지웁니다. 되돌릴 수 없습니다.`)) return;
      const r = await post("/api/data/delete", { name: f.name });
      drawFiles(r.files);
      $("fileNote").textContent = r.ok ? `${f.name}을(를) 지웠습니다.`
                                       : (r.message || "지우지 못했습니다.");
    });
    box.appendChild(el);
  });
}

/* 파일을 base64로 실어 보낸다. 서버의 POST는 전부 JSON이라 multipart를 쓰지 않는다. */
function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result).split(",")[1] || "");
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(file);
  });
}

async function uploadFiles(files) {
  const have = (STATE && STATE.research_files || []).map((f) => f.name);
  const done = [], failed = [];
  for (const file of files) {
    if (have.includes(file.name) &&
        !confirm(`${file.name}이(가) 이미 있습니다. 덮어쓸까요?`)) continue;
    $("fileNote").textContent = `${file.name} 올리는 중…`;
    try {
      const r = await post("/api/data/upload",
                           { name: file.name, data: await readAsBase64(file) });
      if (r.ok) { done.push(r.name); drawFiles(r.files); }
      else failed.push(`${file.name} — ${r.message}`);
    } catch (e) { failed.push(`${file.name} — 보내지 못했습니다.`); }
  }
  $("fileNote").textContent =
    [done.length ? `${done.join(", ")}을(를) 올렸습니다.` : "", ...failed].filter(Boolean).join(" / ")
    || "올린 것이 없습니다.";
  refresh();
}

function draw() {
  drawContext(STATE.context_window);
  drawLlmSettings(STATE.llm_settings);
  $("chipTools").textContent = `도구 ${STATE.tools.length}`;
  const providerName = STATE.llm_settings.provider === "ollama" ? "Ollama" : "OpenRouter";
  $("headerModel").textContent = STATE.llm_settings.model
    ? `${providerName} · ${STATE.llm_settings.model}` : "모델 확인 불가";
  $("prompt").value = STATE.prompt;
  drawChat(STATE.chat);
  drawMcp();
  drawSkills(STATE.skills);
  $("activeToolList").innerHTML = STATE.tools.length ? STATE.tools.map((tool) =>
    `<div class="active-tool"><code>${esc(tool.name)}</code><span>${esc(tool.source)}</span></div>`).join("")
    : '<div class="empty">현재 제공되는 도구가 없습니다.</div>';
  drawFiles(STATE.research_files);
  drawErrors();
}

function updateLlmSettingsFields() {
  const useOllama = $("llmProvider").value === "ollama";
  $("ollamaSettings").hidden = !useOllama;
  $("openRouterSettings").hidden = useOllama;
  $("llmModel").placeholder = useOllama
    ? "Ollama에 설치한 모델 이름" : "OpenRouter 모델 이름";
}

function drawLlmSettings(settings) {
  if (llmSettingsDirty || !settings) return;
  LLM_SETTINGS_CACHE = { ...settings };
  $("llmProvider").value = settings.provider || "openrouter";
  $("llmModel").value = settings.model || "";
  $("ollamaBaseUrl").value = settings.ollama_base_url || "http://localhost:11434/v1";
  updateLlmSettingsFields();
}

async function refresh() {
  const next = await get("/api/state");
  if (next.ok === false) {                    // 작업 중이라 아직 상태를 못 받았다. 화면은 그대로 둔다.
    if (!STATE) $("errors") && ($("errors").textContent = next.message || "");
    return;
  }
  STATE = next;
  draw();
}

/* ── 대화 ───────────────────────────────────────────── */
function renderCalls(calls) {
  if (!calls || !calls.length) {
    return '<div class="meta">도구를 부르지 않았습니다.</div>';
  }
  return calls.map((c) => `
    <div class="call">
      <b>${esc(c.tool)}</b><span class="badge">${esc(c.source)}</span>
      <pre>인자   ${esc(c.args)}
결과   ${esc(c.result)}</pre>
    </div>`).join("");
}

/* 저장된 대화. 서버의 state/chat_history.json과 같은 내용이다. */
function drawChat(turns) {
  turns = turns || [];
  $("chatCount").textContent = turns.length ? `저장된 대화 ${turns.length}개 · 다음 요청에 이어집니다` : "";
  const box = $("chatLog");
  box.innerHTML = turns.length ? turns.map((t) => `
    <div class="turn">
      <div class="turn-message"><div class="turn-who">USER</div><div class="turn-user">${esc(t.message)}</div></div>
      <div class="turn-message"><div class="turn-who">ASSISTANT</div><div class="turn-ai md">${md(t.answer)}</div>
      ${(t.calls || []).length ? `<details class="turn-calls"><summary>도구 ${t.calls.length}회 · ${esc(t.calls.map((c) => c.tool).join(", "))}</summary>${renderCalls(t.calls)}</details>` : ""}</div>
    </div>`).join("")
    : '<div class="chat-empty">저장된 대화가 없습니다.<br>요청을 보내면 최근 30턴까지 다음 요청의 문맥으로 이어집니다.</div>';
  box.scrollTop = box.scrollHeight;
}

/* ── 스킬 ───────────────────────────────────────────── */
let SKILLS = { skills: [], tools: [] };
let SKILL_EDITING = null;           // 고치는 스킬의 이름. 새로 만드는 중이면 null

function drawSkills(view) {
  if (!view) return;
  SKILLS = view;
  $("chipSkills").textContent = `${view.skills.length}개`;
  $("skillList").innerHTML = view.skills.length ? view.skills.map((s) =>
    `<button type="button" class="skill-row" data-name="${esc(s.name)}"><b>${esc(s.name)}</b><span>${esc(s.description)}</span></button>`).join("")
    : '<div class="empty">등록된 스킬이 없습니다.</div>';
}

async function openSkill(name) {
  let s = null;
  if (name) {
    // 목록에는 본문이 없다. 편집 팝업을 열 때 이 스킬의 본문을 받아 온다.
    try {
      const r = await post("/api/skills/get", { name });
      if (!r.ok) { alert(r.message || "스킬을 불러오지 못했습니다."); refresh(); return; }
      s = r.skill;
    } catch (e) { alert(e.message); return; }
  }
  SKILL_EDITING = s ? s.name : null;
  $("skillDialogTitle").textContent = s ? `스킬 · ${s.name}` : "스킬 추가";
  $("skillName").value = s ? s.name : "";
  $("skillName").readOnly = !!s;                  // 이름은 폴더 이름이라 만든 뒤에는 바꾸지 않는다
  $("skillDesc").value = s ? s.description : "";
  $("skillBody").value = s ? s.body : "";
  $("skillTools").innerHTML = SKILLS.tools.map((t) =>
    `<label class="skill-tool"><input type="checkbox" value="${esc(t.name)}"${s && s.tools.includes(t.name) ? " checked" : ""}>`
    + `<span><code>${esc(t.name)}</code> ${esc((t.description.match(/^.*?[.。](?=\s|$)/) || [t.description])[0])}</span></label>`).join("")
    || '<span class="meta">고를 수 있는 도구가 없습니다.</span>';
  $("deleteSkill").hidden = !s;
  $("skillNote").textContent = "";
  $("skillImportText").value = "";
  $("skillImportNote").textContent = "";
  $("skillImport").open = false;
  $("skillDialog").showModal();
  (s ? $("skillDesc") : $("skillName")).focus();
}
/* Claude Code의 SKILL.md를 그대로 붙여 넣어 칸을 채운다. 서버(lab/skills.py)와 같은 규칙으로 읽는다. */
function importSkillMd(raw) {
  const text = String(raw).replace(/\r\n/g, "\n").trim();
  const meta = {};
  let body = text;
  if (text.startsWith("---\n")) {
    const end = text.indexOf("\n---", 4);
    if (end > 0) {
      text.slice(4, end).split("\n").forEach((line) => {
        const i = line.indexOf(":");
        if (i > 0) {
          let v = line.slice(i + 1).trim();
          if (v.length >= 2 && v[0] === v[v.length - 1] && (v[0] === '"' || v[0] === "'")) v = v.slice(1, -1);   // 짝이 맞는 바깥 따옴표만
          meta[line.slice(0, i).trim().toLowerCase()] = v;
        }
      });
      body = text.slice(end + 4).replace(/^\n+/, "");
    }
  }
  const notes = [];
  const desc = (meta.description || "").replace(/\s+/g, " ");
  if (desc.length > 300) notes.push(`설명이 ${desc.length}자라 300자로 줄였습니다. 언제 쓰는지가 남도록 다듬어 주세요.`);
  const have = SKILLS.tools.map((t) => t.name);
  const tools = (meta.tools || "").split(/[,\s]+/).filter((t) => have.includes(t));
  // Claude Code 전용 내용은 이 앱에 없는 도구·명령을 부르게 만든다.
  if (/\bbun\b|Artifact|localhost:31337|~\/\.claude|Voice Notification|\bTools\/\w+\.ts/i.test(body)) {
    notes.push("지침에 Claude Code 전용 내용(bun, Artifact, 음성 알림 등)이 있습니다. 이 앱에는 없으니 지우거나 바꿔 주세요.");
  }
  return { name: (meta.name || "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40),
           description: desc.slice(0, 300), tools, body, notes };
}
$("skillImportRun").addEventListener("click", () => {
  if (!$("skillImportText").value.trim()) { $("skillImportNote").textContent = "붙여 넣은 내용이 없습니다."; return; }
  const r = importSkillMd($("skillImportText").value);
  if (!SKILL_EDITING && r.name) $("skillName").value = r.name;        // 고치는 중이면 이름은 그대로 둔다
  if (r.description) $("skillDesc").value = r.description;
  $("skillBody").value = r.body;
  $("skillTools").querySelectorAll("input").forEach((i) => { i.checked = r.tools.includes(i.value); });
  $("skillImportNote").textContent = ["채웠습니다. 확인하고 저장하세요.", ...r.notes].join(" ");
});

$("skillList").addEventListener("click", (ev) => {
  const row = ev.target.closest(".skill-row");
  if (row) openSkill(row.dataset.name);
});
$("addSkill").addEventListener("click", () => openSkill(null));
$("closeSkill").addEventListener("click", () => $("skillDialog").close());
$("skillDialog").addEventListener("click", (ev) => { if (ev.target === $("skillDialog")) $("skillDialog").close(); });
$("saveSkill").addEventListener("click", async () => {
  $("saveSkill").disabled = true;
  try {
    const r = await post("/api/skills/save", {
      name: $("skillName").value.trim(),
      description: $("skillDesc").value,
      tools: [...$("skillTools").querySelectorAll("input:checked")].map((i) => i.value),
      body: $("skillBody").value,
    });
    if (!r.ok) { $("skillNote").textContent = r.message || "저장하지 못했습니다."; return; }
    drawSkills(r.skills);
    $("skillDialog").close();
    refresh();                                   // 도구 목록과 Context 계기판에 반영
  } catch (e) {
    $("skillNote").textContent = e.message;
  } finally {
    $("saveSkill").disabled = false;
  }
});
$("deleteSkill").addEventListener("click", async () => {
  if (!SKILL_EDITING || !confirm(`'${SKILL_EDITING}' 스킬을 삭제할까요? 되돌릴 수 없습니다.`)) return;
  try {
    const r = await post("/api/skills/delete", { name: SKILL_EDITING });
    if (!r.ok) { $("skillNote").textContent = r.message || "삭제하지 못했습니다."; return; }
    drawSkills(r.skills);
    $("skillDialog").close();
    refresh();
  } catch (e) {
    $("skillNote").textContent = e.message;
  }
});

$("goMcp").addEventListener("click", () => document.querySelector('.tab[data-tab="mcp"]').click());

/* ── HTML 결과 미리보기 ──────────────────────────────── */
/* 답변에 완성된 HTML 문서가 있으면 소스 대신 화면으로 그리고 [다운로드]를 붙인다.
   iframe은 sandbox=""(스크립트·같은 출처 접근 없음)에 CSP로 외부 요청을 막아, 모델이 만든 HTML이 앱에 손대지 못하게 한다. */
const HTML_DOCS = new Map();   // 해시 -> 원문. 다시 그려도 같은 글은 한 번만 담긴다.
const attr = (s) => esc(s).replace(/"/g, "&quot;");
function hashText(t) {
  // 서로 다른 계산 두 개를 이어 붙인다. 하나만 쓰면 드물게 충돌해 [다운로드]가 다른 문서를 줄 수 있다.
  let a = 5381, b = 2166136261;
  for (let i = 0; i < t.length; i++) {
    const c = t.charCodeAt(i);
    a = ((a * 33) ^ c) >>> 0;
    b = Math.imul(b ^ c, 16777619) >>> 0;
  }
  return a.toString(36) + b.toString(36) + t.length.toString(36);
}
function injectHead(html, tag) {
  if (/<head[^>]*>/i.test(html)) return html.replace(/<head[^>]*>/i, (m) => m + tag);
  if (/<html[^>]*>/i.test(html)) return html.replace(/<html[^>]*>/i, (m) => m + "<head>" + tag + "</head>");
  return tag + html;
}
const looksLikeHtmlDoc = (t) => /^\s*(<!doctype\s+html|<html[\s>])/i.test(t);
function htmlPreview(source) {
  const key = hashText(source);
  HTML_DOCS.set(key, source);
  const csp = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: https:; style-src 'unsafe-inline'; font-src data:">`;
  const titled = /<title[^>]*>([^<]*)<\/title>/i.exec(source);
  const name = titled && titled[1].trim() ? titled[1].trim() : "HTML 결과";
  return `<div class="html-result"><div class="html-result-bar"><b>${esc(name)}</b>`
    + `<button type="button" class="ghost compact html-download" data-doc="${key}">다운로드</button></div>`
    + `<iframe class="html-frame" sandbox="" title="${attr(name)}" srcdoc="${attr(injectHead(source, csp))}"></iframe>`
    + `<details class="html-src"><summary>소스 보기</summary><pre><code>${esc(source)}</code></pre></details></div>`;
}
/* render_html 스킬이 만든 문서는 답변에 [[html:id]] 한 줄로 들어 있다. 서버에서 받아 미리보기로 바꾼다.
   다시 그릴 때마다 받지 않도록 한 번 받은 글은 기억한다. */
const OUTPUTS = new Map();      // id -> 문서 글. 받지 못했으면 null
const OUTPUT_LOADING = new Set();
function outputCard(id) {
  if (OUTPUTS.has(id)) {
    return OUTPUTS.get(id) === null
      ? '<div class="html-result"><div class="html-result-bar"><b>문서를 찾을 수 없습니다. 오래되어 지워졌을 수 있습니다.</b></div></div>'
      : htmlPreview(OUTPUTS.get(id));
  }
  if (!OUTPUT_LOADING.has(id)) {
    OUTPUT_LOADING.add(id);
    fetch("/api/output?id=" + id)
      .then((r) => (r.ok ? r.text() : null), () => null)
      .then((text) => {
        OUTPUTS.set(id, text);
        OUTPUT_LOADING.delete(id);
        document.querySelectorAll(`.html-pending[data-output="${id}"]`).forEach((el) => { el.outerHTML = outputCard(id); });
      });
  }
  return `<div class="html-result html-pending" data-output="${id}"><div class="html-result-bar"><b>HTML 문서를 불러오는 중…</b></div></div>`;
}
document.addEventListener("click", (ev) => {
  const b = ev.target.closest(".html-download");
  if (!b || !HTML_DOCS.has(b.dataset.doc)) return;
  let html = HTML_DOCS.get(b.dataset.doc);
  if (!/<meta[^>]+charset/i.test(html)) html = injectHead(html, '<meta charset="utf-8">');   // 로컬에서 열 때 한글이 깨지지 않게
  const d = new Date(), z = (n) => String(n).padStart(2, "0");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
  a.download = `result-${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}-${z(d.getHours())}${z(d.getMinutes())}.html`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

/* ── 마크다운 ────────────────────────────────────────── */
/* 모델 답변에 흔히 나오는 것만 그린다 — 제목, 목록, 굵게·기울임, 코드. 외부 라이브러리 없이.
   먼저 HTML을 이스케이프하므로 모델이 태그를 보내도 그대로 글자로 보인다. */
function md(src) {
  const inline = (s) => esc(s)
    .replace(/\\\((.+?)\\\)/g, (_, x) => `<code>${plainMath(x).trim()}</code>`)   // 인라인 수식 \( \)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<i>$2</i>");
  const lines = String(src == null ? "" : src).replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let list = null, para = [], code = null, codeLang = "", gap = false, math = null, rawHtml = null;
  const flushPara = () => { if (para.length) { out.push(`<p>${para.join("<br>")}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.join("")}</${list.tag}>`); list = null; } gap = false; };
  // 모델이 가끔 수식을 LaTeX로 쓴다. 렌더링 도구가 없으므로 기호만 바꿔 고정폭 상자에 보여 준다.
  const plainMath = (s) => s.replace(/\\times/g, "×").replace(/\\cdot/g, "·").replace(/\\le\b/g, "≤").replace(/\\ge\b/g, "≥")
    .replace(/\\sum/g, "Σ").replace(/\\pm/g, "±").replace(/\{,\}/g, ",").replace(/\\text\{([^}]*)\}/g, "$1")
    .replace(/\\[a-zA-Z]+/g, "").replace(/[{}]/g, "");
  const closeCode = () => {
    const text = code.join("\n");
    out.push(codeLang === "html" && looksLikeHtmlDoc(text) ? htmlPreview(text) : `<pre><code>${esc(text)}</code></pre>`);
    code = null;
  };
  for (const raw of lines) {
    if (rawHtml !== null) {                       // 코드 블록 없이 그대로 나온 HTML 문서
      rawHtml.push(raw);
      if (/<\/html>/i.test(raw)) { out.push(htmlPreview(rawHtml.join("\n"))); rawHtml = null; }
      continue;
    }
    if (code !== null) {
      if (/^```/.test(raw)) closeCode();
      else code.push(raw);
      continue;
    }
    if (math !== null) {
      if (/^\s*\\\]\s*$/.test(raw)) { out.push(`<pre class="math">${esc(plainMath(math.join(" ")))}</pre>`); math = null; }
      else math.push(raw.trim());
      continue;
    }
    const line = raw.trimEnd();
    let m;
    if ((m = line.match(/^\s*\[\[html:([0-9a-f]{12})\]\]\s*$/))) { flushPara(); flushList(); out.push(outputCard(m[1])); continue; }
    if (/^```/.test(line)) { flushPara(); flushList(); code = []; codeLang = line.slice(3).trim().toLowerCase(); continue; }
    if (looksLikeHtmlDoc(line)) { flushPara(); flushList(); rawHtml = [raw]; if (/<\/html>/i.test(raw)) { out.push(htmlPreview(raw)); rawHtml = null; } continue; }
    if (/^\s*\\\[\s*$/.test(line)) { flushPara(); flushList(); math = []; continue; }
    if ((m = line.match(/^\s*\\\[(.*)\\\]\s*$/))) { flushPara(); flushList(); out.push(`<pre class="math">${esc(plainMath(m[1]))}</pre>`); continue; }
    // 빈 줄 — 목록은 바로 닫지 않는다. 모델이 항목 사이에 빈 줄을 두는 일이 잦아,
    // 다음 줄이 같은 종류의 항목이면 번호를 이어 간다.
    if (!line.trim()) { flushPara(); if (list) gap = true; continue; }
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
      flushPara(); flushList();
      const level = Math.min(m[1].length + 2, 6);   // 답변 안의 제목은 카드 제목보다 작게
      out.push(`<h${level}>${inline(m[2])}</h${level}>`);
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {               // 표 — |로 시작하고 끝나는 줄의 연속
      flushPara(); flushList();
      const cells = line.trim().slice(1, -1).split("|").map((c) => c.trim());
      if (cells.every((c) => /^:?-{2,}:?$/.test(c))) continue;   // |---|---| 구분줄
      const last = out[out.length - 1];
      const tag = last && last.startsWith("<table") ? "td" : "th";
      const row = `<tr>${cells.map((c) => `<${tag}>${inline(c)}</${tag}>`).join("")}</tr>`;
      if (tag === "th") out.push(`<table class="md-table">${row}`);
      else out[out.length - 1] = last.replace(/<\/table>$/, "") + row;
      out[out.length - 1] += "</table>";
      continue;
    }
    if (/^\s*-{3,}\s*$/.test(line)) { flushPara(); flushList(); out.push("<hr>"); continue; }
    if ((m = line.match(/^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$/))) {
      flushPara();
      const tag = m[1] ? "ol" : "ul";
      if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; }
      gap = false;
      list.items.push(`<li>${inline(m[2])}</li>`);
      continue;
    }
    if (list && !gap && /^\s{2,}\S/.test(raw)) {    // 목록 항목에 이어지는 들여쓴 줄
      list.items[list.items.length - 1] = list.items[list.items.length - 1]
        .replace(/<\/li>$/, `<br>${inline(line.trim())}</li>`);
      continue;
    }
    flushList();
    para.push(inline(line));
  }
  flushPara(); flushList();
  if (code !== null) closeCode();
  if (rawHtml !== null) out.push(htmlPreview(rawHtml.join("\n")));   // </html>이 없이 끊긴 응답도 보이게 한다
  if (math !== null) out.push(`<pre class="math">${esc(plainMath(math.join(" ")))}</pre>`);
  return out.join("");
}

/* ── API 호출 내역 ───────────────────────────────────── */
const pretty = (v) => JSON.stringify(v, null, 2);

/* JSON을 색으로 구분한다 — 키 · 문자열 · 숫자 · true/false/null · 괄호와 쉼표.
   문자열 토큰을 통째로 잡고(이스케이프 포함) 뒤에 콜론이 오면 키로 본다. 이스케이프를 먼저 거친 텍스트에 적용한다. */
function hl(value) {
  const text = esc(pretty(value));
  return text.replace(
    /("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false|null)\b|([{}\[\],])/g,
    (m, str, colon, num, lit, punct) => {
      if (str !== undefined) {
        return colon ? `<span class="j-key">${str}</span><span class="j-punct">${colon}</span>`
                     : `<span class="j-str">${str}</span>`;
      }
      if (num !== undefined) return `<span class="j-num">${num}</span>`;
      if (lit !== undefined) return `<span class="j-lit">${lit}</span>`;
      return `<span class="j-punct">${punct}</span>`;
    });
}

/* 화면에는 주요 항목만 — 요청은 model·instructions·input·tools, 응답은 id·object·model·output.
   실제로는 전부 보내고 받는다. 순서는 아래 목록 순서대로 보인다. */
const REQUEST_KEYS = ["model", "instructions", "input", "tools"];
const RESPONSE_KEYS = ["id", "object", "model", "output"];
function pick(obj, keys) {
  const out = {};
  keys.forEach((k) => { if (obj && obj[k] !== undefined) out[k] = obj[k]; });
  return out;
}

/* 요청 → 응답 → 도구 실행 → 요청 → 응답 … 을 일어난 순서 그대로 펼쳐 보인다.
   본문은 가공하지 않는다. 앱이 보낸 JSON과 받은 JSON 그대로다. */
function traceHtml(trace, open = true) {
  const circled = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";
  const calls = trace.filter((e) => e.kind === "request").length;
  const o = open ? " open" : "";
  return trace.map((e, i) => {
    const no = circled[i] || `${i + 1}.`;
    if (e.kind === "request") {
      const nth = e.step, why = nth === 1 ? "사용자 요청과 도구 목록을 보낸다"
        : "도구 결과(function_call_output)를 붙여 다시 보낸다";
      return `<details class="trace-step req"${o}><summary>${no} OpenRouter로 보낸 요청 — API 호출 ${nth}/${calls}
        <span class="trace-sub">POST ${esc(e.url)} · ${why} · 표시: ${REQUEST_KEYS.join(" · ")}</span></summary>
        <pre>${hl(pick(e.payload, REQUEST_KEYS))}</pre></details>`;
    }
    if (e.kind === "response") {
      const out = (e.data && e.data.output) || [];
      const fc = out.filter((o) => o.type === "function_call").map((o) => o.name);
      const why = fc.length ? `도구 호출 결정: ${fc.join(", ")}` : "최종 답변(message)";
      return `<details class="trace-step res"${o}><summary>${no} OpenRouter 응답 — API 호출 ${e.step}/${calls}
        <span class="trace-sub">${e.elapsed}초 · ${why} · 표시: ${RESPONSE_KEYS.join(" · ")}</span></summary>
        <pre>${hl(pick(e.data, RESPONSE_KEYS))}</pre></details>`;
    }
    return `<details class="trace-step tool"${o}><summary>${no} 앱이 실행한 도구 — ${esc(e.name)}
      <span class="trace-sub">${esc(e.source)} · ${e.elapsed}초 · 결과는 다음 요청에 output으로 실린다</span></summary>
      <pre><span class="j-label">인자</span>\n${hl(e.args)}\n<span class="j-label">결과</span>\n${hl(e.result)}</pre></details>`;
  }).join("");
}

async function send() {
  const input = $("message");
  const text = input.value.trim();
  if (!text || $("send").disabled) return;
  $("send").disabled = true;
  $("answer").hidden = false;
  $("answer").classList.remove("md");
  $("answer").textContent = "생각하는 중…";
  $("calls").innerHTML = "";
  pollContext();
  try {
    const r = await post("/api/chat", { message: text });
    if (!r.ok) {
      $("answer").textContent = r.message || "실패했습니다.";
    } else {
      // 답변은 대화 기록에 쌓여 보인다. 기록을 저장하지 못했을 때만 여기 따로 띄운다.
      input.value = "";
      drawChat(r.chat);
      if (r.chat_error) {
        $("answer").classList.add("md");
        $("answer").innerHTML = md(r.answer) + `<p class="meta">${esc(r.chat_error)}</p>`;
      } else {
        $("answer").hidden = true;
      }
      // steps는 모델 API를 부른 횟수다(도구 호출 수와 다르다). 도구를 한 번 부르면
      // 호출을 결정하는 응답과 결과를 보고 답하는 응답으로 API를 두 번 부른다.
      $("calls").innerHTML = renderCalls(r.calls) +
        `<div class="meta">${r.elapsed}초 · 도구 ${r.calls.length}회 ·
         API 호출 ${r.steps}회 · ${r.tokens}토큰</div>`;
      drawContext(r.context_window);
    }
  } catch (e) {
    $("answer").textContent = "서버에 연결하지 못했습니다.";
  }
  contextPollVersion++;
  try { drawContext(await get("/api/context")); } catch { /* 서버 연결 오류는 답변 영역에 표시 */ }
  $("send").disabled = false;
}

/* ── 삼각형 그래프 ───────────────────────────────────── */
/* index.html의 원 좌표와 같아야 한다. 변은 원 테두리에서 시작해 테두리에서 끝난다. */
const GEO = {
  orchestrator: { x: 320, y: 46, color: "#1428A0", label: "연구책임자" },
  research: { x: 140, y: 158, color: "#0F7B6C", label: "자료조사 연구원" },
  experiment: { x: 500, y: 158, color: "#B26A00", label: "실험수행 연구원" },
};
const NODE_R = 30;

function edge(from, to) {
  const a = GEO[from], b = GEO[to];
  const dx = b.x - a.x, dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  return {
    d: `M ${a.x + ux * NODE_R} ${a.y + uy * NODE_R} L ${b.x - ux * NODE_R} ${b.y - uy * NODE_R}`,
    x1: a.x + ux * NODE_R, y1: a.y + uy * NODE_R,
    x2: b.x - ux * NODE_R, y2: b.y - uy * NODE_R,
  };
}

function setNode(role, cls) {
  const g = document.querySelector(`.node[data-role="${role}"]`);
  if (!g) return;
  g.classList.remove("active");
  if (cls) g.classList.add(cls);
}

function clearFlow() {
  $("flow").setAttribute("hidden", "");
  $("packet").setAttribute("hidden", "");
  $("wire").hidden = true;
}

/* 오가는 중인 변 하나를 그린다. back이면 연구원 → 책임자 방향. */
function drawFlow(role, back, moving, fail) {
  const e = back ? edge(role, "orchestrator") : edge("orchestrator", role);
  const flow = $("flow");
  flow.setAttribute("d", e.d);
  flow.setAttribute("stroke", fail ? "#b3261e" : GEO[role].color);
  flow.classList.toggle("moving", !!moving);
  flow.removeAttribute("hidden");

  // 흐름이 멈춘 상태에서는 도착점에 점을 찍어 어디까지 갔는지 보인다.
  const packet = $("packet");
  packet.setAttribute("cx", e.x2);
  packet.setAttribute("cy", e.y2);
  packet.setAttribute("fill", fail ? "#b3261e" : GEO[role].color);
  if (moving) packet.setAttribute("hidden", "");
  else packet.removeAttribute("hidden");
}

function showWire(dir, kind, text, cls) {
  $("wireDir").textContent = dir;
  $("wireKind").textContent = kind;
  $("wireText").textContent = text || "(내용 없음)";
  $("wire").className = "wirebox" + (cls ? " " + cls : "");
  $("wire").hidden = false;
}

function setStatus(text, cls) {
  const el = $("graphStatus");
  el.textContent = text;
  el.className = "status" + (cls ? " " + cls : "");
}

/* 로그의 마지막 항목이 지금 상태를 나타낸다.
   delegate 뒤에 return이 없으면 → 그 연구원이 일하는 중.
   return이 마지막이면 → 보고가 돌아왔고 책임자가 다음을 정하는 중. */
/* 도는 중에는 맡기기를 잠그고 중지를 연다. 새로고침으로 들어와도 맞도록 여기서 정한다.
   이미 중지를 요청했으면 중지 버튼도 다시 잠근다. */
function setRunning(running, stopping) {
  $("startResearch").disabled = !!running;
  $("askFollow").disabled = !!running;
  $("stopResearch").disabled = !running || !!stopping;
  $("stopResearchInline").hidden = !running;
  $("stopResearchInline").disabled = !running || !!stopping;
}

function applyProgress(p) {
  const log = p.log || [];
  setRunning(p.running, p.stopping);
  syncChat(p);
  ["orchestrator", "research", "experiment"].forEach((r) => setNode(r, null));

  if (!log.length) {
    clearFlow();
    if (p.starting) { setNode("orchestrator", "active"); setStatus("연구원을 띄우는 중…", "busy"); }
    else if (p.running) { setNode("orchestrator", "active"); setStatus("연구책임자가 읽는 중…", "busy"); }
    else setStatus("대기 중");
    return;
  }

  const last = log[log.length - 1];

  if (last.kind === "delegate") {
    setNode(last.to, "active");
    drawFlow(last.to, false, true, false);
    showWire(`연구책임자 → ${last.label}`, "지시문", last.instruction);
    setStatus(p.stopping ? "중지하는 중 — 맡긴 일이 끝나기를 기다립니다…"
                         : `${last.label}이 일하는 중…`, "busy");
    return;
  }

  if (last.kind === "return") {
    const bad = last.ok === false;
    drawFlow(last.from, true, false, bad);
    showWire(`${last.label} → 연구책임자`, bad ? "실패" : `보고 · ${last.elapsed}초 · 도구 ${(last.calls || []).length}회`,
             last.result, bad ? "fail" : "back");
    if (p.running) {
      setNode("orchestrator", "active");
      setStatus("연구책임자가 다음을 정하는 중…", "busy");
    } else {
      setStatus(bad ? "실패" : "완료", bad ? "fail" : "done");
    }
    return;
  }

  // final
  clearFlow();
  showWire("연구책임자 결론", last.stopped ? "중지됨" : "최종 보고", last.text, "");
  const n = log.filter((e) => e.kind === "delegate").length;
  if (last.stopped) setStatus(`중지됨 · 위임 ${n}회`, "fail");
  else setStatus(`완료 · 위임 ${n}회`, "done");
}

/* 연구가 도는 동안 진행 상황을 물어본다. 이 GET은 서버에서 락을 잡지 않으므로
   /api/research가 응답을 주지 않은 채 도는 중에도 답이 온다. */
let POLL = null;
let INFLIGHT = false;      // 이 화면이 보낸 /api/research가 아직 돌아오지 않았다

function startPolling() {
  stopPolling();
  POLL = setInterval(async () => {
    try {
      const p = await get("/api/research/progress");
      applyProgress(p);
      // 서버가 "도는 중"이 아니어도 이 화면의 요청이 살아 있으면 계속 묻는다 (연구원 기동 직전 등)
      if (!p.running && !INFLIGHT) stopPolling();
    } catch (e) { /* 잠깐 못 받아도 다음 차례에 다시 묻는다 */ }
  }, 600);
}

function stopPolling() {
  if (POLL) { clearInterval(POLL); POLL = null; }
}

/* ── 에이전트 ────────────────────────────────────────── */
function drawAgents(list) {
  $("agentList").innerHTML = list.map((a) => {
    const tools = (a.tools || []).map((t) => t.name);
    if (a.web_search) tools.push("웹 검색(내장)");
    const button = a.role === "orchestrator" ? "" :
      `<button class="${a.up ? "ghost" : "primary"}" data-role="${a.role}"
        data-up="${a.up ? 1 : 0}">${a.up ? "종료" : "시작"}</button>`;
    return `<div class="server">
      <div class="body">
        <b>${esc(a.label)} ${a.up ? '<span class="up-label">실행 중</span>' : '<span class="down">대기</span>'}</b>
        <span>${a.up ? `PID ${a.pid} · 포트 ${a.port}` : `포트 ${a.port}`}</span>
        <span class="tools">도구 ${tools.length ? esc(tools.join(", ")) : a.up ? "없음" : "시작 후 확인"}</span>
      </div>${button}</div>`;
  }).join("");

  // 그래프의 마디에도 같은 상태를 반영한다 — 떠 있으면 역할 색, 꺼져 있으면 점선.
  list.forEach((a) => {
    const g = document.querySelector(`.node[data-role="${a.role}"]`);
    if (!g) return;
    g.classList.toggle("up", !!a.up);
    g.classList.toggle("off", !a.up);
    const sub = g.querySelector("[data-sub]");
    if (!sub) return;
    if (a.role === "orchestrator") {
      sub.textContent = `이 앱 · ${a.port}`;
    } else if (a.up) {
      const n = (a.tools || []).length + (a.web_search ? 1 : 0);
      sub.textContent = `PID ${a.pid} · 도구 ${n}`;
    } else {
      sub.textContent = "꺼져 있음";
    }
  });

  $("agentList").querySelectorAll("button[data-role]").forEach((b) => {
    b.addEventListener("click", async () => {
      const up = b.dataset.up === "1";
      b.disabled = true;
      b.textContent = up ? "종료 중…" : "시작 중…";
      const r = await post(up ? "/api/agents/stop" : "/api/agents/start",
                           { role: b.dataset.role });
      if (r.agents) drawAgents(r.agents);
      if (!r.ok && r.message) $("researchNote").textContent = r.message;
    });
  });
}

/* ── 연구원 지침 편집 ────────────────────────────────── */
let ROLE_PROMPTS = [];          // 서버가 돌려준 [{role, label, prompt, default, edited}]
const ROLE_DRAFTS = {};         // 저장하지 않고 고치는 중인 글. 연구원을 바꿔도 잃지 않는다.

function currentRolePrompt() {
  return ROLE_PROMPTS.find((p) => p.role === $("rolePromptRole").value);
}

function drawRolePromptState() {
  const p = currentRolePrompt();
  if (!p) return;
  const draft = ROLE_DRAFTS[p.role];
  const dirty = draft !== undefined && draft !== p.prompt;
  const label = dirty ? "저장하지 않은 변경이 있습니다"
    : p.edited ? "수정한 지침 사용 중" : "기본 지침 사용 중";
  $("rolePromptState").textContent = label;
  $("rolePromptSummary").textContent = ROLE_PROMPTS.map((q) => `${q.label}: ${q.edited ? "수정함" : "기본"}`).join(" · ");
  $("resetRolePrompt").disabled = !p.edited && !dirty;
}

function drawRolePrompts(prompts) {
  if (!Array.isArray(prompts) || !prompts.length) return;
  ROLE_PROMPTS = prompts;
  const select = $("rolePromptRole");
  const chosen = select.value;
  if (select.options.length !== prompts.length) {
    select.innerHTML = prompts.map((p) => `<option value="${esc(p.role)}">${esc(p.label)}</option>`).join("");
  }
  select.value = prompts.some((p) => p.role === chosen) ? chosen : prompts[0].role;
  const p = currentRolePrompt();
  // 고치는 중인 글이 있으면 덮어쓰지 않는다. 탭을 오가며 새로 고쳐도 입력이 사라지지 않게 한다.
  $("rolePrompt").value = ROLE_DRAFTS[p.role] !== undefined ? ROLE_DRAFTS[p.role] : p.prompt;
  drawRolePromptState();
}

$("openRolePrompt").addEventListener("click", () => {
  $("rolePromptNote").textContent = "";
  $("rolePromptDialog").showModal();
  $("rolePrompt").focus();
});
$("closeRolePrompt").addEventListener("click", () => $("rolePromptDialog").close());
// 어두운 배경(backdrop)을 눌러도 닫는다. 쓰던 글은 ROLE_DRAFTS에 남는다.
$("rolePromptDialog").addEventListener("click", (ev) => {
  if (ev.target === $("rolePromptDialog")) $("rolePromptDialog").close();
});

$("rolePromptRole").addEventListener("change", () => {
  const p = currentRolePrompt();
  if (!p) return;
  $("rolePrompt").value = ROLE_DRAFTS[p.role] !== undefined ? ROLE_DRAFTS[p.role] : p.prompt;
  $("rolePromptNote").textContent = "";
  drawRolePromptState();
});
$("rolePrompt").addEventListener("input", () => {
  const p = currentRolePrompt();
  if (!p) return;
  ROLE_DRAFTS[p.role] = $("rolePrompt").value;
  drawRolePromptState();
});

async function saveRolePrompt(role, text, doneMessage) {
  $("saveRolePrompt").disabled = $("resetRolePrompt").disabled = true;
  try {
    const r = await post(text === null ? "/api/agents/prompt/reset" : "/api/agents/prompt",
                         text === null ? { role } : { role, text });
    if (!r.ok) {
      $("rolePromptNote").textContent = r.message || "지침을 저장하지 못했습니다.";
      return;
    }
    delete ROLE_DRAFTS[role];
    drawRolePrompts(r.prompts);
    $("rolePromptNote").textContent = doneMessage(r.prompts.find((p) => p.role === role));
  } catch (e) {
    $("rolePromptNote").textContent = e.message;
  } finally {
    $("saveRolePrompt").disabled = false;
    drawRolePromptState();
  }
}
$("saveRolePrompt").addEventListener("click", () => {
  const p = currentRolePrompt();
  if (!p) return;
  if (!$("rolePrompt").value.trim()) {
    $("rolePromptNote").textContent = "지침이 비어 있습니다. 기본 지침으로 되돌리려면 [기본값으로]를 누르세요.";
    return;
  }
  saveRolePrompt(p.role, $("rolePrompt").value,
    (saved) => saved && saved.edited ? "저장했습니다. 다음 위임부터 적용됩니다."
      : "기본 지침과 같아 수정한 지침을 지웠습니다.");
});
$("resetRolePrompt").addEventListener("click", () => {
  const p = currentRolePrompt();
  if (p) saveRolePrompt(p.role, null, () => "기본 지침으로 되돌렸습니다. 다음 위임부터 적용됩니다.");
});

async function refreshAgents() {
  const r = await get("/api/agents");
  drawAgents(r.agents || []);
  drawRolePrompts(r.prompts);
  // 연구가 도는 중에 새로고침해도 그래프가 이어지도록 진행 상황을 맞춰 둔다.
  try {
    const p = await get("/api/research/progress");
    applyProgress(p);
    if (p.running && !POLL) startPolling();
  } catch (e) { /* 진행 중인 것이 없으면 그냥 둔다 */ }
}

/* ── 실행 기록: 대화방 ───────────────────────────────── */
/* 한 연구(1차 또는 후속)가 한 라운드다. 질문 → 지시/보고 말풍선 → 결론 순으로 쌓이고,
   후속 질의는 앞 라운드 아래에 이어 붙는다. 진행 중에는 마지막 라운드가 폴링으로 늘어난다. */
let ROUNDS = [];
let CHAT_KEY = "";

/* 연구원이 안에서 한 일 — trace의 도구 이벤트를 종류별로 알아보기 쉽게 그린다. */
function didHtml(e) {
  const tools = (e.trace || []).filter((t) => t.kind === "tool");
  if (!tools.length) {
    return (e.calls || []).map((c) =>
      `<div class="did"><div class="did-head">${esc(c.tool)} <span>${esc(c.source)}</span></div>
       <pre>인자  ${esc(c.args)}\n결과  ${esc(c.result)}</pre></div>`).join("");
  }
  return tools.map((t) => {
    const a = t.args || {}, r = t.result || {};
    if (t.name === "run_python") {
      const err = r["오류"] || r["알림"];
      return `<div class="did"><div class="did-head">run_python <span>실행한 코드 · ${t.elapsed}초${err ? ' · <b class="errmark">오류</b>' : ""}</span></div>
        <pre class="code">${esc(a.code || "")}</pre>
        <div class="did-sub">출력</div><pre>${esc(r["출력"] || "(없음)")}</pre>
        ${err ? `<div class="did-sub">오류</div><pre class="errtext">${esc(err)}</pre>` : ""}</div>`;
    }
    if (t.name === "read_data_file") {
      const body = r["내용"] !== undefined ? r["내용"] : pretty(r);
      return `<div class="did"><div class="did-head">read_data_file <span>${esc(a.name || "파일 목록")} · ${t.elapsed}초</span></div>
        <pre>${esc(body)}</pre></div>`;
    }
    return `<div class="did"><div class="did-head">${esc(t.name)} <span>${esc(t.source)} · ${t.elapsed}초</span></div>
      <pre><span class="j-label">인자</span>\n${hl(a)}\n<span class="j-label">결과</span>\n${hl(r)}</pre></div>`;
  }).join("");
}

/* 긴 보고는 접어 두고 [더 보기]로 편다. 보고 하나가 화면을 차지하지 않게 한다. */
const CLAMP_CHARS = 1200;
function bodyHtml(text) {
  const long = String(text || "").length > CLAMP_CHARS;
  return `<div class="body md${long ? " clamp" : ""}">${md(text)}</div>`
    + (long ? '<button type="button" class="more-btn">더 보기</button>' : "");
}
document.addEventListener("click", (ev) => {
  const b = ev.target.closest(".more-btn");
  if (!b) return;
  const body = b.previousElementSibling;
  const open = body.classList.toggle("clamp");
  b.textContent = open ? "더 보기" : "접기";
});

function bubbleHtml(e) {
  if (e.kind === "delegate") {
    return `<div class="bubble to ${esc(e.to)}"><div class="who">연구책임자 → ${esc(e.label)} <span class="kind">지시</span></div>
      ${bodyHtml(e.instruction)}</div>`;
  }
  if (e.kind === "return") {
    const bad = e.ok === false;
    const trace = e.trace || [];
    const nTools = trace.length ? trace.filter((t) => t.kind === "tool").length : (e.calls || []).length;
    const nCalls = e.steps || trace.filter((t) => t.kind === "request").length;
    const stat = [`${e.elapsed}초`, `도구 ${nTools}회`, nCalls ? `API 호출 ${nCalls}회` : "", e.tokens ? `${e.tokens}토큰` : ""]
      .filter(Boolean).join(" · ");
    const searches = (e.searches || []).length
      ? `<div class="searches">웹 검색 — ${esc(e.searches.join(" / "))}</div>` : "";
    const did = didHtml(e);
    const inner = trace.length
      ? `<details><summary>연구원의 API 호출 내역 (${nCalls}회)</summary><div class="trace">${traceHtml(trace, false)}</div></details>` : "";
    return `<div class="bubble from ${esc(e.from)}${bad ? " fail" : ""}">
      <div class="who">${esc(e.label)} → 연구책임자 <span class="kind">${bad ? "실패" : "보고"}</span><span class="stat">${stat}</span></div>
      ${bodyHtml(e.result)}${searches}
      ${did ? `<details><summary>연구원이 한 일 (도구 ${nTools}회)</summary>${did}</details>` : ""}${inner}</div>`;
  }
  return `<div class="bubble final"><div class="who">연구책임자 결론${e.stopped ? ' <span class="kind">중지됨</span>' : ""}</div>
    <div class="body md">${md(e.text)}</div></div>`;
}

function typingHtml(p) {
  const log = p.log || [];
  const last = log[log.length - 1];
  if (p.starting) {
    return `<div class="bubble to orchestrator typing"><div class="who">연구책임자</div>
      <div class="body">꺼져 있는 연구원을 띄우는 중… <span class="since" data-at="${p.started || 0}"></span></div></div>`;
  }
  if (last && last.kind === "delegate") {
    return `<div class="bubble from ${esc(last.to)} typing"><div class="who">${esc(last.label)}</div>
      <div class="body">${p.stopping ? "맡은 일을 마치는 중 — 끝나면 멈춥니다" : "일하는 중"}… <span class="since" data-at="${last.at}"></span></div></div>`;
  }
  return `<div class="bubble to orchestrator typing"><div class="who">연구책임자</div>
    <div class="body">${last ? "보고를 읽고 다음을 정하는 중" : "질문을 읽는 중"}… <span class="since" data-at="${last ? last.at : p.started || 0}"></span></div></div>`;
}

function renderChat(running, p) {
  const parts = [];
  ROUNDS.forEach((round, i) => {
    parts.push(`<div class="bubble user"><div class="who">${round.followUp ? "이어서 물어봄" : "연구 요청"}</div>
      <div class="body md">${md(round.question)}</div></div>`);
    round.log.forEach((e) => parts.push(bubbleHtml(e)));
    if (running && i === ROUNDS.length - 1) parts.push(typingHtml(p || { log: round.log }));
  });
  $("researchLog").innerHTML = parts.join("");
}

/* 폴링마다 부른다. 말풍선 수가 바뀔 때만 다시 그려서, 펼쳐 둔 상자가 닫히지 않게 한다. */
function syncChat(p) {
  if (!ROUNDS.length && (p.running || (p.log || []).length)) {
    // 새로고침으로 들어온 경우 — 도는 중이면 이어서 그리고, 끝난 연구면 마지막 결과를 보여 준다
    ROUNDS.push({ question: p.question || "", followUp: !!p.follow_up, log: p.running ? [] : (p.log || []) });
  }
  if (p.running && ROUNDS.length) ROUNDS[ROUNDS.length - 1].log = p.log || [];
  const last = (p.log || [])[(p.log || []).length - 1];
  const key = `${ROUNDS.length}:${(p.log || []).length}:${p.running ? 1 : 0}:${p.starting ? 1 : 0}:${p.stopping ? 1 : 0}:${last ? last.kind : ""}`;
  if (key !== CHAT_KEY) { CHAT_KEY = key; renderChat(!!p.running, p); }
  const now = Date.now() / 1000;
  document.querySelectorAll("#researchLog .since").forEach((s) => {
    const at = Number(s.dataset.at) || 0;
    s.textContent = at ? `${Math.max(0, Math.round(now - at))}초째` : "";
  });
}

async function runResearch(question, followUp) {
  const btn = followUp ? $("askFollow") : $("startResearch");
  btn.disabled = true;
  if (!followUp) { ROUNDS = []; CHAT_KEY = ""; }
  ROUNDS.push({ question, followUp: !!followUp, log: [] });
  let note = "연구를 진행하고 있습니다. 아래에서 지시와 보고를 확인하세요.";
  try {
    const st = await get("/api/agents");
    const down = (st.agents || []).filter((a) => a.role !== "orchestrator" && !a.up).map((a) => a.label);
    if (down.length) note = `${down.join(", ")}을(를) 먼저 띄운 뒤 연구를 시작합니다…`;
  } catch (e) { /* 상태를 못 읽어도 연구는 시작한다 */ }
  $("researchNote").textContent = note;
  applyProgress({ running: true, starting: true, log: [], question, follow_up: !!followUp, started: Date.now() / 1000 });
  INFLIGHT = true;
  startPolling();
  try {
    const r = await post("/api/research", { question, follow_up: !!followUp });
    INFLIGHT = false;
    stopPolling();
    ROUNDS[ROUNDS.length - 1].log = r.log || [];
    CHAT_KEY = "";
    applyProgress({ running: false, log: r.log || [] });
    const n = (r.log || []).filter((e) => e.kind === "delegate").length;
    $("researchNote").textContent = r.ok
      ? `${r.elapsed}초 · 위임 ${n}회 · ${r.tokens}토큰`
        + ((r.auto_started || []).length ? ` · ${r.auto_started.join(", ")} 자동 시작` : "")
      : (r.message || "실패했습니다.");
    $("followCard").hidden = !r.has_session;
    if (!r.ok) setStatus(r.message || "실패했습니다.", "fail");
    if (followUp) $("followQuestion").value = "";
  } catch (e) {
    $("researchNote").textContent = "서버에 연결하지 못했습니다.";
    setStatus("서버에 연결하지 못했습니다.", "fail");
  }
  INFLIGHT = false;
  stopPolling();
  setRunning(false);
  refreshAgents();
}

/* ── 예시 질문 칩 ────────────────────────────────────── */
const FOLLOW_CHIPS = [
  { label: "후속 — 램프 기간 8·14·20개월",
    text: "공정 안정화가 예상보다 늦어져 수율 램프 기간이 최소 8개월, 기준 14개월, 최대 20개월이라면 어떻게 되나? 나머지 조건과 확률변수를 뽑는 방식은 그대로 두고 다시 계산해 줘." },
  { label: "후속 — 시행 10만 회",
    text: "시행 횟수를 10만 회로 늘려 다시 계산해 줘." },
];

function drawChips(boxId, chips, targetId) {
  $(boxId).innerHTML = chips.map((c, i) =>
    `<button type="button" class="qchip" data-i="${i}">${esc(c.label)}</button>`).join("");
  $(boxId).querySelectorAll(".qchip").forEach((b) => {
    b.addEventListener("click", () => {
      $(targetId).value = chips[Number(b.dataset.i)].text;
      $(targetId).focus();
    });
  });
}
drawChips("followChips", FOLLOW_CHIPS, "followQuestion");

async function agentsAll(path, button, busyText) {
  button.disabled = true;
  const was = button.textContent;
  button.textContent = busyText;
  try {
    const r = await post(path, {});
    if (r.agents) drawAgents(r.agents);
    $("researchNote").textContent = r.message || "";
  } catch (e) { $("researchNote").textContent = "서버에 연결하지 못했습니다."; }
  button.textContent = was;
  button.disabled = false;
}
$("agentsStartAll").addEventListener("click", () => agentsAll("/api/agents/start_all", $("agentsStartAll"), "시작 중…"));
$("agentsStopAll").addEventListener("click", () => agentsAll("/api/agents/stop_all", $("agentsStopAll"), "종료 중…"));

$("stopResearch").addEventListener("click", async () => {
  $("stopResearch").disabled = true;
  $("stopResearchInline").disabled = true;
  const r = await post("/api/research/stop", {});
  $("researchNote").textContent = r.message || "";
});
$("stopResearchInline").addEventListener("click", () => $("stopResearch").click());

document.querySelector('label[for="fileInput"]').addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); $("fileInput").click(); }
});

$("fileInput").addEventListener("change", async (ev) => {
  const files = Array.from(ev.target.files || []);
  ev.target.value = "";              // 같은 파일을 다시 골라도 change가 오도록 비운다
  if (files.length) await uploadFiles(files);
});

// 카드 위로 끌어다 놓아도 업로드된다.
const dropCard = $("fileList").closest(".card");
["dragenter", "dragover"].forEach((t) => dropCard.addEventListener(t, (e) => {
  e.preventDefault(); dropCard.classList.add("drop");
}));
["dragleave", "drop"].forEach((t) => dropCard.addEventListener(t, (e) => {
  e.preventDefault(); dropCard.classList.remove("drop");
}));
dropCard.addEventListener("drop", async (e) => {
  const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
  if (files.length) await uploadFiles(files);
});

$("agentsRefresh").addEventListener("click", refreshAgents);
$("startResearch").addEventListener("click", () => {
  const q = $("question").value.trim();
  if (q) runResearch(q, false);
});
$("askFollow").addEventListener("click", () => {
  const q = $("followQuestion").value.trim();
  if (q) runResearch(q, true);
});
$("followQuestion").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("askFollow").click();
});
$("resetSession").addEventListener("click", async () => {
  await post("/api/research/reset", {});
  $("followCard").hidden = true;
  ROUNDS = []; CHAT_KEY = "";
  $("researchLog").innerHTML = "";
  $("researchNote").textContent = "";
});

document.querySelector('.tab[data-tab="agents"]')
  .addEventListener("click", refreshAgents);

$("send").addEventListener("click", send);
$("message").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });

$("savePrompt").addEventListener("click", async () => {
  await post("/api/prompt", { text: $("prompt").value });
  refresh();
});
$("resetPrompt").addEventListener("click", async () => {
  await post("/api/prompt/reset", {});
  refresh();
});
$("resetChat").addEventListener("click", async () => {
  if ($("send").disabled) return;               // 처리 중인 요청이 끝난 뒤에 비운다
  await post("/api/chat/reset", {});
  $("answer").hidden = true;
  $("calls").innerHTML = "";
  refresh();
});


refresh();

$("llmProvider").addEventListener("change", () => {
  const previous = LLM_SETTINGS_CACHE && LLM_SETTINGS_CACHE.provider || "openrouter";
  if (LLM_SETTINGS_CACHE) LLM_SETTINGS_CACHE[`${previous}_model`] = $("llmModel").value.trim();
  const provider = $("llmProvider").value;
  const nextModel = LLM_SETTINGS_CACHE && LLM_SETTINGS_CACHE[`${provider}_model`];
  $("llmModel").value = nextModel || "";
  if (LLM_SETTINGS_CACHE) LLM_SETTINGS_CACHE.provider = provider;
  llmSettingsDirty = true;
  updateLlmSettingsFields();
});
$("llmModel").addEventListener("input", () => {
  llmSettingsDirty = true;
  if (LLM_SETTINGS_CACHE) LLM_SETTINGS_CACHE[`${$("llmProvider").value}_model`] = $("llmModel").value.trim();
});
$("ollamaBaseUrl").addEventListener("input", () => { llmSettingsDirty = true; });
$("llmSettingsForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("saveLlmSettings"), note = $("llmSettingsNote");
  button.disabled = true;
  note.textContent = "설정 저장 중…";
  try {
    const provider = $("llmProvider").value;
    const r = await post("/api/llm/settings", {
      provider,
      model: $("llmModel").value.trim(),
      openrouter_model: LLM_SETTINGS_CACHE && LLM_SETTINGS_CACHE.openrouter_model || "",
      ollama_model: LLM_SETTINGS_CACHE && LLM_SETTINGS_CACHE.ollama_model || "",
      ollama_base_url: $("ollamaBaseUrl").value.trim(),
    });
    if (!r.ok) {
      note.textContent = r.message || "설정을 저장하지 못했습니다.";
      return;
    }
    llmSettingsDirty = false;
    note.textContent = "설정을 저장했습니다. 다음 요청부터 적용됩니다.";
    await refresh().catch(() => {});
  } catch (error) {
    note.textContent = error instanceof TypeError
      ? "설정 API에 연결하지 못했습니다. 페이지 새로고침 후에도 반복되면 배포 주소의 APP_TRUSTED_ORIGINS 설정과 프록시 연결을 확인해 주세요."
      : (error.message || "설정을 저장하지 못했습니다. 배포 서버 로그를 확인해 주세요.");
  } finally {
    button.disabled = false;
  }
});
