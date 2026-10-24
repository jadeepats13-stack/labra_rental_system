/*
 * Customer availability calendar (Book Court page) and dashboard helpers.
 *
 * - Taken slots come from /availability/ (our own database). Other
 *   customers' bookings arrive only as "Booked": no names or details.
 * - Day headers show the OpenWeatherMap forecast (cached on the server).
 * - Clicking a free slot fills in the booking form's date and start time.
 * Uses FullCalendar (MIT licence, served from /static/vendor/fullcalendar/).
 */
(function () {
    let calendar = null;
    let loaded = { events: [], weather: {}, now: null };

    function el(id) { return document.getElementById(id); }
    function pad(n) { return String(n).padStart(2, '0'); }
    function isoDate(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
    function hhmm(d) { return pad(d.getHours()) + ':' + pad(d.getMinutes()); }

    function notice(text) {
        const box = el('availNotice');
        if (!box) return;
        box.textContent = text || '';
        box.style.display = text ? 'block' : 'none';
        if (text) {
            clearTimeout(notice.timer);
            notice.timer = setTimeout(function () { box.style.display = 'none'; }, 4000);
        }
    }

    function serverNow() {
        return loaded.now ? new Date(loaded.now) : new Date();
    }

    function headerHtml(arg) {
        const d = arg.date;
        const w = loaded.weather[isoDate(d)];
        const day = d.toLocaleDateString('en-PH', { weekday: 'short' });
        let weather = '<span class="cal-day-weather"></span>';
        if (w) {
            weather = '<span class="cal-day-weather" title="' + w.description + ', ' + w.rain_chance +
                '% chance of rain"><img src="' + w.icon_url + '" alt="' + w.description + '">' +
                w.temperature + '°</span>';
        }
        return { html: '<span class="cal-day-name">' + day + '</span><span class="cal-day-num">' +
            d.getDate() + '</span>' + weather };
    }

    function loadEvents(info, success, failure) {
        const url = el('availCalendar').dataset.url +
            '?start=' + encodeURIComponent(info.startStr) + '&end=' + encodeURIComponent(info.endStr);
        fetch(url, { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
            .then(function (data) {
                const hadWeather = Object.keys(loaded.weather).length > 0;
                loaded = { events: data.events || [], weather: data.weather || {}, now: data.now };
                success(loaded.events);
                // Redraw the day headers once the forecast has arrived
                if (!hadWeather && Object.keys(loaded.weather).length) {
                    calendar.setOption('dayHeaderContent', function (arg) { return headerHtml(arg); });
                }
            })
            .catch(function () {
                notice('Availability could not be loaded. You can still book using the form below.');
                failure();
            });
    }

    function onSlotClick(info) {
        const start = info.date;
        const end = new Date(start.getTime() + 30 * 60000);
        if (start < serverNow()) {
            notice('That time has already passed. Please pick a later slot.');
            return;
        }
        const taken = loaded.events.some(function (e) {
            return new Date(e.start) < end && new Date(e.end) > start;
        });
        if (taken) {
            notice('That time is already booked. Please pick an empty slot.');
            return;
        }
        if (!window.LabraBooking) return;
        window.LabraBooking.pickSlot(isoDate(start), hhmm(start)).then(function (ok) {
            if (ok === false) notice('That time is not available. Please pick another slot.');
            else notice('');
        });
    }

    function initCalendar() {
        const box = el('availCalendar');
        if (calendar || !box || typeof FullCalendar === 'undefined') return;
        const narrow = window.innerWidth < 700;
        const today = new Date();
        calendar = new FullCalendar.Calendar(box, {
            initialView: narrow ? 'threeDays' : 'sevenDays',
            views: {
                sevenDays: { type: 'timeGrid', duration: { days: 7 }, buttonText: '7 days' },
                threeDays: { type: 'timeGrid', duration: { days: 3 }, buttonText: '3 days' },
            },
            initialDate: today,
            validRange: { start: isoDate(today) },          // no browsing into the past
            headerToolbar: { left: 'prev,next today', center: 'title', right: '' },
            buttonText: { today: 'Today' },
            height: 'auto',
            slotMinTime: '08:00:00',
            slotMaxTime: '22:00:00',
            slotDuration: '00:30:00',
            allDaySlot: false,
            nowIndicator: true,
            selectable: false,
            eventTimeFormat: { hour: 'numeric', minute: '2-digit', meridiem: 'short' },
            slotLabelFormat: { hour: 'numeric', minute: '2-digit', meridiem: 'short' },
            dayHeaderContent: headerHtml,
            events: loadEvents,
            dateClick: onSlotClick,
            stickyHeaderDates: false,          // the page already has a sticky top bar
            eventClick: function (info) {
                const p = info.event.extendedProps || {};
                if (p.mine) notice('This is your booking #' + p.booking_id + ' (' + p.status + ').');
                else notice('That time is already booked. Please pick an empty slot.');
            },
        });
        calendar.render();
    }

    // Dashboard "This Week" strip: open Book Court on that date
    window.openBookingOn = function (dateStr) {
        showPage('book');
        if (window.LabraBooking) window.LabraBooking.pickDate(dateStr);
        if (calendar) calendar.gotoDate(dateStr);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    document.addEventListener('DOMContentLoaded', function () {
        if (!el('availCalendar')) return;

        // Draw the calendar when the Book Court page is opened
        const originalShowPage = showPage;
        showPage = function (pageId) {
            originalShowPage(pageId);
            if (pageId === 'book') {
                initCalendar();
                if (calendar) calendar.updateSize();
            }
        };

        const bookPage = el('page-book');
        if (bookPage && bookPage.classList.contains('active')) initCalendar();
    });
})();
