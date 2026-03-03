/**
 * Skills — cards no painel direito do notebook
 */
window.Skills = {
    sessionId: null,
    skills: [],
    activeSkillId: null,

    async init(sessionId) {
        this.sessionId = sessionId;
        await this.loadSkills();
    },

    async loadSkills() {
        try {
            this.skills = await API.listSkills();
            this.render();
        } catch (e) {
            Utils.toast('Erro ao carregar skills: ' + e.message, 'error');
        }
    },

    render() {
        const grid = document.getElementById('skills-grid');
        const empty = document.getElementById('skills-empty');

        if (!this.skills.length) {
            grid.innerHTML = '';
            empty.classList.remove('hidden');
            return;
        }

        empty.classList.add('hidden');
        grid.innerHTML = this.skills
            .filter(s => s.is_active)
            .map(s => `
                <div class="skill-card ${this.activeSkillId === s.id ? 'active' : ''}"
                     onclick="Skills.toggle(${s.id})"
                     title="${Utils.escapeHtml(s.description)}"
                     style="${this.activeSkillId === s.id ? `border-color: ${s.color}` : ''}">
                    <div class="skill-card-icon">${s.icon}</div>
                    <div class="skill-card-name">${Utils.escapeHtml(s.name)}</div>
                </div>
            `).join('');
    },

    toggle(skillId) {
        if (this.activeSkillId === skillId) {
            this.activeSkillId = null;
            Utils.toast('Skill desativada', 'info');
            this.render();
        } else {
            this.activeSkillId = skillId;
            this.render();
            // Após a execução da skill, limpa activeSkillId para que perguntas
            // de follow-up usem chat livre (sem re-gerar o relatório inteiro)
            Chat.executeSkill(skillId).then(() => {
                this.activeSkillId = null;
                this.render();
            });
        }
    }
};
