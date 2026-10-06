// ── Elementos ──────────────────────────────────────────────────────────────
const messagesEl = document.getElementById("messages");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send-btn");
const themeToggle = document.getElementById("theme-toggle");
const root = document.documentElement;

// ── Tema claro/oscuro (persistente + respeta preferencia del sistema) ───────
function initTheme() {
  const saved = localStorage.getItem("secretaria_theme");
  const prefersDark = window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  root.setAttribute("data-theme", saved || (prefersDark ? "dark" : "light"));
}
themeToggle.addEventListener("click", () => {
  const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
  root.setAttribute("data-theme", next);
  localStorage.setItem("secretaria_theme", next);
});
initTheme();

// ── Identidad sin login: token UUID por navegador (con fallback) ────────────
function makeUUID() {
  if (window.crypto && crypto.randomUUID) {
    try { return crypto.randomUUID(); } catch (e) { /* fallback abajo */ }
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}
let token = localStorage.getItem("secretaria_token");
if (!token) {
  token = makeUUID();
  localStorage.setItem("secretaria_token", token);
}

// ── Render de mensajes ──────────────────────────────────────────────────────
function addMessage(text, who) {
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  scrollToBottom();
  return div;
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeWelcome() {
  const w = messagesEl.querySelector(".welcome");
  if (w) w.remove();
}

// burbuja de error con botón "Reintentar" que reenvía la última pregunta
function addErrorMessage(text, retryMessage) {
  const div = document.createElement("div");
  div.className = "msg error";
  const span = document.createElement("span");
  span.textContent = text + " ";
  div.appendChild(span);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "retry-btn";
  btn.textContent = "Reintentar";
  btn.addEventListener("click", () => {
    if (busy) return;
    div.remove();
    send(retryMessage);
  });
  div.appendChild(btn);
  messagesEl.appendChild(div);
  scrollToBottom();
}

// burbuja del bot con indicador de escritura; se rellena al llegar tokens
function addBotBubbleWithTyping() {
  const div = document.createElement("div");
  div.className = "msg bot";
  div.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
  messagesEl.appendChild(div);
  scrollToBottom();
  return div;
}

// ── Pantalla de bienvenida ──────────────────────────────────────────────────
const SUGGESTIONS = [
  "¿Qué módulos tiene DAM?",
  "¿Cuándo es el plazo de matrícula?",
  "¿Qué becas hay disponibles?",
  "Horario de secretaría",
];
function showWelcome() {
  const w = document.createElement("div");
  w.className = "welcome";
  w.innerHTML =
    "<h2>¡Hola! 👋</h2>" +
    "<p>Soy el asistente del Centro de FP Ejemplo Norte. Pregúntame sobre ciclos, módulos, " +
    "matrícula, becas, horarios o trámites del centro.</p>" +
    '<div class="suggestions"></div>';
  const cont = w.querySelector(".suggestions");
  SUGGESTIONS.forEach((s) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "suggestion";
    b.textContent = s;
    b.addEventListener("click", () => { input.value = s; submit(); });
    cont.appendChild(b);
  });
  messagesEl.appendChild(w);
}

// ── Cargar historial al abrir ───────────────────────────────────────────────
async function loadHistory() {
  try {
    const r = await fetch(`/history/${token}`);
    if (!r.ok) throw new Error("history " + r.status);
    const data = await r.json();
    const msgs = data.messages || [];
    if (msgs.length === 0) { showWelcome(); return; }
    msgs.forEach((m) => addMessage(m.content, m.role === "user" ? "user" : "bot"));
  } catch (e) {
    showWelcome();
  }
}

// ── Chips de seguimiento (sugerencias proactivas tras la respuesta) ─────────
function removeFollowups() {
  messagesEl.querySelectorAll(".followups").forEach((el) => el.remove());
}

function renderFollowups(botDiv, items) {
  if (!Array.isArray(items) || items.length === 0) return;
  removeFollowups(); // solo el último set de chips visible
  const cont = document.createElement("div");
  cont.className = "followups";
  items.slice(0, 3).forEach((q) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "suggestion";
    b.textContent = q;
    b.addEventListener("click", () => {
      if (busy) return;
      removeFollowups();
      send(q);
    });
    cont.appendChild(b);
  });
  botDiv.insertAdjacentElement("afterend", cont);
  scrollToBottom();
}

// ── Enviar pregunta + leer stream SSE ───────────────────────────────────────
let busy = false;

// Reintentos automáticos ante cortes transitorios (móvil / Wi-Fi inestable, ~32%
// de pérdida de paquetes por VPN). El backend solo persiste los mensajes tras
// recibir [DONE], así que reintentar la petición entera no duplica nada.
const MAX_AUTO_RETRIES = 3;

function setBusy(state) {
  busy = state;
  sendBtn.disabled = state;
  input.disabled = state;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Espera reconexión: vuelve antes si el navegador anuncia 'online', si no agota backoff.
function waitForReconnect(ms) {
  if (navigator.onLine === false) {
    return new Promise((resolve) => {
      const done = () => { window.removeEventListener("online", done); clearTimeout(t); resolve(); };
      const t = setTimeout(done, ms);
      window.addEventListener("online", done, { once: true });
    });
  }
  return sleep(ms);
}

function resetBubbleToTyping(botDiv) {
  removeFollowups();
  botDiv.innerHTML =
    '<span class="typing"><span></span><span></span><span></span></span>';
  scrollToBottom();
}

// Un intento de stream. Devuelve "done" | "empty" | "drop".
// Lanza si la red falla o el status HTTP no es 2xx (lo trata el llamante como corte).
async function streamOnce(message, botDiv) {
  const resp = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_token: token }),
  });
  if (!resp.ok || !resp.body) throw new Error("chat " + resp.status);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let firstToken = true;
  let gotDone = false;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop();
    for (const frame of frames) {
      const line = frame.replace(/^data: /, "").trim();
      if (!line) continue;
      if (line === "[DONE]") { gotDone = true; continue; }
      try {
        const obj = JSON.parse(line);
        if (obj.token) {
          if (firstToken) { botDiv.textContent = ""; firstToken = false; }
          botDiv.textContent += obj.token;
          scrollToBottom();
        } else if (obj.suggestions) {
          renderFollowups(botDiv, obj.suggestions);
        }
      } catch (e) { /* frame parcial, ignorar */ }
    }
  }
  if (!gotDone) return "drop";          // stream cortado antes de terminar
  return firstToken ? "empty" : "done"; // [DONE] sin tokens = respuesta vacía
}

async function send(message) {
  removeWelcome();
  removeFollowups();
  addMessage(message, "user");
  const botDiv = addBotBubbleWithTyping();
  setBusy(true);

  try {
    for (let attempt = 0; attempt <= MAX_AUTO_RETRIES; attempt++) {
      let outcome = "drop";
      try {
        outcome = await streamOnce(message, botDiv);
      } catch (e) {
        outcome = "drop"; // fallo de red / HTTP → reintentable
      }
      if (outcome === "done") return;
      if (outcome === "empty") {
        botDiv.remove();
        addErrorMessage("No he recibido respuesta.", message);
        return;
      }
      // outcome === "drop": corte transitorio → reintentar si quedan intentos
      if (attempt < MAX_AUTO_RETRIES) {
        resetBubbleToTyping(botDiv);
        await waitForReconnect(600 * Math.pow(2, attempt)); // 600ms, 1.2s, 2.4s
      }
    }
    // Agotados los reintentos → error visible con botón Reintentar manual.
    botDiv.remove();
    addErrorMessage(
      "No he podido conectar con el asistente. Comprueba tu conexión.",
      message
    );
  } finally {
    setBusy(false);
    input.focus();
  }
}

// ── Envío (form + sugerencias) ──────────────────────────────────────────────
function submit() {
  if (busy) return;
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  send(message);
}
form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });

loadHistory();
input.focus();
