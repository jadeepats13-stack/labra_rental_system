const now = new Date();
document.getElementById('currentDate').textContent =
    now.toLocaleDateString('en-PH', {
        weekday: 'short',
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });

document.addEventListener('DOMContentLoaded', function () {
    // Message saved before a redirect (e.g. after a payment)
    const paymentMsg = sessionStorage.getItem('paymentSuccess');
    if (paymentMsg) {
        sessionStorage.removeItem('paymentSuccess');
        if (typeof window.showFlash === 'function') window.showFlash(paymentMsg, 'success');
    }
});
