/*
 * Dashboard "This Week" strip: tapping a day opens Book Court on that date.
 * Booked times are greyed out in the Start/End time lists
 * (customer_book_court.js reads them from /availability/).
 */
(function () {
    window.openBookingOn = function (dateStr) {
        showPage('book');
        if (window.LabraBooking) window.LabraBooking.pickDate(dateStr);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };
})();
