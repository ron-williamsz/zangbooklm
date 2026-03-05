/**
 * Skill Editor — CRUD de skills na área admin
 */
window.SkillEditor = {
    skillId: null,
    skill: null,
    steps: [],
    examples: [],
    saving: false,

    async init() {
        this.skillId = window.SKILL_ID || 0;

        if (this.skillId > 0) {
            await this.loadSkill();
            document.getElementById('page-title').textContent = 'Editar Skill';
            document.getElementById('btn-delete').classList.remove('hidden');
            document.getElementById('btn-export').classList.remove('hidden');
        }
    },

    async loadSkill() {
        try {
            this.skill = await API.getSkill(this.skillId);
            document.getElementById('skill-name').value = this.skill.name;
            document.getElementById('skill-desc').value = this.skill.description;
            document.getElementById('skill-icon').value = this.skill.icon;
            document.getElementById('skill-color').value = this.skill.color;
            document.getElementById('skill-macro').value = this.skill.macro_instruction;

            // Deep-copy para não compartilhar referência com this.skill.steps
            this.steps = (this.skill.steps || []).map(s => ({ ...s }));
            this.examples = this.skill.examples || [];
            this.renderSteps();
            this.renderExamples();
        } catch (e) {
            Utils.toast('Erro ao carregar skill: ' + e.message, 'error');
        }
    },

    renderSteps() {
        const list = document.getElementById('steps-list');
        if (!this.steps.length) {
            list.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem;">Nenhuma etapa adicionada.</p>';
            return;
        }

        list.innerHTML = this.steps.map((step, i) => `
            <div class="step-item" data-id="${step.id || ''}">
                <div class="step-number">${i + 1}</div>
                <div class="step-content">
                    <input type="text" class="input" value="${Utils.escapeHtml(step.title)}"
                           placeholder="Título da etapa" oninput="SkillEditor.updateLocalStep(${i}, 'title', this.value)">
                    <textarea class="input" rows="2" placeholder="Instrução específica para esta etapa"
                              oninput="SkillEditor.updateLocalStep(${i}, 'instruction', this.value)">${Utils.escapeHtml(step.instruction)}</textarea>
                </div>
                <div class="step-actions">
                    <button class="btn-icon btn-ghost btn-danger" onclick="SkillEditor.removeStep(${i})" title="Remover etapa">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
                </div>
            </div>
        `).join('');
    },

    renderExamples() {
        const list = document.getElementById('examples-list');
        if (!this.examples.length) {
            list.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem;">Nenhum arquivo de exemplo.</p>';
            return;
        }

        list.innerHTML = this.examples.map(ex => `
            <div class="example-item">
                <span class="example-icon">📄</span>
                <div class="example-info">
                    <div class="example-name">${Utils.escapeHtml(ex.filename)}</div>
                    <div class="example-desc">${Utils.escapeHtml(ex.description || 'Sem descrição')}</div>
                </div>
                <button class="btn-icon btn-ghost btn-danger" onclick="SkillEditor.removeExample(${ex.id})" title="Remover">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                </button>
            </div>
        `).join('');
    },

    addStep() {
        this.steps.push({ title: '', instruction: '', expected_output: null });
        this.renderSteps();
        // Foca no último
        const inputs = document.querySelectorAll('.step-item:last-child input');
        if (inputs.length) inputs[0].focus();
    },

    updateLocalStep(index, field, value) {
        this.steps[index][field] = value;
    },

    removeStep(index) {
        this.steps.splice(index, 1);
        this.renderSteps();
    },

    async exampleFileSelected(event) {
        const file = event.target.files[0];
        if (!file) return;

        const description = prompt('Descrição do exemplo (o que o LLM deve observar neste arquivo):');
        if (description === null) return;

        if (this.skillId > 0) {
            try {
                await API.uploadExample(this.skillId, file, description);
                Utils.toast('Exemplo adicionado', 'success');
                await this.loadSkill();
            } catch (e) {
                Utils.toast('Erro no upload: ' + e.message, 'error');
            }
        } else {
            Utils.toast('Salve a skill primeiro antes de adicionar exemplos', 'warning');
        }
        event.target.value = '';
    },

    async removeExample(exampleId) {
        if (!confirm('Remover este exemplo?')) return;
        try {
            await API.deleteExample(this.skillId, exampleId);
            Utils.toast('Exemplo removido', 'success');
            await this.loadSkill();
        } catch (e) {
            Utils.toast('Erro: ' + e.message, 'error');
        }
    },

    async save() {
        if (this.saving) return;
        this.saving = true;
        const btn = document.getElementById('btn-save');
        if (btn) btn.disabled = true;

        const data = {
            name: document.getElementById('skill-name').value.trim(),
            description: document.getElementById('skill-desc').value.trim(),
            icon: document.getElementById('skill-icon').value.trim() || '📋',
            color: document.getElementById('skill-color').value,
            macro_instruction: document.getElementById('skill-macro').value.trim(),
        };

        if (!data.name) {
            Utils.toast('Nome é obrigatório', 'warning');
            this.saving = false;
            if (btn) btn.disabled = false;
            return;
        }

        // Coleta valores atuais dos steps direto do DOM (garante dados frescos)
        this._collectStepsFromDOM();

        try {
            let skill;
            if (this.skillId > 0) {
                skill = await API.updateSkill(this.skillId, data);
            } else {
                skill = await API.createSkill(data);
                this.skillId = skill.id;
                window.SKILL_ID = skill.id;
                history.replaceState(null, '', `/admin/skills/${skill.id}`);
                document.getElementById('page-title').textContent = 'Editar Skill';
                document.getElementById('btn-delete').classList.remove('hidden');
                document.getElementById('btn-export').classList.remove('hidden');
            }

            // Salva etapas
            await this.syncSteps(skill.id);

            Utils.toast('Skill salva com sucesso!', 'success');
            await this.loadSkill();
        } catch (e) {
            Utils.toast('Erro ao salvar: ' + e.message, 'error');
        } finally {
            this.saving = false;
            if (btn) btn.disabled = false;
        }
    },

    _collectStepsFromDOM() {
        const stepItems = document.querySelectorAll('.step-item');
        stepItems.forEach((el, i) => {
            if (i < this.steps.length) {
                const titleInput = el.querySelector('input');
                const instrTextarea = el.querySelector('textarea');
                if (titleInput) this.steps[i].title = titleInput.value;
                if (instrTextarea) this.steps[i].instruction = instrTextarea.value;
            }
        });
    },

    async syncSteps(skillId) {
        // Envia todas as etapas de uma vez — backend faz delete + recreate numa única transação
        const steps = this.steps
            .filter(s => s.title.trim())
            .map(s => ({
                title: s.title,
                instruction: s.instruction,
                expected_output: s.expected_output || null,
            }));
        await API.syncSteps(skillId, steps);
    },

    async deleteSkill() {
        if (!confirm('Tem certeza que deseja excluir esta skill?')) return;
        try {
            await API.deleteSkill(this.skillId);
            Utils.toast('Skill excluída', 'success');
            location.href = '/admin/skills';
        } catch (e) {
            Utils.toast('Erro: ' + e.message, 'error');
        }
    },

    exportSkill() {
        if (!this.skillId) return;
        window.location.href = `/api/v1/skills/${this.skillId}/export`;
    }
};

document.addEventListener('DOMContentLoaded', () => SkillEditor.init());
