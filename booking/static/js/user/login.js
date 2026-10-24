function showRegister() {
    document.getElementById('loginForm').style.display = 'none';
    document.getElementById('registerForm').style.display = 'block';
}

function showLogin() {
    document.getElementById('registerForm').style.display = 'none';
    document.getElementById('loginForm').style.display = 'block';
}
function showModal(message) {
    const modal = document.getElementById('loginMessageModal');
    document.getElementById('modalMessage').textContent = message;
    modal.classList.add('show');
}

function closeModal() {
    document.getElementById('loginMessageModal').classList.remove('show');
}
document.getElementById('closeModal').addEventListener('click', closeModal);
document.getElementById('loginMessageModal').addEventListener('click', function (e) {
    if (e.target === this) closeModal();
});
document.addEventListener('DOMContentLoaded', function () {
    const messagesEl = document.getElementById('loginMessages');
    if (messagesEl) {
        const raw = messagesEl.getAttribute('data-messages');
        if (raw && raw.trim() !== '') {
            const messages = raw.split('|').map(m => m.trim()).filter(m => m);
            if (messages.length > 0) {
                showModal(messages.join('\n'));
            }
        }
    }
});