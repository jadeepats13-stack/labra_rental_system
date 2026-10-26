/*
 * Customer pages: shared interface behaviour.
 *  - Messages: success/info fade after 5s, errors and warnings stay until dismissed
 *  - window.showFlash(text, type): show a message in the same place (used after PayPal)
 *  - POST buttons show a loading state so a slow response isn't submitted twice
 *  - Payment pop-up: Escape closes it, focus moves into it and back again
 */
(function () {
    function dismiss(el) {
        el.style.opacity = '0';
        setTimeout(function () {
            const area = el.parentElement;
            el.remove();
            if (area && area.classList.contains('flash-area') && !area.children.length) area.hidden = true;
        }, 300);
    }

    function wireAlert(el) {
        const close = el.querySelector('.alert-close');
        if (close) close.addEventListener('click', function () { dismiss(el); });
        if (!el.classList.contains('alert-error') && !el.classList.contains('alert-warning')) {
            setTimeout(function () { if (!el.contains(document.activeElement)) dismiss(el); }, 5000);
        }
    }

    window.showFlash = function (text, type) {
        const area = document.getElementById('flashArea');
        if (!area) return;
        const kind = type || 'success';
        const el = document.createElement('div');
        el.className = 'alert alert-' + kind;
        el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
        const icon = kind === 'success' ? 'i-check' : (kind === 'error' || kind === 'warning') ? 'i-error' : 'i-info';
        el.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#' + icon + '"/></svg>' +
            '<span class="alert-text"></span>' +
            '<button type="button" class="alert-close" aria-label="Dismiss message">' +
            '<svg class="icon" aria-hidden="true"><use href="#i-close"/></svg></button>';
        el.querySelector('.alert-text').textContent = text;   // message text never parsed as HTML
        area.hidden = false;
        area.appendChild(el);
        wireAlert(el);
    };

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.flash-area .alert, .main-content > .alert').forEach(wireAlert);

        // Loading state on POST buttons. Runs after inline confirm() checks and
        // after scripts that cancel the submit (those set defaultPrevented).
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

        // Coming back with the browser's Back button: buttons work again
        window.addEventListener('pageshow', function (e) {
            if (!e.persisted) return;
            document.querySelectorAll('.is-loading').forEach(function (btn) {
                btn.disabled = false;
                btn.classList.remove('is-loading');
                btn.removeAttribute('aria-busy');
            });
        });

        // Payment pop-up (dashboard only)
        const modal = document.getElementById('paymentModal');
        if (!modal) return;
        let returnFocus = null;
        document.addEventListener('click', function (e) {
            const btn = e.target.closest('.pay-now-btn');
            if (!btn) return;
            returnFocus = btn;
            requestAnimationFrame(function () {
                const first = modal.querySelector('.payment-method input');
                if (first && modal.classList.contains('open')) first.focus();
            });
        });
        const close = function () {
            if (typeof window.closePaymentModal === 'function') window.closePaymentModal();
            if (returnFocus && document.contains(returnFocus)) returnFocus.focus();
        };
        modal.addEventListener('click', function (e) { if (e.target === modal && returnFocus) returnFocus.focus(); });
        modal.querySelectorAll('.modal-x, .modal-actions .btn-outline').forEach(function (b) {
            b.addEventListener('click', function () { if (returnFocus && document.contains(returnFocus)) returnFocus.focus(); });
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modal.classList.contains('open')) close();
        });
    });
})();
