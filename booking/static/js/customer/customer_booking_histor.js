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
        dashboard: 'Customer Dashboard',
        book: 'Book a Court',
        bookings: 'My Bookings',
        history: 'Booking History',
        payment: 'Payment',
        profile: 'Edit Profile'
    };
    document.querySelector('.page-title').innerHTML =
        pageNames[pageId]?.replace(/(\S+)$/, '<span>$1</span>') || 'Dashboard';
}
document.querySelectorAll('.table-wrap').forEach(function (el) {
    let isDown = false;
    let startX;
    let scrollLeft;

    el.addEventListener('mousedown', function (e) {
        isDown = true;
        el.style.cursor = 'grabbing';
        startX = e.pageX - el.offsetLeft;
        scrollLeft = el.scrollLeft;
    });

    el.addEventListener('mouseleave', function () {
        isDown = false;
        el.style.cursor = 'grab';
    });

    el.addEventListener('mouseup', function () {
        isDown = false;
        el.style.cursor = 'grab';
    });

    el.addEventListener('mousemove', function (e) {
        if (!isDown) return;
        e.preventDefault();
        const x = e.pageX - el.offsetLeft;
        const walk = (x - startX) * 2;
        el.scrollLeft = scrollLeft - walk;
    });

    el.addEventListener('touchstart', function (e) {
        startX = e.touches[0].pageX - el.offsetLeft;
        scrollLeft = el.scrollLeft;
    });

    el.addEventListener('touchmove', function (e) {
        const x = e.touches[0].pageX - el.offsetLeft;
        const walk = (x - startX) * 2;
        el.scrollLeft = scrollLeft - walk;
    });
});