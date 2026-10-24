// ── Sidebar variables (declared here, assigned in DOMContentLoaded) ──
let sidebarToggle, sidebar, sidebarOverlay;

function openSidebar() {
    if (!sidebar) return;
    sidebar.style.transform = 'translateX(0)';
    sidebar.classList.add('open');
    sidebarOverlay.classList.add('visible');
    sidebarToggle.classList.add('open');
}

function closeSidebar() {
    if (!sidebar) return;
    sidebar.style.transform = 'translateX(-100%)';
    sidebar.classList.remove('open');
    sidebarOverlay.classList.remove('visible');
    if (sidebarToggle) sidebarToggle.classList.remove('open');
}

// ── Page navigation ─────────────────────────────────────────────
const PAGE_TITLES = {
    dashboard: 'Dashboard',
    courts: 'Manage Courts',
    bookings: 'Manage Bookings',
    customers: 'Manage Customers',
    payments: 'Payments',
    damages: 'Damage Reports',
    records: 'Booking Records',
};

function showPage(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(n => n.classList.remove('active'));

    const page = document.getElementById('page-' + pageId);
    if (page) page.classList.add('active');

    const link = document.querySelector('[data-page="' + pageId + '"]');
    if (link) link.classList.add('active');

    const titleEl = document.getElementById('headerTitle');
    if (titleEl) titleEl.textContent = PAGE_TITLES[pageId] || 'Admin Dashboard';

    history.replaceState(null, '', '#' + pageId);

    // Close sidebar on mobile
    if (window.innerWidth <= 900) {
        setTimeout(closeSidebar, 50);
    }
}

// ── Modal helpers ───────────────────────────────────────────────
function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('open');
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('open');
}

document.addEventListener('click', function (e) {
    if (e.target.classList.contains('modal-overlay')) {
        e.target.classList.remove('open');
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
    openModal('damageModal');
}

function viewCustomerHistory(customerId, customerName) {
    document.getElementById('customerHistoryTitle').textContent = customerName + ' — Booking History';
    const tbody = document.getElementById('customerHistoryBody');
    tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><p>Loading...</p></div></td></tr>';

    fetch('/admin_customer_history/' + customerId + '/')
        .then(res => res.json())
        .then(data => {
            if (data.bookings.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><p>No bookings found.</p></div></td></tr>';
                return;
            }
            tbody.innerHTML = data.bookings.map(b => `
                <tr>
                    <td class="mono">${b.booking_id}</td>
                    <td>Court ${b.court_id}</td>
                    <td>${b.booking_date}</td>
                    <td class="mono">${b.start_time}</td>
                    <td class="mono">${b.end_time}</td>
                    <td class="mono">₱${b.total_price}</td>
                    <td>${b.payment_status}</td>
                    <td>${b.booking_status}</td>
                    <td>${b.liabilities}</td>
                </tr>
            `).join('');
        });

    openModal('customerHistoryModal');
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
            sidebar.classList.contains('open') ? closeSidebar() : openSidebar();
        });
    }

    // Close on overlay click
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', closeSidebar);
    }

    // Close on resize to desktop
    window.addEventListener('resize', function () {
        if (window.innerWidth > 900) closeSidebar();
    });

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

    // Auto-dismiss alerts after 4s
    document.querySelectorAll('.alert').forEach(function (el) {
        setTimeout(function () {
            el.style.transition = 'opacity 0.4s';
            el.style.opacity = '0';
            setTimeout(function () { el.remove(); }, 400);
        }, 4000);
    });

    // Horizontal scroll drag + wheel on all table wraps
    document.querySelectorAll('.table-wrap').forEach(function (el) {
        let isDown = false;
        let startX, scrollLeft;

        el.addEventListener('mousedown', function (e) {
            isDown = true;
            el.style.cursor = 'grabbing';
            startX = e.pageX - el.offsetLeft;
            scrollLeft = el.scrollLeft;
        });

        el.addEventListener('mouseleave', function () {
            isDown = false;
            el.style.cursor = 'grab';
        });

        el.addEventListener('mouseup', function () {
            isDown = false;
            el.style.cursor = 'grab';
        });

        el.addEventListener('mousemove', function (e) {
            if (!isDown) return;
            e.preventDefault();
            const x = e.pageX - el.offsetLeft;
            const walk = (x - startX) * 2;
            el.scrollLeft = scrollLeft - walk;
        });

        // Mouse wheel horizontal scroll
        el.addEventListener('wheel', function (e) {
            if (e.deltaY !== 0) {
                e.preventDefault();
                el.scrollLeft += e.deltaY * 1.5;
            }
        }, { passive: false });

        // Touch support
        let touchStartX, touchScrollLeft;
        el.addEventListener('touchstart', function (e) {
            touchStartX = e.touches[0].pageX - el.offsetLeft;
            touchScrollLeft = el.scrollLeft;
        });

        el.addEventListener('touchmove', function (e) {
            const x = e.touches[0].pageX - el.offsetLeft;
            const walk = (x - touchStartX) * 2;
            el.scrollLeft = touchScrollLeft - walk;
        });
    });
});