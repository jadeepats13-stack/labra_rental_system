const BOOKING_ID = bookingData.bookingId;
const CSRF_TOKEN = bookingData.csrfToken;
let selectedMethod = null;

function selectPaymentMethod(element, method) {
    document.querySelectorAll('.payment-method').forEach(m => m.classList.remove('selected'));
    element.classList.add('selected');
    element.querySelector('input[type=radio]').checked = true;
    selectedMethod = method;

    const paypalContainer = document.getElementById('paypal-button-container');
    const payBtn = document.getElementById('payBtn');

    if (method === 'Online') {
        paypalContainer.style.display = 'block';
        payBtn.style.display = 'none';
    } else {
        paypalContainer.style.display = 'none';
        payBtn.style.display = 'inline-flex';
        payBtn.disabled = false;
    }
}

paypal.Buttons({
    createOrder: async function () {
        const res = await fetch('/create_paypal_order/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN
            },
            body: JSON.stringify({ booking_id: BOOKING_ID })
        });
        const data = await res.json();
        return data.id;
    },

    onApprove: async function (data) {
        const res = await fetch('/capture_paypal_order/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN
            },
            body: JSON.stringify({
                order_id: data.orderID,
                booking_id: BOOKING_ID
            })
        });
        const result = await res.json();
        if (result.status === 'COMPLETED') {
            window.location.href = '/customer_dashboard/#payment';
        } else {
            window.location.href = '/customer_dashboard/#payment';
        }
    },

    onError: function (err) {
        console.error('PayPal error:', err);
    }

}).render('#paypal-button-container');

const now = new Date();
document.getElementById('currentDate').textContent =
    now.toLocaleDateString('en-PH', { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });