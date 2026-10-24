/*
 * Shared search + filter for any table (admin and customer pages).
 *
 * Usage in a template:
 *   <div class="table-filter" data-table="bookingsTable">
 *     <input type="search" class="form-control" data-filter="search" placeholder="Search…">
 *     <select class="form-control" data-filter="status"> <option value="">All</option> … </select>
 *     <input type="date" class="form-control" data-filter="from">
 *     <input type="date" class="form-control" data-filter="to">
 *     <button type="button" data-filter="clear">Clear</button>
 *     <span data-filter="count"></span>
 *   </div>
 *
 * Each filterable <tr> carries the values to match:
 *   data-search="text to search"  data-status="Pending"  data-date="2026-10-25"
 * A <select data-filter="xyz"> matches the row's data-xyz exactly.
 * Rows without data-search (e.g. the "No bookings" row) are left alone.
 */
(function () {
    function setupFilter(bar) {
        const table = document.getElementById(bar.dataset.table);
        if (!table) return;
        const tbody = table.tBodies[0];
        const rows = Array.from(tbody.querySelectorAll('tr[data-search]'));
        const controls = Array.from(bar.querySelectorAll('[data-filter]'));
        const countEl = bar.querySelector('[data-filter="count"]');
        const columnCount = table.tHead ? table.tHead.rows[0].cells.length : 1;

        // "No matching results" row, shown only when filters hide everything
        const noMatch = document.createElement('tr');
        noMatch.className = 'table-filter-nomatch';
        noMatch.innerHTML = '<td colspan="' + columnCount + '">No matching results. Try a different search or clear the filters.</td>';
        noMatch.style.display = 'none';
        tbody.appendChild(noMatch);

        function apply() {
            let search = '', from = '', to = '';
            const selects = [];
            controls.forEach(function (c) {
                const key = c.dataset.filter;
                if (key === 'search') search = c.value.trim().toLowerCase().replace(/^#/, '');
                else if (key === 'from') from = c.value;
                else if (key === 'to') to = c.value;
                else if (c.tagName === 'SELECT') selects.push({ key: key, value: c.value });
            });

            let shown = 0;
            rows.forEach(function (row) {
                let ok = true;
                if (search && row.dataset.search.toLowerCase().indexOf(search) === -1) ok = false;
                selects.forEach(function (s) {
                    if (ok && s.value && (row.dataset[s.key] || '') !== s.value) ok = false;
                });
                const date = row.dataset.date || '';
                if (ok && from && (!date || date < from)) ok = false;
                if (ok && to && (!date || date > to)) ok = false;

                row.style.display = ok ? '' : 'none';
                if (ok) shown++;
            });

            noMatch.style.display = (rows.length > 0 && shown === 0) ? '' : 'none';
            if (countEl) {
                countEl.textContent = rows.length ? 'Showing ' + shown + ' of ' + rows.length : '';
            }
        }

        controls.forEach(function (c) {
            const key = c.dataset.filter;
            if (key === 'clear') {
                c.addEventListener('click', function () {
                    controls.forEach(function (x) {
                        if (x.tagName === 'INPUT' || x.tagName === 'SELECT') x.value = '';
                    });
                    apply();
                });
            } else if (key !== 'count') {
                c.addEventListener('input', apply);
                c.addEventListener('change', apply);
            }
        });

        apply();
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.table-filter[data-table]').forEach(setupFilter);
    });
})();
