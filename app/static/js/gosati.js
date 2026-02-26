/**
 * GoSATI — consultas de dados do Zangari
 */
window.GoSati = {
    _lastQuery: null,
    _searchTimer: null,
    _selectedCond: null,

    // --- Autocomplete de condomínios ---

    searchCond(value) {
        clearTimeout(this._searchTimer);
        const list = document.getElementById('gosati-cond-list');

        if (!value || value.length < 2) {
            list.classList.add('hidden');
            return;
        }

        this._searchTimer = setTimeout(async () => {
            try {
                const results = await API.searchCondominios(value);
                if (!results.length) {
                    list.innerHTML = '<div class="autocomplete-empty">Nenhum condomínio encontrado</div>';
                } else {
                    list.innerHTML = results.map(c => `
                        <div class="autocomplete-item" onclick="GoSati.selectCond(${c.codigo}, '${Utils.escapeHtml(c.nome)}')">
                            <span class="ac-code">${c.codigo}</span>
                            <span class="ac-name">${Utils.escapeHtml(c.nome)}</span>
                        </div>
                    `).join('');
                }
                list.classList.remove('hidden');
            } catch (e) {
                list.classList.add('hidden');
            }
        }, 250);
    },

    selectCond(codigo, nome) {
        document.getElementById('gosati-cond').value = codigo;
        document.getElementById('gosati-cond-search').value = `${codigo} — ${nome}`;
        document.getElementById('gosati-cond-list').classList.add('hidden');
        this._selectedCond = { codigo, nome };
    },

    // --- Consultas GoSATI ---

    async query() {
        const btn = document.getElementById('btn-gosati');
        const sessionId = window.SESSION_ID;

        const data = {
            query_type: document.getElementById('gosati-tipo').value,
            condominio: parseInt(document.getElementById('gosati-cond').value) || 0,
            mes: parseInt(document.getElementById('gosati-mes').value),
            ano: parseInt(document.getElementById('gosati-ano').value),
        };

        if (!data.condominio) {
            Utils.toast('Informe o código do condomínio', 'warning');
            return;
        }

        btn.disabled = true;
        btn.textContent = 'Consultando...';

        try {
            const result = await API.queryGoSati(sessionId, data);
            Utils.toast(`Dados carregados: ${result.label}`, 'success');
            this._lastQuery = data;
            await Sources.loadSources();

            // Se prestação de contas, oferece listar comprovantes
            if (data.query_type === 'prestacao_contas') {
                await this.loadComprovantes(sessionId, data);
            } else {
                document.getElementById('comprovantes-section').style.display = 'none';
            }
        } catch (e) {
            Utils.toast('Erro GoSATI: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Consultar GoSATI';
        }
    },

    async loadComprovantes(sessionId, queryData) {
        const section = document.getElementById('comprovantes-section');
        const list = document.getElementById('comprovantes-list');

        try {
            const result = await API.listComprovantes(sessionId, {
                condominio: queryData.condominio,
                mes: queryData.mes,
                ano: queryData.ano,
            });

            if (!result.despesas || result.despesas.length === 0) {
                section.style.display = 'none';
                return;
            }

            list.innerHTML = result.despesas.map(d => `
                <label class="comprovante-item" style="display:flex; align-items:center; gap:8px; padding:4px 0; font-size:12px; color:var(--text-secondary); cursor:pointer;">
                    <input type="checkbox" value="${d.link_docto}" class="comp-check" checked>
                    <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${d.historico}">
                        ${d.historico}
                    </span>
                    <span style="color:var(--text-tertiary); white-space:nowrap;">R$ ${d.valor}</span>
                </label>
            `).join('');

            section.style.display = 'block';
        } catch (e) {
            section.style.display = 'none';
        }
    },

    _initClickOutside: (() => {
        document.addEventListener('click', (e) => {
            const list = document.getElementById('gosati-cond-list');
            const input = document.getElementById('gosati-cond-search');
            if (list && input && !list.contains(e.target) && e.target !== input) {
                list.classList.add('hidden');
            }
        });
    })(),

    async reset() {
        const sessionId = window.SESSION_ID;
        const btn = document.getElementById('btn-gosati-reset');

        if (!confirm('Limpar todos os dados GoSATI e o cache do chat desta sessão?')) return;

        btn.disabled = true;
        try {
            await API.resetGoSati(sessionId);

            // Limpa form
            document.getElementById('gosati-cond').value = '';
            document.getElementById('gosati-cond-search').value = '';
            document.getElementById('comprovantes-section').style.display = 'none';
            this._lastQuery = null;
            this._selectedCond = null;

            // Limpa chat visual
            const chatMessages = document.getElementById('chat-messages');
            if (chatMessages) chatMessages.innerHTML = '';
            const chatWelcome = document.getElementById('chat-welcome');
            if (chatWelcome) chatWelcome.classList.remove('hidden');

            await Sources.loadSources();
            Utils.toast('Dados GoSATI e cache do chat limpos', 'success');
        } catch (e) {
            Utils.toast('Erro ao limpar: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
        }
    },

    async downloadSelected() {
        const sessionId = window.SESSION_ID;
        const btn = document.getElementById('btn-comprovantes');
        const checks = document.querySelectorAll('.comp-check:checked');
        const links = Array.from(checks).map(c => c.value);

        if (links.length === 0) {
            Utils.toast('Selecione ao menos um comprovante', 'warning');
            return;
        }

        btn.disabled = true;
        btn.textContent = 'Baixando...';

        try {
            const result = await API.downloadComprovantes(sessionId, links);
            Utils.toast(`${result.downloaded} comprovante(s) baixado(s)`, 'success');
            await Sources.loadSources();
        } catch (e) {
            Utils.toast('Erro ao baixar: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Baixar Selecionados';
        }
    }
};
