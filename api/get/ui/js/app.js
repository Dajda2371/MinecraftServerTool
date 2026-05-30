/* ============================================================================
   Minecraft Server Manager — Frontend Application
   ============================================================================ */

// --- State ---
let servers = [];
let deleteTargetName = null;
let refreshInterval = null;
let currentUser = null;
let logsPollInterval = null;

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
        const badge = document.getElementById('proxy-status');
        const text = badge.querySelector('.status-text');
        const btn = document.getElementById('btn-proxy-toggle');

        badge.classList.remove('is-running', 'is-stopped');

        if (data.running) {
            badge.classList.add('is-running');
            text.textContent = 'Proxy Running';
            btn.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
                Stop
            `;
        } else {
            badge.classList.add('is-stopped');
            text.textContent = 'Proxy Stopped';
            btn.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                Start
            `;
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
        const statusLabel = status;
        const hostname = srv.hostname || '—';
        const port = srv.port || '—';
        const version = srv.version || '—';
        const type = srv.type || '—';
        const memory = srv.memory_mb || 1024;
        const containerName = srv.container_name || `mc-${srv.name}`;
        const isRunning = status === 'running';

        return `
            <div class="server-card" style="animation-delay: ${i * 0.06}s" id="card-${srv.name}">
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
                        <button class="btn btn-icon" style="opacity: 0.6;" onclick="showHostnameModal('${escapeAttr(srv.name)}', '${escapeAttr(hostname)}')">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                        </button>
                    </div>
                    <div class="detail-item" style="grid-column: span 2; display: flex; flex-direction: row; justify-content: space-between; align-items: center;">
                        <div style="display: flex; flex-direction: column;">
                            <span class="detail-label">RAM Limit</span>
                            <span class="detail-value">${memory} MB</span>
                        </div>
                        <button class="btn btn-icon" style="opacity: 0.6;" onclick="showMemoryModal('${escapeAttr(srv.name)}', ${memory})">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                        </button>
                    </div>
                </div>
                <div class="card-actions">
                    ${status === 'creating'
                        ? `<button class="btn btn-sm btn-ghost" onclick="showCreationLogs('${escapeAttr(srv.name)}')">
                               <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                               Logs
                           </button>
                           <button class="btn btn-sm btn-danger" onclick="cancelServerCreation('${escapeAttr(srv.name)}')">
                               <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                               Cancel
                           </button>`
                        : !srv.eula_agreed
                            ? `<button class="btn btn-sm" style="background: var(--yellow); color: var(--text-inverse); font-weight: 600;" onclick="agreeToEula('${escapeAttr(srv.name)}')">
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                                   Agree to EULA
                               </button>`
                            : isRunning
                                ? `<button class="btn btn-sm btn-warning" onclick="stopServer('${escapeAttr(srv.name)}')">
                                       <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
                                       Stop
                                   </button>`
                                : `<button class="btn btn-sm btn-success" onclick="startServer('${escapeAttr(srv.name)}')">
                                       <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                                       Start
                                   </button>`
                    }
                    ${status !== 'creating'
                        ? `<button class="btn btn-sm btn-ghost" onclick="showDeleteModal('${escapeAttr(srv.name)}')">
                               <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                               Delete
                           </button>`
                        : ''
                    }
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
}

async function createServer(e) {
    e.preventDefault();
    const name = document.getElementById('server-name').value.trim();
    const type = document.getElementById('server-type').value;
    const version = document.getElementById('server-version').value.trim();
    const memory_mb = parseInt(document.getElementById('server-memory').value) || 1024;

    if (!name || !version) {
        showToast('Please fill in all fields', 'error');
        return;
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

// --- Proxy Toggle ---
async function toggleProxy() {
    const badge = document.getElementById('proxy-status');
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
    document.getElementById('logs-server-name').textContent = name;
    const contentArea = document.getElementById('creation-logs-content');
    contentArea.textContent = 'Loading logs...';
    
    document.getElementById('logs-modal-overlay').classList.add('is-visible');
    
    // Poll immediately, then every 1.5 seconds
    const pollLogs = async () => {
        try {
            const data = await apiFetch(`/api/server/${name}/creation-logs`);
            
            // Check if user has closed the modal in the meantime
            if (!document.getElementById('logs-modal-overlay').classList.contains('is-visible')) {
                return;
            }
            
            // Update logs
            const isScrolledToBottom = contentArea.scrollHeight - contentArea.clientHeight <= contentArea.scrollTop + 30;
            contentArea.textContent = data.logs;
            
            // Auto scroll to bottom if it was already at the bottom (or on first load)
            if (isScrolledToBottom || contentArea.textContent === 'Loading logs...') {
                contentArea.scrollTop = contentArea.scrollHeight;
            }
        } catch (err) {
            console.error('Error polling creation logs:', err);
            contentArea.textContent = `Error loading logs: ${err.message}`;
        }
    };
    
    pollLogs();
    logsPollInterval = setInterval(pollLogs, 1500);
}

function hideLogsModal(e) {
    if (e && e.target !== e.currentTarget) return;
    document.getElementById('logs-modal-overlay').classList.remove('is-visible');
    if (logsPollInterval) {
        clearInterval(logsPollInterval);
        logsPollInterval = null;
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
    }
    // Ctrl+N to create server
    if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
        e.preventDefault();
        showCreateModal();
    }
});

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();

    // Auto-refresh every 10 seconds
    refreshInterval = setInterval(() => {
        if (currentUser) {
            loadServers();
            if (currentUser.username === 'admin') {
                loadProxyStatus();
            }
        }
    }, 10000);
});
