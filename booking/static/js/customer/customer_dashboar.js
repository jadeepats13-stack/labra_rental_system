const now = new Date();
document.getElementById('currentDate').textContent =
    now.toLocaleDateString('en-PH', {
        weekday: 'short',
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });

document.addEventListener('DOMContentLoaded', function () {
    const paymentMsg = sessionStorage.getItem('paymentSuccess');
    if (paymentMsg) {
        sessionStorage.removeItem('paymentSuccess');
        const alertDiv = document.createElement('div');
        alertDiv.className = 'alert alert-success';
        alertDiv.textContent = paymentMsg;
        alertDiv.style.margin = '16px 32px 0';
        const content = document.querySelector('.main-content');
        if (content) content.insertBefore(alertDiv, content.children[1]);
        setTimeout(function () {
            alertDiv.style.transition = 'opacity 0.6s ease';
            alertDiv.style.opacity = '0';
            setTimeout(function () { alertDiv.remove(); }, 600);
        }, 4000);
    }
    const statCards = document.querySelectorAll('.stat-card');
    statCards.forEach(function (card, index) {
        card.style.opacity = '0';
        card.style.transform = 'translateY(16px)';
        setTimeout(function () {
            card.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
            card.style.opacity = '1';
            card.style.transform = 'translateY(0)';
        }, index * 100);
    });

    const courtCards = document.querySelectorAll('.court-card');
    courtCards.forEach(function (card, index) {
        card.style.opacity = '0';
        card.style.transform = 'translateY(12px)';
        setTimeout(function () {
            card.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
            card.style.opacity = '1';
            card.style.transform = 'translateY(0)';
        }, 200 + index * 80);
    });

    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(function (alert) {
        setTimeout(function () {
            alert.style.transition = 'opacity 0.6s ease';
            alert.style.opacity = '0';
            setTimeout(function () { alert.style.display = 'none'; }, 600);
        }, 3000);
    });

});