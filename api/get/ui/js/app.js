/* ============================================================================
   Minecraft Server Manager — Frontend Application
   ============================================================================ */

// --- State ---
let servers = [];
let deleteTargetName = null;
let currentUser = null;
let activeLogServer = null;
let activeConsoleServer = null;
let activeExplorerServer = null;
let currentExplorerPath = "";
let explorerChanges = {};
let editorOriginalPath = null;
let activeSettingsServer = null;
let activeLogsServer = null;
let activeLogsFilename = null;

// --- Socket.IO Real-Time Client ---
const socket = io();

socket.on('servers_updated', async () => {
    console.log('Real-time server update received');
    if (currentUser) {
        await loadServers();
    }
});

socket.on('console_init', (data) => {
    if (activeConsoleServer && data.name === activeConsoleServer) {
        const contentArea = document.getElementById('console-logs-content');
        const container = document.querySelector('.console-logs-container');

        // The backend pushes the full console snapshot on every change, so
        // we always replace the textContent — never append. Preserve scroll
        // position: if the user is at the bottom, stick there; otherwise
        // keep their distance from the bottom unchanged so they can read
        // history without being yanked back down by each update.
        let wasAtBottom = true;
        let distanceFromBottom = 0;
        if (container) {
            wasAtBottom = container.scrollHeight - container.clientHeight <= container.scrollTop + 60;
            distanceFromBottom = container.scrollHeight - container.scrollTop;
        }

        contentArea.textContent = data.logs;

        if (container) {
            if (wasAtBottom) {
                container.scrollTop = container.scrollHeight;
            } else {
                container.scrollTop = Math.max(0, container.scrollHeight - distanceFromBottom);
            }
        }
    }
});

socket.on('proxy_routes_updated', async () => {
    console.log('Real-time proxy status update received');
    if (currentUser && currentUser.username === 'admin') {
        await loadProxyStatus();
        await loadProxyRoutesSettings();
    }
});

socket.on('logs_init', (data) => {
    if (activeLogServer && data.name === activeLogServer) {
        const contentArea = document.getElementById('creation-logs-content');
        contentArea.textContent = data.logs;
        contentArea.scrollTop = contentArea.scrollHeight;
    }
});

socket.on('logs_append', (data) => {
    if (activeLogServer && data.name === activeLogServer) {
        const contentArea = document.getElementById('creation-logs-content');
        
        // Clear placeholder text if it's currently showing
        if (contentArea.textContent === 'Loading logs...' || 
            contentArea.textContent === 'No creation logs found yet. Please wait...') {
            contentArea.textContent = '';
        }
        
        const isScrolledToBottom = contentArea.scrollHeight - contentArea.clientHeight <= contentArea.scrollTop + 30;
        
        contentArea.textContent += data.line;
        
        if (isScrolledToBottom || contentArea.textContent === data.line) {
            contentArea.scrollTop = contentArea.scrollHeight;
        }
    }
});

// --- API Helpers ---
async function apiFetch(endpoint, method = 'GET', data = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (data) {
        opts.body = JSON.stringify(data);
    }
    const resp = await fetch(endpoint, opts);
    const json = await resp.json();
    if (resp.status === 401 && endpoint !== '/api/auth/login' && endpoint !== '/api/auth/me') {
        window.location.href = '/login.html';
        throw new Error('Please log in.');
    }
    if (!resp.ok) {
        throw new Error(json.error || `HTTP ${resp.status}`);
    }
    return json;
}

// --- Auth ---
async function checkAuth() {
    try {
        currentUser = await apiFetch('/api/auth/me');
        document.getElementById('current-user-badge').textContent = currentUser.username;
        if (currentUser.username === 'admin') {
            document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'inline-flex');
        } else {
            document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'none');
        }
        await loadServers();
        if (currentUser.username === 'admin') {
            await loadProxyStatus();
        }
    } catch (err) {
        window.location.href = '/login.html';
    }
}

async function handleLogout() {
    try {
        await apiFetch('/api/auth/logout', 'POST');
    } catch(e) {}
    window.location.href = '/login.html';
}

// --- Toast Notifications ---
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    // Remove after animation
    setTimeout(() => {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 4000);
}

// --- Data Loading ---
async function loadServers() {
    try {
        const data = await apiFetch('/api/servers');
        servers = data.servers || [];
        renderServers();
        updateStats();
    } catch (err) {
        console.error('Failed to load servers:', err);
    }
}

async function loadProxyStatus() {
    try {
        const data = await apiFetch('/api/proxy/status');
        
        // Header badge
        const badge = document.getElementById('proxy-status');
        if (badge) {
            const text = badge.querySelector('.status-text');
            badge.classList.remove('is-running', 'is-stopped');
            if (data.running) {
                badge.classList.add('is-running');
                if (text) text.textContent = 'Proxy Running';
            } else {
                badge.classList.add('is-stopped');
                if (text) text.textContent = 'Proxy Stopped';
            }
        }
        
        // Settings badge
        const settingsBadge = document.getElementById('proxy-status-settings');
        if (settingsBadge) {
            const settingsText = settingsBadge.querySelector('.status-text');
            settingsBadge.classList.remove('is-running', 'is-stopped');
            if (data.running) {
                settingsBadge.classList.add('is-running');
                if (settingsText) settingsText.textContent = 'Proxy Running';
            } else {
                settingsBadge.classList.add('is-stopped');
                if (settingsText) settingsText.textContent = 'Proxy Stopped';
            }
        }
        
        // Settings toggle button
        const settingsBtn = document.getElementById('btn-proxy-toggle-settings');
        if (settingsBtn) {
            if (data.running) {
                settingsBtn.className = 'btn btn-sm btn-warning';
                settingsBtn.innerHTML = `
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px;"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
                    Stop Proxy
                `;
            } else {
                settingsBtn.className = 'btn btn-sm btn-success';
                settingsBtn.innerHTML = `
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px;"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                    Start Proxy
                `;
            }
        }
        
        // Backward-compatible header toggle button
        const btn = document.getElementById('btn-proxy-toggle');
        if (btn) {
            if (data.running) {
                btn.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
                    Stop
                `;
            } else {
                btn.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                    Start
                `;
            }
        }
    } catch (err) {
        console.error('Failed to load proxy status:', err);
    }
}

// --- Rendering ---
function renderServers() {
    const grid = document.getElementById('servers-list');
    const empty = document.getElementById('servers-empty');

    if (servers.length === 0) {
        grid.style.display = 'none';
        empty.style.display = 'flex';
        return;
    }

    grid.style.display = 'grid';
    empty.style.display = 'none';

    grid.innerHTML = servers.map((srv, i) => {
        const rawStatus = (srv.status || 'unknown').toLowerCase();
        let status = rawStatus;
        if (status === 'not running') status = 'stopped';
        
        const badgeClass = `badge-${status}`;
        const statusLabel = status.replace('_', ' ');
        const hostname = srv.hostname || '—';
        const port = srv.port || '—';
        const version = srv.version || '—';
        const type = srv.type || '—';
        const memory = srv.memory_mb || 1024;
        const containerName = srv.container_name || `mc-${srv.name}`;
        const isRunning = status === 'running';

        const perms = srv.permissions || {};
        const isOwner = !!srv.is_owner;
        const canWriteFiles = !!perms.can_write_files;

        const editHostnameBtn = canWriteFiles
            ? `<button class="btn btn-icon" style="opacity: 0.6;" onclick="event.stopPropagation(); showHostnameModal('${escapeAttr(srv.name)}', '${escapeAttr(hostname)}')">
                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
               </button>`
            : '';

        const editMemoryBtn = canWriteFiles
            ? `<button class="btn btn-icon" style="opacity: 0.6;" onclick="event.stopPropagation(); showMemoryModal('${escapeAttr(srv.name)}', ${memory})">
                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
               </button>`
            : '';

        let actionsHtml = '';
        if (status === 'downloading_mods') {
            if (perms.can_read_files) {
                actionsHtml += `<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation(); showCreationLogs('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                                   Logs
                               </button>`;
            }
            if (perms.can_write_files) {
                actionsHtml += `<button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); cancelModDownload('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                                   Cancel
                               </button>`;
            }
        } else if (status === 'creating') {
            if (perms.can_read_files) {
                actionsHtml += `<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation(); showCreationLogs('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                                   Logs
                               </button>`;
            }
            if (perms.can_write_files) {
                actionsHtml += `<button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); cancelServerCreation('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                                   Cancel
                               </button>`;
            }
        } else if (status === 'install_required') {
            if (perms.can_write_files) {
                actionsHtml += `<button class="btn btn-sm btn-success" style="background: var(--green); color: white;" onclick="event.stopPropagation(); installServer('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                                   Install
                               </button>`;
            }
            if (isOwner) {
                actionsHtml += `<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation(); showDeleteModal('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                                   Delete
                               </button>`;
            }
        } else if (!srv.eula_agreed) {
            if (perms.can_start) {
                actionsHtml += `<button class="btn btn-sm" style="background: var(--yellow); color: var(--text-inverse); font-weight: 600;" onclick="event.stopPropagation(); agreeToEula('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                                   Agree to EULA
                               </button>`;
            }
            if (isOwner) {
                actionsHtml += `<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation(); showDeleteModal('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                                   Delete
                               </button>`;
            }
        } else if (isRunning) {
            if (perms.can_read_console) {
                actionsHtml += `<button class="btn btn-sm btn-primary" style="background: var(--accent); color: white;" onclick="event.stopPropagation(); showConsoleModal('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                                   Console
                               </button>`;
            }
            if (perms.can_stop) {
                actionsHtml += `<button class="btn btn-sm btn-warning" onclick="event.stopPropagation(); stopServer('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
                                   Stop
                               </button>`;
            }
            if (perms.can_read_files) {
                actionsHtml += `<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation(); showFileExplorerModal('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                                   Files
                               </button>
                               <button class="btn btn-sm btn-ghost" onclick="event.stopPropagation(); showServerLogsModal('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
                                   Logs
                               </button>`;
            }
        } else {
            if (perms.can_start) {
                actionsHtml += `<button class="btn btn-sm btn-success" onclick="event.stopPropagation(); startServer('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                                   Start
                               </button>`;
            }
            if (isOwner) {
                actionsHtml += `<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation(); showDeleteModal('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                                   Delete
                               </button>`;
            }
            if (perms.can_read_files) {
                actionsHtml += `<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation(); showFileExplorerModal('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                                   Files
                               </button>
                               <button class="btn btn-sm btn-ghost" onclick="event.stopPropagation(); showServerLogsModal('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
                                   Logs
                               </button>`;
            }
        }

        return `
            <div class="server-card" style="animation-delay: ${i * 0.06}s; cursor: pointer;" id="card-${srv.name}" onclick="showServerSettingsModal('${escapeAttr(srv.name)}')">
                <div class="card-header">
                    <div class="card-title-group">
                        <span class="card-title">${escapeHtml(srv.name)}</span>
                        <span class="card-subtitle">${escapeHtml(containerName)}</span>
                    </div>
                    <span class="card-status-badge ${badgeClass}">
                        <span class="badge-dot"></span>
                        ${statusLabel}
                    </span>
                </div>
                <div class="card-details">
                    <div class="detail-item">
                        <span class="detail-label">Type</span>
                        <span class="detail-value">${escapeHtml(type)}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">Version</span>
                        <span class="detail-value">${escapeHtml(version)}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">Port</span>
                        <span class="detail-value">${port}</span>
                    </div>
                    <div class="detail-item" style="grid-column: span 2; display: flex; flex-direction: row; justify-content: space-between; align-items: center;">
                        <div style="display: flex; flex-direction: column;">
                            <span class="detail-label">Hostname</span>
                            <span class="detail-value">${escapeHtml(hostname)}</span>
                        </div>
                        ${editHostnameBtn}
                    </div>
                    <div class="detail-item" style="grid-column: span 2; display: flex; flex-direction: row; justify-content: space-between; align-items: center;">
                        <div style="display: flex; flex-direction: column;">
                            <span class="detail-label">RAM Limit</span>
                            <span class="detail-value">${memory} MB</span>
                        </div>
                        ${editMemoryBtn}
                    </div>
                </div>
                <div class="card-actions">
                    ${actionsHtml}
                </div>
            </div>
        `;
    }).join('');
}

function updateStats() {
    const total = servers.length;
    const running = servers.filter(s => s.status === 'running').length;
    const stopped = total - running;

    animateValue(document.querySelector('#stat-total .stat-value'), total);
    animateValue(document.querySelector('#stat-running .stat-value'), running);
    animateValue(document.querySelector('#stat-stopped .stat-value'), stopped);
}

function animateValue(el, target) {
    const current = parseInt(el.textContent) || 0;
    if (current === target) return;
    el.textContent = target;
    el.style.transform = 'scale(1.15)';
    el.style.transition = 'transform 0.2s ease';
    setTimeout(() => {
        el.style.transform = 'scale(1)';
    }, 200);
}

// --- Server Actions ---
async function startServer(name) {
    try {
        showToast(`Starting ${name}...`, 'info');
        const data = await apiFetch('/api/server/run', 'POST', { name });
        showToast(data.message || `${name} started`, 'success');
        await loadServers();
    } catch (err) {
        showToast(`Failed to start ${name}: ${err.message}`, 'error');
    }
}

async function stopServer(name) {
    try {
        showToast(`Stopping ${name}...`, 'info');
        const data = await apiFetch('/api/server/stop', 'POST', { name });
        showToast(data.message || `${name} stopped`, 'success');
        await loadServers();
    } catch (err) {
        showToast(`Failed to stop ${name}: ${err.message}`, 'error');
    }
}

// --- Create Server ---
function showCreateModal() {
    document.getElementById('modal-overlay').classList.add('is-visible');
    setTimeout(() => document.getElementById('server-name').focus(), 100);
}

function hideCreateModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('modal-overlay').classList.remove('is-visible');
    document.getElementById('create-server-form').reset();
    document.getElementById('forge-version-group').style.display = 'none';
    document.getElementById('version-label').textContent = 'Version';
    document.getElementById('server-version').placeholder = 'e.g. 1.21.1';
}

async function createServer(e) {
    e.preventDefault();
    const name = document.getElementById('server-name').value.trim();
    const type = document.getElementById('server-type').value;
    const versionInput = document.getElementById('server-version').value.trim();
    const memory_mb = parseInt(document.getElementById('server-memory').value) || 1024;

    if (!name || !versionInput) {
        showToast('Please fill in all fields', 'error');
        return;
    }

    let version = versionInput;
    if (type === 'forge' || type === 'neoforge') {
        const forgeSelect = document.getElementById('forge-version-select');
        const forgeVersion = forgeSelect.value;
        if (!forgeVersion) {
            showToast(type === 'forge' ? 'Please select a Forge version' : 'Please select a NeoForge version', 'error');
            return;
        }
        version = `${versionInput}-${forgeVersion}`;
    }

    if (memory_mb < 512) {
        showToast('Memory must be at least 512 MB', 'error');
        return;
    }

    const btn = document.getElementById('btn-submit-create');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Creating...';

    try {
        const data = await apiFetch('/api/server/create', 'POST', { name, type, version, memory_mb });
        showToast(data.message || `Server '${name}' creation started!`, 'success');
        hideCreateModal();
        // Refresh after a short delay so the early DB entry appears
        setTimeout(loadServers, 1000);
    } catch (err) {
        showToast(`Failed to create server: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            Create Server
        `;
    }
}

// --- Delete Server ---
function showDeleteModal(name) {
    deleteTargetName = name;
    document.getElementById('delete-server-name').textContent = name;
    document.getElementById('delete-remove-data').checked = false;
    document.getElementById('delete-modal-overlay').classList.add('is-visible');
}

function hideDeleteModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('delete-modal-overlay').classList.remove('is-visible');
    deleteTargetName = null;
}

async function confirmDelete() {
    if (!deleteTargetName) return;

    const removeData = document.getElementById('delete-remove-data').checked;
    const btn = document.getElementById('btn-confirm-delete');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Deleting...';

    try {
        const data = await apiFetch('/api/server/delete', 'POST', {
            name: deleteTargetName,
            remove_data: removeData
        });
        showToast(data.message || `Server '${deleteTargetName}' deleted`, 'success');
        hideDeleteModal();
        await loadServers();
    } catch (err) {
        showToast(`Failed to delete: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            Delete Server
        `;
    }
}

// --- Edit Hostname ---
function showHostnameModal(name, hostname) {
    document.getElementById('hostname-server-name').value = name;
    document.getElementById('server-hostname').value = hostname === '—' ? '' : hostname;
    document.getElementById('hostname-modal-overlay').classList.add('is-visible');
    setTimeout(() => document.getElementById('server-hostname').focus(), 100);
}

function hideHostnameModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('hostname-modal-overlay').classList.remove('is-visible');
    document.getElementById('edit-hostname-form').reset();
}

async function updateHostname(e) {
    e.preventDefault();
    const name = document.getElementById('hostname-server-name').value;
    const hostname = document.getElementById('server-hostname').value.trim();

    if (!name) return;

    const btn = document.getElementById('btn-submit-hostname');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Saving...';

    try {
        const data = await apiFetch('/api/server/hostname', 'POST', { name, hostname });
        showToast(data.message || `Hostname updated!`, 'success');
        hideHostnameModal();
        await loadServers();
    } catch (err) {
        showToast(`Failed to update hostname: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>
            Save
        `;
    }
}

async function toggleProxy() {
    const badge = document.getElementById('proxy-status-settings') || document.getElementById('proxy-status');
    if (!badge) return;
    const isRunning = badge.classList.contains('is-running');

    try {
        if (isRunning) {
            showToast('Stopping proxy...', 'info');
            await apiFetch('/api/proxy/stop', 'POST');
            showToast('Proxy stopped', 'success');
        } else {
            showToast('Starting proxy...', 'info');
            await apiFetch('/api/proxy/start', 'POST');
            showToast('Proxy started', 'success');
        }
        await loadProxyStatus();
        await loadProxyRoutesSettings();
    } catch (err) {
        showToast(`Proxy error: ${err.message}`, 'error');
    }
}

// --- Utilities ---
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// --- Memory Editing ---
function showMemoryModal(name, memory) {
    document.getElementById('memory-server-name').value = name;
    document.getElementById('server-memory-mb').value = memory;
    document.getElementById('memory-modal-overlay').classList.add('is-visible');
    setTimeout(() => document.getElementById('server-memory-mb').focus(), 100);
}

function hideMemoryModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('memory-modal-overlay').classList.remove('is-visible');
    document.getElementById('edit-memory-form').reset();
}

async function updateMemory(e) {
    e.preventDefault();
    const name = document.getElementById('memory-server-name').value;
    const memory_mb = document.getElementById('server-memory-mb').value;

    if (!name) return;

    const btn = document.getElementById('btn-submit-memory');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Saving...';

    try {
        const data = await apiFetch('/api/server/memory', 'POST', { name, memory_mb: parseInt(memory_mb) });
        showToast(data.message || `Memory updated!`, 'success');
        hideMemoryModal();
        await loadServers();
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `Save limit`;
    }
}

// --- Users Admin ---
async function showUsersModal() {
    document.getElementById('users-modal-overlay').classList.add('is-visible');
    await loadUsersList();
}

function hideUsersModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('users-modal-overlay').classList.remove('is-visible');
}

async function loadUsersList() {
    try {
        const data = await apiFetch('/api/users');
        const container = document.getElementById('users-list-container');
        container.innerHTML = data.users.map(u => `
            <div style="padding: 1rem; border-bottom: 1px solid var(--border-default); display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <strong>${escapeHtml(u.username)}</strong>
                    <div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 4px;">Memory Limit: ${u.memory_limit} MB</div>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-sm btn-ghost" onclick="assignUserMemory('${escapeAttr(u.username)}')">Set RAM</button>
                    ${u.username !== 'admin' ? `
                        <button class="btn btn-sm btn-ghost" onclick="resetUserPass('${escapeAttr(u.username)}')">Pasword</button>
                        <button class="btn btn-sm btn-danger" onclick="removeUser('${escapeAttr(u.username)}')">Del</button>
                    ` : ''}
                </div>
            </div>
        `).join('');
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function addUser() {
    const input = document.getElementById('new-username');
    const username = input.value.trim();
    if (!username) return;
    try {
        await apiFetch('/api/user/add', 'POST', { username });
        showToast(`User ${username} added. Password is 'password'.`, 'success');
        input.value = '';
        await loadUsersList();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function removeUser(username) {
    if (!confirm(`Are you sure you want to delete user ${username}?`)) return;
    try {
        await apiFetch('/api/user/remove', 'POST', { username });
        showToast(`User ${username} deleted.`, 'success');
        await loadUsersList();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function assignUserMemory(username) {
    const limit = prompt(`Enter memory limit (MB) for ${username}:`, "8192");
    if (!limit) return;
    try {
        await apiFetch('/api/user/assign', 'POST', { username, limit_mb: parseInt(limit) });
        showToast(`Memory limit updated for ${username}.`, 'success');
        await loadUsersList();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function resetUserPass(username) {
    const pwd = prompt(`Enter new password for ${username}:`);
    if (!pwd) return;
    try {
        await apiFetch('/api/user/reset', 'POST', { username, new_password: pwd });
        showToast(`Password updated for ${username}.`, 'success');
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// --- Creation Logs & Cancel Creation ---
function showCreationLogs(name) {
    activeLogServer = name;
    document.getElementById('logs-server-name').textContent = name;
    const contentArea = document.getElementById('creation-logs-content');
    contentArea.textContent = 'Loading logs...';
    
    document.getElementById('logs-modal-overlay').classList.add('is-visible');
    
    // Join creation logs room via Socket.IO
    socket.emit('join_creation_logs', { name });
}

function hideLogsModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('logs-modal-overlay').classList.remove('is-visible');
    
    if (activeLogServer) {
        socket.emit('leave_creation_logs', { name: activeLogServer });
        activeLogServer = null;
    }
}

async function cancelServerCreation(name) {
    if (!confirm(`Are you sure you want to cancel the creation of server '${name}'? This will stop the setup and completely delete the server.`)) {
        return;
    }
    
    showToast(`Cancelling creation of ${name}...`, 'info');
    try {
        const data = await apiFetch('/api/server/delete', 'POST', { name, remove_data: true });
        showToast(data.message || `Creation cancelled.`, 'success');
        await loadServers();
    } catch (err) {
        showToast(`Failed to cancel: ${err.message}`, 'error');
    }
}

async function cancelModDownload(name) {
    if (!confirm(`Are you sure you want to cancel the mod download for server '${name}'?`)) {
        return;
    }
    
    showToast(`Cancelling mod download for ${name}...`, 'info');
    try {
        const data = await apiFetch('/api/server/cancel-mod-download', 'POST', { name });
        showToast(data.message || `Download cancelled.`, 'success');
        await loadServers();
    } catch (err) {
        showToast(`Failed to cancel: ${err.message}`, 'error');
    }
}

// --- Console Modal ---
function showConsoleModal(name) {
    activeConsoleServer = name;
    document.getElementById('console-server-name').textContent = name;
    const contentArea = document.getElementById('console-logs-content');
    contentArea.textContent = 'Connecting to console...';
    
    // Check write console permissions
    const currentServer = servers.find(s => s.name === name);
    const perms = currentServer ? currentServer.permissions : {};
    const canWriteConsole = !!perms.can_write_console;
    
    const inputEl = document.getElementById('console-command-input');
    if (inputEl) {
        inputEl.value = '';
        inputEl.disabled = !canWriteConsole;
        inputEl.placeholder = canWriteConsole ? "Type server command here..." : "You do not have permission to send commands";
    }
    
    document.getElementById('console-modal-overlay').classList.add('is-visible');
    
    // Join console room via Socket.IO
    socket.emit('join_console', { name });
    
    // Auto-focus input if writable
    if (canWriteConsole) {
        setTimeout(() => {
            document.getElementById('console-command-input').focus();
        }, 200);
    }
}

function hideConsoleModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('console-modal-overlay').classList.remove('is-visible');
    
    if (activeConsoleServer) {
        socket.emit('leave_console', { name: activeConsoleServer });
        activeConsoleServer = null;
    }
}

async function sendConsoleCommand(e) {
    e.preventDefault();
    const inputEl = document.getElementById('console-command-input');
    const command = inputEl.value.trim();
    if (!command || !activeConsoleServer) return;
    
    // Clear input
    inputEl.value = '';
    
    try {
        await apiFetch('/api/server/command', 'POST', { name: activeConsoleServer, command });
    } catch (err) {
        const contentArea = document.getElementById('console-logs-content');
        contentArea.textContent += `[Error executing command: ${err.message}]\n`;
        const container = document.querySelector('.console-logs-container');
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }
}

async function agreeToEula(name) {
    if (!confirm(`Do you agree to the Minecraft End User License Agreement (EULA) at https://aka.ms/MinecraftEULA to run server '${name}'?`)) {
        return;
    }
    
    try {
        showToast(`Agreeing to EULA for ${name}...`, 'info');
        const data = await apiFetch('/api/server/agree-eula', 'POST', { name });
        showToast(data.message || `EULA agreed successfully!`, 'success');
        await loadServers();
    } catch (err) {
        showToast(`Failed to agree to EULA: ${err.message}`, 'error');
    }
}

// --- Keyboard Shortcuts ---
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        hideCreateModal();
        hideDeleteModal();
        hideHostnameModal();
        hideMemoryModal();
        hideUsersModal();
        hideLogsModal();
        hideConsoleModal();
        hideFileExplorerModal();
        hideServerSettingsModal();
        hideQuickSettingsModal();
        hideServerLogsModal();
        hideFirewallModal();
        hideModsModal();
        closeUserSettingsModal();
        closeAdminSettingsModal();
    }
    // Ctrl+N to create server
    if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
        e.preventDefault();
        showCreateModal();
    }
});

// --- Forge Version Scraper ---
let forgeDebounceTimeout = null;

function handleServerTypeChange() {
    const type = document.getElementById('server-type').value;
    const versionLabel = document.getElementById('version-label');
    const versionInput = document.getElementById('server-version');
    const forgeGroup = document.getElementById('forge-version-group');
    const forgeLabel = document.querySelector('label[for="forge-version-select"]');
    
    if (type === 'forge' || type === 'neoforge') {
        versionLabel.textContent = 'Minecraft Version';
        versionInput.placeholder = type === 'forge' ? 'e.g. 1.20.1' : 'e.g. 1.21.1';
        forgeGroup.style.display = 'block';
        if (forgeLabel) {
            forgeLabel.textContent = type === 'forge' ? 'Forge Version' : 'NeoForge Version';
        }
        handleMinecraftVersionInput();
    } else {
        versionLabel.textContent = 'Version';
        versionInput.placeholder = 'e.g. 1.21.1';
        forgeGroup.style.display = 'none';
    }
}

function handleMinecraftVersionInput() {
    const type = document.getElementById('server-type').value;
    if (type !== 'forge' && type !== 'neoforge') return;
    
    const mcVersion = document.getElementById('server-version').value.trim();
    const select = document.getElementById('forge-version-select');
    const hint = document.getElementById('forge-version-hint');
    
    select.innerHTML = '';
    
    if (!mcVersion) {
        select.innerHTML = '<option value="">Enter a Minecraft version first</option>';
        return;
    }
    
    clearTimeout(forgeDebounceTimeout);
    forgeDebounceTimeout = setTimeout(async () => {
        const isNeo = (type === 'neoforge');
        hint.textContent = isNeo ? 'Fetching NeoForge versions...' : 'Fetching Forge versions...';
        select.innerHTML = '<option value="">Loading versions...</option>';
        try {
            const endpoint = isNeo 
                ? `/api/neoforge/versions?mc_version=${encodeURIComponent(mcVersion)}`
                : `/api/forge/versions?mc_version=${encodeURIComponent(mcVersion)}`;
            const data = await apiFetch(endpoint);
            select.innerHTML = '';
            
            if (!data.versions || data.versions.length === 0) {
                select.innerHTML = isNeo ? '<option value="">No NeoForge versions found</option>' : '<option value="">No Forge versions found</option>';
                hint.textContent = isNeo 
                    ? 'Could not find any NeoForge versions for this Minecraft version.'
                    : 'Could not find any Forge versions for this Minecraft version.';
                return;
            }
            
            data.versions.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v.version;
                
                let label = v.version;
                if (v.is_recommended) {
                    label += ' (Recommended)';
                } else if (v.is_latest) {
                    label += ' (Latest)';
                }
                opt.textContent = label;
                select.appendChild(opt);
            });
            
            let defaultVersion = null;
            if (data.recommended) {
                defaultVersion = data.recommended.version;
            } else if (data.latest) {
                defaultVersion = data.latest.version;
            } else if (data.versions.length > 0) {
                defaultVersion = data.versions[0].version;
            }
            
            if (defaultVersion) {
                select.value = defaultVersion;
            }
            
            hint.textContent = isNeo 
                ? `Fetched successfully from NeoForge releases.`
                : `Scraped successfully from official Forge files. Recommended/Latest selected by default.`;
        } catch (err) {
            select.innerHTML = '<option value="">Failed to load versions</option>';
            hint.textContent = `Error: ${err.message}`;
        }
    }, 500);
}

async function installServer(name) {
    try {
        showToast(`Starting installation of Forge on ${name}...`, 'info');
        const data = await apiFetch('/api/server/install', 'POST', { name });
        showToast(data.message || `Installation started`, 'success');
        showCreationLogs(name);
        await loadServers();
    } catch (err) {
        showToast(`Failed to start installation: ${err.message}`, 'error');
    }
}

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
});

// --- Upload Mods State & Functions ---
let modsServerTarget = null;
let modsSelectedSource = null;
let modsFileToUpload = null;
let modsDragDropInitialized = false;

function showModsModal(name) {
    modsServerTarget = name;
    document.getElementById('mods-server-name').textContent = name;
    
    // Reset steps and states
    modsSelectedSource = null;
    modsFileToUpload = null;
    
    document.getElementById('mods-step-source').style.display = 'block';
    document.getElementById('mods-step-upload').style.display = 'none';
    
    // Clear any selected file info
    clearSelectedModFile();
    
    // Hide progress bar
    document.getElementById('mods-progress-container').style.display = 'none';
    document.getElementById('mods-progress-bar').style.width = '0%';
    document.getElementById('mods-progress-percent').textContent = '0%';
    document.getElementById('mods-progress-status').textContent = 'Uploading...';
    
    // Show modal
    document.getElementById('mods-modal-overlay').classList.add('is-visible');
    
    // Initialize drag and drop if not already done
    initModsDragDrop();
}

function hideModsModal(e) {
    if (e && e.target !== e.currentTarget) return;
    
    // If upload is in progress, warn or block closing
    const progressContainer = document.getElementById('mods-progress-container');
    if (progressContainer.style.display === 'block' && 
        !document.getElementById('btn-submit-upload').disabled) {
        if (!confirm("An upload/download is in progress. Are you sure you want to close this window?")) {
            return;
        }
    }
    
    document.getElementById('mods-modal-overlay').classList.remove('is-visible');
    modsServerTarget = null;
    modsSelectedSource = null;
    modsFileToUpload = null;
}

function selectModsSource(source) {
    modsSelectedSource = source;
    
    const fileInput = document.getElementById('mods-file-input');
    const subtitle = document.getElementById('mods-upload-subtitle');
    const text = document.querySelector('.drop-zone-text');
    const hint = document.getElementById('mods-file-hint');
    
    if (source === 'curseforge') {
        fileInput.setAttribute('accept', '.html,.json');
        subtitle.textContent = 'Import CurseForge Modlist / manifest.json';
        text.innerHTML = 'Drag & drop your CurseForge <span class="browse-link">.html modlist or manifest.json</span> here or browse';
        hint.textContent = 'Accepts CurseForge HTML export files (.html) or manifest.json (.json)';
    } else {
        fileInput.setAttribute('accept', '.jar');
        subtitle.textContent = 'Upload Local Mods';
        text.innerHTML = 'Drag & drop your mod <span class="browse-link">.jar file</span> here or browse';
        hint.textContent = 'Accepts Minecraft Mod files (.jar)';
    }
    
    document.getElementById('mods-step-source').style.display = 'none';
    document.getElementById('mods-step-upload').style.display = 'block';
    
    // Reset file selection
    clearSelectedModFile();
}

function goBackToSourceSelect() {
    // If progress is visible, don't allow going back easily
    const progressContainer = document.getElementById('mods-progress-container');
    if (progressContainer.style.display === 'block') return;
    
    modsSelectedSource = null;
    clearSelectedModFile();
    
    document.getElementById('mods-step-upload').style.display = 'none';
    document.getElementById('mods-step-source').style.display = 'block';
}

function clearSelectedModFile() {
    modsFileToUpload = null;
    document.getElementById('mods-file-input').value = '';
    document.getElementById('mods-selected-file').style.display = 'none';
    document.getElementById('mods-drop-zone').style.display = 'flex';
    
    const submitBtn = document.getElementById('btn-submit-upload');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Upload & Install';
}

function handleSelectedModFile(file) {
    if (!file) return;
    
    // Type checking
    if (modsSelectedSource === 'curseforge' && !file.name.endsWith('.html') && !file.name.endsWith('.json')) {
        showToast('Please select a .html CurseForge modlist or manifest.json file.', 'error');
        clearSelectedModFile();
        return;
    }
    
    if (modsSelectedSource === 'local' && !file.name.endsWith('.jar')) {
        showToast('Please select a .jar Minecraft mod file.', 'error');
        clearSelectedModFile();
        return;
    }
    
    modsFileToUpload = file;
    
    // Show selected file in UI
    document.getElementById('mods-filename').textContent = file.name;
    document.getElementById('mods-filesize').textContent = formatBytes(file.size);
    
    document.getElementById('mods-drop-zone').style.display = 'none';
    document.getElementById('mods-selected-file').style.display = 'flex';
    
    // Enable submit
    const submitBtn = document.getElementById('btn-submit-upload');
    submitBtn.disabled = false;
    if (modsSelectedSource === 'curseforge') {
        submitBtn.textContent = 'Import & Download';
    } else {
        submitBtn.textContent = 'Upload Mod';
    }
}

function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function initModsDragDrop() {
    if (modsDragDropInitialized) return;
    
    const dropZone = document.getElementById('mods-drop-zone');
    const fileInput = document.getElementById('mods-file-input');
    
    if (!dropZone || !fileInput) return;
    
    // Open explorer when clicking drop zone
    dropZone.addEventListener('click', () => {
        fileInput.click();
    });
    
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleSelectedModFile(e.target.files[0]);
        }
    });
    
    // Drag events
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.add('drop-zone--over');
        }, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove('drop-zone--over');
        }, false);
    });
    
    dropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            handleSelectedModFile(files[0]);
        }
    }, false);
    
    modsDragDropInitialized = true;
}

function submitModUpload() {
    if (!modsServerTarget || !modsSelectedSource || !modsFileToUpload) return;
    
    const submitBtn = document.getElementById('btn-submit-upload');
    const progressContainer = document.getElementById('mods-progress-container');
    const progressBar = document.getElementById('mods-progress-bar');
    const progressPercent = document.getElementById('mods-progress-percent');
    const progressStatus = document.getElementById('mods-progress-status');
    
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner"></span> Processing...';
    
    progressContainer.style.display = 'block';
    progressBar.style.width = '0%';
    progressPercent.textContent = '0%';
    progressStatus.textContent = 'Uploading file...';
    
    const formData = new FormData();
    formData.append('file', modsFileToUpload);
    
    const xhr = new XMLHttpRequest();
    const endpoint = modsSelectedSource === 'curseforge' 
        ? `/api/server/${encodeURIComponent(modsServerTarget)}/upload-modlist`
        : `/api/server/${encodeURIComponent(modsServerTarget)}/upload-mod`;
        
    xhr.open('POST', endpoint, true);
    
    // Track upload progress
    xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) {
            const percent = Math.round((e.loaded / e.total) * 100);
            progressBar.style.width = percent + '%';
            progressPercent.textContent = percent + '%';
            if (percent === 100) {
                if (modsSelectedSource === 'curseforge') {
                    progressStatus.textContent = 'CurseForge List received! Starting downloader...';
                } else {
                    progressStatus.textContent = 'Saving mod...';
                }
            }
        }
    });
    
    xhr.onload = function() {
        let respData = {};
        try {
            respData = JSON.parse(xhr.responseText);
        } catch (e) {}
        
        if (xhr.status >= 200 && xhr.status < 300) {
            showToast(respData.message || 'File processed successfully!', 'success');
            
            if (modsSelectedSource === 'curseforge') {
                // Close modal and open logs room to watch download!
                hideModsModal();
                setTimeout(() => {
                    showCreationLogs(modsServerTarget);
                }, 300);
            } else {
                // For direct mods uploader, clear selection and let them add more
                clearSelectedModFile();
                progressContainer.style.display = 'none';
            }
        } else {
            showToast(respData.detail || respData.error || `Upload failed (Status ${xhr.status})`, 'error');
            submitBtn.disabled = false;
            submitBtn.textContent = modsSelectedSource === 'curseforge' ? 'Import & Download' : 'Upload Mod';
            progressContainer.style.display = 'none';
        }
    };
    
    xhr.onerror = function() {
        showToast('Network error occurred during file upload.', 'error');
        submitBtn.disabled = false;
        submitBtn.textContent = modsSelectedSource === 'curseforge' ? 'Import & Download' : 'Upload Mod';
        progressContainer.style.display = 'none';
    };
    
    xhr.send(formData);
}


// ============================================================================
// File Explorer & Git-like Staging Actions
// ============================================================================

async function showFileExplorerModal(name) {
    activeExplorerServer = name;
    currentExplorerPath = "";
    explorerChanges = {};
    editorOriginalPath = null;
    
    // Check permissions
    const currentServer = servers.find(s => s.name === name);
    const perms = currentServer ? currentServer.permissions : {};
    const canWriteFiles = !!perms.can_write_files;
    
    // Toggle New File / Folder / Upload buttons visibility
    const btnNewFile = document.getElementById('btn-explorer-new-file');
    const btnNewFolder = document.getElementById('btn-explorer-new-folder');
    const btnUploadLocal = document.getElementById('btn-explorer-upload-local');
    if (btnNewFile) btnNewFile.style.display = canWriteFiles ? 'inline-flex' : 'none';
    if (btnNewFolder) btnNewFolder.style.display = canWriteFiles ? 'inline-flex' : 'none';
    if (btnUploadLocal) btnUploadLocal.style.display = canWriteFiles ? 'inline-flex' : 'none';
    
    // Toggle right changes staging panel and adjust explorer grid columns
    const rightContainer = document.querySelector('.explorer-right-container');
    const explorerGrid = document.querySelector('.explorer-grid');
    if (rightContainer && explorerGrid) {
        if (canWriteFiles) {
            rightContainer.style.display = 'block';
            explorerGrid.classList.remove('explorer-grid--no-write');
        } else {
            rightContainer.style.display = 'none';
            explorerGrid.classList.add('explorer-grid--no-write');
        }
    }
    
    document.getElementById('explorer-server-name').textContent = name;
    document.getElementById('file-explorer-modal-overlay').classList.add('is-visible');
    
    setupExplorerDragAndDrop();
    await loadExplorerDirectory("");
    renderExplorerChanges();
}

function hideFileExplorerModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('file-explorer-modal-overlay').classList.remove('is-visible');
    activeExplorerServer = null;
}

async function loadExplorerDirectory(path) {
    currentExplorerPath = path;
    
    // Set breadcrumbs
    const crumbs = document.getElementById('explorer-breadcrumbs');
    crumbs.textContent = path ? `/${path}` : "/";
    
    try {
        const data = await apiFetch(`/api/server/${activeExplorerServer}/files?path=${encodeURIComponent(path)}`);
        renderExplorerFiles(data.files || []);
    } catch (err) {
        showToast(`Failed to load directory: ${err.message}`, 'error');
    }
}

function renderExplorerFiles(files) {
    const listContainer = document.getElementById('explorer-file-list-container');
    listContainer.innerHTML = '';
    
    if (files.length === 0) {
        listContainer.innerHTML = `
            <div style="padding: var(--space-2xl); text-align: center; color: var(--text-muted); font-size: 0.875rem;">
                This directory is empty
            </div>
        `;
        return;
    }
    
    files.forEach(file => {
        const itemEl = document.createElement('div');
        itemEl.className = 'explorer-item';
        
        // Icon based on type
        let iconHtml = '';
        if (file.is_dir) {
            iconHtml = `
                <div class="explorer-item-icon folder">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                </div>
            `;
        } else {
            iconHtml = `
                <div class="explorer-item-icon">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
                </div>
            `;
        }
        
        // Size format
        const sizeText = file.is_dir ? '—' : formatBytes(file.size);
        
        itemEl.innerHTML = `
            ${iconHtml}
            <span class="explorer-item-name">${escapeHtml(file.name)}</span>
            <div class="explorer-item-details">
                <span>${sizeText}</span>
            </div>
        `;
        
        // Click action: enter dir or edit/view file
        itemEl.onclick = async () => {
            if (file.is_dir) {
                await loadExplorerDirectory(file.path);
            } else {
                await editFileInExplorer(file.path);
            }
        };
        
        listContainer.appendChild(itemEl);
    });
}

function navigateExplorerUp() {
    if (!currentExplorerPath) return;
    const parts = currentExplorerPath.split('/');
    parts.pop();
    loadExplorerDirectory(parts.join('/'));
}

async function editFileInExplorer(path) {
    try {
        showToast(`Loading file...`, 'info');
        const data = await apiFetch(`/api/server/${activeExplorerServer}/file?path=${encodeURIComponent(path)}`);
        
        if (data.is_binary) {
            showToast(`Binary file. Edits not supported in Web UI.`, 'warning');
            return;
        }
        
        editorOriginalPath = path;
        
        // Check permissions
        const currentServer = servers.find(s => s.name === activeExplorerServer);
        const perms = currentServer ? currentServer.permissions : {};
        const canWrite = !!perms.can_write_files;
        
        document.getElementById('editor-filename-label').textContent = canWrite ? `Editing: ${path}` : `Viewing: ${path}`;
        
        // Pre-fill content (or load from explorerChanges if already edited but unstaged)
        const currentChange = explorerChanges[path];
        const initialText = currentChange ? currentChange.content : data.content;
        
        const textarea = document.getElementById('explorer-editor-textarea');
        textarea.value = initialText;
        textarea.readOnly = !canWrite;
        
        // Hide/show Keep Changes button
        const btnSave = document.getElementById('btn-explorer-editor-save');
        if (btnSave) {
            btnSave.style.display = canWrite ? 'inline-flex' : 'none';
        }
        
        // Swap views
        document.getElementById('explorer-browser-view').style.display = 'none';
        document.getElementById('explorer-editor-view').style.display = 'flex';
        
        // Auto-focus editor if writable
        if (canWrite) {
            setTimeout(() => {
                textarea.focus();
            }, 100);
        }
        
    } catch (err) {
        showToast(`Failed to load file: ${err.message}`, 'error');
    }
}

function closeExplorerEditor() {
    document.getElementById('explorer-editor-view').style.display = 'none';
    document.getElementById('explorer-browser-view').style.display = 'flex';
    editorOriginalPath = null;
}

function saveExplorerEditor() {
    if (!editorOriginalPath) return;
    
    const newContent = document.getElementById('explorer-editor-textarea').value;
    
    // Add to unstaged changes
    explorerChanges[editorOriginalPath] = {
        path: editorOriginalPath,
        type: 'edit',
        content: newContent,
        staged: false
    };
    
    showToast(`Kept edits in unstaged changes list.`, 'success');
    closeExplorerEditor();
    renderExplorerChanges();
}

function promptCreateFile() {
    const filename = prompt("Enter new file name (e.g. motd.txt):");
    if (!filename) return;
    
    const cleanFilename = filename.trim();
    if (!cleanFilename) return;
    
    const path = currentExplorerPath ? `${currentExplorerPath}/${cleanFilename}` : cleanFilename;
    
    // Store as new file change
    explorerChanges[path] = {
        path: path,
        type: 'new',
        content: '',
        staged: false
    };
    
    renderExplorerChanges();
    
    // Open in editor directly so they can write!
    editFileInExplorer(path);
}

function promptCreateFolder() {
    const foldername = prompt("Enter new folder name (e.g. backup):");
    if (!foldername) return;
    
    const cleanFoldername = foldername.trim();
    if (!cleanFoldername) return;
    
    const path = currentExplorerPath ? `${currentExplorerPath}/${cleanFoldername}` : cleanFoldername;
    
    // A folder doesn't have file content, but to write/commit a folder on the server
    // we can create a placeholder `.keep` file so the folder gets created!
    const keepFilePath = `${path}/.keep`;
    explorerChanges[keepFilePath] = {
        path: keepFilePath,
        type: 'new',
        content: '# Placeholder to preserve directory structure',
        staged: false
    };
    
    renderExplorerChanges();
    showToast(`Prepared folder creation in unstaged changes.`, 'success');
}

function triggerLocalFileSelect() {
    document.getElementById('explorer-file-input').click();
}

function handleLocalFileSelect(e) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    
    Array.from(files).forEach(file => {
        const path = currentExplorerPath ? `${currentExplorerPath}/${file.name}` : file.name;
        explorerChanges[path] = {
            path: path,
            type: 'new',
            content: file, // Keep the native File object!
            staged: false
        };
    });
    
    renderExplorerChanges();
    showToast(`Prepared ${files.length} file(s) in unstaged changes.`, 'success');
    
    // Reset file input
    e.target.value = '';
}

// Staging Control Actions
function toggleStageChange(path) {
    if (explorerChanges[path]) {
        explorerChanges[path].staged = !explorerChanges[path].staged;
        renderExplorerChanges();
    }
}

function discardChange(path) {
    if (explorerChanges[path]) {
        if (confirm(`Are you sure you want to discard the pending changes for ${path}?`)) {
            delete explorerChanges[path];
            renderExplorerChanges();
            showToast(`Discarded change.`, 'info');
        }
    }
}

function renderExplorerChanges() {
    const unstagedList = document.getElementById('unstaged-changes-list');
    const stagedList = document.getElementById('staged-changes-list');
    
    unstagedList.innerHTML = '';
    stagedList.innerHTML = '';
    
    const changesArray = Object.values(explorerChanges);
    const unstagedItems = changesArray.filter(c => !c.staged);
    const stagedItems = changesArray.filter(c => c.staged);
    
    document.getElementById('count-unstaged').textContent = unstagedItems.length;
    document.getElementById('count-staged').textContent = stagedItems.length;
    
    // Render Unstaged
    if (unstagedItems.length === 0) {
        unstagedList.innerHTML = `
            <div style="padding: var(--space-md); text-align: center; color: var(--text-muted); font-size: 0.75rem;">
                No unstaged changes
            </div>
        `;
    } else {
        unstagedItems.forEach(c => {
            const el = document.createElement('div');
            el.className = 'change-item';
            
            const tagClass = c.type === 'new' ? 'tag-new' : 'tag-edit';
            const tagLabel = c.type === 'new' ? 'NEW' : 'MOD';
            
            el.innerHTML = `
                <span class="change-tag ${tagClass}">${tagLabel}</span>
                <span class="change-item-path" title="${escapeHtml(c.path)}">${escapeHtml(c.path)}</span>
                <div class="change-item-actions">
                    <button class="btn btn-icon btn-sm" onclick="toggleStageChange('${escapeAttr(c.path)}')" title="Stage Change">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                    </button>
                    <button class="btn btn-icon btn-sm" onclick="discardChange('${escapeAttr(c.path)}')" title="Discard Edits">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M2.5 2v6h6M21.5 22v-6h-6"/><path d="M22 11.5A10 10 0 0 0 12.3 2.5a10.16 10.16 0 0 0-8.5 4.5L2.5 8m19 8-1.3 1A10.16 10.16 0 0 1 11.7 21.5a10 10 0 0 1-9.2-9"/></svg>
                    </button>
                </div>
            `;
            unstagedList.appendChild(el);
        });
    }
    
    // Render Staged
    if (stagedItems.length === 0) {
        stagedList.innerHTML = `
            <div style="padding: var(--space-md); text-align: center; color: var(--text-muted); font-size: 0.75rem;">
                No staged changes
            </div>
        `;
    } else {
        stagedItems.forEach(c => {
            const el = document.createElement('div');
            el.className = 'change-item';
            
            const tagClass = c.type === 'new' ? 'tag-new' : 'tag-edit';
            const tagLabel = c.type === 'new' ? 'NEW' : 'MOD';
            
            el.innerHTML = `
                <span class="change-tag ${tagClass}">${tagLabel}</span>
                <span class="change-item-path" title="${escapeHtml(c.path)}">${escapeHtml(c.path)}</span>
                <div class="change-item-actions">
                    <button class="btn btn-icon btn-sm" onclick="toggleStageChange('${escapeAttr(c.path)}')" title="Unstage Change">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"/></svg>
                    </button>
                </div>
            `;
            stagedList.appendChild(el);
        });
    }
    
    // Button Label logic: "upload the staged chnges and if none are staged upload all changes"
    const btn = document.getElementById('btn-explorer-upload');
    const btnText = document.getElementById('btn-upload-text');
    
    if (changesArray.length === 0) {
        btn.disabled = true;
        btnText.textContent = "Upload Changes";
    } else {
        btn.disabled = false;
        if (stagedItems.length > 0) {
            btnText.textContent = `Upload Staged (${stagedItems.length})`;
        } else {
            btnText.textContent = `Upload All (${unstagedItems.length})`;
        }
    }
}

// Bulk Upload to Server
async function uploadChangesToServer() {
    const changesArray = Object.values(explorerChanges);
    if (changesArray.length === 0) return;
    
    const stagedItems = changesArray.filter(c => c.staged);
    const unstagedItems = changesArray.filter(c => !c.staged);
    
    // Determine target changes to send
    const targets = stagedItems.length > 0 ? stagedItems : unstagedItems;
    
    if (targets.length === 0) return;
    
    const btn = document.getElementById('btn-explorer-upload');
    const oldHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Saving...';
    
    try {
        const formData = new FormData();
        const pathsList = [];
        
        targets.forEach(c => {
            pathsList.push(c.path);
            
            // Build the appropriate File/Blob payload
            if (c.content instanceof File) {
                // It is already a native File object from file browser or drag-and-drop
                formData.append('files', c.content);
            } else {
                // It is text content from edit panel
                const blob = new Blob([c.content], { type: 'text/plain' });
                formData.append('files', blob, c.path.split('/').pop());
            }
        });
        
        formData.append('paths_json', JSON.stringify(pathsList));
        
        // POST to backend API
        const resp = await fetch(`/api/server/${activeExplorerServer}/files`, {
            method: 'POST',
            body: formData // Body is multipart/form-data, browser handles boundaries automatically
        });
        
        const json = await resp.json();
        if (!resp.ok) {
            throw new Error(json.error || `HTTP ${resp.status}`);
        }
        
        showToast(json.message || "Successfully committed changes!", "success");
        
        // Remove uploaded items from state
        targets.forEach(c => {
            delete explorerChanges[c.path];
        });
        
        // Reload current view and update staged/unstaged change lists
        await loadExplorerDirectory(currentExplorerPath);
        renderExplorerChanges();
        
    } catch (err) {
        showToast(`Failed to upload changes: ${err.message}`, "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = oldHtml;
    }
}

// Drag & Drop Setup
function setupExplorerDragAndDrop() {
    const zone = document.getElementById('explorer-drag-zone');
    const overlay = document.getElementById('explorer-drag-overlay');
    
    if (!zone || !overlay) return;
    
    // Check write permissions
    const currentServer = servers.find(s => s.name === activeExplorerServer);
    const perms = currentServer ? currentServer.permissions : {};
    if (!perms.can_write_files) return;
    
    // Remove duplicates if setup multiple times
    const newZone = zone.cloneNode(true);
    zone.parentNode.replaceChild(newZone, zone);
    
    const dragOverlay = document.getElementById('explorer-drag-overlay');
    
    ['dragenter', 'dragover'].forEach(eventName => {
        newZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dragOverlay.classList.add('drag-active');
        }, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        newZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dragOverlay.classList.remove('drag-active');
        }, false);
    });
    
    newZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (!files || files.length === 0) return;
        
        Array.from(files).forEach(file => {
            const path = currentExplorerPath ? `${currentExplorerPath}/${file.name}` : file.name;
            explorerChanges[path] = {
                path: path,
                type: 'new',
                content: file,
                staged: false
            };
        });
        
        renderExplorerChanges();
        showToast(`Prepared ${files.length} drop file(s) in unstaged changes.`, 'success');
    }, false);
}

// Helper formats
function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}


// --- Server Settings Controller ---
function showServerSettingsModal(name) {
    activeSettingsServer = name;
    document.getElementById('settings-server-name').textContent = name;
    
    // Check permissions for buttons
    const currentServer = servers.find(s => s.name === name);
    const perms = currentServer ? currentServer.permissions : {};
    const isOwner = currentServer ? currentServer.is_owner : true;
    
    // Quick Settings: visible if they can read files
    const btnQuickSettings = document.getElementById('btn-settings-quick-settings');
    if (btnQuickSettings) {
        btnQuickSettings.style.display = perms.can_read_files ? 'flex' : 'none';
    }
    
    // Upload Mods: visible if they can write files
    const btnUploadMods = document.getElementById('btn-settings-upload-mods');
    if (btnUploadMods) {
        btnUploadMods.style.display = perms.can_write_files ? 'flex' : 'none';
    }
    
    // Firewall: visible if they can read OR write firewall
    const btnFirewall = document.getElementById('btn-settings-firewall');
    if (btnFirewall) {
        btnFirewall.style.display = (perms.can_read_firewall || perms.can_write_firewall) ? 'flex' : 'none';
    }
    
    // Sharing: visible only to owner/admin
    const btnSharing = document.getElementById('btn-settings-sharing');
    if (btnSharing) {
        btnSharing.style.display = isOwner ? 'flex' : 'none';
    }

    document.getElementById('settings-modal-overlay').classList.add('is-visible');
}

function hideServerSettingsModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('settings-modal-overlay').classList.remove('is-visible');
    activeSettingsServer = null;
}

function triggerSettingsModsUpload() {
    if (!activeSettingsServer) return;
    const name = activeSettingsServer;
    hideServerSettingsModal();
    // Open mods modal directly
    setTimeout(() => {
        showModsModal(name);
    }, 200);
}

function triggerSettingsQuickSettings() {
    if (!activeSettingsServer) return;
    const name = activeSettingsServer;
    hideServerSettingsModal();
    setTimeout(() => {
        showQuickSettingsModal(name);
    }, 200);
}

let activeQuickSettingsServer = null;
let loadedQuickSettings = {};
let hasRconFirewallRule = false;

// Dynamic change tracking and highlight helper
function checkUnsavedChanges() {
    let hasChanges = false;
    const inputs = document.querySelectorAll('[id^="qs-"]');
    
    inputs.forEach(input => {
        // Skip elements inside voicechat container since they are rendered dynamically and handled separately
        if (input.closest('#quick-settings-voicechat-container')) return;
        
        let currentVal = input.type === 'checkbox' ? input.checked : input.value.trim();
        let originalVal = loadedQuickSettings[input.id];
        
        // Normalize comparison
        if (input.type === 'number' && originalVal !== undefined) {
            currentVal = parseFloat(currentVal);
            originalVal = parseFloat(originalVal);
        }
        
        let changed = false;
        if (input.type === 'checkbox') {
            changed = currentVal !== !!originalVal;
        } else {
            changed = String(currentVal) !== String(originalVal !== undefined && originalVal !== null ? originalVal : '');
        }
        
        const formGroup = input.closest('.form-group-flex') || input.closest('.form-group-toggle') || input.closest('.form-group');
        const label = formGroup ? formGroup.querySelector('label') : null;
        
        if (changed) {
            hasChanges = true;
            input.classList.add('qs-input-changed');
            if (label && !label.querySelector('.qs-unsaved-badge')) {
                const badge = document.createElement('span');
                badge.className = 'qs-unsaved-badge';
                badge.textContent = '● Unsaved';
                label.appendChild(badge);
            }
        } else {
            input.classList.remove('qs-input-changed');
            if (label) {
                const badge = label.querySelector('.qs-unsaved-badge');
                if (badge) badge.remove();
            }
        }
    });
    
    // Highlight Save Button if changes are present
    const saveBtn = document.getElementById('btn-save-quick-settings');
    if (hasChanges) {
        saveBtn.classList.add('btn-primary--glowing');
    } else {
        saveBtn.classList.remove('btn-primary--glowing');
    }
    
    // Suggestion display for RCON
    checkRconFirewallSuggestion();
}

function checkRconFirewallSuggestion() {
    const enableRconEl = document.getElementById('qs-enable-rcon');
    const rconAlertBox = document.getElementById('qs-rcon-firewall-alert');
    const rconPortInput = document.getElementById('qs-rcon-port');
    const portLabel = document.getElementById('qs-rcon-port-suggest');
    
    // Hide if user lacks write firewall permission
    const serverName = activeQuickSettingsServer;
    const currentServer = servers.find(s => s.name === serverName);
    const hasWriteFirewall = currentServer && currentServer.permissions ? currentServer.permissions.can_write_firewall : true;
    
    if (!hasWriteFirewall) {
        if (rconAlertBox) rconAlertBox.style.display = 'none';
        return;
    }
    
    if (enableRconEl && enableRconEl.checked) {
        const rconPortVal = rconPortInput ? rconPortInput.value : 25575;
        if (portLabel) portLabel.textContent = rconPortVal;
        
        if (!hasRconFirewallRule) {
            rconAlertBox.style.display = 'flex';
        } else {
            rconAlertBox.style.display = 'none';
        }
    } else {
        rconAlertBox.style.display = 'none';
    }
}

async function quickAddRconRule() {
    if (!activeQuickSettingsServer) return;
    const rconPortInput = document.getElementById('qs-rcon-port');
    const rconPortVal = parseInt(rconPortInput ? rconPortInput.value : 25575);
    
    if (isNaN(rconPortVal) || rconPortVal < 1 || rconPortVal > 65535) {
        showToast('Please enter a valid RCON port.', 'error');
        return;
    }
    
    try {
        const payload = {
            protocol: 'TCP',
            enabled: true,
            internal_port: rconPortVal,
            external_port: rconPortVal,
            label: 'RCON Access'
        };
        
        await apiFetch(`/api/server/${activeQuickSettingsServer}/firewall/rule`, 'POST', payload);
        showToast('RCON TCP firewall rule successfully added!', 'success');
        hasRconFirewallRule = true;
        checkRconFirewallSuggestion();
    } catch (err) {
        showToast(`Failed to add firewall rule: ${err}`, 'error');
    }
}

async function showQuickSettingsModal(name) {
    activeQuickSettingsServer = name;
    document.getElementById('quick-settings-server-name').textContent = name;
    document.getElementById('quick-settings-modal-overlay').classList.add('is-visible');
    
    // Clear and set loading status
    const allInputs = document.querySelectorAll('#quick-settings-form input, #quick-settings-form select');
    allInputs.forEach(input => {
        if (input.closest('#quick-settings-voicechat-container')) return;
        input.disabled = true;
        if (input.type === 'checkbox') {
            input.checked = false;
        } else {
            input.value = '';
        }
        input.classList.remove('qs-input-changed');
    });
    
    // Clear any previous unsaved badges
    document.querySelectorAll('.qs-unsaved-badge').forEach(b => b.remove());
    document.getElementById('btn-save-quick-settings').classList.remove('btn-primary--glowing');
    
    const vcContainer = document.getElementById('quick-settings-voicechat-container');
    vcContainer.style.display = 'none';
    vcContainer.innerHTML = '';
    
    loadedQuickSettings = {};
    hasRconFirewallRule = false;
    
    try {
        // Fetch properties & firewall info in parallel
        const [data, fwData] = await Promise.all([
            apiFetch(`/api/server/${name}/quick-settings`),
            apiFetch(`/api/server/${name}/firewall`)
        ]);
        
        // Check if RCON rule exists in the firewall list
        const rconPortVal = data.rcon_port || 25575;
        hasRconFirewallRule = (fwData.rules || []).some(r => r.protocol === 'TCP' && r.internal_port === parseInt(rconPortVal) && r.enabled);
        
        const currentServer = servers.find(s => s.name === name);
        const hasWriteAccess = currentServer && currentServer.permissions ? currentServer.permissions.can_write_files : true;
        
        // Hide/show save button
        const saveBtn = document.getElementById('btn-save-quick-settings');
        if (saveBtn) {
            saveBtn.style.display = hasWriteAccess ? 'inline-block' : 'none';
        }
        
        // Populate and enable all inputs
        const fieldMapping = {
            'qs-server-port': data.server_port,
            'qs-motd': data.motd,
            'qs-max-players': data.max_players,
            'qs-difficulty': data.difficulty,
            'qs-gamemode': data.gamemode,
            'qs-hardcore': data.hardcore,
            'qs-white-list': data.white_list,
            'qs-online-mode': data.online_mode,
            'qs-level-name': data.level_name,
            'qs-level-seed': data.level_seed,
            'qs-level-type': data.level_type,
            'qs-spawn-protection': data.spawn_protection,
            'qs-view-distance': data.view_distance,
            'qs-simulation-distance': data.simulation_distance,
            'qs-enable-rcon': data.enable_rcon,
            'qs-rcon-port': data.rcon_port,
            'qs-rcon-password': data.rcon_password
        };
        
        Object.keys(fieldMapping).forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                const val = fieldMapping[id];
                if (el.type === 'checkbox') {
                    el.checked = !!val;
                } else {
                    el.value = val !== undefined && val !== null ? val : '';
                }
                el.disabled = !hasWriteAccess;
                // Store loaded value
                loadedQuickSettings[id] = el.type === 'checkbox' ? el.checked : String(el.value).trim();
            }
        });
        
        // Register input change event listeners
        const form = document.getElementById('quick-settings-form');
        form.removeEventListener('input', checkUnsavedChanges);
        form.removeEventListener('change', checkUnsavedChanges);
        form.addEventListener('input', checkUnsavedChanges);
        form.addEventListener('change', checkUnsavedChanges);
        
        // Render Voice Chat Properties if detected
        if (data.voicechat && data.voicechat.detected && data.voicechat.properties) {
            vcContainer.style.display = 'block';
            const props = data.voicechat.properties;
            let html = `
                <h4 style="border-bottom: 1px solid var(--border-default); padding-bottom: var(--space-xs); margin-bottom: var(--space-md); color: var(--accent); font-size: 0.95rem; font-weight: 600;">voicechat-server.properties</h4>
                <div style="display: flex; flex-direction: column; gap: var(--space-md);">
            `;
            
            const keys = ["port", "max_voice_distance", "whisper_distance", "enable_groups", "allow_recording", "spectator_interaction", "spectator_player_possession", "broadcast_range"];
            
            keys.forEach(key => {
                if (!props[key]) return;
                const prop = props[key];
                const val = prop.value;
                const desc = prop.description || '';
                const descHtml = desc.split('\n').map(line => escapeHtml(line)).join('<br>');
                const isBool = val === 'true' || val === 'false';
                
                if (isBool) {
                    const isChecked = val === 'true';
                    html += `
                        <div class="form-group" style="display: flex; flex-direction: column; gap: var(--space-xs); border-bottom: 1px solid rgba(255,255,255,0.03); padding-bottom: var(--space-sm);">
                            <div style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-md);">
                                <label style="font-weight: 600; margin-bottom: 0;">${escapeHtml(key)}</label>
                                <label class="toggle-switch">
                                    <input type="checkbox" id="qs-vc-${key}" ${isChecked ? 'checked' : ''} ${hasWriteAccess ? '' : 'disabled'}>
                                    <span class="toggle-slider"></span>
                                </label>
                            </div>
                            <span class="form-hint" style="color: var(--text-muted); font-size: 0.725rem; margin-top: 2px; line-height: 1.4;">
                                ${descHtml}
                            </span>
                        </div>
                    `;
                } else {
                    const isInt = key === 'port';
                    const inputType = (isInt || key.includes('distance') || key.includes('range')) ? 'number' : 'text';
                    const stepAttr = key.includes('distance') || key.includes('range') ? 'step="0.1"' : '';
                    
                    html += `
                        <div class="form-group" style="display: flex; flex-direction: column; gap: var(--space-xs); border-bottom: 1px solid rgba(255,255,255,0.03); padding-bottom: var(--space-sm);">
                            <div style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-md);">
                                <label for="qs-vc-${key}" style="font-weight: 600; margin-bottom: 0;">${escapeHtml(key)}</label>
                                <input type="${inputType}" id="qs-vc-${key}" value="${escapeHtml(val)}" required ${stepAttr} ${hasWriteAccess ? '' : 'disabled'} style="width: 120px; text-align: right; font-weight: 600;">
                            </div>
                            <span class="form-hint" style="color: var(--text-muted); font-size: 0.725rem; margin-top: 2px; line-height: 1.4;">
                                ${descHtml}
                            </span>
                        </div>
                    `;
                }
            });
            
            html += `</div>`;
            vcContainer.innerHTML = html;
        }
        
        // Initial suggestion check
        checkRconFirewallSuggestion();
    } catch (err) {
        showToast(`Failed to load Quick Settings: ${err}`, 'error');
        hideQuickSettingsModal();
    }
}

function hideQuickSettingsModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('quick-settings-modal-overlay').classList.remove('is-visible');
    activeQuickSettingsServer = null;
}

async function saveQuickSettings(e) {
    e.preventDefault();
    if (!activeQuickSettingsServer) return;
    
    // Gather all fields
    const server_port = parseInt(document.getElementById('qs-server-port').value);
    const motd = document.getElementById('qs-motd').value;
    const max_players = parseInt(document.getElementById('qs-max-players').value);
    const difficulty = document.getElementById('qs-difficulty').value;
    const gamemode = document.getElementById('qs-gamemode').value;
    const hardcore = document.getElementById('qs-hardcore').checked;
    const white_list = document.getElementById('qs-white-list').checked;
    const online_mode = document.getElementById('qs-online-mode').checked;
    const level_name = document.getElementById('qs-level-name').value;
    const level_seed = document.getElementById('qs-level-seed').value.trim();
    const level_type = document.getElementById('qs-level-type').value;
    const spawn_protection = parseInt(document.getElementById('qs-spawn-protection').value);
    const view_distance = parseInt(document.getElementById('qs-view-distance').value);
    const simulation_distance = parseInt(document.getElementById('qs-simulation-distance').value);
    const enable_rcon = document.getElementById('qs-enable-rcon').checked;
    const rcon_port = parseInt(document.getElementById('qs-rcon-port').value);
    const rcon_password = document.getElementById('qs-rcon-password').value;

    if (isNaN(server_port) || server_port < 1 || server_port > 65535) {
        showToast('Please enter a valid port between 1 and 65535.', 'error');
        return;
    }
    
    // Alert user if seed changed
    const originalSeed = loadedQuickSettings['qs-level-seed'];
    if (originalSeed !== undefined && level_seed !== originalSeed) {
        const confirmed = confirm(
            "⚠️ WARNING: Changing the seed will permanently delete the server's existing world folders (" +
            level_name + ", " + level_name + "_nether, " + level_name + "_the_end) to let Minecraft generate a brand new world.\n\n" +
            "This action is completely permanent and cannot be undone!\n\n" +
            "Do you want to proceed and delete the world folders?"
        );
        if (!confirmed) return;
    }
    
    // Gather Voice Chat settings if container is visible
    let voicechatPayload = null;
    const vcContainer = document.getElementById('quick-settings-voicechat-container');
    if (vcContainer.style.display === 'block') {
        voicechatPayload = {};
        const keys = ["port", "max_voice_distance", "whisper_distance", "enable_groups", "allow_recording", "spectator_interaction", "spectator_player_possession", "broadcast_range"];
        keys.forEach(key => {
            const el = document.getElementById(`qs-vc-${key}`);
            if (el) {
                if (el.type === 'checkbox') {
                    voicechatPayload[key] = el.checked;
                } else if (el.type === 'number') {
                    voicechatPayload[key] = parseFloat(el.value);
                } else {
                    voicechatPayload[key] = el.value;
                }
            }
        });
    }
    
    const saveBtn = document.getElementById('btn-save-quick-settings');
    const originalText = saveBtn.textContent;
    saveBtn.textContent = 'Saving...';
    saveBtn.disabled = true;
    
    try {
        const payload = {
            server_port,
            motd,
            max_players,
            difficulty,
            gamemode,
            hardcore,
            white_list,
            online_mode,
            level_name,
            level_seed,
            level_type,
            spawn_protection,
            view_distance,
            simulation_distance,
            enable_rcon,
            rcon_port,
            rcon_password,
            voicechat: voicechatPayload
        };
        await apiFetch(`/api/server/${activeQuickSettingsServer}/quick-settings`, 'PUT', payload);
        showToast('Quick Settings updated successfully!', 'success');
        hideQuickSettingsModal();
        
        // Refresh server lists
        if (typeof loadServers === 'function') {
            loadServers();
        }
    } catch (err) {
        showToast(`Failed to save Quick Settings: ${err}`, 'error');
    } finally {
        saveBtn.textContent = originalText;
        saveBtn.disabled = false;
    }
}

// --- Server Logs Modal Controller ---
async function showServerLogsModal(name) {
    activeLogsServer = name;
    activeLogsFilename = null;
    
    document.getElementById('server-logs-title-name').textContent = name;
    document.getElementById('active-log-filename-label').textContent = "No log selected";
    document.getElementById('server-logs-viewer-pre').textContent = "Select a log file on the left to read its contents.";
    
    document.getElementById('server-logs-modal-overlay').classList.add('is-visible');
    await loadServerLogsList();
}

function hideServerLogsModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('server-logs-modal-overlay').classList.remove('is-visible');
    activeLogsServer = null;
    activeLogsFilename = null;
}

async function loadServerLogsList() {
    try {
        const data = await apiFetch(`/api/server/${activeLogsServer}/logs`);
        renderServerLogsList(data.logs || []);
    } catch (err) {
        showToast(`Failed to load logs list: ${err.message}`, 'error');
    }
}

function renderServerLogsList(logs) {
    const listContainer = document.getElementById('logs-file-list-container');
    listContainer.innerHTML = '';
    
    if (logs.length === 0) {
        listContainer.innerHTML = `
            <div style="padding: var(--space-lg); text-align: center; color: var(--text-muted); font-size: 0.775rem;">
                No log files found in logs/ directory
            </div>
        `;
        return;
    }
    
    logs.forEach(log => {
        const itemEl = document.createElement('div');
        itemEl.className = 'log-file-item';
        if (activeLogsFilename === log.name) {
            itemEl.classList.add('is-active');
        }
        
        const dateStr = new Date(log.mtime * 1000).toLocaleString();
        const sizeStr = formatBytes(log.size);
        
        itemEl.innerHTML = `
            <span class="log-file-name">${escapeHtml(log.name)}</span>
            <div class="log-file-meta">
                <span>${sizeStr}</span>
                <span>${dateStr}</span>
            </div>
        `;
        
        itemEl.onclick = async () => {
            document.querySelectorAll('.log-file-item').forEach(el => el.classList.remove('is-active'));
            itemEl.classList.add('is-active');
            await viewSpecificServerLog(log.name, log.path);
        };
        
        listContainer.appendChild(itemEl);
    });
}

async function viewSpecificServerLog(name, path) {
    activeLogsFilename = name;
    document.getElementById('active-log-filename-label').textContent = `logs/${name}`;
    const preEl = document.getElementById('server-logs-viewer-pre');
    preEl.textContent = "Loading log content...";
    
    try {
        const data = await apiFetch(`/api/server/${activeLogsServer}/file?path=${encodeURIComponent(path)}`);
        
        preEl.textContent = data.content || "";
        
        // Wait for rendering to complete so scrollHeight is accurate, then scroll to bottom
        setTimeout(() => {
            const container = document.querySelector('.logs-view-container');
            if (container) {
                container.scrollTop = container.scrollHeight;
            }
            preEl.scrollTop = preEl.scrollHeight;
        }, 50);
        
    } catch (err) {
        preEl.textContent = `Error loading log: ${err.message}`;
        showToast(`Failed to load log file: ${err.message}`, 'error');
    }
}

// ============================================================================
// Firewall & Voice Chat Integration Controller
// ============================================================================
let activeFirewallServer = null;
let firewallServerPort = 25565;
let isExternalPortLocked = true;

function updateExternalPortLockUI() {
    const btn = document.getElementById('btn-lock-external-port');
    const input = document.getElementById('rule-external-port');
    const protocol = document.getElementById('rule-protocol').value;
    
    if (protocol === 'UDP') {
        btn.style.display = 'none';
        return;
    }
    
    btn.style.display = 'flex';
    
    if (isExternalPortLocked) {
        btn.classList.add('active');
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
        `;
        btn.title = "Unlock external port to customize";
        
        input.disabled = true;
        input.value = document.getElementById('rule-internal-port').value || '';
        input.placeholder = 'Same as internal port';
    } else {
        btn.classList.remove('active');
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 9.9-1"></path></svg>
        `;
        btn.title = "Lock external port to match internal port";
        
        const label = document.getElementById('rule-label').value;
        const isVoiceChatRule = label && label.toLowerCase().includes('simple voice chat');
        if (isVoiceChatRule) {
            input.disabled = true;
        } else {
            input.disabled = false;
            input.placeholder = 'e.g. 8080 (leave blank to match internal)';
        }
    }
}

function toggleExternalPortLock(forceState) {
    if (forceState !== undefined) {
        isExternalPortLocked = forceState;
    } else {
        isExternalPortLocked = !isExternalPortLocked;
    }
    updateExternalPortLockUI();
}

function handleInternalPortInput() {
    if (isExternalPortLocked && document.getElementById('rule-protocol').value === 'TCP') {
        const internalVal = document.getElementById('rule-internal-port').value;
        document.getElementById('rule-external-port').value = internalVal;
    }
}


function triggerSettingsFirewall() {
    if (!activeSettingsServer) return;
    const name = activeSettingsServer;
    hideServerSettingsModal();
    setTimeout(() => {
        showFirewallModal(name);
    }, 200);
}

async function showFirewallModal(name) {
    activeFirewallServer = name;
    document.getElementById('firewall-server-name').textContent = name;
    
    // Check permissions
    const currentServer = servers.find(s => s.name === name);
    const perms = currentServer ? currentServer.permissions : {};
    const canWrite = !!perms.can_write_firewall;
    
    const toggleBtn = document.getElementById('btn-toggle-add-rule');
    if (toggleBtn) {
        toggleBtn.style.display = canWrite ? 'inline-flex' : 'none';
    }
    
    const applyBtn = document.getElementById('btn-apply-firewall');
    if (applyBtn) {
        applyBtn.style.display = canWrite ? 'inline-block' : 'none';
    }
    
    document.getElementById('firewall-modal-overlay').classList.add('is-visible');
    toggleAddRuleForm(false);
    await loadFirewallRules();
}

function hideFirewallModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('firewall-modal-overlay').classList.remove('is-visible');
    activeFirewallServer = null;
}

function toggleAddRuleForm(show) {
    const container = document.getElementById('add-rule-form-container');
    const toggleBtn = document.getElementById('btn-toggle-add-rule');
    
    if (show === undefined) {
        show = container.style.display === 'none';
    }
    
    // Always enable inputs when toggled/reset
    document.getElementById('rule-protocol').disabled = false;
    document.getElementById('rule-internal-port').disabled = false;
    document.getElementById('rule-external-port').disabled = false;
    document.getElementById('rule-label').disabled = false;
    
    if (show) {
        container.style.display = 'block';
        toggleBtn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            <span>Hide Form</span>
        `;
        document.getElementById('add-rule-form').reset();
        document.getElementById('edit-rule-id').value = '';
        document.getElementById('btn-save-rule').textContent = 'Add Rule';
        
        isExternalPortLocked = true;
        handleRuleProtocolChange();
    } else {
        container.style.display = 'none';
        toggleBtn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
            <span>Add Rule</span>
        `;
    }
}

function handleRuleProtocolChange() {
    const protocol = document.getElementById('rule-protocol').value;
    const externalInput = document.getElementById('rule-external-port');
    const externalLabel = document.getElementById('rule-external-label');
    const hint = document.getElementById('rule-external-hint');
    
    // External port is optional for TCP (defaults to matching internal port) and auto-assigned for UDP
    externalInput.required = false;
    
    if (protocol === 'UDP') {
        externalInput.disabled = true;
        externalInput.value = '';
        externalInput.placeholder = 'Auto-assigned (23000-23999)';
        hint.style.display = 'block';
        document.getElementById('btn-lock-external-port').style.display = 'none';
    } else {
        hint.style.display = 'none';
        document.getElementById('btn-lock-external-port').style.display = 'flex';
        updateExternalPortLockUI();
    }
}

async function loadFirewallRules() {
    if (!activeFirewallServer) return;
    try {
        const data = await apiFetch(`/api/server/${activeFirewallServer}/firewall`);
        firewallServerPort = data.server_port || 25565;
        renderFirewallRules(data.rules || []);
        
        // Hide simple voicechat alert if user lacks write firewall permission
        const currentServer = servers.find(s => s.name === activeFirewallServer);
        const hasWriteFirewall = currentServer && currentServer.permissions ? currentServer.permissions.can_write_firewall : true;
        if (hasWriteFirewall) {
            renderVoiceChatAlert(data.voicechat, data.rules || []);
        } else {
            const alertBox = document.getElementById('voicechat-detect-alert');
            if (alertBox) alertBox.style.display = 'none';
        }
    } catch (err) {
        showToast(`Failed to load firewall rules: ${err.message}`, 'error');
    }
}

function renderFirewallRules(rules) {
    const tbody = document.getElementById('firewall-rules-tbody');
    const emptyState = document.getElementById('firewall-rules-empty');
    tbody.innerHTML = '';
    
    if (rules.length === 0) {
        emptyState.style.display = 'block';
        return;
    }
    emptyState.style.display = 'none';
    
    const currentServer = servers.find(s => s.name === activeFirewallServer);
    const hasWriteFirewall = currentServer && currentServer.permissions ? currentServer.permissions.can_write_firewall : true;
    
    rules.forEach(rule => {
        const tr = document.createElement('tr');
        const protoBadge = rule.protocol === 'TCP' ? 'badge-proto--tcp' : 'badge-proto--udp';
        const labelHtml = rule.label ? escapeHtml(rule.label) : '<span style="color: var(--text-muted); font-style: italic;">No description</span>';
        
        // Escape whole rule object securely for inline onclick usage
        const ruleEscaped = escapeAttr(JSON.stringify(rule));
        
        // Prevent deleting the primary server game port rule
        const isPrimaryPortRule = (rule.protocol === 'TCP' && rule.internal_port === firewallServerPort) || rule.label === 'Primary Game Port';
        
        let actionsHtml = '';
        if (hasWriteFirewall) {
            const deleteBtnHtml = isPrimaryPortRule
                ? `<button class="btn btn-icon btn-sm" disabled style="opacity: 0.35; cursor: not-allowed;" title="Primary Game Port (Cannot delete)">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--text-muted);"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
                   </button>`
                : `<button class="btn btn-icon btn-sm" onclick="deleteRule(${rule.id})" title="Delete Rule">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--red);"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                   </button>`;
                   
            actionsHtml = `
                <button class="btn btn-icon btn-sm" onclick="editRule('${ruleEscaped}')" title="Edit Rule">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                </button>
                ${deleteBtnHtml}
            `;
        } else {
            actionsHtml = `<span style="color: var(--text-muted); font-size: 0.75rem;">Read-only</span>`;
        }
        
        tr.innerHTML = `
            <td><span class="badge-proto ${protoBadge}">${rule.protocol}</span></td>
            <td><strong>${rule.internal_port}</strong></td>
            <td><strong>${rule.external_port || '—'}</strong></td>
            <td>${labelHtml}</td>
            <td style="text-align: center;">
                <label class="toggle-switch">
                    <input type="checkbox" ${rule.enabled ? 'checked' : ''} ${hasWriteFirewall ? '' : 'disabled'} onchange="toggleRuleEnabled(${rule.id}, ${rule.enabled})">
                    <span class="toggle-slider"></span>
                </label>
            </td>
            <td style="text-align: right;">
                ${actionsHtml}
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function renderVoiceChatAlert(voicechat, rules) {
    const alertBox = document.getElementById('voicechat-detect-alert');
    if (!voicechat || !voicechat.detected) {
        alertBox.style.display = 'none';
        return;
    }
    
    const internalPort = voicechat.current_port || 24454;
    const ruleExists = rules.some(r => r.protocol === 'UDP' && (r.label.toLowerCase().includes('voice') || r.internal_port === internalPort));
    
    if (ruleExists) {
        alertBox.style.display = 'none';
    } else {
        alertBox.style.display = 'flex';
    }
}

async function quickAddVoiceChat() {
    if (!activeFirewallServer) return;
    try {
        showToast('Adding Voice Chat firewall rule...', 'info');
        await apiFetch(`/api/server/${activeFirewallServer}/firewall/quick-add-voicechat`, 'POST');
        showToast('Voice Chat rule added successfully!', 'success');
        await loadFirewallRules();
    } catch (err) {
        showToast(`Failed to add Voice Chat rule: ${err.message}`, 'error');
    }
}

function editRule(ruleJsonEscaped) {
    // Unescape and parse the JSON string
    const txt = document.createElement('textarea');
    txt.innerHTML = ruleJsonEscaped;
    const rule = JSON.parse(txt.value);
    
    toggleAddRuleForm(true);
    document.getElementById('edit-rule-id').value = rule.id;
    document.getElementById('rule-protocol').value = rule.protocol;
    document.getElementById('rule-internal-port').value = rule.internal_port;
    document.getElementById('rule-external-port').value = rule.external_port || '';
    document.getElementById('rule-label').value = rule.label;
    document.getElementById('btn-save-rule').textContent = 'Update Rule';
    
    // Infer and set lock state
    const isLocked = !rule.external_port || (parseInt(rule.external_port) === parseInt(rule.internal_port));
    toggleExternalPortLock(isLocked);
    
    handleRuleProtocolChange();
    
    // Prevent modifying the internal port, protocol, or label for the primary server game port rule
    const isPrimaryPortRule = (rule.protocol === 'TCP' && rule.internal_port === firewallServerPort) || rule.label === 'Primary Game Port';
    const isVoiceChatRule = rule.label && rule.label.toLowerCase() === 'simple voice chat';
    if (isPrimaryPortRule) {
        document.getElementById('rule-protocol').disabled = true;
        document.getElementById('rule-internal-port').disabled = true;
        document.getElementById('rule-label').disabled = true; // Description is locked to "Primary Game Port"
        showToast('Primary Game Port rule cannot have its internal port, protocol, or description modified.', 'info');
        updateExternalPortLockUI();
    } else if (isVoiceChatRule) {
        document.getElementById('rule-protocol').disabled = true;
        document.getElementById('rule-internal-port').disabled = true; // Locked, loaded from properties!
        document.getElementById('rule-external-port').disabled = true; // Locked/fixed for UDP voice chat
        document.getElementById('rule-label').disabled = true; // Locked to "Simple Voice Chat"
        showToast('Simple Voice Chat rule cannot have its ports, protocol, or description modified.', 'info');
    } else {
        if (rule.protocol === 'UDP') {
            document.getElementById('rule-external-port').disabled = true;
        }
    }
}

async function saveFirewallRule(e) {
    e.preventDefault();
    if (!activeFirewallServer) return;
    
    const ruleId = document.getElementById('edit-rule-id').value;
    // Protocol, internal_port and external_port might be disabled for primary rule edits,
    // so read their values correctly even if disabled by directly accessing the value
    const protocol = document.getElementById('rule-protocol').value;
    const internal_port = parseInt(document.getElementById('rule-internal-port').value);
    const externalVal = document.getElementById('rule-external-port').value;
    
    // Fall back to matching internal port if left blank or locked for TCP
    const external_port = (protocol === 'TCP' && isExternalPortLocked) ? internal_port : (externalVal ? parseInt(externalVal) : (protocol === 'TCP' ? internal_port : null));
    const label = document.getElementById('rule-label').value;
    
    const payload = {
        protocol,
        enabled: true,
        internal_port,
        external_port,
        label
    };
    
    try {
        if (ruleId) {
            await apiFetch(`/api/server/${activeFirewallServer}/firewall/rule/${ruleId}`, 'PUT', payload);
            showToast('Firewall rule updated successfully!', 'success');
        } else {
            await apiFetch(`/api/server/${activeFirewallServer}/firewall/rule`, 'POST', payload);
            showToast('Firewall rule created successfully!', 'success');
        }
        toggleAddRuleForm(false);
        await loadFirewallRules();
    } catch (err) {
        showToast(`Failed to save firewall rule: ${err.message}`, 'error');
    }
}

async function toggleRuleEnabled(ruleId, currentStatus) {
    if (!activeFirewallServer) return;
    try {
        const data = await apiFetch(`/api/server/${activeFirewallServer}/firewall`);
        const rule = data.rules.find(r => r.id === ruleId);
        if (!rule) return;
        
        const payload = {
            enabled: !currentStatus,
            internal_port: rule.internal_port,
            external_port: rule.external_port,
            label: rule.label
        };
        
        await apiFetch(`/api/server/${activeFirewallServer}/firewall/rule/${ruleId}`, 'PUT', payload);
        showToast(`Rule ${payload.enabled ? 'enabled' : 'disabled'} successfully!`, 'success');
        await loadFirewallRules();
    } catch (err) {
        showToast(`Failed to toggle rule: ${err.message}`, 'error');
        await loadFirewallRules();
    }
}

async function deleteRule(ruleId) {
    if (!activeFirewallServer) return;
    if (!confirm('Are you sure you want to delete this firewall rule?')) return;
    
    try {
        await apiFetch(`/api/server/${activeFirewallServer}/firewall/rule/${ruleId}`, 'DELETE');
        showToast('Firewall rule deleted successfully!', 'success');
        await loadFirewallRules();
    } catch (err) {
        showToast(`Failed to delete firewall rule: ${err.message}`, 'error');
    }
}

async function confirmApplyFirewall() {
    if (!activeFirewallServer) return;
    
    // Check if the server is running by querying its current status
    let isRunning = false;
    try {
        const srvInfo = await apiFetch(`/api/server/${activeFirewallServer}`);
        isRunning = srvInfo && srvInfo.status === 'running';
    } catch (e) {
        // Fallback to locally cached servers array
        const srv = servers.find(s => s.name === activeFirewallServer);
        isRunning = srv && srv.status === 'running';
    }
    
    let warningMsg = 'Apply changes now?\n\n';
    if (isRunning) {
        warningMsg += 'WARNING: This server is currently RUNNING. Applying changes will stop, recreate, and restart the container, which will disconnect all players.';
    } else {
        warningMsg += 'Applying changes will recreate the Docker container setup with the new ports. It will apply on the next server start.';
    }
    
    if (!confirm(warningMsg)) return;
    
    const btn = document.getElementById('btn-apply-firewall');
    const oldText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Applying...';
    
    try {
        showToast('Applying firewall rules and recreating container...', 'info');
        const res = await apiFetch(`/api/server/${activeFirewallServer}/firewall/apply`, 'POST');
        showToast(res.message || 'Firewall rules applied successfully!', 'success');
        hideFirewallModal();
    } catch (err) {
        showToast(`Failed to apply changes: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = oldText;
    }
}

// --- User Rollout Menu & Settings Modals ---
function toggleUserMenu(e) {
    if (e) e.stopPropagation();
    const menu = document.getElementById('user-dropdown-menu');
    menu.classList.toggle('is-visible');
}

// Click outside dropdown to close it
document.addEventListener('click', (e) => {
    const menu = document.getElementById('user-dropdown-menu');
    const trigger = document.getElementById('user-menu-trigger');
    if (menu && menu.classList.contains('is-visible')) {
        const isClickInsideMenu = menu.contains(e.target);
        const isClickInsideTrigger = trigger && trigger.contains(e.target);
        if (!isClickInsideMenu && !isClickInsideTrigger) {
            menu.classList.remove('is-visible');
        }
    }
});

function openUserSettingsModal() {
    // Hide rollout menu first
    const menu = document.getElementById('user-dropdown-menu');
    if (menu) menu.classList.remove('is-visible');

    document.getElementById('user-settings-modal-overlay').classList.add('is-visible');
    switchUserTab('user-tab-account');
}

function closeUserSettingsModal() {
    document.getElementById('user-settings-modal-overlay').classList.remove('is-visible');
}

function openAdminSettingsModal() {
    // Hide rollout menu first
    const menu = document.getElementById('user-dropdown-menu');
    if (menu) menu.classList.remove('is-visible');

    document.getElementById('admin-settings-modal-overlay').classList.add('is-visible');
    switchAdminTab('admin-tab-users');
}

function closeAdminSettingsModal() {
    document.getElementById('admin-settings-modal-overlay').classList.remove('is-visible');
}

function switchUserTab(tabId) {
    document.querySelectorAll('#user-settings-modal-overlay .settings-content-pane').forEach(el => {
        el.classList.remove('is-active');
    });
    document.querySelectorAll('#user-settings-modal-overlay .settings-sidebar-btn').forEach(el => {
        el.classList.remove('is-active');
    });

    const targetPane = document.getElementById(tabId + '-pane');
    const targetBtn = document.getElementById(tabId + '-btn');
    if (targetPane) targetPane.classList.add('is-active');
    if (targetBtn) targetBtn.classList.add('is-active');
}

function switchAdminTab(tabId) {
    document.querySelectorAll('#admin-settings-modal-overlay .settings-content-pane').forEach(el => {
        el.classList.remove('is-active');
    });
    document.querySelectorAll('#admin-settings-modal-overlay .settings-sidebar-btn').forEach(el => {
        el.classList.remove('is-active');
    });

    const targetPane = document.getElementById(tabId + '-pane');
    const targetBtn = document.getElementById(tabId + '-btn');
    if (targetPane) targetPane.classList.add('is-active');
    if (targetBtn) targetBtn.classList.add('is-active');

    if (tabId === 'admin-tab-users') {
        loadUsersList();
    } else if (tabId === 'admin-tab-proxy') {
        loadProxySettingsView();
    } else if (tabId === 'admin-tab-system') {
        loadSystemHttpsSettings();
    }
}

async function submitChangePassword(e) {
    e.preventDefault();
    const currentPass = document.getElementById('change-pwd-current').value;
    const newPass = document.getElementById('change-pwd-new').value;
    const confirmPass = document.getElementById('change-pwd-confirm').value;

    if (newPass !== confirmPass) {
        showToast("New passwords do not match", "error");
        return;
    }

    const btn = document.getElementById('btn-submit-change-pwd');
    btn.disabled = true;
    const oldText = btn.textContent;
    btn.textContent = 'Updating...';

    try {
        await apiFetch('/api/user/change-password', 'POST', {
            current_password: currentPass,
            new_password: newPass
        });
        showToast("Password updated successfully!", "success");
        document.getElementById('change-password-form').reset();
    } catch (err) {
        showToast(`Failed to update password: ${err.message}`, "error");
    } finally {
        btn.disabled = false;
        btn.textContent = oldText;
    }
}

async function loadProxySettingsView() {
    await loadProxyStatus();
    await loadProxyRoutesSettings();
}

async function loadProxyRoutesSettings() {
    const list = document.getElementById('proxy-routes-list-settings');
    if (!list) return;

    try {
        const data = await apiFetch('/api/proxy/routes');
        const routes = data.routes || [];

        if (routes.length === 0) {
            list.innerHTML = `
                <div class="empty-state" style="padding: var(--space-xl) 0;">
                    <p style="font-size: 0.9rem; color: var(--text-muted);">No active proxy routes found.</p>
                </div>
            `;
            return;
        }

        list.innerHTML = routes.map((r, i) => `
            <div class="route-card" style="margin-bottom: var(--space-md); padding: var(--space-md); border: 1px solid var(--border-default); border-radius: var(--radius-md); background: rgba(255,255,255,0.01);">
                <div class="route-header" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-sm); border-bottom: 1px solid var(--border-subtle); padding-bottom: 6px;">
                    <span class="route-file" style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--accent-hover); font-weight: 500;">${escapeHtml(r.file)}</span>
                    <span class="card-status-badge badge-running" style="font-size: 0.6rem; padding: 2px 8px;">
                        <span class="badge-dot"></span>
                        active
                    </span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: var(--space-sm);">
                    <div>
                        <span class="detail-label" style="font-size: 0.65rem; color: var(--text-muted); display: block;">Domain</span>
                        <span class="detail-value" style="font-size: 0.8rem; font-family: var(--font-mono); color: var(--text-primary);">${escapeHtml(r.domain)}</span>
                    </div>
                    <div>
                        <span class="detail-label" style="font-size: 0.65rem; color: var(--text-muted); display: block;">Backend Address</span>
                        <span class="detail-value" style="font-size: 0.8rem; font-family: var(--font-mono); color: var(--accent-hover);">${escapeHtml(r.address)}</span>
                    </div>
                </div>
                <details>
                    <summary style="font-size: 0.725rem; color: var(--text-muted); cursor: pointer; user-select: none;">Show Raw Config</summary>
                    <pre style="margin-top: 6px; padding: 8px; background: var(--bg-primary); border: 1px solid var(--border-default); border-radius: var(--radius-sm); font-family: var(--font-mono); font-size: 0.7rem; color: var(--text-secondary); max-height: 120px; overflow-y: auto; white-space: pre-wrap;"><code>${escapeHtml(r.content)}</code></pre>
                </details>
            </div>
        `).join('');
    } catch (err) {
        console.error('Failed to load proxy routes:', err);
        list.innerHTML = `<div style="color: var(--red); font-size: 0.8rem;">Failed to load proxy routes: ${escapeHtml(err.message)}</div>`;
    }
}

async function reloadInfraredConfigSettings() {
    const btn = document.getElementById('btn-reload-proxy-settings');
    if (!btn) return;
    btn.disabled = true;
    const oldHtml = btn.innerHTML;
    btn.innerHTML = '<span class="spinner"></span> Reloading...';
    try {
        showToast('Reloading Infrared proxy configuration...', 'info');
        const data = await apiFetch('/api/proxy/reload', 'POST');
        showToast(data.message || 'Config reloaded successfully!', 'success');
        await loadProxyRoutesSettings();
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = oldHtml;
    }
}

// Redirect old users modal triggers to the admin settings modal
function showUsersModal() {
    openAdminSettingsModal();
}

function hideUsersModal() {
    closeAdminSettingsModal();
}

let sysHttpsPollingTimeout = null;

async function loadSystemHttpsSettings() {
    // Clear any active polling timeout to avoid multiples
    if (sysHttpsPollingTimeout) {
        clearTimeout(sysHttpsPollingTimeout);
        sysHttpsPollingTimeout = null;
    }

    // Ensure we are currently in the System Configuration tab to avoid background polling loops
    const activeTab = document.getElementById('admin-tab-system-pane');
    if (!activeTab || !activeTab.classList.contains('is-active')) return;

    try {
        const data = await apiFetch('/api/system/https');
        
        const enabledCheckbox = document.getElementById('sys-https-enabled');
        const domainInput = document.getElementById('sys-https-domain');
        const statusContainer = document.getElementById('sys-https-status-container');
        const statusBadge = document.getElementById('sys-https-status-badge');
        const statusText = document.getElementById('sys-https-status-text');
        const statusDetail = document.getElementById('sys-https-status-detail');

        const isEnabled = data.status === 'enabling' || data.status === 'enabled';
        enabledCheckbox.checked = isEnabled;
        domainInput.value = data.domain || '';

        // Display status details
        if (data.status === 'disabled') {
            statusContainer.style.display = 'none';
        } else {
            statusContainer.style.display = 'block';
            statusBadge.className = 'card-status-badge';
            
            if (data.status === 'enabling') {
                statusBadge.classList.add('badge-unknown'); // Yellow dot
                statusText.textContent = 'Acquiring SSL Certificate...';
                statusDetail.innerHTML = '<span class="spinner" style="display:inline-block; vertical-align:middle; margin-right:6px;"></span>Let\'s Encrypt verification is currently running. Nginx is starting and verifying domain ownership. This may take up to a minute...';
                
                // Poll again in 3 seconds to update the UI once certbot finishes
                sysHttpsPollingTimeout = setTimeout(loadSystemHttpsSettings, 3000);
            } else if (data.status === 'enabled') {
                statusBadge.classList.add('badge-running'); // Green dot
                statusText.textContent = 'SSL/TLS Active';
                
                const currentProtocol = window.location.protocol;
                if (currentProtocol === 'http:') {
                    statusDetail.innerHTML = `<strong style="color:var(--green);">HTTPS enabled successfully!</strong> Your server is now secured. Redirecting you to secure HTTPS interface at <a href="https://${data.domain}" style="color:var(--accent-hover); text-decoration:underline;">https://${data.domain}</a> in 3 seconds...`;
                    setTimeout(() => {
                        window.location.href = `https://${data.domain}`;
                    }, 3000);
                } else {
                    statusDetail.innerHTML = `SSL certificate is installed successfully and running. Your connection is fully secure.`;
                }
            } else if (data.status === 'failed') {
                statusBadge.classList.add('badge-stopped'); // Red dot
                statusText.textContent = 'Setup Failed';
                statusDetail.innerHTML = `<span style="color:var(--red); font-weight:600; display:block; margin-bottom:4px;">Error details:</span><pre style="background:var(--bg-primary); border:1px solid var(--border-default); border-radius:4px; padding:6px; color:var(--text-secondary); font-family:var(--font-mono); font-size:0.75rem; white-space:pre-wrap; max-height:150px; overflow-y:auto;">${escapeHtml(data.error)}</pre>`;
            }
        }
    } catch (err) {
        console.error('Failed to load HTTPS settings:', err);
    }
}

async function saveSystemHttpsSettings() {
    const enabled = document.getElementById('sys-https-enabled').checked;
    const domain = document.getElementById('sys-https-domain').value.trim();

    if (enabled && !domain) {
        showToast('Please enter a domain name to enable HTTPS.', 'error');
        return;
    }

    const btn = document.getElementById('btn-save-https-settings');
    btn.disabled = true;
    const oldText = btn.textContent;
    btn.textContent = 'Saving Settings...';

    try {
        showToast('Saving System HTTPS configuration...', 'info');
        const res = await apiFetch('/api/system/https', 'POST', { enabled, domain });
        showToast(res.message || 'Settings saved successfully!', 'success');
        await loadSystemHttpsSettings();
    } catch (err) {
        showToast(`Failed to save settings: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = oldText;
    }
}

// ============================================================================
// Server Sharing Controller
// ============================================================================
let activeSharingServer = null;

function triggerSettingsSharing() {
    if (!activeSettingsServer) return;
    const name = activeSettingsServer;
    hideServerSettingsModal();
    setTimeout(() => {
        showSharingModal(name);
    }, 200);
}

function triggerSettingsFirewall() {
    if (!activeSettingsServer) return;
    const name = activeSettingsServer;
    hideServerSettingsModal();
    setTimeout(() => {
        showFirewallModal(name);
    }, 200);
}

async function showSharingModal(name) {
    activeSharingServer = name;
    document.getElementById('sharing-server-name').textContent = name;
    
    // Reset form
    document.getElementById('share-server-form').reset();
    document.getElementById('share-username').value = '';
    document.getElementById('share-username').disabled = false;
    document.getElementById('btn-share-submit').textContent = 'Share Server';
    
    // Clear checkboxes
    const checkboxes = [
        'share-perm-start',
        'share-perm-stop',
        'share-perm-read-console',
        'share-perm-write-console',
        'share-perm-read-files',
        'share-perm-write-files',
        'share-perm-read-firewall',
        'share-perm-write-firewall'
    ];
    checkboxes.forEach(id => {
        const cb = document.getElementById(id);
        if (cb) cb.checked = false;
    });

    document.getElementById('sharing-modal-overlay').classList.add('is-visible');
    await loadServerShares();
}

function hideSharingModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('sharing-modal-overlay').classList.remove('is-visible');
    activeSharingServer = null;
}

async function loadServerShares() {
    if (!activeSharingServer) return;
    try {
        const data = await apiFetch(`/api/server/${activeSharingServer}/shares`);
        renderSharedUsers(data.shares || []);
    } catch (err) {
        showToast(`Failed to load server shares: ${err.message}`, 'error');
    }
}

function renderSharedUsers(shares) {
    const tbody = document.getElementById('sharing-rules-tbody');
    const emptyState = document.getElementById('sharing-empty-state');
    tbody.innerHTML = '';
    
    if (shares.length === 0) {
        emptyState.style.display = 'block';
        return;
    }
    emptyState.style.display = 'none';
    
    shares.forEach(share => {
        const tr = document.createElement('tr');
        
        // Build badges for active permissions
        const badgeList = [];
        if (share.can_start) badgeList.push('<span class="share-badge share-badge--start">Start</span>');
        if (share.can_stop) badgeList.push('<span class="share-badge share-badge--stop">Stop</span>');
        if (share.can_read_console) badgeList.push('<span class="share-badge share-badge--read-console">Read Console</span>');
        if (share.can_write_console) badgeList.push('<span class="share-badge share-badge--write-console">Send Commands</span>');
        if (share.can_read_files) badgeList.push('<span class="share-badge share-badge--read-files">Read Files</span>');
        if (share.can_write_files) badgeList.push('<span class="share-badge share-badge--write-files">Write Files</span>');
        if (share.can_read_firewall) badgeList.push('<span class="share-badge share-badge--read-firewall">Read Firewall</span>');
        if (share.can_write_firewall) badgeList.push('<span class="share-badge share-badge--write-firewall">Write Firewall</span>');
        
        const badgesHtml = badgeList.length > 0 ? badgeList.join(' ') : '<span style="color: var(--text-muted); font-style: italic;">No permissions</span>';
        
        // Escape share object for editing
        const shareEscaped = escapeAttr(JSON.stringify(share));
        
        tr.innerHTML = `
            <td><strong>${escapeHtml(share.username)}</strong></td>
            <td><div style="display: flex; flex-wrap: wrap; gap: 4px;">${badgesHtml}</div></td>
            <td style="text-align: right; white-space: nowrap;">
                <button class="btn btn-icon btn-sm" onclick="editShare('${shareEscaped}')" title="Edit Permissions">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                </button>
                <button class="btn btn-icon btn-sm" onclick="revokeShare('${escapeAttr(share.username)}')" title="Revoke Share">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--red);"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function editShare(shareJsonEscaped) {
    const txt = document.createElement('textarea');
    txt.innerHTML = shareJsonEscaped;
    const share = JSON.parse(txt.value);
    
    document.getElementById('share-username').value = share.username;
    document.getElementById('share-username').disabled = true;
    document.getElementById('btn-share-submit').textContent = 'Update Share';
    
    document.getElementById('share-perm-start').checked = !!share.can_start;
    document.getElementById('share-perm-stop').checked = !!share.can_stop;
    document.getElementById('share-perm-read-console').checked = !!share.can_read_console;
    document.getElementById('share-perm-write-console').checked = !!share.can_write_console;
    document.getElementById('share-perm-read-files').checked = !!share.can_read_files;
    document.getElementById('share-perm-write-files').checked = !!share.can_write_files;
    document.getElementById('share-perm-read-firewall').checked = !!share.can_read_firewall;
    document.getElementById('share-perm-write-firewall').checked = !!share.can_write_firewall;
}

async function shareServer(e) {
    e.preventDefault();
    if (!activeSharingServer) return;
    
    const username = document.getElementById('share-username').value.trim();
    if (!username) return;
    
    const payload = {
        username: username,
        can_start: document.getElementById('share-perm-start').checked,
        can_stop: document.getElementById('share-perm-stop').checked,
        can_read_console: document.getElementById('share-perm-read-console').checked,
        can_write_console: document.getElementById('share-perm-write-console').checked,
        can_read_files: document.getElementById('share-perm-read-files').checked,
        can_write_files: document.getElementById('share-perm-write-files').checked,
        can_read_firewall: document.getElementById('share-perm-read-firewall').checked,
        can_write_firewall: document.getElementById('share-perm-write-firewall').checked
    };
    
    const btn = document.getElementById('btn-share-submit');
    const oldText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Saving...';
    
    try {
        const res = await apiFetch(`/api/server/${activeSharingServer}/share`, 'POST', payload);
        showToast(res.message || 'Share access updated!', 'success');
        
        // Reset form but keep focus/view
        document.getElementById('share-server-form').reset();
        document.getElementById('share-username').value = '';
        document.getElementById('share-username').disabled = false;
        btn.textContent = 'Share Server';
        
        await loadServerShares();
    } catch (err) {
        showToast(`Failed to update share: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = oldText;
    }
}

async function revokeShare(username) {
    if (!activeSharingServer || !username) return;
    if (!confirm(`Are you sure you want to revoke share access for user '${username}'?`)) {
        return;
    }
    
    try {
        showToast(`Revoking access for ${username}...`, 'info');
        const res = await apiFetch(`/api/server/${activeSharingServer}/share/${username}`, 'DELETE');
        showToast(res.message || 'Access revoked successfully!', 'success');
        await loadServerShares();
    } catch (err) {
        showToast(`Failed to revoke access: ${err.message}`, 'error');
    }
}

