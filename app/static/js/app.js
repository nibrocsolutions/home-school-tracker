// Home School Tracker — client-side enhancements

if ('scrollRestoration' in history) {
    history.scrollRestoration = 'manual';
}

const SCROLL_KEY = 'hst-scroll-y';

function saveScrollPosition() {
    sessionStorage.setItem(SCROLL_KEY, String(window.scrollY));
}

function restoreScrollPosition() {
    const saved = sessionStorage.getItem(SCROLL_KEY);
    if (saved === null) {
        return;
    }
    sessionStorage.removeItem(SCROLL_KEY);
    const scrollY = parseInt(saved, 10);
    requestAnimationFrame(function () {
        window.scrollTo(0, scrollY);
    });
}

function initPreserveScroll() {
    document.querySelectorAll('[data-preserve-scroll]').forEach(function (container) {
        container.querySelectorAll('a[href]').forEach(function (link) {
            if (link.target === '_blank') {
                return;
            }
            link.addEventListener('click', saveScrollPosition);
        });

        container.querySelectorAll('.cal-date-picker[data-nav-url]').forEach(function (picker) {
            picker.addEventListener('change', function () {
                saveScrollPosition();
                window.location.href = picker.dataset.navUrl + picker.value;
            });
        });
    });
}

const DAY_TYPE_CLASSES = [
    'day-type-actual_school',
    'day-type-school_off',
    'day-type-holiday',
    'day-type-weekend',
    'day-type-sick',
];

const DAY_TYPE_LABELS = {
    actual_school: 'planned actual school day',
    school_off: 'planned school day off',
    holiday: 'holiday',
    weekend: 'weekend',
    sick: 'sick day',
};

function formatSchoolDayDate(isoDate) {
    const parts = isoDate.split('-');
    const dateObj = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    return dateObj.toLocaleDateString(undefined, {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
    });
}

function displaySchoolDayType(dayType) {
    // Holidays keep holiday metadata/text but look like normal school days on the calendar.
    // Sick days keep day-type-sick (styled red like planned school days off).
    if (dayType === 'holiday') {
        return 'actual_school';
    }
    return dayType;
}

function updateSchoolDayButton(button, dayType, isCompleted, holidayName) {
    DAY_TYPE_CLASSES.forEach(function (className) {
        button.classList.remove(className);
    });
    const displayType = displaySchoolDayType(dayType);
    button.classList.add('day-type-' + displayType);
    button.classList.toggle('completed', dayType === 'actual_school' && isCompleted);
    button.dataset.dayType = dayType;
    button.dataset.isCompleted = isCompleted ? 'true' : 'false';

    let check = button.querySelector('.school-day-check');
    if (dayType === 'actual_school' && isCompleted) {
        if (!check) {
            check = document.createElement('span');
            check.className = 'school-day-check';
            check.setAttribute('aria-hidden', 'true');
            check.textContent = '✓';
            button.appendChild(check);
        }
    } else if (check) {
        check.remove();
    }

    let holidayLabel = button.querySelector('.school-day-holiday-name');
    if (holidayName) {
        if (!holidayLabel) {
            holidayLabel = document.createElement('span');
            holidayLabel.className = 'school-day-holiday-name';
            holidayLabel.setAttribute('aria-hidden', 'true');
            const dayNum = button.querySelector('.school-day-num');
            if (dayNum) {
                dayNum.insertAdjacentElement('afterend', holidayLabel);
            } else {
                button.appendChild(holidayLabel);
            }
        }
        holidayLabel.textContent = holidayName;
        button.dataset.holidayName = holidayName;
    } else if (holidayLabel) {
        holidayLabel.remove();
        delete button.dataset.holidayName;
    }

    const datePart = formatSchoolDayDate(button.dataset.dayDate || '');
    button.title = holidayName ? datePart + ' — ' + holidayName : datePart;
    let ariaLabel = datePart;
    if (holidayName) {
        ariaLabel += ', ' + holidayName;
    } else {
        ariaLabel += ', ' + (DAY_TYPE_LABELS[displayType] || displayType.replace(/_/g, ' '));
    }
    if (dayType === 'actual_school' && isCompleted) {
        ariaLabel += ', completed';
    }
    button.setAttribute('aria-label', ariaLabel);
}

function updateSubjectsProgress(rows) {
    if (!rows || !rows.length) {
        return;
    }
    rows.forEach(function (row) {
        const tr = document.querySelector('[data-subject-progress-id="' + row.id + '"]');
        if (!tr) {
            return;
        }
        const available = tr.querySelector('.subject-available-days');
        const balance = tr.querySelector('.subject-balance');
        const scheduled = tr.querySelector('.subject-scheduled');
        const dropped = tr.querySelector('.subject-dropped');
        const requested = tr.querySelector('.subject-lessons-requested');
        if (requested) requested.textContent = row.lessons_per_year;
        if (available) available.textContent = row.available_days;
        if (balance) {
            balance.textContent = row.balance;
            balance.classList.toggle('count-negative', row.balance < 0);
        }
        if (scheduled) scheduled.textContent = row.scheduled;
        if (dropped) {
            dropped.textContent = row.dropped;
            dropped.classList.toggle('count-negative', row.dropped > 0);
        }
    });
}

function updateSchoolDayCounters(data) {
    const completeBanner = document.getElementById('school-day-complete-banner');

    function setCounter(selector, value) {
        if (value === undefined || value === null) {
            return;
        }
        document.querySelectorAll(selector).forEach(function (el) {
            el.textContent = value;
        });
    }

    setCounter('.counter-planned-actual', data.planned_actual_count);
    setCounter('.counter-planned-off', data.planned_school_off_count);
    setCounter('.counter-planned-sick', data.planned_sick_count);
    setCounter('.counter-completed', data.completed_count);
    setCounter('.counter-remaining', data.remaining_days);
    setCounter('.counter-required', data.required_days);

    if (completeBanner) {
        completeBanner.hidden = !data.complete;
    }
}

function initSchoolDayEditor() {
    const dialog = document.getElementById('school-day-editor');
    const form = document.getElementById('school-day-editor-form');
    const calendar = document.querySelector('.school-day-calendar');
    if (!dialog || !form || !calendar) {
        return;
    }

    const dateLabel = document.getElementById('school-day-editor-date');
    const completedWrap = document.getElementById('school-day-completed-wrap');
    const completedInput = document.getElementById('school-day-completed');
    const closeBtn = dialog.querySelector('.school-day-editor-close');
    const cancelBtn = dialog.querySelector('.school-day-editor-cancel');
    const saveBtn = dialog.querySelector('.school-day-editor-save');
    const typeInputs = form.querySelectorAll('input[name="day_type"]');
    let activeButton = null;

    function syncCompletedVisibility() {
        const selected = form.querySelector('input[name="day_type"]:checked');
        const isActualSchool = selected && selected.value === 'actual_school';
        if (completedWrap) {
            completedWrap.hidden = !isActualSchool;
        }
        if (!isActualSchool && completedInput) {
            completedInput.checked = false;
        }
    }

    typeInputs.forEach(function (input) {
        input.addEventListener('change', syncCompletedVisibility);
    });

    function closeEditor() {
        activeButton = null;
        dialog.close();
    }

    function openEditor(button) {
        activeButton = button;
        const dayDate = button.dataset.dayDate;
        const dayType = button.dataset.dayType;
        const isCompleted = button.dataset.isCompleted === 'true';

        if (dateLabel) {
            dateLabel.textContent = formatSchoolDayDate(dayDate);
        }

        typeInputs.forEach(function (input) {
            input.checked = input.value === dayType;
        });
        if (completedInput) {
            completedInput.checked = isCompleted;
        }
        syncCompletedVisibility();
        dialog.showModal();
    }

    calendar.querySelectorAll('.school-day-edit-btn').forEach(function (button) {
        button.addEventListener('click', function () {
            openEditor(button);
        });
    });

    closeBtn?.addEventListener('click', closeEditor);
    cancelBtn?.addEventListener('click', closeEditor);
    dialog.addEventListener('cancel', function () {
        activeButton = null;
    });
    dialog.addEventListener('click', function (event) {
        if (event.target === dialog) {
            closeEditor();
        }
    });

    form.addEventListener('submit', async function (event) {
        event.preventDefault();
        if (!activeButton) {
            return;
        }

        const selectedType = form.querySelector('input[name="day_type"]:checked');
        if (!selectedType) {
            return;
        }

        const dayType = selectedType.value;
        const isCompleted = dayType === 'actual_school' && completedInput?.checked;
        const calMonth = calendar.dataset.calMonth || '';
        const formData = new FormData();
        formData.append('day_date', activeButton.dataset.dayDate);
        formData.append('day_type', dayType);
        formData.append('is_completed', isCompleted ? 'true' : 'false');
        if (calMonth) {
            formData.append('cal_month', calMonth);
        }

        saveBtn.disabled = true;
        try {
            const response = await fetch('/teacher/school-days/update-day', {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            if (!response.ok) {
                return;
            }
            const data = await response.json();
            updateSchoolDayButton(
                activeButton,
                data.day_type,
                data.is_completed,
                data.holiday_name
            );
            updateSchoolDayCounters(data);
            if (data.subjects_progress) {
                updateSubjectsProgress(data.subjects_progress);
            }
            closeEditor();
        } finally {
            saveBtn.disabled = false;
        }
    });
}

function initPossibleSchoolDaysPreview() {
    const startInput = document.getElementById('start_date');
    const endInput = document.getElementById('end_date');
    if (!startInput || !endInput) {
        return;
    }

    const possibleEl = document.querySelector('.counter-possible');
    const previewRow = document.querySelector('.counter-possible-preview-row');
    const previewValue = document.querySelector('.counter-possible-preview');
    const hint = document.querySelector('.possible-days-hint');
    let requestId = 0;

    async function refreshPossibleDays() {
        const start = startInput.value;
        const end = endInput.value;
        if (!start || !end) {
            if (previewRow) {
                previewRow.hidden = true;
            }
            if (hint) {
                hint.hidden = false;
            }
            return;
        }

        const currentRequest = ++requestId;
        try {
            const params = new URLSearchParams({ start_date: start, end_date: end });
            const response = await fetch('/teacher/school-days/possible-count?' + params.toString());
            if (!response.ok || currentRequest !== requestId) {
                return;
            }
            const data = await response.json();
            if (possibleEl) {
                possibleEl.textContent = data.possible_days;
            }
            if (previewRow) {
                previewRow.hidden = !!possibleEl;
            }
            if (previewValue) {
                previewValue.textContent = data.possible_days;
            }
            if (hint) {
                hint.hidden = true;
            }
        } catch (error) {
            if (previewRow) {
                previewRow.hidden = true;
            }
        }
    }

    startInput.addEventListener('change', refreshPossibleDays);
    endInput.addEventListener('change', refreshPossibleDays);
    refreshPossibleDays();
}

document.addEventListener('DOMContentLoaded', function () {
    restoreScrollPosition();
    initPreserveScroll();
    initSchoolDayEditor();
    initPossibleSchoolDaysPreview();

    document.querySelectorAll('.alert-success').forEach(function (alert) {
        setTimeout(function () {
            alert.style.transition = 'opacity 0.4s';
            alert.style.opacity = '0';
            setTimeout(function () { alert.remove(); }, 400);
        }, 5000);
    });
});
