/**
 * Notebook page — inicialização e orquestração
 */
window.Notebook = {
    sessionId: null,
    session: null,

    async init() {
        this.sessionId = window.SESSION_ID;
        if (!this.sessionId) return;

        try {
            this.session = await API.getSession(this.sessionId);
            document.getElementById('notebook-title').textContent = this.session.title;
            document.getElementById('chat-welcome-title').textContent = this.session.title;

            // Carrega componentes em paralelo
            await Promise.all([
                Sources.init(this.sessionId),
                Skills.init(this.sessionId),
                Chat.init(this.sessionId),
            ]);
        } catch (e) {
            Utils.toast('Erro ao carregar notebook: ' + e.message, 'error');
        }
    },

    updateSourceCount(count) {
        const el = document.getElementById('chat-source-count');
        const welEl = document.getElementById('chat-welcome-sources');
        if (el) el.textContent = `${count} fonte${count !== 1 ? 's' : ''}`;
        if (welEl) welEl.textContent = `${count} fonte${count !== 1 ? 's' : ''}`;
    }
};

document.addEventListener('DOMContentLoaded', () => Notebook.init());
