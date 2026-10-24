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

const TIME_START = 8 * 60;
const TIME_END = 22 * 60;

function pad(n) { return String(n).padStart(2, '0'); }

function minutesToLabel(m) {
    const h = Math.floor(m / 60);
    const min = m % 60;
    const suffix = h < 12 ? 'AM' : 'PM';
    const displayH = h > 12 ? h - 12 : (h === 0 ? 12 : h);
    return `${displayH}:${pad(min)} ${suffix}`;
}

function minutesToValue(m) {
    return `${pad(Math.floor(m / 60))}:${pad(m % 60)}`;
}

function buildStartTimes() {
    const sel = document.getElementById('startTime');
    if (!sel) return;
    sel.innerHTML = '<option value="">— Start Time —</option>';
    for (let m = TIME_START; m < TIME_END; m += 30) {
        const opt = document.createElement('option');
        opt.value = minutesToValue(m);
        opt.textContent = minutesToLabel(m);
        opt.dataset.label = opt.textContent;
        sel.appendChild(opt);
    }
    applyAvailability();
}

function buildEndTimes(afterMinutes) {
    const sel = document.getElementById('endTime');
    if (!sel) return;
    sel.innerHTML = '<option value="">— End Time —</option>';
    const start = afterMinutes !== undefined ? afterMinutes + 30 : TIME_START + 30;
    for (let m = start; m <= TIME_END; m += 30) {
        const opt = document.createElement('option');
        opt.value = minutesToValue(m);
        opt.textContent = minutesToLabel(m);
        opt.dataset.label = opt.textContent;
        sel.appendChild(opt);
    }
    applyAvailability();
}
let currentRate = 0;

function onCourtChange() {
    const sel = document.getElementById('courtSelect');
    if (!sel) return;
    // Single LA court: the hidden input itself carries the court data
    const opt = sel.options ? sel.options[sel.selectedIndex] : sel;
    const id = opt ? opt.value : '';

    currentRate = parseFloat((opt && opt.dataset.rate) ? opt.dataset.rate : 0);

    if (!id) {
        document.getElementById('previewEmpty').style.display = 'flex';
        document.getElementById('previewFilled').style.display = 'none';
        computePrice();
        return;
    }

    const courtName = (opt.dataset.name && opt.dataset.name.trim())
        ? opt.dataset.name.trim() : ('Court ' + id);
    const courtImg = (opt.dataset.img && opt.dataset.img.trim())
        ? opt.dataset.img.trim() : '';

    document.getElementById('previewImg').src = courtImg;
    document.getElementById('previewName').textContent = courtName;
    document.getElementById('previewRate').textContent = '₱' + parseFloat(currentRate).toFixed(2);
    document.getElementById('previewEmpty').style.display = 'none';
    document.getElementById('previewFilled').style.display = 'flex';

    computePrice();
}

function computePrice() {
    const start = document.getElementById('startTime').value;
    const end = document.getElementById('endTime').value;
    const dateVal = document.getElementById('bookingDate').value;
    const priceText = document.getElementById('priceText');
    const totalInput = document.getElementById('totalPriceInput');
    const submitBtn = document.getElementById('submitBtn');

    if (!start || !end || currentRate <= 0) {
        priceText.textContent = 'Select date & time to compute';
        totalInput.value = 0;
        submitBtn.disabled = true;
        document.getElementById('bookingBreakdown').style.display = 'none';
        return;
    }

    const [sh, sm] = start.split(':').map(Number);
    const [eh, em] = end.split(':').map(Number);
    const totalMins = (eh * 60 + em) - (sh * 60 + sm);

    if (totalMins <= 0) {
        priceText.textContent = '⚠️ End time must be after start time';
        totalInput.value = 0;
        submitBtn.disabled = true;
        return;
    }

    const hours = totalMins / 60;
    const price = (hours * currentRate).toFixed(2);
    priceText.textContent = '₱' + price;
    totalInput.value = price;
    submitBtn.disabled = false;

    const durationLabel = hours === Math.floor(hours)
        ? `${hours} hr${hours > 1 ? 's' : ''}`
        : `${Math.floor(hours)}h ${totalMins % 60}m`;

    document.getElementById('bdDate').textContent = dateVal || '—';
    document.getElementById('bdDuration').textContent = durationLabel;
    document.getElementById('bdTime').textContent = minutesToLabel(sh * 60 + sm) + ' – ' + minutesToLabel(eh * 60 + em);
    document.getElementById('bdTotal').textContent = '₱' + price;
    document.getElementById('bookingBreakdown').style.display = 'grid';
}

function updateBreakdown() { computePrice(); }

function resetBookingForm() {
    document.getElementById('bookingDate').value = '';
    buildStartTimes();
    buildEndTimes();
    document.getElementById('priceText').textContent = 'Select date & time to compute';
    document.getElementById('totalPriceInput').value = 0;
    document.getElementById('submitBtn').disabled = true;
    document.getElementById('bookingBreakdown').style.display = 'none';
    updateWeather();
}

function selectCourt(courtId) {
    // Only one court (LA), so just open the booking page
    showPage('book');
    onCourtChange();
}

document.addEventListener('DOMContentLoaded', function () {
    const bd = document.getElementById('bookingDate');
    if (bd) {
        const now = new Date();
        bd.min = now.toISOString().split('T')[0];
        bd.addEventListener('change', updateBreakdown);
    }

    buildStartTimes();
    buildEndTimes();

    // Single LA court: load its preview and rate immediately
    onCourtChange();

    const startTime = document.getElementById('startTime');
    if (startTime) startTime.addEventListener('change', function () {
        const val = this.value;
        if (val) {
            const parts = val.split(':').map(Number);
            buildEndTimes(parts[0] * 60 + parts[1]);
        }
        computePrice();
    });

    const endTime = document.getElementById('endTime');
    if (endTime) endTime.addEventListener('change', computePrice);
});

// ── Weather forecast (OpenWeatherMap via our Django server) ──────────
let weatherRequestId = 0;

function updateWeather() {
    const box = document.getElementById('weatherBox');
    if (!box) return;
    const text = document.getElementById('weatherText');
    const icon = document.getElementById('weatherIcon');
    const dateVal = document.getElementById('bookingDate').value;
    const startVal = document.getElementById('startTime').value;

    icon.style.display = 'none';
    if (!dateVal || !startVal) {
        text.textContent = 'Select date & start time to see the forecast';
        return;
    }

    text.textContent = 'Loading forecast…';
    const requestId = ++weatherRequestId;   // ignore late answers from older requests
    const url = box.dataset.url + '?date=' + encodeURIComponent(dateVal) +
        '&start=' + encodeURIComponent(startVal);

    fetch(url, { credentials: 'same-origin' })
        .then(r => r.json())
        .then(data => {
            if (requestId !== weatherRequestId) return;
            if (!data.available) {
                text.textContent = data.message || 'Weather forecast is unavailable right now.';
                return;
            }
            icon.src = data.icon_url;
            icon.alt = data.description;
            icon.style.display = 'block';
            let msg = data.temperature + '°C, ' + data.description + ' · ' +
                data.rain_chance + '% chance of rain';
            if (data.rain_warning) msg += ' — rain is likely, as the LA court is outdoors.';
            text.textContent = msg;
        })
        .catch(() => {
            if (requestId !== weatherRequestId) return;
            text.textContent = 'Weather forecast is unavailable right now.';
        });
}

document.addEventListener('DOMContentLoaded', function () {
    const bd = document.getElementById('bookingDate');
    const st = document.getElementById('startTime');
    if (bd) bd.addEventListener('change', updateWeather);
    if (st) st.addEventListener('change', updateWeather);
});


// ── Greyed-out times (taken slots come from our own database) ────────
// takenIntervals: [[startMinutes, endMinutes], ...] for the chosen date
let takenIntervals = [];
let availabilityDate = '';
let serverNow = null;          // { date: 'YYYY-MM-DD', minutes: 870 }
let availabilityRequest = 0;

function overlapsTaken(from, to) {
    return takenIntervals.some(function (iv) { return iv[0] < to && iv[1] > from; });
}

function isPast(minutes) {
    const dateVal = document.getElementById('bookingDate').value;
    return serverNow && dateVal === serverNow.date && minutes <= serverNow.minutes;
}

function markOption(opt, disabled, reason) {
    opt.disabled = disabled;
    opt.textContent = (opt.dataset.label || opt.textContent) + (disabled ? ' (' + reason + ')' : '');
}

function applyAvailability() {
    const startSel = document.getElementById('startTime');
    const endSel = document.getElementById('endTime');
    if (!startSel || !endSel) return;

    Array.from(startSel.options).forEach(function (opt) {
        if (!opt.value) return;
        const [h, m] = opt.value.split(':').map(Number);
        const mins = h * 60 + m;
        if (isPast(mins)) markOption(opt, true, 'past');
        else if (overlapsTaken(mins, mins + 30)) markOption(opt, true, 'booked');
        else markOption(opt, false);
    });

    const startVal = startSel.value;
    Array.from(endSel.options).forEach(function (opt) {
        if (!opt.value) return;
        if (!startVal) { markOption(opt, false); return; }
        const [sh, sm] = startVal.split(':').map(Number);
        const [eh, em] = opt.value.split(':').map(Number);
        markOption(opt, overlapsTaken(sh * 60 + sm, eh * 60 + em), 'booked');
    });

    // Clear a choice that just became unavailable
    let cleared = false;
    if (startSel.selectedOptions[0] && startSel.selectedOptions[0].disabled) { startSel.value = ''; cleared = true; }
    if (endSel.selectedOptions[0] && endSel.selectedOptions[0].disabled) { endSel.value = ''; cleared = true; }
    if (cleared && typeof computePrice === 'function') computePrice();
}

function nextDay(dateStr) {
    const d = new Date(dateStr + 'T00:00:00');
    d.setDate(d.getDate() + 1);
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
}

// Load taken times for the chosen date, then grey them out. Returns a Promise.
function refreshAvailability() {
    const dateVal = document.getElementById('bookingDate').value;
    const box = document.getElementById('availCalendar');
    if (!dateVal || !box) {
        takenIntervals = [];
        applyAvailability();
        return Promise.resolve();
    }
    const requestId = ++availabilityRequest;
    const url = box.dataset.url + '?start=' + encodeURIComponent(dateVal + 'T00:00:00') +
        '&end=' + encodeURIComponent(nextDay(dateVal) + 'T00:00:00');
    return fetch(url, { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (data) {
            if (requestId !== availabilityRequest) return;
            availabilityDate = dateVal;
            if (data.now) {
                const [d, t] = data.now.split('T');
                const [h, m] = t.split(':').map(Number);
                serverNow = { date: d, minutes: h * 60 + m };
            }
            takenIntervals = (data.events || []).filter(function (e) {
                return e.start.slice(0, 10) === dateVal;
            }).map(function (e) {
                const s = e.start.slice(11, 16).split(':').map(Number);
                const en = e.end.slice(11, 16).split(':').map(Number);
                return [s[0] * 60 + s[1], en[0] * 60 + en[1]];
            });
            applyAvailability();
        })
        .catch(function () {
            // If this check fails, the server still blocks double bookings on Confirm
            takenIntervals = [];
            applyAvailability();
        });
}

// Used by the availability calendar and the dashboard "This Week" strip
window.LabraBooking = {
    pickDate: function (dateStr) {
        const bd = document.getElementById('bookingDate');
        if (!bd) return Promise.resolve();
        bd.value = dateStr;
        bd.dispatchEvent(new Event('change'));
        return refreshAvailability();
    },
    pickSlot: function (dateStr, timeStr) {
        return window.LabraBooking.pickDate(dateStr).then(function () {
            const st = document.getElementById('startTime');
            const opt = Array.from(st.options).find(function (o) { return o.value === timeStr; });
            if (!opt || opt.disabled) return false;
            st.value = timeStr;
            st.dispatchEvent(new Event('change'));
            const form = document.getElementById('bookingForm');
            if (form) form.scrollIntoView({ behavior: 'smooth', block: 'start' });
            const end = document.getElementById('endTime');
            if (end) end.focus({ preventScroll: true });
            return true;
        });
    },
};

document.addEventListener('DOMContentLoaded', function () {
    const bd = document.getElementById('bookingDate');
    if (bd) bd.addEventListener('change', refreshAvailability);
    const st = document.getElementById('startTime');
    // after the existing handler rebuilds the end times, grey out clashing ones
    if (st) st.addEventListener('change', applyAvailability);
});
