/*
 * Customer check-in helpers:
 *  - "Check-in QR" pop-up (QR image from the goQR.me API + Confirmation ID)
 *  - live "Playing now" countdown on the Your next game ticket
 */
(function () {
    function el(id) { return document.getElementById(id); }
    function pad(n) { return String(n).padStart(2, '0'); }
    let lastFocus = null;

    function openQr(btn) {
        el('qrModalTitle').textContent = 'Check-in QR · Booking #' + btn.dataset.id;
        el('qrWhen').textContent = btn.dataset.when || '';
        el('qrImage').src = btn.dataset.qr;
        el('qrCode').textContent = btn.dataset.code;
        let note = 'Show this to the staff at Labra Basketball Court when you arrive. ' +
            'If the QR doesn\'t scan, they can type the ID.';
        if (btn.dataset.status === 'Pending') {
            note = 'Your QR code becomes valid once your booking is approved. ' + note;
        }
        if (btn.dataset.paid !== '1') {
            note += ' Please pay before your game: staff can only start your playing time once it is paid.';
        }
        el('qrNote').textContent = note;
        lastFocus = document.activeElement;
        el('qrModal').hidden = false;
        el('qrClose').focus();
    }

    function closeQr() {
        el('qrModal').hidden = true;
        if (lastFocus) lastFocus.focus();
    }

    // If the QR image can't load (goQR.me unreachable), the ID still works
    function qrFailed() {
        el('qrImage').alt = 'QR code unavailable right now. Use the Confirmation ID below.';
    }

    function startTicketCountdown() {
        const live = document.querySelector('.ticket-live');
        if (!live) return;
        const offset = new Date(live.dataset.now).getTime() - Date.now();   // server - browser clock
        const ends = new Date(live.dataset.ends).getTime();
        const out = live.querySelector('.ticket-live-left');
        function tick() {
            const left = ends - (Date.now() + offset);
            if (left <= 0) {
                live.textContent = 'Time\'s up. Thanks for playing!';
                clearInterval(timer);
                return;
            }
            const s = Math.floor(left / 1000);
            out.textContent = pad(Math.floor(s / 3600)) + ':' + pad(Math.floor((s % 3600) / 60)) + ':' + pad(s % 60);
        }
        const timer = setInterval(tick, 1000);
        tick();
    }

    // ── "Bookings" badge: counts new or changed bookings since you last opened Bookings ──
    function seenKey(badge) { return 'labra_seen_bookings_' + badge.dataset.user; }

    function readSeen(badge) {
        try { return JSON.parse(localStorage.getItem(seenKey(badge)) || '[]'); } catch (e) { return []; }
    }

    function updateBookingsBadge(markSeen) {
        const badge = el('badgeBookings');
        if (!badge) return;
        const items = badge.dataset.items ? badge.dataset.items.split(',') : [];
        if (markSeen) {
            try { localStorage.setItem(seenKey(badge), JSON.stringify(items)); } catch (e) { /* private mode */ }
        }
        const seen = readSeen(badge);
        const unseen = items.filter(function (i) { return seen.indexOf(i) === -1; }).length;
        badge.textContent = unseen;
        badge.hidden = unseen === 0;
    }

    document.addEventListener('DOMContentLoaded', function () {
        updateBookingsBadge(false);
        if (typeof showPage === 'function') {
            const originalShowPage = showPage;
            showPage = function (pageId) {
                originalShowPage(pageId);
                if (pageId === 'bookings') updateBookingsBadge(true);
            };
        }
        if (!el('qrModal')) return;
        document.addEventListener('click', function (e) {
            const btn = e.target.closest('[data-qr-open]');
            if (btn) openQr(btn);
        });
        el('qrClose').addEventListener('click', closeQr);
        el('qrModal').addEventListener('click', function (e) { if (e.target === el('qrModal')) closeQr(); });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && !el('qrModal').hidden) closeQr();
        });
        el('qrImage').addEventListener('error', qrFailed);
        startTicketCountdown();
    });
})();
