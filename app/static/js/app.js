// Home School Tracker — client-side enhancements

document.addEventListener('DOMContentLoaded', function () {
    // Auto-dismiss success alerts after 5 seconds
    document.querySelectorAll('.alert-success').forEach(function (alert) {
        setTimeout(function () {
            alert.style.transition = 'opacity 0.4s';
            alert.style.opacity = '0';
            setTimeout(function () { alert.remove(); }, 400);
        }, 5000);
    });
});
