/**
 * Dashboard — listagem e criação de notebooks
 */
window.Dashboard = {
    async init() {
        await this.loadNotebooks();
    },

    async loadNotebooks() {
        try {
            const sessions = await API.listSessions();
            const grid = document.getElementById('notebook-grid');
            const empty = document.getElementById('empty-state');

            if (!sessions.length) {
                grid.innerHTML = '';
                empty.classList.remove('hidden');
                return;
            }

            empty.classList.add('hidden');
            grid.innerHTML = sessions.map(s => `
                <div class="notebook-card" onclick="location.href='/notebooks/${s.id}'">
                    <div class="notebook-card-emoji">${Utils.randomEmoji()}</div>
                    <div class="notebook-card-title">${Utils.escapeHtml(s.title)}</div>
                    <div class="notebook-card-meta">
                        <span>${Utils.formatDate(s.created_at)} &middot; ${s.source_count} fontes</span>
                        <button class="btn-icon btn-ghost btn-sm" onclick="event.stopPropagation(); Dashboard.deleteNotebook(${s.id})" title="Excluir">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/>
                            </svg>
                        </button>
                    </div>
                </div>
            `).join('');
        } catch (e) {
            Utils.toast('Erro ao carregar notebooks: ' + e.message, 'error');
        }
    },

    showCreateModal() {
        const modal = document.getElementById('create-modal');
        document.getElementById('notebook-title').value = '';
        modal.showModal();
        document.getElementById('notebook-title').focus();
    },

    async createNotebook() {
        const titleInput = document.getElementById('notebook-title');
        const title = titleInput.value.trim();
        if (!title) {
            Utils.toast('Digite um nome para o notebook', 'warning');
            return;
        }

        try {
            const session = await API.createSession(title);
            document.getElementById('create-modal').close();
            location.href = `/notebooks/${session.id}`;
        } catch (e) {
            Utils.toast('Erro ao criar notebook: ' + e.message, 'error');
        }
    },

    async deleteNotebook(id) {
        if (!confirm('Excluir este notebook?')) return;
        try {
            await API.deleteSession(id);
            Utils.toast('Notebook excluído', 'success');
            await this.loadNotebooks();
        } catch (e) {
            Utils.toast('Erro ao excluir: ' + e.message, 'error');
        }
    }
};

document.addEventListener('DOMContentLoaded', () => Dashboard.init());

// Enter no modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && document.getElementById('create-modal').open) {
        Dashboard.createNotebook();
    }
});
