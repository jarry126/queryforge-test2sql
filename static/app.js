// QueryForge 前端：登录 / 历史会话 / 多轮聊天（原生 JS，无构建）
const API = "/api/v1";
const $ = (id) => document.getElementById(id);

let currentSession = null; // {id, title, db_id}

// ---- token ----
const getToken = () => localStorage.getItem("qf_token");
const setToken = (t) => localStorage.setItem("qf_token", t);
const clearToken = () => localStorage.removeItem("qf_token");

// ---- 通用请求 ----
async function api(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  const tok = getToken();
  if (tok) headers["Authorization"] = "Bearer " + tok;
  const res = await fetch(API + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (res.status === 401) { logout(); throw new Error("登录已失效"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// ---- 视图切换 ----
function showAuth() { $("auth-view").classList.remove("hidden"); $("app-view").classList.add("hidden"); }
function showApp(username) {
  $("auth-view").classList.add("hidden"); $("app-view").classList.remove("hidden");
  $("who").textContent = "👤 " + username;
}

// ---- 鉴权 ----
async function doAuth(kind) {
  $("auth-error").textContent = "";
  const username = $("username").value.trim();
  const password = $("password").value;
  if (!username || !password) { $("auth-error").textContent = "请输入用户名和密码"; return; }
  try {
    const data = await api(`/auth/${kind}`, { method: "POST", body: { username, password } });
    setToken(data.access_token);
    await enterApp(data.username);
  } catch (e) { $("auth-error").textContent = e.message; }
}

function logout() { clearToken(); currentSession = null; showAuth(); }

async function enterApp(username) {
  showApp(username);
  await loadDatabases();
  await loadSessions();
}

// ---- 数据库下拉 ----
async function loadDatabases() {
  const dbs = await api("/databases");
  const sel = $("db-select");
  sel.innerHTML = '<option value="">选择数据库…</option>' +
    dbs.map((d) => `<option value="${esc(d)}">${esc(d)}</option>`).join("");
}

// ---- 会话列表 ----
async function loadSessions() {
  const list = await api("/sessions");
  const ul = $("session-list");
  ul.innerHTML = "";
  list.forEach((s) => {
    const li = document.createElement("li");
    if (currentSession && s.id === currentSession.id) li.classList.add("active");
    li.innerHTML = `<span class="title">${esc(s.title)}</span>
      <span class="db">${esc(s.db_id)}</span>
      <span class="del" title="删除">✕</span>`;
    li.querySelector(".title").onclick = () => openSession(s);
    li.querySelector(".db").onclick = () => openSession(s);
    li.querySelector(".del").onclick = async (ev) => {
      ev.stopPropagation();
      await api(`/sessions/${s.id}`, { method: "DELETE" });
      if (currentSession && currentSession.id === s.id) { currentSession = null; resetChat(); }
      loadSessions();
    };
    ul.appendChild(li);
  });
}

async function newSession() {
  const db_id = $("db-select").value;
  if (!db_id) { alert("请先选择一个数据库"); return; }
  const s = await api("/sessions", { method: "POST", body: { db_id } });
  await loadSessions();
  openSession(s);
}

// ---- 打开会话 + 渲染消息 ----
function resetChat() {
  $("chat-title").textContent = "选择或新建一个会话开始";
  $("messages").innerHTML = "";
  $("chat-input").disabled = true; $("chat-send").disabled = true;
}

async function openSession(s) {
  currentSession = s;
  $("chat-title").textContent = `${s.title}  ·  库：${s.db_id}`;
  $("chat-input").disabled = false; $("chat-send").disabled = false;
  $("chat-input").focus();
  await loadSessions();
  const msgs = await api(`/sessions/${s.id}/messages`);
  $("messages").innerHTML = "";
  msgs.forEach(renderMessage);
  scrollBottom();
}

function renderMessage(m) {
  const div = document.createElement("div");
  div.className = "msg " + (m.role === "user" ? "user" : "assistant");
  let html = esc(m.content);
  if (m.role === "assistant") {
    if (m.sql) html += `<div class="sql">${esc(m.sql)}</div>`;
    if (m.result && m.result.columns && m.result.rows) html += renderTable(m.result);
  }
  div.innerHTML = html;
  $("messages").appendChild(div);
}

function renderTable(r) {
  if (!r.rows.length) return `<div class="meta">（无数据）</div>`;
  const head = "<tr>" + r.columns.map((c) => `<th>${esc(c)}</th>`).join("") + "</tr>";
  const body = r.rows.slice(0, 20).map((row) =>
    "<tr>" + row.map((c) => `<td>${esc(c)}</td>`).join("") + "</tr>").join("");
  const more = r.row_count > 20 ? `<div class="meta">共 ${r.row_count} 行，已截断显示前 20 行</div>` : "";
  return `<table>${head}${body}</table>${more}`;
}

function scrollBottom() { const m = $("messages"); m.scrollTop = m.scrollHeight; }

// ---- 发送（多轮）----
async function sendChat(ev) {
  ev.preventDefault();
  if (!currentSession) return;
  const input = $("chat-input");
  const question = input.value.trim();
  if (!question) return;
  input.value = "";
  renderMessage({ role: "user", content: question });
  scrollBottom();

  const pending = document.createElement("div");
  pending.className = "msg assistant"; pending.textContent = "思考中…";
  $("messages").appendChild(pending); scrollBottom();

  try {
    const resp = await api(`/sessions/${currentSession.id}/chat`, { method: "POST", body: { question } });
    pending.remove();
    renderMessage({
      role: "assistant", content: resp.answer, sql: resp.sql,
      result: { columns: resp.columns, rows: resp.rows, row_count: resp.row_count },
    });
    scrollBottom();
    loadSessions(); // 刷新标题/排序
  } catch (e) {
    pending.textContent = "出错了：" + e.message;
  }
}

// ---- 绑定事件 ----
$("btn-login").onclick = () => doAuth("login");
$("btn-register").onclick = () => doAuth("register");
$("btn-logout").onclick = logout;
$("btn-new").onclick = newSession;
$("chat-form").onsubmit = sendChat;
$("password").addEventListener("keydown", (e) => { if (e.key === "Enter") doAuth("login"); });

// ---- 启动：有 token 直接进 ----
(async function init() {
  if (getToken()) {
    try { const me = await api("/auth/me"); await enterApp(me.username); return; } catch (_) {}
  }
  showAuth();
})();
