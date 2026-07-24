/**
 * Multi external-link chips and custom fields for lesson activity rows.
 */
(function () {
    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function parseNewlineList(value) {
        return String(value || '')
            .replace(/\r\n/g, '\n')
            .replace(/\r/g, '\n')
            .split('\n')
            .map((item) => item.trim())
            .filter(Boolean);
    }

    function serializeNewlineList(items) {
        const seen = new Set();
        const cleaned = [];
        (items || []).forEach((item) => {
            const text = String(item || '').trim();
            if (!text || seen.has(text)) return;
            seen.add(text);
            cleaned.push(text);
        });
        return cleaned.join('\n');
    }

    function parseCustomFields(value) {
        if (!value || !String(value).trim()) return [];
        try {
            const data = JSON.parse(value);
            if (!Array.isArray(data)) return [];
            // Keep blank draft rows in the editor; the server strips empties on save.
            return data
                .filter((item) => item && typeof item === 'object')
                .map((item) => ({
                    label: String(item.label || '').trim(),
                    value: String(item.value || '').trim(),
                }));
        } catch (error) {
            return [];
        }
    }

    function serializeCustomFields(fields) {
        const cleaned = (fields || []).map((item) => ({
            label: String(item.label || '').trim(),
            value: String(item.value || '').trim(),
        }));
        return cleaned.length ? JSON.stringify(cleaned) : '';
    }

    function shortLinkLabel(url) {
        const text = String(url || '').trim();
        if (!text) return '';
        try {
            const parsed = new URL(text);
            return parsed.hostname.replace(/^www\./, '') + (parsed.pathname !== '/' ? parsed.pathname : '');
        } catch (error) {
            return text.length > 48 ? `${text.slice(0, 45)}…` : text;
        }
    }

    function syncLinkGroup(group) {
        if (!group) return;
        const field = group.querySelector('.activity-links-field');
        const chips = group.querySelector('.activity-link-chips');
        if (!field || !chips) return;
        const urls = parseNewlineList(field.value);
        chips.innerHTML = '';
        if (!urls.length) {
            chips.hidden = true;
            return;
        }
        chips.hidden = false;
        urls.forEach((url) => {
            const chip = document.createElement('span');
            chip.className = 'activity-media-chip activity-link-chip';
            chip.innerHTML = `
                <a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(shortLinkLabel(url))}</a>
                <button type="button" class="activity-media-chip-remove" aria-label="Remove link">&times;</button>
            `;
            chip.querySelector('.activity-media-chip-remove').addEventListener('click', () => {
                field.value = serializeNewlineList(parseNewlineList(field.value).filter((item) => item !== url));
                field.dispatchEvent(new Event('change', { bubbles: true }));
                syncLinkGroup(group);
            });
            chips.appendChild(chip);
        });
    }

    function addLinkFromInput(group) {
        const field = group.querySelector('.activity-links-field');
        const input = group.querySelector('.activity-link-input');
        if (!field || !input) return;
        const url = input.value.trim();
        if (!url) {
            input.focus();
            return;
        }
        field.value = serializeNewlineList([...parseNewlineList(field.value), url]);
        field.dispatchEvent(new Event('change', { bubbles: true }));
        input.value = '';
        syncLinkGroup(group);
        input.focus();
    }

    function syncCustomFieldsGroup(group) {
        if (!group) return;
        const field = group.querySelector('.activity-custom-fields-field');
        const list = group.querySelector('.activity-custom-fields-list');
        if (!field || !list) return;

        const fields = parseCustomFields(field.value);
        list.innerHTML = '';
        if (!fields.length) {
            list.hidden = true;
            return;
        }
        list.hidden = false;
        fields.forEach((item, index) => {
            const row = document.createElement('div');
            row.className = 'activity-custom-field-row';
            row.innerHTML = `
                <input type="text" class="activity-custom-label" placeholder="Field label" value="${escapeHtml(item.label)}" aria-label="Custom field label">
                <input type="text" class="activity-custom-value" placeholder="Value" value="${escapeHtml(item.value)}" aria-label="Custom field value">
                <button type="button" class="btn btn-ghost btn-sm activity-custom-remove" aria-label="Remove custom field">&times;</button>
            `;
            const labelInput = row.querySelector('.activity-custom-label');
            const valueInput = row.querySelector('.activity-custom-value');
            const persist = () => {
                const next = parseCustomFields(field.value);
                next[index] = {
                    label: labelInput.value.trim(),
                    value: valueInput.value.trim(),
                };
                field.value = serializeCustomFields(next);
                field.dispatchEvent(new Event('change', { bubbles: true }));
            };
            labelInput.addEventListener('input', persist);
            valueInput.addEventListener('input', persist);
            row.querySelector('.activity-custom-remove').addEventListener('click', () => {
                const next = parseCustomFields(field.value);
                next.splice(index, 1);
                field.value = serializeCustomFields(next);
                field.dispatchEvent(new Event('change', { bubbles: true }));
                syncCustomFieldsGroup(group);
            });
            list.appendChild(row);
        });
    }

    function addCustomField(group, seed = { label: '', value: '' }) {
        const field = group.querySelector('.activity-custom-fields-field');
        if (!field) return;
        const next = parseCustomFields(field.value);
        next.push({
            label: String(seed.label || '').trim(),
            value: String(seed.value || '').trim(),
        });
        field.value = serializeCustomFields(next);
        field.dispatchEvent(new Event('change', { bubbles: true }));
        syncCustomFieldsGroup(group);
        const rows = group.querySelectorAll('.activity-custom-field-row');
        const last = rows[rows.length - 1];
        last?.querySelector('.activity-custom-label')?.focus();
    }

    function syncActivityRow(row) {
        if (!row) return;
        syncLinkGroup(row.querySelector('[data-link-group]'));
        syncCustomFieldsGroup(row.querySelector('[data-custom-fields-group]'));
    }

    function initExisting() {
        document.querySelectorAll('[data-activity-row]').forEach((row) => syncActivityRow(row));
    }

    document.addEventListener('click', (event) => {
        const addLinkBtn = event.target.closest('.btn-add-link');
        if (addLinkBtn) {
            event.preventDefault();
            const group = addLinkBtn.closest('[data-link-group]');
            if (group) addLinkFromInput(group);
            return;
        }
        const addCustomBtn = event.target.closest('.btn-add-custom-field');
        if (addCustomBtn) {
            event.preventDefault();
            const group = addCustomBtn.closest('[data-custom-fields-group]');
            if (group) addCustomField(group);
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter') return;
        const input = event.target.closest('.activity-link-input');
        if (!input) return;
        event.preventDefault();
        const group = input.closest('[data-link-group]');
        if (group) addLinkFromInput(group);
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initExisting);
    } else {
        initExisting();
    }

    window.HomeSchoolActivityExtras = {
        syncLinkGroup,
        syncCustomFieldsGroup,
        syncActivityRow,
        parseNewlineList,
        serializeNewlineList,
        parseCustomFields,
        serializeCustomFields,
        addCustomField,
    };
})();
