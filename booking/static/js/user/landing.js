/*
 * Landing page: mobile menu + Log in / Sign up pop-up.
 * The pop-up also has the "Confirm your email" (6-digit code), "Forgot
 * password" and "Set a new password" steps; only Log in / Sign up show tabs.
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
    const TITLES = {
        login: 'Welcome back', register: 'Create your account', verify: 'Confirm your email',
        forgot: 'Forgot password', reset: 'Set a new password',
    };

    function selectTab(name) {
        const tabs = document.querySelector('.auth-tabs');
        if (tabs) tabs.hidden = !(name === 'login' || name === 'register');
        document.querySelectorAll('.auth-tab').forEach(function (t) {
            const on = t.dataset.tab === name;
            t.classList.toggle('active', on);
            t.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        document.querySelectorAll('.auth-form').forEach(function (f) {
            f.hidden = f.dataset.panel !== name;
        });
        el('authTitle').textContent = TITLES[name] || 'Welcome back';
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
        if (/\/(login|register|verify-email|forgot-password|reset-password)\/?$/.test(window.location.pathname)) {
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

    // ── 6-digit code boxes ─────────────────────────────────────
    function setupCodeBoxes() {
        document.querySelectorAll('[data-otp]').forEach(function (group) {
            const boxes = Array.from(group.querySelectorAll('.otp-box'));
            const hidden = group.querySelector('input[name=code]');
            const sync = function () { hidden.value = boxes.map(function (b) { return b.value; }).join(''); };
            function fill(from, digits) {
                digits.split('').forEach(function (d, i) { if (boxes[from + i]) boxes[from + i].value = d; });
                const next = boxes[Math.min(from + digits.length, boxes.length - 1)];
                next.focus();
                sync();
            }
            boxes.forEach(function (box, i) {
                box.addEventListener('input', function () {
                    const digits = box.value.replace(/\D/g, '');
                    box.value = '';
                    if (digits) fill(i, digits.slice(0, boxes.length - i));   // typing or phone autofill
                    else sync();
                });
                box.addEventListener('keydown', function (e) {
                    if (e.key === 'Backspace' && !box.value && i > 0) { boxes[i - 1].value = ''; boxes[i - 1].focus(); sync(); e.preventDefault(); }
                    if (e.key === 'ArrowLeft' && i > 0) boxes[i - 1].focus();
                    if (e.key === 'ArrowRight' && i < boxes.length - 1) boxes[i + 1].focus();
                });
                box.addEventListener('paste', function (e) {
                    const digits = (e.clipboardData || window.clipboardData).getData('text').replace(/\D/g, '');
                    if (!digits) return;
                    e.preventDefault();
                    fill(0, digits.slice(0, boxes.length));
                });
                box.addEventListener('focus', function () { box.select(); });
            });
        });
    }

    function codeReady(form) {
        const group = form.querySelector('[data-otp]');
        const error = form.querySelector('[data-otp-error]');
        const ok = /^\d{6}$/.test(group.querySelector('input[name=code]').value);
        error.textContent = ok ? '' : 'Enter all 6 digits of the code.';
        group.classList.toggle('invalid', !ok);
        if (!ok) group.querySelector('.otp-box').focus();
        return ok;
    }

    // "Resend code" waits 60 seconds between emails (the server checks this too)
    function setupResendTimers() {
        document.querySelectorAll('[data-resend]').forEach(function (btn) {
            const label = btn.textContent;
            let left = parseInt(btn.dataset.wait || '0', 10);
            function tick() {
                btn.disabled = left > 0;
                btn.textContent = left > 0 ? label + ' (' + left + 's)' : label;
                if (left-- > 0) setTimeout(tick, 1000);
            }
            tick();
        });
    }

    function validateForgot(e) {
        const input = el('forgotEmail');
        const v = input.value.trim();
        const message = !v ? 'Enter your email address.' : (!EMAIL.test(v) ? 'Enter a valid email address, e.g. name@gmail.com.' : '');
        showError(input, el('forgotEmailError'), message);
        if (message) { e.preventDefault(); input.focus(); }
    }

    function validateReset(e) {
        const form = e.target;
        if (!codeReady(form)) { e.preventDefault(); return; }
        const pw = el('resetPassword');
        const confirm = el('resetConfirm');
        const message = !pw.value ? 'Enter a new password.' : (pw.value !== confirm.value ? 'Passwords do not match.' : '');
        showError(confirm, el('resetPasswordError'), message);
        if (message) { e.preventDefault(); (pw.value ? confirm : pw).focus(); }
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

        setupCodeBoxes();
        setupResendTimers();
        const forgot = modal.querySelector('[data-panel=forgot]');
        if (forgot) forgot.addEventListener('submit', validateForgot);
        const reset = modal.querySelector('[data-panel=reset]');
        if (reset) reset.addEventListener('submit', validateReset);
        const verify = modal.querySelector('[data-panel=verify]');
        if (verify) verify.addEventListener('submit', function (e) { if (!codeReady(verify)) e.preventDefault(); });

        // /login/ and /register/ open the pop-up straight away (with any server message)
        if (modal.dataset.open) openAuth(modal.dataset.open, true);
    });
})();
