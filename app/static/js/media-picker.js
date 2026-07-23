/**
 * Lesson media library picker.
 * Opens a dialog listing files from /api/media-library and writes the chosen
 * /media/... URL into the nearest activity link field.
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
            <form method="dialog" class="media-library-panel">
                <header class="media-library-header">
                    <h3>Choose media file</h3>
                    <p class="section-hint">Files come from the server media library folder.</p>
                </header>
                <input type="search" id="media-library-filter" class="media-library-filter"
                       placeholder="Search by file or folder name..." autocomplete="off">
                <div id="media-library-list" class="media-library-list" role="listbox" aria-label="Media files"></div>
                <p id="media-library-empty" class="empty-state" hidden>
                    No files found. Ask an admin to copy files into the media folder.
                </p>
                <footer class="media-library-footer">
                    <button type="submit" value="cancel" class="btn btn-secondary btn-sm">Cancel</button>
                </footer>
            </form>
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

    async function loadFiles(query) {
        const params = new URLSearchParams();
        if (query) params.set('q', query);
        const response = await fetch(`/api/media-library?${params.toString()}`, {
            headers: { Accept: 'application/json' },
        });
        if (!response.ok) {
            throw new Error('Unable to load media library');
        }
        return response.json();
    }

    function renderFiles(files, onPick) {
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
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'media-library-item';
            button.setAttribute('role', 'option');
            button.innerHTML = `
                <span class="media-library-item-main">
                    <strong>${escapeHtml(file.name)}</strong>
                    <span class="media-library-item-path">${escapeHtml(file.path)}</span>
                </span>
                <span class="media-library-item-meta">
                    <span class="media-kind-tag">${escapeHtml(kindLabel(file.kind))}</span>
                    <span>${escapeHtml(file.size_label || '')}</span>
                </span>
            `;
            button.addEventListener('click', () => onPick(file));
            list.appendChild(button);
        });
    }

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    async function openMediaPicker(targetInput) {
        if (!targetInput) return;
        const dialog = ensureDialog();
        const filter = dialog.querySelector('#media-library-filter');
        let latestQuery = '';

        const refresh = async () => {
            try {
                const data = await loadFiles(latestQuery);
                renderFiles(data.files || [], (file) => {
                    targetInput.value = file.url;
                    targetInput.dispatchEvent(new Event('input', { bubbles: true }));
                    targetInput.dispatchEvent(new Event('change', { bubbles: true }));
                    dialog.close('selected');
                });
            } catch (error) {
                renderFiles([], () => {});
                const empty = document.getElementById('media-library-empty');
                if (empty) {
                    empty.hidden = false;
                    empty.textContent = 'Could not load the media library. Try again or check that you are signed in.';
                }
            }
        };

        filter.value = '';
        latestQuery = '';
        filter.oninput = () => {
            latestQuery = filter.value.trim();
            refresh();
        };
        await refresh();
        if (typeof dialog.showModal === 'function') {
            dialog.showModal();
        } else {
            dialog.setAttribute('open', 'open');
        }
        filter.focus();
    }

    function findLinkInput(fromEl) {
        const row = fromEl.closest('[data-activity-row]');
        if (!row) return null;
        return row.querySelector('input[name="activity_external_links"]');
    }

    document.addEventListener('click', (event) => {
        const button = event.target.closest('.btn-choose-media');
        if (!button) return;
        event.preventDefault();
        const input = findLinkInput(button);
        openMediaPicker(input);
    });

    window.HomeSchoolMediaPicker = {
        open: openMediaPicker,
        ensureDialog,
    };
})();
