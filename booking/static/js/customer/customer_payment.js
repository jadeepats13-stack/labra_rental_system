var dashboardBookingId = null;

function openPaymentModal(bookingId, courtName, date, start, end, total) {
    document.getElementById('sum-booking').textContent = '#' + bookingId;
    document.getElementById('sum-court').textContent = courtName;
    document.getElementById('sum-date').textContent = date;
    document.getElementById('sum-time').textContent = start + ' – ' + end;
    document.getElementById('sum-total').textContent = '₱' + total;
    document.getElementById('pay-booking-id').value = bookingId;
    dashboardBookingId = bookingId;

    // Reset payment method selection
    document.querySelectorAll('.payment-method').forEach(m => m.classList.remove('selected'));

    // Clear and hide PayPal container
    const paypalContainer = document.getElementById('dashboard-paypal-container');
    paypalContainer.style.display = 'none';
    paypalContainer.innerHTML = '';
    paypalContainer.dataset.rendered = 'false';

    // Show confirm button
    document.getElementById('dashboard-pay-btn').style.display = 'inline-flex';

    // Open modal
    document.getElementById('paymentModal').classList.add('open');
}

function selectPayMethod(el) {
    document.querySelectorAll('.payment-method').forEach(m => m.classList.remove('selected'));
    el.classList.add('selected');
    el.querySelector('input[type=radio]').checked = true;

    const paypalContainer = document.getElementById('dashboard-paypal-container');
    const payBtn = document.getElementById('dashboard-pay-btn');

    if (el.querySelector('input').value === 'Online') {
        if (paypalContainer.dataset.rendered === 'true') return;
        paypalContainer.dataset.rendered = 'true';

        paypalContainer.innerHTML = '';
        paypalContainer.style.display = 'block';
        payBtn.style.display = 'none';

        paypal.Buttons({
            createOrder: async function () {
                const res = await fetch('/create_paypal_order/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': dashboardData.csrfToken
                    },
                    body: JSON.stringify({ booking_id: dashboardBookingId })
                });
                const data = await res.json();
                return data.id;
            },
            onApprove: async function (data) {
                const res = await fetch('/capture_paypal_order/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': dashboardData.csrfToken
                    },
                    body: JSON.stringify({
                        order_id: data.orderID,
                        booking_id: dashboardBookingId
                    })
                });
                const result = await res.json();
                if (result.status === 'COMPLETED') {
                    closePaymentModal();

                    const alertDiv = document.createElement('div');
                    alertDiv.className = 'alert alert-success';
                    alertDiv.textContent = 'Payment completed successfully via PayPal!';
                    alertDiv.style.margin = '16px 32px 0';
                    const content = document.querySelector('.main-content');
                    if (content) content.insertBefore(alertDiv, content.children[1]);

                    setTimeout(function () {
                        alertDiv.style.transition = 'opacity 0.6s ease';
                        alertDiv.style.opacity = '0';
                        setTimeout(function () { alertDiv.remove(); }, 600);
                    }, 4000);

                    const payNowBtn = document.querySelector(`.pay-now-btn[data-id="${dashboardBookingId}"]`);
                    if (payNowBtn) {
                        payNowBtn.closest('.action-btns').innerHTML = '<span style="font-size:12px; color:#22c55e; font-weight:600;">Paid</span>';
                    }
                    showPage('bookings');
                }
            },
            onError: function (err) { console.error('PayPal error:', err); }
        }).render('#dashboard-paypal-container');

    } else {
        paypalContainer.innerHTML = '';
        paypalContainer.style.display = 'none';
        paypalContainer.dataset.rendered = 'false';
        payBtn.style.display = 'inline-flex';
    }
}

function closePaymentModal() {
    document.getElementById('paymentModal').classList.remove('open');
    const paypalContainer = document.getElementById('dashboard-paypal-container');
    paypalContainer.innerHTML = '';
    paypalContainer.style.display = 'none';
    paypalContainer.dataset.rendered = 'false';
}

document.addEventListener('DOMContentLoaded', function () {
    // Close modal when clicking outside
    const modal = document.getElementById('paymentModal');
    if (modal) {
        modal.addEventListener('click', function (e) {
            if (e.target === this) closePaymentModal();
        });
    }

    // Pay Now button click handler
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.pay-now-btn');
        if (!btn) return;
        openPaymentModal(
            btn.dataset.id,
            btn.dataset.court,
            btn.dataset.date,
            btn.dataset.start,
            btn.dataset.end,
            btn.dataset.total
        );
    });
});