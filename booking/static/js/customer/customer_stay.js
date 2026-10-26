/*
 * Customer pages: stay on the same page after submitting a form.
 *
 * - Every POST form sends "return_to" = the page that is open now
 *   (bookings, payment, profile, ...). The server redirects back to
 *   /customer_dashboard/#<that page> instead of the Dashboard.
 * - On load, #bookings, #payment, ... open that page directly.
 * Load this after the other customer scripts.
 */
(function () {
    const PAGES = ['dashboard', 'book', 'bookings', 'history', 'payment', 'profile'];

    function activePage() {
        const page = document.querySelector('.page-content.active');
        const id = page ? page.id.replace(/^page-/, '') : '';
        return PAGES.indexOf(id) !== -1 ? id : 'dashboard';
    }

    // Add the current page to every POST form just before it is sent
    document.addEventListener('submit', function (e) {
        const form = e.target;
        if (!form || (form.method || '').toLowerCase() !== 'post') return;
        let input = form.querySelector('input[name="return_to"]');
        if (!input) {
            input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'return_to';
            form.appendChild(input);
        }
        input.value = activePage();
    }, true);

    document.addEventListener('DOMContentLoaded', function () {
        if (typeof showPage !== 'function') return;
        const hash = window.location.hash.replace('#', '');
        if (PAGES.indexOf(hash) !== -1) showPage(hash);
        // The address bar follows the page, so a refresh stays there too
        const originalShowPage = showPage;
        showPage = function (pageId) {
            originalShowPage(pageId);
            if (PAGES.indexOf(pageId) !== -1) history.replaceState(null, '', '#' + pageId);
        };
        // A link or bookmark that only changes the #page opens that page too
        window.addEventListener('hashchange', function () {
            const id = window.location.hash.replace('#', '');
            if (PAGES.indexOf(id) !== -1) showPage(id);
        });
    });
})();
