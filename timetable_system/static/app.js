/* ─── Notification Panel ─── */
function toggleNotifPanel() {
    document.getElementById('notifPanel').classList.toggle('open');
    document.getElementById('notifOverlay').classList.toggle('show');
    if (document.getElementById('notifPanel').classList.contains('open')) {
        loadNotifications();
    }
}

function closeNotifPanel() {
    document.getElementById('notifPanel').classList.remove('open');
    document.getElementById('notifOverlay').classList.remove('show');
}

function loadNotifications() {
    fetch('/api/notifications')
        .then(r => r.json())
        .then(data => {
            const list = document.getElementById('notifList');
            list.innerHTML = data.map(n => `
                <div class="notif-item ${n.read ? '' : 'unread'}" onclick="markRead(${n.id})">
                    <div class="notif-title">${n.title}</div>
                    <div class="notif-message">${n.message}</div>
                    <div class="notif-time">${n.created_at || 'recent'}</div>
                </div>
            `).join('') || '<div class="empty-state"><div class="empty-icon">🔔</div><h3>No notifications</h3></div>';
        });
}

function markRead(id) {
    fetch('/api/notifications/read/' + id, { method: 'POST' })
        .then(() => updateNotifCount());
}

function markAllRead() {
    fetch('/api/notifications/read-all', { method: 'POST' })
        .then(() => { loadNotifications(); updateNotifCount(); });
}

function updateNotifCount() {
    fetch('/api/notifications/count')
        .then(r => r.json())
        .then(data => {
            const dot = document.getElementById('notifDot');
            if (dot) dot.style.display = data.count > 0 ? 'block' : 'none';
        });
}

setInterval(updateNotifCount, 30000);

/* ─── Chatbot ─── */
function toggleChatbot() {
    const w = document.getElementById('chatbotWindow');
    const b = document.getElementById('chatbotBtn');
    w.classList.toggle('open');
    b.textContent = w.classList.contains('open') ? '✕' : '💬';
}

function sendChat() {
    const input = document.getElementById('chatInput');
    const query = input.value.trim();
    if (!query) return;

    const msgs = document.getElementById('chatMessages');
    msgs.innerHTML += `<div class="chat-message user">${escapeHtml(query)}</div>`;
    input.value = '';
    msgs.scrollTop = msgs.scrollHeight;

    msgs.innerHTML += `<div class="chat-message bot"><em>Thinking...</em></div>`;
    msgs.scrollTop = msgs.scrollHeight;

    fetch('/api/chatbot', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query})
    })
    .then(r => r.json())
    .then(data => {
        msgs.querySelector('.chat-message.bot:last-child').remove();
        msgs.innerHTML += `<div class="chat-message bot">${escapeHtml(data.response).replace(/\n/g, '<br>')}</div>`;
        msgs.scrollTop = msgs.scrollHeight;
    })
    .catch(() => {
        msgs.querySelector('.chat-message.bot:last-child').remove();
        msgs.innerHTML += `<div class="chat-message bot">Sorry, I couldn't process that. Please try again.</div>`;
    });
}

document.addEventListener('DOMContentLoaded', function() {
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
        chatInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendChat(); });
    }
});

/* ─── Timetable Drag & Drop ─── */
let dragSrc = null;

function initDragDrop() {
    document.querySelectorAll('.timetable-event').forEach(el => {
        el.setAttribute('draggable', 'true');

        el.addEventListener('dragstart', function(e) {
            dragSrc = this;
            this.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', this.dataset.entryId);
        });

        el.addEventListener('dragend', function() {
            this.classList.remove('dragging');
            document.querySelectorAll('.timetable-cell').forEach(c => c.classList.remove('drag-over'));
        });
    });

    document.querySelectorAll('.timetable-cell').forEach(cell => {
        cell.addEventListener('dragover', function(e) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            this.classList.add('drag-over');
        });

        cell.addEventListener('dragleave', function() {
            this.classList.remove('drag-over');
        });

        cell.addEventListener('drop', function(e) {
            e.preventDefault();
            this.classList.remove('drag-over');
            if (!dragSrc) return;

            const entryId = dragSrc.dataset.entryId;
            const day = this.dataset.day;
            const timeSlot = this.dataset.time;

            if (!day || !timeSlot) return;

            const startTime = timeSlot.split('-')[0];
            const endTime = timeSlot.split('-')[1];

            validateAndMove(entryId, day, startTime, endTime, this);
        });
    });
}

function validateAndMove(entryId, day, startTime, endTime, cell) {
    const eventEl = document.querySelector(`.timetable-event[data-entry-id="${entryId}"]`);
    const lecturerId = eventEl ? eventEl.dataset.lecturerId : '';
    const roomId = eventEl ? eventEl.dataset.roomId : '';
    const groupName = eventEl ? eventEl.dataset.group : '';

    fetch('/api/validate-entry', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            id: entryId, day, start_time: startTime, end_time: endTime,
            room_id: parseInt(roomId), lecturer_id: parseInt(lecturerId),
            group_name: groupName, exclude_id: parseInt(entryId)
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.valid) {
            moveEntry(entryId, day, startTime, endTime, cell);
        } else {
            showConflictModal(data.conflicts, () => {
                moveEntry(entryId, day, startTime, endTime, cell);
            });
        }
    });
}

function moveEntry(entryId, day, startTime, endTime, cell) {
    fetch('/api/timetable/update', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: parseInt(entryId), day, start_time: startTime, end_time: endTime})
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'ok') {
            const el = document.querySelector(`.timetable-event[data-entry-id="${entryId}"]`);
            if (el && cell) {
                el.dataset.day = day;
                cell.appendChild(el);
                showToast('Entry moved successfully', 'success');
            }
        }
    });
}

function showConflictModal(conflicts, onForce) {
    const modal = document.getElementById('conflictModal');
    if (!modal) return;
    document.getElementById('conflictList').innerHTML = conflicts.map(c =>
        `<div class="conflict-item conflict-high">⚠️ ${c}</div>`
    ).join('');
    modal.classList.add('show');
    window._onForceMove = onForce;
}

function forceMove() {
    if (window._onForceMove) window._onForceMove();
    document.getElementById('conflictModal').classList.remove('show');
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('show');
}

/* ─── Toast Notifications ─── */
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `alert alert-${type}`;
    toast.style.cssText = 'animation: fadeIn 0.3s ease; margin-bottom: 0.5rem;';
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

/* ─── Search & Filter ─── */
function filterTimetable() {
    const search = (document.getElementById('searchInput')?.value || '').toLowerCase();
    const lecturer = document.getElementById('filterLecturer')?.value || '';
    const room = document.getElementById('filterRoom')?.value || '';
    const group = document.getElementById('filterGroup')?.value || '';
    const course = document.getElementById('filterCourse')?.value || '';

    document.querySelectorAll('.timetable-event, .timetable-row').forEach(row => {
        const text = row.textContent.toLowerCase();
        const rowLecturer = row.dataset.lecturer || '';
        const rowRoom = row.dataset.room || '';
        const rowGroup = row.dataset.group || '';
        const rowCourse = row.dataset.course || '';

        const matchSearch = !search || text.includes(search);
        const matchLecturer = !lecturer || rowLecturer === lecturer;
        const matchRoom = !room || rowRoom === room;
        const matchGroup = !group || rowGroup === group;
        const matchCourse = !course || rowCourse === course;

        row.style.display = (matchSearch && matchLecturer && matchRoom && matchGroup && matchCourse) ? '' : 'none';
    });
}

/* ─── Timetable Generation ─── */
function generateTimetable() {
    const btn = document.getElementById('generateBtn');
    const status = document.getElementById('generateStatus');
    if (!btn) return;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" style="width:16px;height:16px;border-width:2px;"></span> Generating...';
    if (status) { status.style.display = 'none'; }

    fetch('/admin/generate', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (status) {
                status.className = 'alert alert-success';
                status.textContent = `Timetable generated with ${data.count} entries!`;
                status.style.display = 'block';
            }
            showToast(`Generated ${data.count} entries!`, 'success');
            setTimeout(() => location.reload(), 1500);
        })
        .catch(() => {
            if (status) {
                status.className = 'alert alert-error';
                status.textContent = 'Error generating timetable.';
                status.style.display = 'block';
            }
            btn.disabled = false;
            btn.textContent = 'Generate Timetable';
        });
}

/* ─── Charts ─── */
function initCharts(chartData) {
    if (typeof Chart === 'undefined') return;

    const isDark = true;
    const textColor = '#8892a8';
    const gridColor = '#2a3348';

    Chart.defaults.color = textColor;
    Chart.defaults.borderColor = gridColor;

    if (chartData.day_distribution && document.getElementById('dayChart')) {
        new Chart(document.getElementById('dayChart'), {
            type: 'bar',
            data: {
                labels: chartData.days_order,
                datasets: [{
                    label: 'Classes per Day',
                    data: chartData.days_order.map(d => chartData.day_distribution[d] || 0),
                    backgroundColor: ['#4f8cff', '#6c5ce7', '#00d68f', '#ffaa44', '#ff6b6b'],
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, grid: { color: gridColor } },
                    x: { grid: { display: false } }
                }
            }
        });
    }

    if (chartData.lecturer_load && document.getElementById('lecturerChart')) {
        new Chart(document.getElementById('lecturerChart'), {
            type: 'bar',
            data: {
                labels: chartData.lecturer_load.map(l => l.name.split(' ').pop()),
                datasets: [{
                    label: 'Hours/Week',
                    data: chartData.lecturer_load.map(l => l.hours),
                    backgroundColor: '#4f8cff',
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, grid: { color: gridColor } },
                    x: { grid: { display: false } }
                }
            }
        });
    }

    if (chartData.room_usage && document.getElementById('roomChart')) {
        new Chart(document.getElementById('roomChart'), {
            type: 'doughnut',
            data: {
                labels: chartData.room_usage.map(r => r.name),
                datasets: [{
                    data: chartData.room_usage.map(r => r.hours),
                    backgroundColor: ['#4f8cff', '#6c5ce7', '#00d68f', '#ffaa44', '#ff6b6b', '#54a0ff', '#2ecc71', '#e67e22'],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'right', labels: { color: textColor, boxWidth: 12, padding: 12 } }
                }
            }
        });
    }

    if (chartData.level_distribution && document.getElementById('levelChart')) {
        new Chart(document.getElementById('levelChart'), {
            type: 'pie',
            data: {
                labels: ['University-wide', 'Department-wide', 'Single-course'],
                datasets: [{
                    data: [chartData.level_distribution.university || 0,
                           chartData.level_distribution.department || 0,
                           chartData.level_distribution.single || 0],
                    backgroundColor: ['#4f8cff', '#6c5ce7', '#00d68f'],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'right', labels: { color: textColor, boxWidth: 12, padding: 12 } }
                }
            }
        });
    }
}

/* ─── Heatmap ─── */
function initHeatmap(data) {
    if (!data || !data.rooms) return;
    const container = document.getElementById('heatmapBody');
    if (!container) return;

    let html = '';
    data.rooms.forEach(room => {
        html += '<tr>';
        html += `<td class="heatmap-label">${room.name}</td>`;
        data.days.forEach(day => {
            data.slots.forEach(slot => {
                const val = room.data[day]?.[slot] || 0;
                const intensity = Math.min(255, Math.floor(val * 80));
                const color = val > 0 ? `rgb(79, 140, 255, ${Math.min(1, val * 0.3)})` : 'transparent';
                html += `<td class="heatmap-cell" style="background:${color}">${val || ''}</td>`;
            });
        });
        html += '</tr>';
    });
    container.innerHTML = html;
}

/* ─── Live TV ─── */
function toggleLiveTV() {
    const tv = document.getElementById('liveTV');
    if (tv) tv.classList.toggle('active');
}

function closeLiveTV() {
    const tv = document.getElementById('liveTV');
    if (tv) tv.classList.remove('active');
}

/* ─── Export ─── */
function exportICS() {
    window.location.href = '/api/export/ics' + (new URLSearchParams(window.location.search).get('published') ? '?published=1' : '');
}

function exportCSV() {
    window.location.href = '/api/export/csv' + (new URLSearchParams(window.location.search).get('published') ? '?published=1' : '');
}

function shareTimetable() {
    const modal = document.getElementById('shareModal');
    if (!modal) return;
    modal.classList.add('show');
    fetch('/api/share', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            document.getElementById('shareUrl').value = data.url;
        });
}

function copyShareUrl() {
    const input = document.getElementById('shareUrl');
    input.select();
    document.execCommand('copy');
    showToast('Link copied!', 'success');
}

/* ─── Sidebar Toggle ─── */
function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('open');
    document.getElementById('sidebarOverlay')?.classList.toggle('show');
}

/* ─── Tabs ─── */
function switchTab(tabGroup, tabName) {
    document.querySelectorAll(`.${tabGroup}-tab`).forEach(t => t.classList.remove('active'));
    document.querySelectorAll(`.${tabGroup}-content`).forEach(c => c.classList.remove('active'));
    document.querySelector(`.${tabGroup}-tab[data-tab="${tabName}"]`)?.classList.add('active');
    document.getElementById(`${tabGroup}-${tabName}`)?.classList.add('active');
}

/* ─── Utility ─── */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(timeStr) {
    if (!timeStr) return '';
    const [h, m] = timeStr.split(':');
    const hour = parseInt(h);
    const ampm = hour >= 12 ? 'PM' : 'AM';
    const h12 = hour % 12 || 12;
    return `${h12}:${m} ${ampm}`;
}

/* ─── Auto-save Draft ─── */
let autoSaveTimer = null;

function startAutoSave() {
    const entries = [];
    document.querySelectorAll('.timetable-event').forEach(el => {
        entries.push({
            id: parseInt(el.dataset.entryId),
            day: el.dataset.day,
            start_time: el.dataset.startTime,
            end_time: el.dataset.endTime,
            room_id: parseInt(el.dataset.roomId)
        });
    });

    clearTimeout(autoSaveTimer);
    autoSaveTimer = setTimeout(() => {
        fetch('/api/draft/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({entries})
        }).catch(() => {});
    }, 5000);
}

/* ─── Init ─── */
document.addEventListener('DOMContentLoaded', function() {
    initDragDrop();
    updateNotifCount();

    if (document.getElementById('liveTV')) {
        setInterval(() => {
            const tv = document.getElementById('liveTV');
            if (tv && tv.classList.contains('active')) {
                location.reload();
            }
        }, 30000);
    }

    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', filterTimetable);
    }
    ['filterLecturer', 'filterRoom', 'filterGroup', 'filterCourse'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', filterTimetable);
    });
});
