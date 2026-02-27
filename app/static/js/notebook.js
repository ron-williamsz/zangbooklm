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

/* ===== Mobile panel switching ===== */
window.MobileNav = {
    init() {
        const tabBar = document.getElementById('mobile-tab-bar');
        if (!tabBar) return;

        tabBar.addEventListener('click', (e) => {
            const tab = e.target.closest('.mobile-tab');
            if (!tab) return;
            this.switchPanel(tab.dataset.panel);
        });

        // Set initial state on mobile
        if (window.matchMedia('(max-width: 768px)').matches) {
            this.switchPanel('panel-chat');
        }

        // Handle resize: restore panels on desktop, reapply on mobile
        window.matchMedia('(max-width: 768px)').addEventListener('change', (e) => {
            const panels = document.querySelectorAll('.notebook-view > .panel');
            if (e.matches) {
                this.switchPanel('panel-chat');
            } else {
                panels.forEach(p => p.classList.remove('mobile-active'));
            }
        });
    },

    switchPanel(panelId) {
        const panels = document.querySelectorAll('.notebook-view > .panel');
        const tabs = document.querySelectorAll('.mobile-tab');

        panels.forEach(p => p.classList.remove('mobile-active'));
        tabs.forEach(t => t.classList.remove('active'));

        const target = document.getElementById(panelId);
        if (target) target.classList.add('mobile-active');

        const activeTab = document.querySelector(`.mobile-tab[data-panel="${panelId}"]`);
        if (activeTab) activeTab.classList.add('active');
    }
};

document.addEventListener('DOMContentLoaded', () => {
    Notebook.init();
    MobileNav.init();
});
