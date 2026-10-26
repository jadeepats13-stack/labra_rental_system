/*
 * Staff Check-in page (admin panel).
 *
 * Two ways to verify the same booking record:
 *   1. Scan the customer's QR with the camera (html5-qrcode library, local)
 *   2. Type the Booking Confirmation ID (e.g. LBC-7K3P-9Q2X)
 * After a successful check, "Start playing time" starts the countdown,
 * which ends at the reserved end time (or when staff click "End playing
 * time now"). Then staff mark the booking Completed in Manage Bookings.
 * The server prevents a booking from being started twice.
 */
(function () {
    let current = null;          // last verified booking summary
    let scanner = null;          // Html5Qrcode instance
    let scanning = false;
    let busy = false;
    let serverOffset = 0;        // server clock - browser clock (ms)
    let sessions = [];
    let pollTimer = null;
    let lastScanned = '';

    // Let #checkin open this page directly (set before the main admin script routes the hash)
    if (typeof PAGE_TITLES !== 'undefined') PAGE_TITLES.checkin = 'Check-in';

    function el(id) { return document.getElementById(id); }
    function pad(n) { return String(n).padStart(2, '0'); }

    function csrfToken() {
        const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        if (m) return decodeURIComponent(m[1]);
        const input = document.querySelector('input[name=csrfmiddlewaretoken]');
        return input ? input.value : '';
    }

    function syncClock(data) {
        if (data && data.now) serverOffset = new Date(data.now).getTime() - Date.now();
    }

    function serverNow() { return Date.now() + serverOffset; }

    function formatLeft(ms) {
        if (ms <= 0) return '00:00:00';
        const s = Math.floor(ms / 1000);
        return pad(Math.floor(s / 3600)) + ':' + pad(Math.floor((s % 3600) / 60)) + ':' + pad(s % 60);
    }

    function post(url, body) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
            body: JSON.stringify(body || {}),
        }).then(function (r) { return r.json(); });
    }

    // ── Result card ────────────────────────────────────────────────
    const TONES = {
        ok: 'ok', started: 'ok', already: 'info', unpaid: 'warn',
        early: 'warn', day: 'error', ended: 'error', status: 'error',
        not_found: 'error', read_error: 'error', network: 'error',
        ended: 'ok', already_ended: 'info', not_started: 'error',
    };
    let ending = null;           // booking summary shown in the "End early" pop-up

    function showResult(data) {
        syncClock(data);
        const box = el('checkinResult');
        const b = data.booking;
        current = data.found ? b : null;

        let html = '<div class="ci-banner ci-' + (TONES[data.reason] || 'error') + '">' +
            escapeHtml(data.message) + '</div>';

        if (b) {
            html += '<dl class="ci-details">' +
                row('Confirmation ID', '<span class="mono">' + escapeHtml(b.code) + '</span>') +
                row('Customer', escapeHtml(b.customer) + ' <span class="ci-muted">@' + escapeHtml(b.username) + '</span>') +
                row('Booking', '#' + b.booking_id + ' · ' + escapeHtml(b.court)) +
                row('Date', escapeHtml(b.date)) +
                row('Reserved time', escapeHtml(b.time)) +
                row('Payment', (b.paid ? '<span class="ci-paid">Paid</span>' : '<span class="ci-unpaid">Unpaid</span>') +
                    ' · ₱' + escapeHtml(b.total)) +
                row('Status', escapeHtml(b.stage || b.status) + (b.checked_in_at ? ' · checked in at ' + escapeHtml(b.checked_in_at) +
                    (b.checked_in_by ? ' by ' + escapeHtml(b.checked_in_by) : '') : '')) +
                '</dl>';

            if (b.ends_at && (data.reason === 'started' || data.reason === 'already') && new Date(b.ends_at).getTime() > serverNow()) {
                html += '<div class="ci-timer" data-ends="' + b.ends_at + '">' +
                    '<span class="ci-timer-label">Playing time left</span>' +
                    '<span class="ci-timer-value">--:--:--</span></div>';
            }

            const playing = b.ends_at && b.status === 'Approved' && new Date(b.ends_at).getTime() > serverNow();
            html += '<div class="ci-actions">';
            if (playing && (data.reason === 'started' || data.reason === 'already')) {
                html += '<button type="button" class="btn btn-outline" id="ciEndBtn">End early</button>';
            }
            if (data.reason === 'ok') {          // verified and ready (not "started" / "ended")
                html += '<button type="button" class="btn btn-success" id="ciStartBtn">Start playing time</button>';
            }
            if (data.reason === 'unpaid') {
                html += '<button type="button" class="btn btn-warning" id="ciCashBtn">Record cash payment (₱' +
                    escapeHtml(b.total) + ')</button>';
            }
            html += '<button type="button" class="btn btn-outline" id="ciResetBtn">Verify another booking</button></div>';
        } else {
            html += '<div class="ci-actions"><button type="button" class="btn btn-outline" id="ciResetBtn">Try again</button></div>';
        }

        box.innerHTML = html;
        box.classList.add('has-result');
        tick();

        const start = el('ciStartBtn');
        if (start) start.addEventListener('click', startSession);
        const cash = el('ciCashBtn');
        if (cash) cash.addEventListener('click', recordCash);
        const endBtn = el('ciEndBtn');
        if (endBtn) endBtn.addEventListener('click', function () { openEnd(b); });
        el('ciResetBtn').addEventListener('click', resetResult);
    }

    function row(label, value) { return '<dt>' + label + '</dt><dd>' + value + '</dd>'; }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    function resetResult() {
        current = null;
        lastScanned = '';
        const box = el('checkinResult');
        box.classList.remove('has-result');
        box.innerHTML = '<div class="ci-empty">Scan a QR code or type a Confirmation ID. ' +
            'The booking details will appear here.</div>';
        const input = el('ciCodeInput');
        if (input) { input.value = ''; }
    }

    function setBusy(on, text) {
        busy = on;
        const box = el('checkinResult');
        if (on) {
            box.classList.add('has-result');
            box.innerHTML = '<div class="ci-empty">' + (text || 'Checking…') + '</div>';
        }
    }

    function networkError() {
        showResult({ found: false, ok: false, reason: 'network',
            message: 'Could not reach the server. Check the connection and try again.' });
    }

    // ── Verify / start / record cash ───────────────────────────────
    function verify(code) {
        if (busy) return;
        setBusy(true, 'Checking ' + escapeHtml(code) + '…');
        post(el('page-checkin').dataset.verifyUrl, { code: code })
            .then(function (data) { busy = false; showResult(data); })
            .catch(function () { busy = false; networkError(); });
    }

    function startSession() {
        if (!current || busy) return;
        const btn = el('ciStartBtn');
        if (btn) btn.disabled = true;
        busy = true;
        post(el('page-checkin').dataset.startUrl, { code: current.code })
            .then(function (data) { busy = false; showResult(data); loadSessions(); })
            .catch(function () { busy = false; networkError(); });
    }

    function recordCash() {
        if (!current || busy) return;
        if (!confirm('Record a cash payment of ₱' + current.total + ' for booking #' + current.booking_id + '?')) return;
        busy = true;
        post(el('page-checkin').dataset.cashUrl, { code: current.code })
            .then(function (data) { busy = false; showResult(data); })
            .catch(function () { busy = false; networkError(); });
    }

    // ── Method 1: camera scan ──────────────────────────────────────
    function startCamera() {
        if (typeof Html5Qrcode === 'undefined') {
            showResult({ found: false, ok: false, reason: 'read_error',
                message: 'The QR scanner could not load. Use the Confirmation ID instead.' });
            return;
        }
        if (scanning) return;
        if (!scanner) scanner = new Html5Qrcode('qrReader');
        el('ciCameraHint').textContent = 'Starting camera…';
        scanner.start(
            { facingMode: 'environment' },
            { fps: 10, qrbox: { width: 220, height: 220 } },
            function onScan(text) {
                if (busy || text === lastScanned) return;   // ignore repeats of the same frame
                lastScanned = text;
                stopCamera();
                verify(text);
            },
            function () { /* no QR in this frame */ }
        ).then(function () {
            scanning = true;
            el('ciStartCam').style.display = 'none';
            el('ciStopCam').style.display = '';
            el('ciCameraHint').textContent = 'Point the camera at the customer\'s QR code.';
        }).catch(function () {
            el('ciCameraHint').textContent = 'Camera not available or permission denied. ' +
                'Allow camera access, or use "Enter ID".';
        });
    }

    function stopCamera() {
        if (scanner && scanning) {
            scanner.stop().catch(function () {});
        }
        scanning = false;
        if (el('ciStartCam')) el('ciStartCam').style.display = '';
        if (el('ciStopCam')) el('ciStopCam').style.display = 'none';
        if (el('ciCameraHint')) el('ciCameraHint').textContent = 'Click "Start camera" and point it at the customer\'s QR code.';
    }

    // ── Tabs ───────────────────────────────────────────────────────
    function selectTab(name) {
        document.querySelectorAll('.ci-tab').forEach(function (t) {
            const on = t.dataset.tab === name;
            t.classList.toggle('active', on);
            t.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        document.querySelectorAll('.ci-panel').forEach(function (p) {
            p.hidden = p.dataset.panel !== name;
        });
        if (name !== 'scan') stopCamera();
        if (name === 'id') setTimeout(function () { el('ciCodeInput').focus(); }, 50);
    }

    // ── Courts in use (countdowns) ─────────────────────────────────
    function loadSessions() {
        fetch(el('page-checkin').dataset.sessionsUrl, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                syncClock(data);
                sessions = data.sessions || [];
                renderSessions();
            })
            .catch(function () {});
    }

    function renderSessions() {
        const badge = el('badgeCheckin');
        if (badge) { badge.textContent = sessions.length; badge.hidden = sessions.length === 0; }
        const list = el('ciSessions');
        if (!sessions.length) {
            list.innerHTML = '<div class="ci-empty">No one is playing right now.</div>';
            return;
        }
        list.innerHTML = sessions.map(function (s) {
            return '<div class="ci-session">' +
                '<div class="ci-session-who"><strong>' + escapeHtml(s.customer) + '</strong>' +
                '<span>Booking #' + s.booking_id + ' · ' + escapeHtml(s.time) + ' · checked in ' + escapeHtml(s.checked_in_at) + '</span></div>' +
                '<div class="ci-timer" data-ends="' + s.ends_at + '">' +
                '<span class="ci-timer-label">Time left</span><span class="ci-timer-value">--:--:--</span></div>' +
                '<div class="ci-session-actions"><button type="button" class="btn btn-outline btn-sm" ' +
                'data-end-code="' + escapeHtml(s.code) + '">End early</button></div>' +
                '</div>';
        }).join('');
        list.querySelectorAll('[data-end-code]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const s = sessions.find(function (x) { return x.code === btn.dataset.endCode; });
                if (s) openEnd(s);
            });
        });
        tick();
    }

    // ── End early (customer finished before the time was up) ─────
    function openEnd(b) {
        ending = b;
        el('ciEndCustomer').textContent = b.customer;
        el('ciEndBooking').textContent = '#' + b.booking_id + ' · ' + b.code;
        el('ciEndTime').textContent = b.time;
        el('ciEndConfirm').disabled = false;
        updateEndLeft();
        openModal('ciEndModal');
        el('ciEndCancel').focus();
    }

    function updateEndLeft() {
        if (!ending) return;
        el('ciEndLeft').textContent = formatLeft(new Date(ending.ends_at).getTime() - serverNow());
    }

    function confirmEnd() {
        if (!ending || busy) return;
        el('ciEndConfirm').disabled = true;
        busy = true;
        const code = ending.code;
        post(el('page-checkin').dataset.endUrl, { code: code })
            .then(function (data) {
                busy = false;
                closeModal('ciEndModal');
                ending = null;
                if (data.ok && data.reason === 'ended') {
                    showEnded(data);          // short pop-up, then Manage Bookings
                    return;
                }
                showResult(data);
                loadSessions();
            })
            .catch(function () { busy = false; closeModal('ciEndModal'); networkError(); });
    }

    // Pop-up after "End playing time now", then open Manage Bookings
    function goToBookings(bookingId) {
        try { sessionStorage.setItem('labra_highlight_booking', String(bookingId)); } catch (e) { /* ignore */ }
        history.replaceState(null, '', window.location.pathname + '#bookings');
        window.location.reload();             // fresh list with the Complete button
    }

    function showEnded(data) {
        const id = data.booking ? data.booking.booking_id : '';
        el('ciEndedMessage').textContent = data.message;
        openModal('ciEndedModal');
        el('ciEndedGo').onclick = function () { goToBookings(id); };
        setTimeout(function () { goToBookings(id); }, 2500);
    }

    function tick() {
        updateEndLeft();
        let expired = false;
        document.querySelectorAll('#page-checkin .ci-timer').forEach(function (t) {
            const left = new Date(t.dataset.ends).getTime() - serverNow();
            t.querySelector('.ci-timer-value').textContent = formatLeft(left);
            t.classList.toggle('ending', left > 0 && left <= 10 * 60 * 1000);
            if (left <= 0 && !t.classList.contains('done')) {
                t.classList.add('done');
                t.querySelector('.ci-timer-label').textContent = 'Time\'s up';
                expired = true;
            }
        });
        if (expired) setTimeout(loadSessions, 1500);   // it now waits for Complete in Manage Bookings
    }

    // ── Wire up ────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        const page = el('page-checkin');
        if (!page) return;
        document.querySelectorAll('.ci-tab').forEach(function (t) {
            t.addEventListener('click', function () { selectTab(t.dataset.tab); });
        });
        el('ciStartCam').addEventListener('click', startCamera);
        el('ciStopCam').addEventListener('click', stopCamera);
        el('ciIdForm').addEventListener('submit', function (e) {
            e.preventDefault();
            const code = el('ciCodeInput').value.trim();
            if (code) verify(code);
        });
        el('ciEndCancel').addEventListener('click', function () { ending = null; closeModal('ciEndModal'); });
        el('ciEndConfirm').addEventListener('click', confirmEnd);

        const originalShowPage = showPage;
        showPage = function (pageId) {
            originalShowPage(pageId);
            if (pageId === 'checkin') {
                loadSessions();
                if (!pollTimer) pollTimer = setInterval(loadSessions, 30000);
            } else {
                stopCamera();
                if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
            }
        };

        setInterval(tick, 1000);
        resetResult();
        if (page.classList.contains('active')) showPage('checkin');
    });
})();
