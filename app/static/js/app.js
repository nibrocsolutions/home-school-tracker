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
];

function updateSchoolDayButton(button, dayType, isCompleted) {
    DAY_TYPE_CLASSES.forEach(function (className) {
        button.classList.remove(className);
    });
    button.classList.add('day-type-' + dayType);
    button.classList.toggle('completed', dayType === 'actual_school' && isCompleted);

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

    const typeLabel = dayType.replace(/_/g, ' ');
    const labelBase = button.title;
    let ariaLabel = labelBase + ', ' + typeLabel;
    if (dayType === 'actual_school' && isCompleted) {
        ariaLabel += ', completed';
    }
    button.setAttribute('aria-label', ariaLabel);
}

function updateSchoolDayCounters(data) {
    const plannedActualEl = document.querySelector('.counter-planned-actual');
    const completedEl = document.querySelector('.counter-completed');
    const remainingEl = document.querySelector('.counter-remaining');
    const requiredEl = document.querySelector('.counter-required');
    const completeBanner = document.getElementById('school-day-complete-banner');

    if (plannedActualEl) {
        plannedActualEl.textContent = data.planned_actual_count;
    }
    if (completedEl) {
        completedEl.textContent = data.completed_count;
    }
    if (remainingEl) {
        remainingEl.textContent = data.remaining_days;
    }
    if (requiredEl) {
        requiredEl.textContent = data.required_days;
    }
    if (completeBanner) {
        completeBanner.hidden = !data.complete;
    }
}

function initSchoolDayUpdates() {
    document.querySelectorAll('.school-day-update-form').forEach(function (form) {
        form.addEventListener('submit', async function (event) {
            event.preventDefault();
            const button = form.querySelector('button.school-day-cell');
            if (!button || button.disabled) {
                return;
            }

            button.disabled = true;
            try {
                const response = await fetch(form.action, {
                    method: 'POST',
                    body: new FormData(form),
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                });
                if (!response.ok) {
                    return;
                }
                const data = await response.json();
                updateSchoolDayButton(button, data.day_type, data.is_completed);
                updateSchoolDayCounters(data);
            } finally {
                button.disabled = false;
            }
        });
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
    initSchoolDayUpdates();
    initPossibleSchoolDaysPreview();

    document.querySelectorAll('.alert-success').forEach(function (alert) {
        setTimeout(function () {
            alert.style.transition = 'opacity 0.4s';
            alert.style.opacity = '0';
            setTimeout(function () { alert.remove(); }, 400);
        }, 5000);
    });
});
