// ── Sidebar variables (declared here, assigned in DOMContentLoaded) ──
let sidebarToggle, sidebar, sidebarOverlay;

function openSidebar() {
    if (!sidebar) return;
    sidebar.classList.add('open');
    sidebarOverlay.classList.add('visible');
    if (sidebarToggle) sidebarToggle.setAttribute('aria-expanded', 'true');
    const current = sidebar.querySelector('.nav-link.active') || sidebar.querySelector('.nav-link');
    if (current) current.focus();
}

function closeSidebar(restoreFocus) {
    if (!sidebar) return;
    const wasOpen = sidebar.classList.contains('open');
    sidebar.classList.remove('open');
    sidebarOverlay.classList.remove('visible');
    if (sidebarToggle) {
        sidebarToggle.setAttribute('aria-expanded', 'false');
        if (wasOpen && restoreFocus) sidebarToggle.focus();
    }
}

function isMobileNav() {
    return window.innerWidth <= 900;
}

// ── Page navigation ─────────────────────────────────────────────
const PAGE_TITLES = {
    dashboard: 'Dashboard',
    courts: 'Manage Court',
    bookings: 'Manage Bookings',
    customers: 'Manage Customers',
    payments: 'Payments',
    damages: 'Damage Reports',
    records: 'Booking Records',
};

function showPage(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(n => {
        n.classList.remove('active');
        n.removeAttribute('aria-current');
    });

    const page = document.getElementById('page-' + pageId);
    if (page) page.classList.add('active');

    const link = document.querySelector('.nav-link[data-page="' + pageId + '"]');
    if (link) {
        link.classList.add('active');
        link.setAttribute('aria-current', 'page');
    }

    // Header: the page name only (empty on Dashboard, whose page heading already says it)
    const titleEl = document.getElementById('headerTitle');
    if (titleEl) titleEl.textContent = pageId === 'dashboard' ? '' : (PAGE_TITLES[pageId] || '');
    // "Check-in" shortcut: hidden while already on the Check-in page
    const checkinBtn = document.getElementById('headerCheckin');
    if (checkinBtn) checkinBtn.hidden = pageId === 'checkin';
    document.title = (PAGE_TITLES[pageId] || 'Admin Dashboard') + ' – Labra Basketball Court Admin';

    history.replaceState(null, '', '#' + pageId);

    // Close sidebar on mobile
    if (isMobileNav()) {
        setTimeout(closeSidebar, 50);
    }
}

// Move keyboard / screen-reader focus to the new page's heading
function focusPageHeading(pageId) {
    const heading = document.querySelector('#page-' + pageId + ' .page-heading');
    if (heading) heading.focus({ preventScroll: true });
    window.scrollTo(0, 0);
}

// ── Modal helpers ───────────────────────────────────────────────
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const modalReturnFocus = {};

function openModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    modalReturnFocus[id] = document.activeElement;
    el.classList.add('open');
    // Focus the first field unless the caller already moved focus into the modal
    requestAnimationFrame(function () {
        if (el.contains(document.activeElement)) return;
        const first = el.querySelector('.modal-body ' + FOCUSABLE) || el.querySelector(FOCUSABLE);
        if (first) first.focus();
    });
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (!el || !el.classList.contains('open')) return;
    el.classList.remove('open');
    const back = modalReturnFocus[id];
    delete modalReturnFocus[id];
    if (back && document.contains(back) && typeof back.focus === 'function') back.focus();
}

function topOpenModal() {
    const open = document.querySelectorAll('.modal-overlay.open');
    return open.length ? open[open.length - 1] : null;
}

document.addEventListener('click', function (e) {
    if (e.target.classList.contains('modal-overlay')) {
        closeModal(e.target.id);
    }
});

document.addEventListener('keydown', function (e) {
    const modal = topOpenModal();
    if (e.key === 'Escape') {
        if (modal) {
            // Let the check-in script reset its own state through its Cancel button
            const cancel = modal.querySelector('#ciEndCancel');
            if (cancel) cancel.click(); else closeModal(modal.id);
        } else if (sidebar && sidebar.classList.contains('open')) {
            closeSidebar(true);
        }
        return;
    }
    // Keep Tab inside an open modal
    if (e.key === 'Tab' && modal) {
        const items = Array.from(modal.querySelectorAll(FOCUSABLE)).filter(x => x.offsetParent !== null);
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    }
});

// ── Edit Court Modal pre-fill ───────────────────────────────────
function openEditModal(courtId, courtName, rate, status) {
    document.getElementById('editCourtName').value = courtName;
    document.getElementById('editCourtRate').value = rate;
    document.getElementById('editCourtStatus').value = status;
    document.getElementById('editCourtForm').action = '/update_court/' + courtId + '/';
    openModal('editCourtModal');
}

function openDamageModal(bookingId) {
    const form = document.getElementById('damageForm');
    if (form) form.action = '/add_damage/' + bookingId + '/';
    const title = document.getElementById('damageTitle');
    if (title) title.textContent = 'File Damage Report – Booking #' + bookingId;
    openModal('damageModal');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
}

function statusPill(text) {
    const slug = String(text || '').toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    return '<span class="status status-' + slug + '">' + escapeHtml(text) + '</span>';
}

function viewCustomerHistory(customerId, customerName) {
    document.getElementById('customerHistoryTitle').textContent = customerName + ' — Booking History';
    const tbody = document.getElementById('customerHistoryBody');
    tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><p>Loading…</p></div></td></tr>';

    fetch('/admin_customer_history/' + customerId + '/')
        .then(res => {
            if (!res.ok) throw new Error('HTTP ' + res.status);
            return res.json();
        })
        .then(data => {
            if (data.bookings.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><p>This customer has no bookings yet.</p></div></td></tr>';
                return;
            }
            tbody.innerHTML = data.bookings.map(b => `
                <tr>
                    <td class="mono">${escapeHtml(b.booking_id)}</td>
                    <td>Court ${escapeHtml(b.court_id)}</td>
                    <td>${escapeHtml(b.booking_date)}</td>
                    <td class="mono">${escapeHtml(b.start_time)}</td>
                    <td class="mono">${escapeHtml(b.end_time)}</td>
                    <td class="mono num">₱${escapeHtml(b.total_price)}</td>
                    <td>${statusPill(b.payment_status)}</td>
                    <td>${statusPill(b.booking_status)}</td>
                    <td>${escapeHtml(b.liabilities)}</td>
                </tr>
            `).join('');
        })
        .catch(() => {
            tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><p>Couldn\'t load the booking history. ' +
                'Check your connection and try again.</p></div></td></tr>';
        });

    openModal('customerHistoryModal');
}

// ── Messages (Django alerts) ────────────────────────────────────
function dismissAlert(el) {
    el.style.opacity = '0';
    setTimeout(function () { el.remove(); }, 300);
}

// ── Single DOMContentLoaded ─────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {

    // Assign sidebar elements AFTER DOM is ready
    sidebarToggle = document.getElementById('sidebarToggle');
    sidebar = document.getElementById('sidebar');
    sidebarOverlay = document.getElementById('sidebarOverlay');

    // Sidebar toggle button
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function () {
            sidebar.classList.contains('open') ? closeSidebar(true) : openSidebar();
        });
    }

    const sidebarClose = document.getElementById('sidebarClose');
    if (sidebarClose) sidebarClose.addEventListener('click', function () { closeSidebar(true); });

    // Close on overlay click
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', function () { closeSidebar(true); });
    }

    // Close on resize to desktop
    window.addEventListener('resize', function () {
        if (!isMobileNav()) closeSidebar();
    });

    // Nav clicks: after the page switches (inline onclick), move focus to its heading
    document.querySelectorAll('.sidebar .nav-link[data-page]').forEach(function (link) {
        link.addEventListener('click', function () {
            focusPageHeading(link.dataset.page);
        });
    });

    // Skip link: focus the main region without changing the page hash
    const skip = document.querySelector('.skip-link');
    if (skip) {
        skip.addEventListener('click', function (e) {
            e.preventDefault();
            const active = document.querySelector('.page.active .page-heading');
            (active || document.getElementById('mainContent')).focus();
        });
    }

    // Set date in header
    const dateEl = document.getElementById('headerDate');
    if (dateEl) {
        dateEl.textContent = new Date().toLocaleDateString('en-PH', {
            weekday: 'short', year: 'numeric', month: 'short', day: 'numeric'
        });
    }

    // Navigate to hash on load
    const hash = window.location.hash.replace('#', '');
    if (hash && PAGE_TITLES[hash]) {
        showPage(hash);
    } else {
        showPage('dashboard');
    }

    // Messages: success/info fade after 5s; errors and warnings stay until dismissed
    document.querySelectorAll('.alert').forEach(function (el) {
        const close = el.querySelector('.alert-close');
        if (close) close.addEventListener('click', function () { dismissAlert(el); });
        if (!el.classList.contains('alert-error') && !el.classList.contains('alert-warning')) {
            setTimeout(function () { if (!el.contains(document.activeElement)) dismissAlert(el); }, 5000);
        }
    });

    // Loading state on POST buttons, so a slow response isn't submitted twice.
    // Runs after inline confirm() handlers and after scripts that cancel the submit.
    document.addEventListener('submit', function (e) {
        if (e.defaultPrevented) return;
        const form = e.target;
        if ((form.getAttribute('method') || '').toUpperCase() !== 'POST') return;
        const btn = e.submitter || form.querySelector('button[type="submit"]');
        if (!btn) return;
        setTimeout(function () {
            btn.disabled = true;
            btn.classList.add('is-loading');
            btn.setAttribute('aria-busy', 'true');
        }, 0);
    });

    // Restore buttons if the page comes back from the browser's back/forward cache
    window.addEventListener('pageshow', function (e) {
        if (!e.persisted) return;
        document.querySelectorAll('.btn.is-loading').forEach(function (btn) {
            btn.disabled = false;
            btn.classList.remove('is-loading');
            btn.removeAttribute('aria-busy');
        });
    });
});
