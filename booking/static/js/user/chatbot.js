/*
 * Landing page chatbot ("Labra Assistant").
 * Quick buttons -> instant answers from our own data.
 * Typed questions -> /chatbot/ on our server, which asks Google Gemini
 * (the API key never reaches the browser) and falls back to built-in answers.
 */
(function () {
    const STORE = 'labra_chat_v1';
    let history = [];          // [{role: 'user'|'bot', text}]
    let busy = false;

    function el(id) { return document.getElementById(id); }

    function csrfToken() {
        const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        if (m) return decodeURIComponent(m[1]);
        const input = document.querySelector('input[name=csrfmiddlewaretoken]');
        return input ? input.value : '';
    }

    function save() {
        try { sessionStorage.setItem(STORE, JSON.stringify(history.slice(-30))); } catch (e) { /* ignore */ }
    }

    function load() {
        try { return JSON.parse(sessionStorage.getItem(STORE) || '[]') || []; } catch (e) { return []; }
    }

    function addMessage(role, text, remember) {
        const div = document.createElement('div');
        div.className = 'cb-msg ' + role;
        div.textContent = text;                 // plain text only: never HTML from the server
        el('cbLog').appendChild(div);
        el('cbLog').scrollTop = el('cbLog').scrollHeight;
        if (remember !== false && (role === 'user' || role === 'bot')) {
            history.push({ role: role, text: text });
            save();
        }
    }

    function showTyping(on) {
        const old = el('cbTyping');
        if (old) old.remove();
        if (!on) return;
        const div = document.createElement('div');
        div.className = 'cb-msg bot cb-typing';
        div.id = 'cbTyping';
        div.setAttribute('aria-label', 'Labra Assistant is typing');
        div.innerHTML = '<i></i><i></i><i></i>';
        el('cbLog').appendChild(div);
        el('cbLog').scrollTop = el('cbLog').scrollHeight;
    }

    function setBusy(on) {
        busy = on;
        el('cbSend').disabled = on;
        showTyping(on);
    }

    function send(payload) {
        if (busy) return;
        setBusy(true);
        fetch(el('chatbot').dataset.url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
            body: JSON.stringify(payload),
        })
            .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
            .then(function (data) {
                setBusy(false);
                addMessage('bot', data.reply || 'Sorry, something went wrong.');
            })
            .catch(function () {
                setBusy(false);
                addMessage('bot', 'Sorry, I can\'t connect right now. Please try again, or call +63 912 345 6789.', false);
            });
    }

    function ask(text) {
        text = text.trim();
        if (!text || busy) return;
        const earlier = history.slice(-6);
        addMessage('user', text);
        send({ message: text, history: earlier });
    }

    function quick(btn) {
        if (busy) return;
        addMessage('user', btn.textContent.trim());
        send({ intent: btn.dataset.intent });
    }

    function open() {
        const root = el('chatbot');
        root.classList.add('open');
        el('cbOpen').setAttribute('aria-expanded', 'true');
        el('cbPanel').setAttribute('aria-hidden', 'false');
        if (!el('cbLog').children.length) {
            addMessage('bot', 'Hi! I\'m Labra Assistant 🏀 Ask me about free times, rates, booking, payment or check-in. ' +
                'Pwede ka rin magtanong sa Tagalog o Bisaya.', false);
        }
        setTimeout(function () { el('cbInput').focus(); }, 60);
    }

    function close() {
        el('chatbot').classList.remove('open');
        el('cbOpen').setAttribute('aria-expanded', 'false');
        el('cbPanel').setAttribute('aria-hidden', 'true');
        el('cbOpen').focus();
    }

    document.addEventListener('DOMContentLoaded', function () {
        if (!el('chatbot')) return;
        // Keep the conversation while the visitor stays on the site (this tab only)
        load().forEach(function (m) { addMessage(m.role, m.text, false); });
        history = load();

        el('cbOpen').addEventListener('click', open);
        el('cbClose').addEventListener('click', close);
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && el('chatbot').classList.contains('open')) close();
        });
        el('cbForm').addEventListener('submit', function (e) {
            e.preventDefault();
            const input = el('cbInput');
            ask(input.value);
            input.value = '';
        });
        document.querySelectorAll('#chatbot .cb-chip').forEach(function (btn) {
            btn.addEventListener('click', function () { quick(btn); });
        });
    });
})();
