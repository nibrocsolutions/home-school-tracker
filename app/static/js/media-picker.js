/**
 * Lesson media library picker with folder browsing and multi-select.
 * Writes selected /media/... URLs into the activity media attachments field.
 */
(function () {
    const DIALOG_ID = 'media-library-dialog';

    function ensureDialog() {
        let dialog = document.getElementById(DIALOG_ID);
        if (dialog) return dialog;

        dialog = document.createElement('dialog');
        dialog.id = DIALOG_ID;
        dialog.className = 'media-library-dialog';
        dialog.innerHTML = `
            <div class="media-library-panel">
                <header class="media-library-header">
                    <h3>Choose media files</h3>
                    <p class="section-hint">Browse subject folders and select one or more files to attach.</p>
                </header>
                <div id="media-library-folders" class="media-library-folders" aria-label="Media folders"></div>
                <input type="search" id="media-library-filter" class="media-library-filter"
                       placeholder="Search by file or folder name..." autocomplete="off">
                <div id="media-library-list" class="media-library-list" role="listbox" aria-multiselectable="true" aria-label="Media files"></div>
                <p id="media-library-empty" class="empty-state" hidden>
                    No files found. Ask an admin to copy files into a media subfolder (for example media/history/).
                </p>
                <footer class="media-library-footer">
                    <span id="media-library-selected-count" class="media-library-selected-count">0 selected</span>
                    <div class="media-library-footer-actions">
                        <button type="button" class="btn btn-secondary btn-sm" data-media-cancel>Cancel</button>
                        <button type="button" class="btn btn-primary btn-sm" data-media-add>Add selected</button>
                    </div>
                </footer>
            </div>
        `;
        document.body.appendChild(dialog);
        return dialog;
    }

    function kindLabel(kind) {
        if (kind === 'audio') return 'Audio';
        if (kind === 'document') return 'Document';
        if (kind === 'image') return 'Image';
        if (kind === 'video') return 'Video';
        return 'File';
    }

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function displayName(url) {
        if (!url) return '';
        return String(url).replace(/^\/media\//, '');
    }

    function parseAttachments(value) {
        return String(value || '')
            .split(/[\n,]+/)
            .map((item) => item.trim())
            .filter(Boolean);
    }

    function serializeAttachments(urls) {
        const seen = new Set();
        const cleaned = [];
        urls.forEach((url) => {
            const item = String(url || '').trim();
            if (!item || seen.has(item)) return;
            seen.add(item);
            cleaned.push(item);
        });
        return cleaned.join('\n');
    }

    async function loadLibrary({ query, folder }) {
        const params = new URLSearchParams();
        if (query) params.set('q', query);
        if (folder) params.set('folder', folder);
        const response = await fetch(`/api/media-library?${params.toString()}`, {
            headers: { Accept: 'application/json' },
        });
        if (!response.ok) {
            throw new Error('Unable to load media library');
        }
        return response.json();
    }

    function renderFolders(folders, activeFolder, onSelect) {
        const wrap = document.getElementById('media-library-folders');
        if (!wrap) return;
        wrap.innerHTML = '';

        const allBtn = document.createElement('button');
        allBtn.type = 'button';
        allBtn.className = `media-folder-chip${activeFolder ? '' : ' active'}`;
        allBtn.textContent = 'All folders';
        allBtn.addEventListener('click', () => onSelect(''));
        wrap.appendChild(allBtn);

        (folders || []).forEach((folder) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `media-folder-chip${activeFolder === folder.path ? ' active' : ''}`;
            button.textContent = `${folder.name} (${folder.file_count})`;
            button.addEventListener('click', () => onSelect(folder.path));
            wrap.appendChild(button);
        });
    }

    function renderFiles(files, selectedSet, onToggle) {
        const list = document.getElementById('media-library-list');
        const empty = document.getElementById('media-library-empty');
        if (!list || !empty) return;
        list.innerHTML = '';
        if (!files.length) {
            empty.hidden = false;
            return;
        }
        empty.hidden = true;
        files.forEach((file) => {
            const checked = selectedSet.has(file.url);
            const label = document.createElement('label');
            label.className = `media-library-item${checked ? ' selected' : ''}`;
            label.dataset.url = file.url;
            label.innerHTML = `
                <input type="checkbox" ${checked ? 'checked' : ''} aria-label="Select ${escapeHtml(file.name)}">
                <span class="media-library-item-main">
                    <strong>${escapeHtml(file.name)}</strong>
                    <span class="media-library-item-path">${escapeHtml(file.path)}</span>
                </span>
                <span class="media-library-item-meta">
                    <span class="media-kind-tag">${escapeHtml(kindLabel(file.kind))}</span>
                    <span>${escapeHtml(file.size_label || '')}</span>
                </span>
            `;
            const checkbox = label.querySelector('input[type="checkbox"]');
            const applyState = (isSelected) => {
                checkbox.checked = isSelected;
                label.classList.toggle('selected', isSelected);
                onToggle(file.url, isSelected);
            };
            checkbox.addEventListener('change', () => applyState(checkbox.checked));
            list.appendChild(label);
        });
    }

    function updateSelectedCount(count) {
        const el = document.getElementById('media-library-selected-count');
        if (el) {
            el.textContent = `${count} selected`;
        }
    }

    function renderAttachmentChips(group) {
        const field = group.querySelector('.activity-media-field');
        const chips = group.querySelector('.activity-media-chips');
        if (!field || !chips) return;
        const urls = parseAttachments(field.value);
        chips.innerHTML = '';
        if (!urls.length) {
            chips.hidden = true;
            return;
        }
        chips.hidden = false;
        urls.forEach((url) => {
            const chip = document.createElement('span');
            chip.className = 'activity-media-chip';
            chip.innerHTML = `
                <a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(displayName(url))}</a>
                <button type="button" class="activity-media-chip-remove" aria-label="Remove ${escapeHtml(displayName(url))}">&times;</button>
            `;
            chip.querySelector('.activity-media-chip-remove').addEventListener('click', () => {
                const next = parseAttachments(field.value).filter((item) => item !== url);
                field.value = serializeAttachments(next);
                field.dispatchEvent(new Event('change', { bubbles: true }));
                renderAttachmentChips(group);
            });
            chips.appendChild(chip);
        });
    }

    function syncMediaGroup(group) {
        renderAttachmentChips(group);
    }

    async function openMediaPicker(group) {
        if (!group) return;
        const field = group.querySelector('.activity-media-field');
        if (!field) return;

        const dialog = ensureDialog();
        const filter = dialog.querySelector('#media-library-filter');
        const cancelBtn = dialog.querySelector('[data-media-cancel]');
        const addBtn = dialog.querySelector('[data-media-add]');
        const selected = new Set(parseAttachments(field.value));
        let latestQuery = '';
        let activeFolder = '';
        let folderCache = [];

        const refresh = async () => {
            try {
                const data = await loadLibrary({ query: latestQuery, folder: activeFolder || null });
                folderCache = data.folders || folderCache;
                renderFolders(folderCache, activeFolder, (folderPath) => {
                    activeFolder = folderPath;
                    refresh();
                });
                renderFiles(data.files || [], selected, (url, isSelected) => {
                    if (isSelected) selected.add(url);
                    else selected.delete(url);
                    updateSelectedCount(selected.size);
                });
                updateSelectedCount(selected.size);
            } catch (error) {
                renderFiles([], selected, () => {});
                const empty = document.getElementById('media-library-empty');
                if (empty) {
                    empty.hidden = false;
                    empty.textContent = 'Could not load the media library. Try again or check that you are signed in.';
                }
            }
        };

        filter.value = '';
        latestQuery = '';
        activeFolder = '';
        filter.oninput = () => {
            latestQuery = filter.value.trim();
            refresh();
        };

        const onCancel = () => dialog.close('cancel');
        const onAdd = () => {
            field.value = serializeAttachments([...selected]);
            field.dispatchEvent(new Event('input', { bubbles: true }));
            field.dispatchEvent(new Event('change', { bubbles: true }));
            syncMediaGroup(group);
            dialog.close('selected');
        };
        cancelBtn.onclick = onCancel;
        addBtn.onclick = onAdd;

        await refresh();
        if (typeof dialog.showModal === 'function') {
            dialog.showModal();
        } else {
            dialog.setAttribute('open', 'open');
        }
        filter.focus();
    }

    function findMediaGroup(fromEl) {
        return fromEl.closest('[data-media-group]')
            || fromEl.closest('[data-activity-row]')?.querySelector('[data-media-group]');
    }

    document.addEventListener('click', (event) => {
        const button = event.target.closest('.btn-choose-media');
        if (!button) return;
        event.preventDefault();
        openMediaPicker(findMediaGroup(button));
    });

    function initExistingGroups() {
        document.querySelectorAll('[data-media-group]').forEach((group) => syncMediaGroup(group));
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initExistingGroups);
    } else {
        initExistingGroups();
    }

    window.HomeSchoolMediaPicker = {
        open: openMediaPicker,
        ensureDialog,
        syncMediaGroup,
        parseAttachments,
        serializeAttachments,
        displayName,
    };
})();
