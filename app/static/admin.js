const STORAGE_KEY = "pipelineApiKey";

let pipelineKey = localStorage.getItem(STORAGE_KEY) || "";
let pipelineKeyRequired = true;
let pollTimer = null;
let selectedSite = null;
let selectedFile = null;

function headers() {
  return {
    "Content-Type": "application/json",
    "X-Pipeline-Key": pipelineKey,
  };
}

function isProcessedLayer() {
  return document.querySelector('input[name="layer"]:checked')?.value !== "raw";
}

function formatTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function statusBadge(status) {
  const safe = String(status || "unknown").toLowerCase();
  return `<span class="badge badge-${safe}">${safe}</span>`;
}

function showAdminUnlocked(unlocked) {
  document.getElementById("admin-auth").classList.toggle("hidden", unlocked);
  document.getElementById("admin-content").classList.toggle("hidden", !unlocked);
}

function ensureKey() {
  if (!pipelineKeyRequired) {
    showAdminUnlocked(true);
    return true;
  }
  if (pipelineKey) {
    showAdminUnlocked(true);
    return true;
  }
  showAdminUnlocked(false);
  return false;
}

function saveKey(key) {
  pipelineKey = key.trim();
  if (pipelineKey) {
    localStorage.setItem(STORAGE_KEY, pipelineKey);
    showAdminUnlocked(true);
  }
  return Boolean(pipelineKey);
}

function renderJobs(jobs) {
  const el = document.getElementById("jobs-list");
  if (!jobs.length) {
    el.className = "jobs-list empty-hint";
    el.innerHTML = "No jobs yet.";
    return;
  }
  el.className = "jobs-list";
  el.innerHTML = jobs
    .map(
      (job) => `
    <button type="button" class="job-row" data-job-id="${job.id}">
      <span class="job-row-main">
        ${statusBadge(job.status)}
        <strong>${job.site || job.url || job.id.slice(0, 8)}</strong>
        <span class="muted">${job.syncType || ""}</span>
      </span>
      <span class="muted">${formatTime(job.createdAt)}</span>
    </button>`,
    )
    .join("");

  el.querySelectorAll(".job-row").forEach((btn) => {
    btn.addEventListener("click", () => loadJobDetail(btn.dataset.jobId));
  });
}

function renderJobDetail(job) {
  const detail = document.getElementById("job-detail");
  const log = document.getElementById("job-log");
  detail.classList.remove("hidden");
  detail.open = true;

  const steps = (job.steps || [])
    .map(
      (s) =>
        `• ${s.name}: ${s.status}${s.exitCode != null ? ` (exit ${s.exitCode})` : ""}`,
    )
    .join("\n");

  log.textContent = [
    `Status: ${job.status}`,
    `URL: ${job.url}`,
    `Site: ${job.site}`,
    `Created: ${formatTime(job.createdAt)}`,
    job.error ? `Error: ${job.error}` : "",
    steps ? `\nSteps:\n${steps}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

async function loadJobDetail(jobId) {
  const response = await fetch(`/api/pipeline/jobs/${jobId}`, { headers: headers() });
  const job = await response.json();
  if (response.ok) renderJobDetail(job);
}

async function loadJobs() {
  const response = await fetch("/api/pipeline/jobs", { headers: headers() });
  const jobs = await response.json();
  if (response.ok) renderJobs(jobs);
}

async function loadSyncState() {
  const el = document.getElementById("sync-state");
  const response = await fetch("/api/pipeline/sync-state", { headers: headers() });
  const state = await response.json();
  if (!response.ok) {
    el.className = "sync-state empty-hint";
    el.textContent = "Could not load sync state.";
    return;
  }
  if (!state.sourceId) {
    el.className = "sync-state empty-hint";
    el.textContent = "No sync state recorded.";
    return;
  }
  el.className = "sync-state";
  const last = state.lastSync || {};
  el.innerHTML = `
    <dl class="meta-grid">
      <dt>Source</dt><dd>${state.sourceName || "—"} <code>${state.sourceId}</code></dd>
      <dt>Last sync</dt><dd>${formatTime(last.completedAt)}</dd>
      <dt>Files uploaded</dt><dd>${last.fileCount ?? "—"}</dd>
      <dt>Status</dt><dd>${last.finalStatus || "—"} / ${last.ingestionStatus || "—"}</dd>
    </dl>`;
}

function renderSites(sites) {
  const select = document.getElementById("site-select");
  if (!sites.length) {
    select.innerHTML = '<option value="">No sites crawled yet</option>';
    document.getElementById("file-list").innerHTML = "";
    return;
  }
  select.innerHTML = sites
    .map((s) => `<option value="${s.site}">${s.site}</option>`)
    .join("");
  selectedSite = sites[0].site;
  select.value = selectedSite;
  loadFilesForSite();
}

async function loadSites() {
  const response = await fetch("/api/content/sites", { headers: headers() });
  const sites = await response.json();
  if (response.ok) renderSites(sites);
}

async function loadFilesForSite() {
  const select = document.getElementById("site-select");
  selectedSite = select.value;
  if (!selectedSite) return;

  const processed = isProcessedLayer();
  const response = await fetch(
    `/api/content/sites/${encodeURIComponent(selectedSite)}/files?processed=${processed}`,
    { headers: headers() },
  );
  const payload = await response.json();
  const list = document.getElementById("file-list");
  const files = payload.files || [];
  if (!files.length) {
    list.innerHTML = '<li class="empty-hint">No files in this layer.</li>';
    return;
  }
  list.innerHTML = files
    .map(
      (name) =>
        `<li><button type="button" class="file-item${name === selectedFile ? " active" : ""}" data-file="${name}">${name}</button></li>`,
    )
    .join("");

  list.querySelectorAll(".file-item").forEach((btn) => {
    btn.addEventListener("click", () => previewFile(btn.dataset.file));
  });
}

async function previewFile(filename) {
  selectedFile = filename;
  document.querySelectorAll(".file-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.file === filename);
  });

  const processed = isProcessedLayer();
  const response = await fetch(
    `/api/content/sites/${encodeURIComponent(selectedSite)}/files/${encodeURIComponent(filename)}?processed=${processed}`,
    { headers: headers() },
  );
  const payload = await response.json();
  document.getElementById("preview-title").textContent = filename;
  document.getElementById("preview-body").textContent = response.ok
    ? payload.content
    : payload.detail || "Could not load file.";
}

async function pollJob(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const response = await fetch(`/api/pipeline/jobs/${jobId}`, { headers: headers() });
    const job = await response.json();
    if (response.ok) {
      renderJobDetail(job);
      await loadJobs();
    }
    if (job.status === "completed" || job.status === "failed") {
      clearInterval(pollTimer);
      await loadSites();
      await loadSyncState();
    }
  }, 2500);
}

async function refreshAll() {
  if (!ensureKey()) return;
  await Promise.all([loadJobs(), loadSites(), loadSyncState()]);
}

export function initAdmin(config) {
  pipelineKeyRequired = config.pipelineKeyRequired !== "false";
  const keyForm = document.getElementById("admin-key-form");
  const pipelineForm = document.getElementById("pipeline-form");

  if (pipelineKeyRequired && !pipelineKey) {
    showAdminUnlocked(false);
  } else {
    showAdminUnlocked(true);
  }

  keyForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const input = document.getElementById("admin-key-input");
    if (saveKey(input.value)) refreshAll();
  });

  pipelineForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!ensureKey()) return;

    const body = {
      url: document.getElementById("url").value,
      syncType: document.getElementById("sync-type").value,
      crawlLimit: Number(document.getElementById("crawl-limit").value),
    };
    const sourceId = document.getElementById("source-id").value.trim();
    if (sourceId) body.sourceId = sourceId;

    document.getElementById("job-log").textContent = "Starting pipeline...";
    document.getElementById("job-detail").classList.remove("hidden");

    const response = await fetch("/api/pipeline/run", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) {
      document.getElementById("job-log").textContent = JSON.stringify(payload, null, 2);
      return;
    }
    pollJob(payload.jobId);
  });

  document.getElementById("refresh-admin").addEventListener("click", refreshAll);
  document.getElementById("site-select").addEventListener("change", loadFilesForSite);
  document.querySelectorAll('input[name="layer"]').forEach((input) => {
    input.addEventListener("change", () => {
      selectedFile = null;
      loadFilesForSite();
      document.getElementById("preview-title").textContent = "Select a file";
      document.getElementById("preview-body").textContent = "";
    });
  });
}

export function onAdminTabShown() {
  if (ensureKey()) refreshAll();
}
