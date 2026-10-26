/*
 * Dark / light theme switch (admin panel and customer pages).
 *
 * The saved theme is applied in <head> by templates/common/theme_init.html
 * before the page paints. This script only handles the button:
 *   <button data-theme-toggle data-theme-key="labra-theme-admin">…</button>
 * Each interface keeps its own key, so admin and customer choices are independent.
 *
 * Clicking the button fades the whole page to the other theme (about 0.3 s):
 *   - browsers with the View Transitions API cross-fade the page in one piece;
 *   - other browsers fade colours, backgrounds and borders with CSS transitions.
 * People who turned on "reduce motion" get an instant switch.
 */
(function () {
    const FADE_MS = 300;
    let fadeTimer = null;

    function current() {
        return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    }

    function reducedMotion() {
        return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    }

    function setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        const dark = theme === 'dark';
        document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
            btn.setAttribute('aria-pressed', dark ? 'true' : 'false');
            btn.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
        });
    }

    // Instant switch (page load, other tabs, reduced motion): no half-faded mix
    function switchInstantly(theme) {
        const root = document.documentElement;
        root.classList.add('theme-switching');
        setTheme(theme);
        void root.offsetWidth;
        requestAnimationFrame(function () { root.classList.remove('theme-switching'); });
    }

    function switchSmoothly(theme) {
        if (document.startViewTransition) {
            document.startViewTransition(function () { setTheme(theme); });
            return;
        }
        const root = document.documentElement;
        root.classList.add('theme-fading');
        setTheme(theme);
        clearTimeout(fadeTimer);
        fadeTimer = setTimeout(function () { root.classList.remove('theme-fading'); }, FADE_MS + 50);
    }

    function apply(theme, animate) {
        if (animate && !reducedMotion()) switchSmoothly(theme);
        else switchInstantly(theme);
    }

    document.addEventListener('DOMContentLoaded', function () {
        apply(current(), false);
        document.addEventListener('click', function (e) {
            const btn = e.target.closest('[data-theme-toggle]');
            if (!btn) return;
            const next = current() === 'dark' ? 'light' : 'dark';
            apply(next, true);
            try { localStorage.setItem(btn.dataset.themeKey, next); } catch (err) { /* storage blocked */ }
        });
    });

    // Another open tab of the same interface changed the theme
    window.addEventListener('storage', function (e) {
        const btn = document.querySelector('[data-theme-toggle]');
        if (btn && e.key === btn.dataset.themeKey && (e.newValue === 'dark' || e.newValue === 'light')) apply(e.newValue, false);
    });
})();
