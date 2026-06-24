import { initAdmin, onAdminTabShown } from "./admin.js";

const messagesEl = document.getElementById("messages");
const composerEl = document.getElementById("composer");
const inputEl = document.getElementById("input");
const sendEl = document.getElementById("send");
const newChatEl = document.getElementById("new-chat");
const titleEl = document.getElementById("app-title");
const subtitleEl = document.getElementById("app-subtitle");

let sessionId = null;
let chatKey = null;
let busy = false;
let appConfig = {};

function headers() {
  const value = { "Content-Type": "application/json" };
  if (chatKey) value["X-Chat-Key"] = chatKey;
  return value;
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatAssistantHtml(text) {
  const normalized = text.replace(/\bLearn more:\s*/gi, "Source: ");
  const escaped = escapeHtml(normalized);
  return escaped.replace(
    /https?:\/\/[^\s<]+[^\s<.,;:!?)}\]'"]/g,
    (url) =>
      `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`,
  );
}

function appendMessage(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `message ${role}`;
  if (role === "assistant") {
    bubble.innerHTML = formatAssistantHtml(text);
  } else {
    bubble.textContent = text;
  }
  messagesEl.appendChild(bubble);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setBusy(next) {
  busy = next;
  sendEl.disabled = next;
  inputEl.disabled = next;
}

function switchTab(tab) {
  const isChat = tab === "chat";
  document.getElementById("panel-chat").classList.toggle("active", isChat);
  document.getElementById("panel-chat").hidden = !isChat;
  document.getElementById("panel-admin").classList.toggle("active", !isChat);
  document.getElementById("panel-admin").hidden = isChat;

  document.getElementById("tab-chat").classList.toggle("active", isChat);
  document.getElementById("tab-chat").setAttribute("aria-selected", String(isChat));
  document.getElementById("tab-admin").classList.toggle("active", !isChat);
  document.getElementById("tab-admin").setAttribute("aria-selected", String(!isChat));

  subtitleEl.textContent = isChat
    ? appConfig.subtitle || "Ask questions about our products and services."
    : "Manage crawl data and manual ingest to Knowledge Fabric.";

  if (!isChat) onAdminTabShown();
  history.replaceState(null, "", isChat ? "/" : "/?tab=admin");
}

async function loadConfig() {
  const response = await fetch("/api/config/public");
  appConfig = await response.json();
  titleEl.textContent = appConfig.title;
  subtitleEl.textContent = appConfig.subtitle;
  document.title = appConfig.title;
  if (appConfig.chatKeyRequired === "true") {
    chatKey = window.prompt("Enter chat API key") || "";
  }
  initAdmin(appConfig);
}

async function startSession() {
  messagesEl.innerHTML = "";
  setBusy(true);
  try {
    const response = await fetch("/api/chat/session", {
      method: "POST",
      headers: headers(),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Could not start session");
    sessionId = payload.sessionId;
    const greeting =
      payload.greeting || "Hi! How can I help you today?";
    appendMessage("assistant", greeting);
  } catch (error) {
    appendMessage("assistant", `Unable to connect: ${error.message}`);
  } finally {
    setBusy(false);
    inputEl.focus();
  }
}

async function sendMessage(event) {
  event.preventDefault();
  const message = inputEl.value.trim();
  if (!message || busy || !sessionId) return;

  appendMessage("user", message);
  inputEl.value = "";
  setBusy(true);

  try {
    const response = await fetch("/api/chat/message", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ sessionId, message }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Message failed");
    appendMessage("assistant", payload.text);
  } catch (error) {
    appendMessage("assistant", `Something went wrong: ${error.message}`);
  } finally {
    setBusy(false);
    inputEl.focus();
  }
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});

composerEl.addEventListener("submit", sendMessage);
newChatEl.addEventListener("click", startSession);
inputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composerEl.requestSubmit();
  }
});

loadConfig().then(() => {
  const params = new URLSearchParams(window.location.search);
  if (params.get("tab") === "admin" || window.location.hash === "#admin") {
    switchTab("admin");
  } else {
    startSession();
  }
});
