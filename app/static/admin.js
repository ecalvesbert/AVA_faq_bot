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

function clearKey(message) {
  pipelineKey = "";
  localStorage.removeItem(STORAGE_KEY);
  showAdminUnlocked(false);
  const note = document.querySelector("#admin-auth .admin-note");
  if (note) {
    note.textContent = message
      || "Enter your pipeline API key to manage ingest and content. Find it in Railway → ava-faq-chat → Variables → PIPELINE_API_KEY.";
  }
  document.getElementById("admin-key-input").value = "";
}

function apiErrorMessage(payload, fallback = "Request failed.") {
  if (!payload) return fallback;
  if (typeof payload.detail === "string") return payload.detail;
  if (Array.isArray(payload.detail)) {
    return payload.detail.map((item) => item.msg || String(item)).join("; ");
  }
  return fallback;
}

async function adminFetch(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { ...headers(), ...(options.headers || {}) },
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (response.status === 401) {
    clearKey(
      `${apiErrorMessage(payload, "Invalid pipeline API key")} Update the key from Railway → Variables → PIPELINE_API_KEY.`,
    );
    throw new Error(apiErrorMessage(payload, "Invalid pipeline API key"));
  }
  return { response, payload };
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
  const { response, payload } = await adminFetch(`/api/pipeline/jobs/${jobId}`);
  if (response.ok) renderJobDetail(payload);
}

async function loadJobs() {
  const { response, payload } = await adminFetch("/api/pipeline/jobs");
  if (response.ok) renderJobs(payload);
}

async function loadSyncState() {
  const el = document.getElementById("sync-state");
  try {
    const { response, payload } = await adminFetch("/api/pipeline/sync-state");
    if (!response.ok) {
      el.className = "sync-state empty-hint";
      el.textContent = apiErrorMessage(payload, "Could not load sync state.");
      return;
    }
    if (!payload.sourceId) {
      el.className = "sync-state empty-hint";
      el.textContent = "No sync state recorded.";
      return;
    }
    el.className = "sync-state";
    const last = payload.lastSync || {};
    el.innerHTML = `
    <dl class="meta-grid">
      <dt>Source</dt><dd>${payload.sourceName || "—"} <code>${payload.sourceId}</code></dd>
      <dt>Last sync</dt><dd>${formatTime(last.completedAt)}</dd>
      <dt>Files uploaded</dt><dd>${last.fileCount ?? "—"}</dd>
      <dt>Status</dt><dd>${last.finalStatus || "—"} / ${last.ingestionStatus || "—"}</dd>
    </dl>`;
  } catch {
    el.className = "sync-state empty-hint";
    el.textContent = "Could not load sync state.";
  }
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
  try {
    const { response, payload } = await adminFetch("/api/content/sites");
    if (response.ok) renderSites(payload);
  } catch {
    /* auth handler already cleared the saved key */
  }
}

async function loadFilesForSite() {
  const select = document.getElementById("site-select");
  selectedSite = select.value;
  if (!selectedSite) return;

  const processed = isProcessedLayer();
  try {
    const { response, payload } = await adminFetch(
      `/api/content/sites/${encodeURIComponent(selectedSite)}/files?processed=${processed}`,
    );
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
  } catch {
    /* auth handler already cleared the saved key */
  }
}

async function previewFile(filename) {
  selectedFile = filename;
  document.querySelectorAll(".file-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.file === filename);
  });

  const processed = isProcessedLayer();
  try {
    const { response, payload } = await adminFetch(
      `/api/content/sites/${encodeURIComponent(selectedSite)}/files/${encodeURIComponent(filename)}?processed=${processed}`,
    );
    document.getElementById("preview-title").textContent = filename;
    document.getElementById("preview-body").textContent = response.ok
      ? payload.content
      : apiErrorMessage(payload, `Could not load file (HTTP ${response.status}).`);
  } catch (error) {
    document.getElementById("preview-body").textContent = error.message;
  }
}

async function pollJob(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const { response, payload } = await adminFetch(`/api/pipeline/jobs/${jobId}`);
      if (response.ok) {
        renderJobDetail(payload);
        await loadJobs();
      }
      if (payload.status === "completed" || payload.status === "failed") {
        clearInterval(pollTimer);
        await loadSites();
        await loadSyncState();
      }
    } catch {
      clearInterval(pollTimer);
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

  keyForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("admin-key-input");
    if (!saveKey(input.value)) return;
    try {
      await loadJobs();
    } catch (error) {
      document.getElementById("job-log").textContent = error.message;
      document.getElementById("job-detail").classList.remove("hidden");
      return;
    }
    refreshAll();
  });

  document.getElementById("clear-admin-key").addEventListener("click", () => {
    clearKey();
    document.getElementById("admin-key-input").focus();
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

    try {
      const { response, payload } = await adminFetch("/api/pipeline/run", {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        document.getElementById("job-log").textContent = apiErrorMessage(
          payload,
          "Could not start ingest.",
        );
        return;
      }
      pollJob(payload.jobId);
    } catch (error) {
      document.getElementById("job-log").textContent = error.message;
    }
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
