/*
 * Landing page: mobile menu + Log in / Sign up pop-up.
 * The forms post to /login/ and /register/; the server re-checks everything.
 * These checks only give quicker feedback (e.g. an invalid email).
 */
(function () {
    const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
    let lastFocus = null;

    function el(id) { return document.getElementById(id); }

    // ── Mobile menu ────────────────────────────────────────────
    function setupMenu() {
        const toggle = el('menuToggle');
        const links = el('navLinks');
        if (!toggle || !links) return;
        toggle.addEventListener('click', function () {
            const open = links.classList.toggle('open');
            toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
        links.querySelectorAll('a').forEach(function (a) {
            a.addEventListener('click', function () {
                links.classList.remove('open');
                toggle.setAttribute('aria-expanded', 'false');
            });
        });
    }

    // ── Pop-up ─────────────────────────────────────────────────
    function selectTab(name) {
        document.querySelectorAll('.auth-tab').forEach(function (t) {
            const on = t.dataset.tab === name;
            t.classList.toggle('active', on);
            t.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        document.querySelectorAll('.auth-form').forEach(function (f) {
            f.hidden = f.dataset.panel !== name;
        });
        el('authTitle').textContent = name === 'register' ? 'Create your account' : 'Welcome back';
    }

    function openAuth(name, keepMessages) {
        const modal = el('authModal');
        if (!keepMessages) {
            const msgs = modal.querySelector('.auth-messages');
            if (msgs) msgs.remove();
        }
        selectTab(name);
        lastFocus = document.activeElement;
        modal.hidden = false;
        document.body.style.overflow = 'hidden';
        const first = modal.querySelector('.auth-form:not([hidden]) input:not([type=hidden])');
        if (first) setTimeout(function () { first.focus(); }, 30);
    }

    function closeAuth() {
        el('authModal').hidden = true;
        document.body.style.overflow = '';
        if (lastFocus) lastFocus.focus();
        // leave /login/ or /register/ so a refresh doesn't reopen the pop-up
        if (/\/(login|register)\/?$/.test(window.location.pathname)) {
            history.replaceState(null, '', '/');
        }
    }

    // ── Validation (quick feedback; the server checks again) ───
    function showError(input, errorEl, message) {
        errorEl.textContent = message || '';
        input.classList.toggle('invalid', !!message);
        input.setAttribute('aria-invalid', message ? 'true' : 'false');
    }

    function validateLogin(e) {
        const input = el('loginIdentifier');
        const value = input.value.trim();
        let message = '';
        if (!value) message = 'Enter your username or email.';
        else if (value.indexOf('@') !== -1 && !EMAIL.test(value)) {
            message = 'That email address is not valid. Check it and try again.';
        }
        showError(input, el('loginIdentifierError'), message);
        const pw = e.target.querySelector('input[name=password]');
        if (!message && !pw.value) { message = 'Enter your password.'; pw.focus(); }
        if (message) { e.preventDefault(); if (value) input.focus(); }
    }

    function validateRegister(e) {
        const form = e.target;
        let firstBad = null;
        const email = el('registerEmail');
        const emailMsg = !email.value.trim() ? 'Enter your email address.'
            : (!EMAIL.test(email.value.trim()) ? 'Enter a valid email address, e.g. name@gmail.com.' : '');
        showError(email, el('registerEmailError'), emailMsg);
        if (emailMsg) firstBad = email;

        const pw = el('registerPassword');
        const confirm = el('registerConfirm');
        let pwMsg = '';
        if (!pw.value) pwMsg = 'Enter a password.';
        else if (pw.value !== confirm.value) pwMsg = 'Passwords do not match.';
        showError(confirm, el('registerPasswordError'), pwMsg);
        if (pwMsg && !firstBad) firstBad = pw.value ? confirm : pw;

        form.querySelectorAll('input[required]').forEach(function (input) {
            const empty = !input.value.trim();
            if (input !== email && input !== pw && input !== confirm) input.classList.toggle('invalid', empty);
            if (empty && !firstBad) firstBad = input;
        });

        if (firstBad) { e.preventDefault(); firstBad.focus(); }
    }

    document.addEventListener('DOMContentLoaded', function () {
        setupMenu();
        const modal = el('authModal');
        if (!modal) return;

        document.querySelectorAll('[data-auth]').forEach(function (btn) {
            btn.addEventListener('click', function () { openAuth(btn.dataset.auth); });
        });
        document.querySelectorAll('.auth-tab').forEach(function (t) {
            t.addEventListener('click', function () { selectTab(t.dataset.tab); });
        });
        document.querySelectorAll('[data-tab-link]').forEach(function (b) {
            b.addEventListener('click', function () { selectTab(b.dataset.tabLink); });
        });
        el('authClose').addEventListener('click', closeAuth);
        modal.addEventListener('click', function (e) { if (e.target === modal) closeAuth(); });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && !modal.hidden) closeAuth();
        });

        document.querySelectorAll('.pw-toggle').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const input = btn.previousElementSibling;
                const show = input.type === 'password';
                input.type = show ? 'text' : 'password';
                btn.textContent = show ? 'Hide' : 'Show';
                btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
            });
        });

        el('registerEmail').addEventListener('blur', function () {
            const v = this.value.trim();
            showError(this, el('registerEmailError'),
                v && !EMAIL.test(v) ? 'Enter a valid email address, e.g. name@gmail.com.' : '');
        });
        modal.querySelector('[data-panel=login]').addEventListener('submit', validateLogin);
        modal.querySelector('[data-panel=register]').addEventListener('submit', validateRegister);

        // /login/ and /register/ open the pop-up straight away (with any server message)
        if (modal.dataset.open) openAuth(modal.dataset.open, true);
    });
})();
