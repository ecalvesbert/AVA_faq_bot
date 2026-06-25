const STORAGE_KEY = "pipelineApiKey";

let pipelineKey = localStorage.getItem(STORAGE_KEY) || "";
let pipelineKeyRequired = true;
let pollTimer = null;
let pollingJobId = null;
let selectedSite = null;
let selectedFile = null;
let sitesCache = [];
let editMode = false;
let currentFileContent = "";

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

function formatElapsed(startedAt) {
  if (!startedAt) return "";
  const ms = Date.now() - new Date(startedAt).getTime();
  if (ms < 0) return "";
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  return `${min}m ${sec % 60}s`;
}

function stepStatusLine(step) {
  let line = `• ${step.name}: ${step.status}`;
  if (step.status === "running" && step.startedAt) {
    line += ` (${formatElapsed(step.startedAt)} elapsed)`;
  }
  if (step.exitCode != null) line += ` (exit ${step.exitCode})`;
  return line;
}

function stepLogSections(steps) {
  return (steps || [])
    .filter((step) => step.stdout || step.stderr)
    .map((step) => {
      const parts = [`--- ${step.name} log ---`];
      if (step.stdout) parts.push(String(step.stdout).trimEnd());
      if (step.stderr) parts.push(String(step.stderr).trimEnd());
      return parts.join("\n");
    });
}

function runningStepHint(steps) {
  const running = (steps || []).find((step) => step.status === "running");
  if (!running) return "";
  if (running.name === "sync") {
    return "\nSync uploads each processed page to Genesys Knowledge Fabric. Large sites can take several minutes — live upload progress appears below as files are sent.\n";
  }
  if (running.name === "crawl") {
    return "\nCrawl is fetching pages from the site. Progress appears below when the crawler emits output.\n";
  }
  return `\n${running.name} is running. Live output appears below when available.\n`;
}

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function statusBadge(status) {
  const safe = String(status || "unknown").toLowerCase();
  return `<span class="badge badge-${escapeHtml(safe)}">${escapeHtml(safe)}</span>`;
}

function showAdminUnlocked(unlocked) {
  document.getElementById("admin-auth").classList.toggle("hidden", unlocked);
  document.getElementById("admin-content").classList.toggle("hidden", !unlocked);
}

function setAuthError(message) {
  const el = document.getElementById("admin-auth-error");
  if (!message) {
    el.textContent = "";
    el.classList.add("hidden");
    return;
  }
  el.textContent = message;
  el.classList.remove("hidden");
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

function persistKey(key) {
  pipelineKey = key.trim();
  if (pipelineKey) {
    localStorage.setItem(STORAGE_KEY, pipelineKey);
  }
  return Boolean(pipelineKey);
}

function clearKey(message) {
  pipelineKey = "";
  localStorage.removeItem(STORAGE_KEY);
  showAdminUnlocked(false);
  const note = document.querySelector("#admin-auth .admin-note");
  if (note && !message) {
    note.textContent =
      "Enter your pipeline API key to manage ingest and content. Find it in Railway → ava-faq-chat → Variables → PIPELINE_API_KEY.";
  }
  setAuthError(message || "");
}

async function fetchWithKey(url, key, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Pipeline-Key": key.trim(),
      ...(options.headers || {}),
    },
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  return { response, payload };
}

async function validatePipelineKey(key) {
  const trimmed = key.trim();
  if (!trimmed) {
    return { ok: false, message: "Enter a pipeline API key." };
  }

  const { response, payload } = await fetchWithKey("/api/pipeline/jobs", trimmed);
  if (response.status === 401) {
    return {
      ok: false,
      message:
        "Invalid pipeline API key. Copy the current value from Railway → ava-faq-chat → Variables → PIPELINE_API_KEY.",
    };
  }
  if (response.status === 503) {
    return {
      ok: false,
      message:
        apiErrorMessage(
          payload,
          "PIPELINE_API_KEY is not configured on the server. Set it in Railway Variables and redeploy.",
        ),
    };
  }
  if (!response.ok) {
    return {
      ok: false,
      message: apiErrorMessage(payload, `Could not verify key (HTTP ${response.status}).`),
    };
  }
  return { ok: true };
}

async function unlockWithKey(key) {
  const submit = document.getElementById("admin-key-submit");
  submit.disabled = true;
  setAuthError("");

  const result = await validatePipelineKey(key);
  submit.disabled = false;

  if (!result.ok) {
    setAuthError(result.message);
    showAdminUnlocked(false);
    return false;
  }

  persistKey(key);
  setAuthError("");
  showAdminUnlocked(true);
  return true;
}

async function tryRestoreStoredKey() {
  if (!pipelineKeyRequired || !pipelineKey) {
    showAdminUnlocked(!pipelineKeyRequired);
    return Boolean(!pipelineKeyRequired);
  }

  showAdminUnlocked(false);
  const result = await validatePipelineKey(pipelineKey);
  if (!result.ok) {
    clearKey(result.message);
    return false;
  }

  showAdminUnlocked(true);
  return true;
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
    <button type="button" class="job-row" data-job-id="${escapeHtml(job.id)}">
      <span class="job-row-main">
        ${statusBadge(job.status)}
        <strong>${escapeHtml(job.site || job.url || job.id.slice(0, 8))}</strong>
        <span class="muted">${escapeHtml(job.syncType || "")}</span>
      </span>
      <span class="muted">${escapeHtml(formatTime(job.createdAt))}</span>
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

  const steps = (job.steps || []).map(stepStatusLine).join("\n");
  const logs = stepLogSections(job.steps).join("\n\n");

  log.textContent = [
    `Status: ${job.status}`,
    `URL: ${job.url}`,
    `Site: ${job.site}`,
    `Created: ${formatTime(job.createdAt)}`,
    job.error ? `Error: ${job.error}` : "",
    steps ? `\nSteps:\n${steps}` : "",
    runningStepHint(job.steps),
    logs ? `\nOutput:\n${logs}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

async function loadJobDetail(jobId) {
  const { response, payload } = await adminFetch(`/api/pipeline/jobs/${jobId}`);
  if (!response.ok) return;
  renderJobDetail(payload);
  if (payload.status === "running" && pollingJobId !== jobId) {
    pollJob(jobId);
  }
}

async function loadJobs() {
  const { response, payload } = await adminFetch("/api/pipeline/jobs");
  if (response.ok) renderJobs(payload);
}

async function loadSyncState() {
  const el = document.getElementById("sync-state");
  const remoteEl = document.getElementById("knowledge-remote");
  const filesWrap = document.getElementById("knowledge-files");
  const filesList = document.getElementById("knowledge-file-list");
  const deleteBtn = document.getElementById("knowledge-delete-source");

  try {
    const { response, payload } = await adminFetch("/api/knowledge/overview");
    if (!response.ok) {
      el.className = "sync-state empty-hint";
      el.textContent = apiErrorMessage(payload, "Could not load knowledge overview.");
      remoteEl.classList.add("hidden");
      filesWrap.classList.add("hidden");
      deleteBtn.disabled = true;
      return;
    }

    const state = payload.localState || {};
    if (!state.sourceId) {
      el.className = "sync-state empty-hint";
      el.textContent = "No Genesys source linked yet. Run a sync step to create one.";
      remoteEl.classList.add("hidden");
      filesWrap.classList.add("hidden");
      deleteBtn.disabled = true;
      return;
    }

    const last = state.lastSync || {};
    el.className = "sync-state";
    el.innerHTML = `
    <dl class="meta-grid">
      <dt>Source</dt><dd>${escapeHtml(state.sourceName || "—")} <code>${escapeHtml(state.sourceId)}</code></dd>
      <dt>Environment</dt><dd>${escapeHtml(state.environment || "—")}</dd>
      <dt>Last sync</dt><dd>${escapeHtml(formatTime(last.completedAt))} (${escapeHtml(last.syncType || "—")})</dd>
      <dt>Files uploaded</dt><dd>${escapeHtml(last.fileCount ?? "—")}</dd>
      <dt>Status</dt><dd>${escapeHtml(last.finalStatus || "—")} / ${escapeHtml(last.ingestionStatus || "—")}</dd>
    </dl>`;

    deleteBtn.disabled = false;
    deleteBtn.dataset.sourceId = state.sourceId;

    if (payload.remoteError) {
      remoteEl.className = "knowledge-remote admin-note";
      remoteEl.textContent = `Could not refresh source from Genesys: ${payload.remoteError}`;
      remoteEl.classList.remove("hidden");
    } else if (payload.remoteSource) {
      const remote = payload.remoteSource;
      remoteEl.className = "knowledge-remote";
      remoteEl.innerHTML = `
      <dl class="meta-grid">
        <dt>Remote name</dt><dd>${escapeHtml(remote.name || "—")}</dd>
        <dt>Remote type</dt><dd>${escapeHtml(remote.type || "—")}</dd>
        <dt>Remote status</dt><dd>${escapeHtml(remote.status || remote.state || "—")}</dd>
      </dl>`;
      remoteEl.classList.remove("hidden");
    } else {
      remoteEl.classList.add("hidden");
    }

    const syncedFiles = last.files || [];
    if (syncedFiles.length) {
      filesList.innerHTML = syncedFiles
        .map((name) => `<li><code>${escapeHtml(name)}</code></li>`)
        .join("");
      filesWrap.classList.remove("hidden");
    } else {
      filesWrap.classList.add("hidden");
    }
  } catch {
    el.className = "sync-state empty-hint";
    el.textContent = "Could not load knowledge overview.";
    remoteEl.classList.add("hidden");
    filesWrap.classList.add("hidden");
    deleteBtn.disabled = true;
  }
}

function renderSiteMeta() {
  const el = document.getElementById("site-meta");
  const site = sitesCache.find((entry) => entry.site === selectedSite);
  if (!site) {
    el.textContent = "Select a site to manage local crawled content.";
    return;
  }
  const parts = [
    `${site.rawFileCount ?? 0} raw pages`,
    `${site.fileCount ?? 0} processed files`,
  ];
  if (site.processedAt) parts.push(`processed ${formatTime(site.processedAt)}`);
  el.textContent = parts.join(" · ");
}

function setEditMode(enabled) {
  editMode = enabled;
  const editor = document.getElementById("preview-editor");
  const body = document.getElementById("preview-body");
  const saveBtn = document.getElementById("content-save");
  const deleteBtn = document.getElementById("content-delete-file");
  const toggleBtn = document.getElementById("content-edit-toggle");

  editor.classList.toggle("hidden", !enabled);
  body.classList.toggle("hidden", enabled);
  saveBtn.classList.toggle("hidden", !enabled);
  deleteBtn.classList.toggle("hidden", !enabled || !selectedFile);
  toggleBtn.textContent = enabled ? "Cancel edit" : "Edit";

  if (enabled) {
    editor.value = currentFileContent;
  }
}

function renderSites(sites) {
  sitesCache = sites;
  const select = document.getElementById("site-select");
  if (!sites.length) {
    select.innerHTML = '<option value="">No sites crawled yet</option>';
    document.getElementById("file-list").innerHTML = "";
    selectedSite = null;
    renderSiteMeta();
    return;
  }
  select.innerHTML = sites
    .map((s) => `<option value="${escapeHtml(s.site)}">${escapeHtml(s.site)}</option>`)
    .join("");
  if (!selectedSite || !sites.some((s) => s.site === selectedSite)) {
    selectedSite = sites[0].site;
  }
  select.value = selectedSite;
  renderSiteMeta();
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
  renderSiteMeta();
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
      selectedFile = null;
      setEditMode(false);
      document.getElementById("preview-title").textContent = "Select a file";
      document.getElementById("preview-body").textContent = "";
      document.getElementById("content-edit-toggle").disabled = true;
      return;
    }
    if (selectedFile && !files.includes(selectedFile)) {
      selectedFile = null;
      setEditMode(false);
      document.getElementById("preview-title").textContent = "Select a file";
      document.getElementById("preview-body").textContent = "";
    }
    list.innerHTML = files
      .map(
        (name) =>
          `<li><button type="button" class="file-item${name === selectedFile ? " active" : ""}" data-file="${escapeHtml(name)}">${escapeHtml(name)}</button></li>`,
      )
      .join("");

    list.querySelectorAll(".file-item").forEach((btn) => {
      btn.addEventListener("click", () => previewFile(btn.dataset.file));
    });
    document.getElementById("content-edit-toggle").disabled = !selectedFile;
  } catch {
    /* auth handler already cleared the saved key */
  }
}

async function previewFile(filename) {
  selectedFile = filename;
  setEditMode(false);
  document.querySelectorAll(".file-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.file === filename);
  });
  document.getElementById("content-edit-toggle").disabled = false;

  const processed = isProcessedLayer();
  try {
    const { response, payload } = await adminFetch(
      `/api/content/sites/${encodeURIComponent(selectedSite)}/files/${encodeURIComponent(filename)}?processed=${processed}`,
    );
    document.getElementById("preview-title").textContent = filename;
    currentFileContent = response.ok
      ? payload.content
      : apiErrorMessage(payload, `Could not load file (HTTP ${response.status}).`);
    document.getElementById("preview-body").textContent = currentFileContent;
  } catch (error) {
    currentFileContent = "";
    document.getElementById("preview-body").textContent = error.message;
  }
}

async function saveCurrentFile() {
  if (!selectedSite || !selectedFile) return;
  const processed = isProcessedLayer();
  const content = document.getElementById("preview-editor").value;
  try {
    const { response, payload } = await adminFetch(
      `/api/content/sites/${encodeURIComponent(selectedSite)}/files/${encodeURIComponent(selectedFile)}?processed=${processed}`,
      { method: "PUT", body: JSON.stringify({ content }) },
    );
    if (!response.ok) {
      window.alert(apiErrorMessage(payload, "Could not save file."));
      return;
    }
    currentFileContent = payload.content;
    document.getElementById("preview-body").textContent = currentFileContent;
    setEditMode(false);
  } catch (error) {
    window.alert(error.message);
  }
}

async function deleteCurrentFile() {
  if (!selectedSite || !selectedFile) return;
  const processed = isProcessedLayer();
  if (!window.confirm(`Delete ${selectedFile} from ${selectedSite}?`)) return;

  try {
    const { response, payload } = await adminFetch(
      `/api/content/sites/${encodeURIComponent(selectedSite)}/files/${encodeURIComponent(selectedFile)}?processed=${processed}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      window.alert(apiErrorMessage(payload, "Could not delete file."));
      return;
    }
    selectedFile = null;
    setEditMode(false);
    document.getElementById("preview-title").textContent = "Select a file";
    document.getElementById("preview-body").textContent = "";
    await loadSites();
  } catch (error) {
    window.alert(error.message);
  }
}

async function createContentFile() {
  if (!selectedSite) {
    window.alert("Select a site first.");
    return;
  }
  const filename = window.prompt("New filename (e.g. page.md):");
  if (!filename) return;
  const processed = isProcessedLayer();
  try {
    const { response, payload } = await adminFetch(
      `/api/content/sites/${encodeURIComponent(selectedSite)}/files`,
      {
        method: "POST",
        body: JSON.stringify({
          filename,
          content: "---\ntitle: New page\nsource_url: \n---\n\n",
          processed,
        }),
      },
    );
    if (!response.ok) {
      window.alert(apiErrorMessage(payload, "Could not create file."));
      return;
    }
    await loadSites();
    await previewFile(filename);
    setEditMode(true);
  } catch (error) {
    window.alert(error.message);
  }
}

async function deleteCurrentSite() {
  if (!selectedSite) return;
  if (
    !window.confirm(
      `Delete all content for ${selectedSite}? This removes raw and processed files from the content store.`,
    )
  ) {
    return;
  }
  try {
    const { response, payload } = await adminFetch(
      `/api/content/sites/${encodeURIComponent(selectedSite)}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      window.alert(apiErrorMessage(payload, "Could not delete site."));
      return;
    }
    selectedSite = null;
    selectedFile = null;
    await loadSites();
  } catch (error) {
    window.alert(error.message);
  }
}

function selectedPipelineSteps() {
  return [...document.querySelectorAll('input[name="pipeline-step"]:checked')].map(
    (input) => input.value,
  );
}

async function startPipelineJob(body) {
  document.getElementById("job-log").textContent = "Starting pipeline...";
  document.getElementById("job-detail").classList.remove("hidden");

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
}

async function reprocessSelectedSite() {
  if (!selectedSite) {
    window.alert("Select a site first.");
    return;
  }
  if (!ensureKey()) return;
  await startPipelineJob({ site: selectedSite, steps: ["process"] });
}

async function pushSelectedSiteToGenesys() {
  if (!selectedSite) {
    window.alert("Select a site in the content store first.");
    return;
  }
  if (!ensureKey()) return;
  const syncType = document.getElementById("sync-type").value;
  const sourceId = document.getElementById("source-id").value.trim();
  const body = { site: selectedSite, steps: ["sync"], syncType };
  if (sourceId) body.sourceId = sourceId;
  await startPipelineJob(body);
}

async function deleteGenesysSource() {
  const btn = document.getElementById("knowledge-delete-source");
  const sourceId = btn.dataset.sourceId;
  if (!sourceId) return;
  if (
    !window.confirm(
      `Delete Genesys knowledge source ${sourceId}? This removes uploaded files from Knowledge Fabric.`,
    )
  ) {
    return;
  }
  try {
    const { response, payload } = await adminFetch(
      `/api/knowledge/sources/${encodeURIComponent(sourceId)}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      window.alert(apiErrorMessage(payload, "Could not delete Genesys source."));
      return;
    }
    await loadSyncState();
  } catch (error) {
    window.alert(error.message);
  }
}

async function pollJob(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollingJobId = jobId;

  async function refreshJob() {
    const { response, payload } = await adminFetch(`/api/pipeline/jobs/${jobId}`);
    if (response.ok) {
      renderJobDetail(payload);
      await loadJobs();
    }
    if (payload?.status === "completed" || payload?.status === "failed") {
      clearInterval(pollTimer);
      pollTimer = null;
      pollingJobId = null;
      await loadSites();
      await loadSyncState();
    }
  }

  try {
    await refreshJob();
  } catch {
    pollingJobId = null;
    return;
  }

  pollTimer = setInterval(async () => {
    try {
      await refreshJob();
    } catch {
      clearInterval(pollTimer);
      pollTimer = null;
      pollingJobId = null;
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

  showAdminUnlocked(false);
  if (!pipelineKeyRequired) {
    showAdminUnlocked(true);
  } else if (pipelineKey) {
    tryRestoreStoredKey().then((ok) => {
      if (ok) refreshAll();
    });
  }

  keyForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("admin-key-input");
    const unlocked = await unlockWithKey(input.value);
    if (unlocked) refreshAll();
  });

  document.getElementById("clear-admin-key").addEventListener("click", () => {
    clearKey("");
    document.getElementById("admin-key-input").value = "";
    document.getElementById("admin-key-input").focus();
  });

  pipelineForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!ensureKey()) return;

    const steps = selectedPipelineSteps();
    if (!steps.length) {
      window.alert("Select at least one pipeline step.");
      return;
    }

    const body = {
      syncType: document.getElementById("sync-type").value,
      crawlLimit: Number(document.getElementById("crawl-limit").value),
      steps,
    };
    const sourceId = document.getElementById("source-id").value.trim();
    if (sourceId) body.sourceId = sourceId;

    if (steps.includes("crawl")) {
      body.url = document.getElementById("url").value;
    } else {
      const url = document.getElementById("url").value;
      body.site = selectedSite || new URL(url).hostname.replace(":", "-");
    }

    try {
      await startPipelineJob(body);
    } catch (error) {
      document.getElementById("job-log").textContent = error.message;
    }
  });

  document.getElementById("refresh-admin").addEventListener("click", refreshAll);
  document.getElementById("refresh-knowledge").addEventListener("click", loadSyncState);
  document.getElementById("content-new-file").addEventListener("click", createContentFile);
  document.getElementById("content-reprocess").addEventListener("click", reprocessSelectedSite);
  document.getElementById("content-delete-site").addEventListener("click", deleteCurrentSite);
  document.getElementById("content-edit-toggle").addEventListener("click", () => {
    if (!selectedFile) return;
    setEditMode(!editMode);
  });
  document.getElementById("content-save").addEventListener("click", saveCurrentFile);
  document.getElementById("content-delete-file").addEventListener("click", deleteCurrentFile);
  document.getElementById("knowledge-resync-site").addEventListener("click", pushSelectedSiteToGenesys);
  document.getElementById("knowledge-delete-source").addEventListener("click", deleteGenesysSource);
  document.getElementById("site-select").addEventListener("change", () => {
    selectedFile = null;
    setEditMode(false);
    loadFilesForSite();
  });
  document.querySelectorAll('input[name="layer"]').forEach((input) => {
    input.addEventListener("change", () => {
      selectedFile = null;
      setEditMode(false);
      loadFilesForSite();
      document.getElementById("preview-title").textContent = "Select a file";
      document.getElementById("preview-body").textContent = "";
      document.getElementById("content-edit-toggle").disabled = true;
    });
  });
}

export function onAdminTabShown() {
  if (!pipelineKeyRequired) {
    refreshAll();
    return;
  }
  if (pipelineKey) {
    tryRestoreStoredKey().then((ok) => {
      if (ok) refreshAll();
    });
    return;
  }
  showAdminUnlocked(false);
}
