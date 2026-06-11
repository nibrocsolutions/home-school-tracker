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

function updateSchoolDayButton(button, approved) {
    button.classList.toggle('approved', approved);
    let check = button.querySelector('.school-day-check');
    if (approved && !check) {
        check = document.createElement('span');
        check.className = 'school-day-check';
        check.setAttribute('aria-hidden', 'true');
        check.textContent = '✓';
        button.appendChild(check);
    } else if (!approved && check) {
        check.remove();
    }
    const labelBase = button.title;
    button.setAttribute(
        'aria-label',
        labelBase + (approved ? ', approved full school day' : ', not yet approved')
    );
}

function initSchoolDayToggles() {
    document.querySelectorAll('.school-day-toggle-form').forEach(function (form) {
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
                updateSchoolDayButton(button, data.approved);

                const approvedEl = document.querySelector('.counter-approved');
                const remainingEl = document.querySelector('.counter-remaining');
                const requiredEl = document.querySelector('.counter-required');
                const completeBanner = document.getElementById('school-day-complete-banner');

                if (approvedEl) {
                    approvedEl.textContent = data.approved_count;
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
            } finally {
                button.disabled = false;
            }
        });
    });
}

document.addEventListener('DOMContentLoaded', function () {
    restoreScrollPosition();
    initPreserveScroll();
    initSchoolDayToggles();

    document.querySelectorAll('.alert-success').forEach(function (alert) {
        setTimeout(function () {
            alert.style.transition = 'opacity 0.4s';
            alert.style.opacity = '0';
            setTimeout(function () { alert.remove(); }, 400);
        }, 5000);
    });
});
