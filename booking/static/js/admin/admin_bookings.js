/*
 * Manage Bookings: live "Playing" countdown and the Complete button.
 *
 * Workflow: Approved -> Playing (countdown) -> Time ended -> Completed.
 * While a booking is playing its Complete button stays hidden; when the
 * countdown reaches zero the row switches to "Time ended" and the button
 * appears. The server checks the same rule, so Complete can't be forced early.
 */
(function () {
    let offset = 0;                    // server clock - browser clock (ms)

    function parseTime(text) {
        // Python ISO times can carry microseconds; keep milliseconds only
        return new Date(String(text).replace(/(\.\d{3})\d+/, '$1')).getTime();
    }

    function pad(n) { return String(n).padStart(2, '0'); }

    function formatLeft(ms) {
        const s = Math.max(Math.floor(ms / 1000), 0);
        const h = Math.floor(s / 3600);
        return (h ? h + ':' : '') + pad(Math.floor((s % 3600) / 60)) + ':' + pad(s % 60);
    }

    function tick() {
        const now = Date.now() + offset;
        document.querySelectorAll('#bookingsTable [data-stage-ends]').forEach(function (cell) {
            const left = parseTime(cell.dataset.stageEnds) - now;
            if (left > 0) {
                cell.querySelector('.stage-left').textContent = formatLeft(left) + ' left';
                return;
            }
            // Playing time is over: show "Time ended" and reveal Complete
            const row = cell.closest('tr');
            cell.removeAttribute('data-stage-ends');
            cell.classList.add('ended');
            cell.querySelector('.stage-text').textContent = 'Time ended';
            cell.querySelector('.stage-left').textContent = '';
            if (row) {
                row.dataset.status = 'Time ended';
                const form = row.querySelector('[data-complete-after-ends]');
                if (form) { form.style.display = 'inline'; form.removeAttribute('data-complete-after-ends'); }
                const note = row.querySelector('.stage-note');
                if (note) note.remove();
            }
        });
    }

    function highlightRow() {
        let id = null;
        try {
            id = sessionStorage.getItem('labra_highlight_booking');
            sessionStorage.removeItem('labra_highlight_booking');
        } catch (e) { /* storage unavailable */ }
        if (!id) return;
        document.querySelectorAll('#bookingsTable tbody tr').forEach(function (row) {
            const first = row.querySelector('td');
            if (first && first.textContent.trim() === id) {
                row.classList.add('row-flash');
                row.scrollIntoView({ block: 'center' });
                setTimeout(function () { row.classList.remove('row-flash'); }, 4000);
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        const table = document.getElementById('bookingsTable');
        if (!table) return;
        if (table.dataset.serverNow) {
            const server = parseTime(table.dataset.serverNow);
            if (!isNaN(server)) offset = server - Date.now();
        }
        tick();
        setInterval(tick, 1000);
        highlightRow();
    });
})();
