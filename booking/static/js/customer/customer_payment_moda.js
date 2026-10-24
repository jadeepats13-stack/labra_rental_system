function openPaymentModal(bookingId, court, date, start, end, total) {
    document.getElementById('sum-booking').textContent = '#' + bookingId;
    document.getElementById('sum-court').textContent = court;
    document.getElementById('sum-date').textContent = date;
    document.getElementById('sum-time').textContent = start + ' - ' + end;
    document.getElementById('sum-total').textContent = '₱' + total;
    document.getElementById('pay-booking-id').value = bookingId;
    document.getElementById('paymentModal').classList.add('active');
}

function closePaymentModal() {
    document.getElementById('paymentModal').classList.remove('active');
    document.getElementById('dashboard-paypal-container').innerHTML = '';
}

function selectPayMethod(el) {
    document.querySelectorAll('.payment-method').forEach(m => m.classList.remove('selected'));
    el.classList.add('selected');
    el.querySelector('input[type=radio]').checked = true;

    const paypalContainer = document.getElementById('dashboard-paypal-container');
    const payBtn = document.getElementById('dashboard-pay-btn');

    if (el.querySelector('input').value === 'Online') {
        paypalContainer.style.display = 'block';
        payBtn.style.display = 'none';
    } else {
        paypalContainer.style.display = 'none';
        payBtn.style.display = 'inline-flex';
    }
}

document.addEventListener('DOMContentLoaded', function () {
    const modal = document.getElementById('paymentModal');
    if (modal) modal.addEventListener('click', function (e) {
        if (e.target === this) closePaymentModal();
    });
});