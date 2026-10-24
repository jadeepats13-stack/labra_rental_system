function showPage(pageId) {
    document.querySelectorAll('.page-content').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.getElementById('page-' + pageId).classList.add('active');

    document.querySelectorAll('.nav-item').forEach(n => {
        if (n.getAttribute('onclick') && n.getAttribute('onclick').includes(`'${pageId}'`)) {
            n.classList.add('active');
        }
    });

    const pageNames = {
        dashboard: 'Customer Dashboard', book: 'Book a Court',
        bookings: 'My Bookings', history: 'Booking History',
        payment: 'Payment', profile: 'Edit Profile'
    };
    document.querySelector('.page-title').innerHTML =
        pageNames[pageId]?.replace(/(\S+)$/, '<span>$1</span>') || 'Dashboard';
}
document.addEventListener('DOMContentLoaded', function () {
    const hash = window.location.hash.replace('#', '');
    if (['dashboard', 'book', 'bookings', 'history', 'payment', 'profile'].includes(hash)) {
        showPage(hash);
    }
});