/*
 * Admin "Court Schedule" page.
 * Approved bookings are read from Google Calendar by Django
 * (/admin_schedule_events/), pending ones come from our database.
 * Uses FullCalendar (MIT licence, served from /static/vendor/fullcalendar/).
 */
(function () {
    let calendar = null;
    // Remember the URL hash now: the main admin script resets it on load
    const initialHash = window.location.hash;
    // Let #schedule and #profile open their pages directly (e.g. after Google sign-in)
    if (typeof PAGE_TITLES !== 'undefined') {
        PAGE_TITLES.schedule = 'Court Schedule';
        PAGE_TITLES.profile = 'Edit Profile';
    }
    let lastData = { events: [], google: { status: 'ok', message: '' } };
    let lastRangeKey = '';

    function el(id) { return document.getElementById(id); }

    function currentFilters() {
        return {
            search: (el('scheduleSearch').value || '').trim().toLowerCase(),
            showPending: el('schedulePending').checked,
        };
    }

    function filteredEvents() {
        const f = currentFilters();
        return lastData.events.filter(function (e) {
            const p = e.extendedProps || {};
            if (!f.showPending && p.source === 'pending') return false;
            if (f.search) {
                const text = (p.customer + ' ' + p.booking_id).toLowerCase();
                if (text.indexOf(f.search.replace(/^#/, '')) === -1) return false;
            }
            return true;
        });
    }

    function showNotice(google) {
        const notice = el('scheduleNotice');
        if (google && google.status !== 'ok') {
            notice.textContent = google.message;
            notice.style.display = '';
        } else {
            notice.textContent = '';
            notice.style.display = 'none';
        }
    }

    function loadEvents(info, success, failure) {
        const rangeKey = info.startStr + '|' + info.endStr;
        if (rangeKey === lastRangeKey) {         // filter change only: no new request
            success(filteredEvents());
            return;
        }
        const url = el('scheduleCalendar').dataset.url +
            '?start=' + encodeURIComponent(info.startStr) + '&end=' + encodeURIComponent(info.endStr);
        el('scheduleLoading').style.display = '';
        fetch(url, { credentials: 'same-origin' })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                lastData = data;
                lastRangeKey = rangeKey;
                showNotice(data.google);
                success(filteredEvents());
            })
            .catch(function () {
                showNotice({ status: 'error', message: 'The schedule could not be loaded. Please refresh the page.' });
                failure();
            })
            .finally(function () { el('scheduleLoading').style.display = 'none'; });
    }

    const SOURCE_LABELS = {
        google: 'Google Calendar (approved)',
        pending: 'Waiting for approval (not in Google yet)',
        not_synced: 'Approved, but not in Google Calendar',
        database: 'Approved (from database, as Google is unavailable)',
    };

    function showDetails(event) {
        const p = event.extendedProps || {};
        el('schedDetailTitle').textContent = 'Booking #' + (p.booking_id || '—');
        el('schedDetailCustomer').textContent = p.customer || '—';
        el('schedDetailDate').textContent = p.date || '—';
        el('schedDetailTime').textContent = p.time || '—';
        el('schedDetailTotal').textContent = p.total ? '₱' + p.total : '—';
        el('schedDetailPayment').textContent = p.payment_status || '—';
        el('schedDetailStatus').textContent = p.booking_status || '—';
        el('schedDetailSource').textContent = SOURCE_LABELS[p.source] || '—';
        openModal('scheduleDetailModal');
    }

    function initCalendar() {
        if (calendar || typeof FullCalendar === 'undefined') return;
        calendar = new FullCalendar.Calendar(el('scheduleCalendar'), {
            initialView: 'dayGridMonth',
            headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,timeGridWeek' },
            buttonText: { today: 'Today', month: 'Month', week: 'Week' },
            height: 'auto',
            slotMinTime: '08:00:00',
            slotMaxTime: '22:00:00',
            allDaySlot: false,
            nowIndicator: true,
            dayMaxEvents: 3,
            eventTimeFormat: { hour: 'numeric', minute: '2-digit', meridiem: 'short' },
            events: loadEvents,
            eventClick: function (info) {
                info.jsEvent.preventDefault();
                showDetails(info.event);
            },
        });
        calendar.render();
    }

    function refilter() {
        if (calendar) calendar.refetchEvents();   // re-uses the loaded range
    }

    document.addEventListener('DOMContentLoaded', function () {
        if (!el('scheduleCalendar')) return;
        PAGE_TITLES.schedule = 'Court Schedule';

        // Wrap the existing page switcher: draw the calendar when its page opens
        const originalShowPage = showPage;
        showPage = function (pageId) {
            originalShowPage(pageId);
            if (pageId === 'schedule') {
                initCalendar();
                if (calendar) calendar.updateSize();
            }
        };

        el('scheduleSearch').addEventListener('input', refilter);
        el('schedulePending').addEventListener('change', refilter);

        if (initialHash === '#schedule') showPage('schedule');
    });
})();
