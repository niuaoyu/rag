/* ========= 基础状态与工具 ========= */
const API = "";                       // 同源，无需写 host
let token = localStorage.getItem("rag_token") || "";
let currentUser = localStorage.getItem("rag_user") || "";
let conversationId = null;
let pollTimer = null;

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function toast(msg, type = "") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast " + type;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add("hidden"), 2600);
}

async function api(path, { method = "GET", body, formData, auth = true } = {}) {
  const headers = {};
  if (auth && token) headers["Authorization"] = "Bearer " + token;
  let payload;
  if (formData) {
    payload = formData;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(API + path, { method, headers, body: payload });
  if (res.status === 401 && auth) {
    logout();
    throw new Error("登录已过期，请重新登录");
  }
  let data = null;
  const text = await res.text();
  if (text) { try { data = JSON.parse(text); } catch { data = text; } }
  if (!res.ok) {
    const detail = (data && data.detail) || data || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

/* ========= 登录 / 注册 ========= */
$$(".tab").forEach((tab) => {
  tab.onclick = () => {
    $$(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const isLogin = tab.dataset.tab === "login";
    $("#login-form").classList.toggle("hidden", !isLogin);
    $("#register-form").classList.toggle("hidden", isLogin);
    $("#auth-msg").textContent = "";
  };
});

function setAuthMsg(msg, type = "") {
  const el = $("#auth-msg");
  el.textContent = msg;
  el.className = "msg " + type;
}

$("#login-form").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  setAuthMsg("登录中…");
  try {
    const data = await api("/auth/login", {
      method: "POST", auth: false,
      body: { username: f.get("username"), password: f.get("password") },
    });
    token = data.access_token;
    const me = await api("/auth/me");
    currentUser = me.username;
    localStorage.setItem("rag_token", token);
    localStorage.setItem("rag_user", currentUser);
    enterApp();
  } catch (err) {
    setAuthMsg(err.message, "error");
  }
};

$("#register-form").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  setAuthMsg("注册中…");
  try {
    await api("/auth/register", {
      method: "POST", auth: false,
      body: { username: f.get("username"), password: f.get("password") },
    });
    const data = await api("/auth/login", {
      method: "POST", auth: false,
      body: { username: f.get("username"), password: f.get("password") },
    });
    token = data.access_token;
    const me = await api("/auth/me");
    currentUser = me.username;
    localStorage.setItem("rag_token", token);
    localStorage.setItem("rag_user", currentUser);
    enterApp();
  } catch (err) {
    setAuthMsg(err.message, "error");
  }
};

function logout() {
  token = ""; currentUser = ""; conversationId = null;
  localStorage.removeItem("rag_token");
  localStorage.removeItem("rag_user");
  clearInterval(pollTimer);
  $("#app-screen").classList.add("hidden");
  $("#auth-screen").classList.remove("hidden");
  $("#messages").innerHTML = "";
}

$("#logout-btn").onclick = logout;

function enterApp() {
  $("#auth-screen").classList.add("hidden");
  $("#app-screen").classList.remove("hidden");
  $("#current-user").textContent = currentUser ? "👤 " + currentUser : "";
  loadHealth();
  loadDocuments();
  if (!pollTimer) pollTimer = setInterval(loadDocuments, 4000);
}

/* ========= 健康状态 ========= */
async function loadHealth() {
  try {
    const h = await api("/health", { auth: false });
    $("#health-badge").textContent = `服务正常 · v${h.version}`;
    $("#health-badge").className = "badge ok";
  } catch {
    $("#health-badge").textContent = "服务不可用";
    $("#health-badge").className = "badge err";
  }
}

/* ========= 文档上传与管理 ========= */
const fileInput = $("#file-input");
const dropzone = $("#dropzone");

dropzone.onclick = () => fileInput.click();
fileInput.onchange = () => {
  if (fileInput.files[0]) uploadFile(fileInput.files[0]);
  fileInput.value = "";
};
["dragenter", "dragover"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("dragover"); }));
["dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("dragover"); }));
dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file);
});

async function uploadFile(file) {
  const ok = /\.(pdf|txt|md|markdown)$/i.test(file.name);
  if (!ok) return toast("只支持 PDF / TXT / MD 文件", "error");
  if (file.size > 20 * 1024 * 1024) return toast("文件超过 20MB", "error");

  const fd = new FormData();
  fd.append("file", file);
  toast(`正在上传 ${file.name} …`);
  try {
    const data = await api("/documents/upload", { method: "POST", formData: fd });
    toast(data.message || "上传成功", "ok");
    loadDocuments();
  } catch (err) {
    toast("上传失败：" + err.message, "error");
  }
}

$("#refresh-docs").onclick = () => loadDocuments();

async function loadDocuments() {
  if (!token) return;
  try {
    const docs = await api("/documents");
    renderDocuments(docs);
  } catch { /* 静默，避免轮询时刷屏 */ }
}

const STATUS_TEXT = { pending: "排队中", processing: "处理中", done: "已完成", failed: "失败" };

function renderDocuments(docs) {
  const list = $("#doc-list");
  if (!docs.length) {
    list.innerHTML = '<li class="empty muted">还没有文档，先上传一个吧</li>';
    return;
  }
  list.innerHTML = docs.map((d) => `
    <li class="doc-item">
      <div class="doc-top">
        <span class="doc-name">📄 ${escapeHtml(d.filename)}</span>
        <button class="doc-del" data-id="${d.id}" title="删除">✕</button>
      </div>
      <div class="doc-meta">
        <span class="status ${d.status}">${STATUS_TEXT[d.status] || d.status}</span>
        <span>${d.chunk_count || 0} 个分块</span>
        <span>#${d.id}</span>
      </div>
      ${d.error ? `<div class="doc-error">${escapeHtml(d.error)}</div>` : ""}
    </li>`).join("");

  $$(".doc-del").forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api("/documents/" + btn.dataset.id, { method: "DELETE" });
        toast("已删除", "ok");
        loadDocuments();
      } catch (err) { toast(err.message, "error"); }
    };
  });
}

/* ========= 对话 ========= */
const chatInput = $("#chat-input");
chatInput.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + "px";
});
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chat-form").requestSubmit(); }
});

$$(".suggestion").forEach((btn) => {
  btn.onclick = () => { chatInput.value = btn.textContent.trim(); chatInput.focus(); };
});

$("#new-conv").onclick = () => {
  conversationId = null;
  $("#conv-title").textContent = "新会话";
  $("#messages").innerHTML = "";
  toast("已开启新会话", "ok");
};

$("#chat-form").onsubmit = async (e) => {
  e.preventDefault();
  const question = chatInput.value.trim();
  if (!question) return;

  chatInput.value = "";
  chatInput.style.height = "auto";
  hideWelcome();
  appendMessage("user", question);
  const typing = appendTyping();
  $("#send-btn").disabled = true;

  try {
    const data = await api("/chat", {
      method: "POST",
      body: {
        question,
        conversation_id: conversationId,
        use_tools: $("#tools-toggle").checked,
      },
    });
    conversationId = data.conversation_id;
    $("#conv-title").textContent = "会话 #" + conversationId;
    typing.remove();
    appendAssistant(data);
  } catch (err) {
    typing.remove();
    appendMessage("assistant", "❌ 出错了：" + err.message);
  } finally {
    $("#send-btn").disabled = false;
    chatInput.focus();
  }
};

function hideWelcome() {
  const w = $("#messages .welcome");
  if (w) w.remove();
}

function appendMessage(role, content) {
  const row = document.createElement("div");
  row.className = "msg-row " + role;
  row.innerHTML = `
    <div class="avatar">${role === "user" ? "我" : "AI"}</div>
    <div class="bubble">${escapeHtml(content)}</div>`;
  $("#messages").appendChild(row);
  scrollBottom();
  return row;
}

function appendTyping() {
  const row = document.createElement("div");
  row.className = "msg-row assistant";
  row.innerHTML = `<div class="avatar">AI</div><div class="bubble typing">正在检索知识库并思考…</div>`;
  $("#messages").appendChild(row);
  scrollBottom();
  return row;
}

function appendAssistant(data) {
  const citations = data.citations || [];
  const toolCalls = data.tool_calls || [];

  let html = `<div class="bubble">${escapeHtml(data.answer)}`;

  if (citations.length) {
    html += `<div class="citations"><div class="citations-title">📎 来源引用（${citations.length}）</div>`;
    citations.forEach((c) => {
      const page = c.page ? `Page ${c.page}` : "无页码";
      html += `
        <div class="citation">
          <div class="citation-head">
            <span>${escapeHtml(c.filename)} · ${page}</span>
            <span>${c.score != null ? "相似度 " + c.score : ""}</span>
          </div>
          <div class="citation-text">${escapeHtml(c.content)}</div>
        </div>`;
    });
    html += "</div>";
  }

  if (toolCalls.length) {
    html += `<div class="tool-calls">`;
    toolCalls.forEach((t) => {
      html += `
        <div class="tool-call ${t.ok ? "" : "bad"}">
          <div class="tool-call-head">🔧 调用工具 ${escapeHtml(t.name)} ${t.ok ? "成功" : "失败"}</div>
          <pre>参数：${escapeHtml(JSON.stringify(t.arguments))}\n结果：${escapeHtml(JSON.stringify(t.result))}</pre>
        </div>`;
    });
    html += "</div>";
  }

  html += `</div>`;

  const row = document.createElement("div");
  row.className = "msg-row assistant";
  row.innerHTML = `<div class="avatar">AI</div>${html}`;
  $("#messages").appendChild(row);
  scrollBottom();
}

function scrollBottom() {
  const box = $("#messages");
  box.scrollTop = box.scrollHeight;
}

/* ========= 启动 ========= */
(async function boot() {
  if (token) {
    try {
      const me = await api("/auth/me");
      currentUser = me.username;
      enterApp();
      return;
    } catch { /* token 失效，回到登录页 */ }
  }
  $("#auth-screen").classList.remove("hidden");
})();
