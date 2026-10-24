# Labra Basketball Court Rental System: API Setup & Testing

External APIs in this project:

| # | API | What it does in the system | Where in the code |
|---|-----|----------------------------|-------------------|
| 1 | PayPal Sandbox | Online payment for a booking (unchanged) | `booking/views.py` (`create_paypal_order`, `capture_paypal_order`) |
| 2 | OpenWeatherMap | Forecast for the booking date/time (the LA court is outdoors) | `booking/services/weather.py` |
| 3 | EmailJS | Booking confirmation email to the customer | `booking/services/emailjs.py` |
| 4 | Google Calendar | Approved bookings appear in the admin's Google Calendar | `booking/services/google_calendar.py` |

All API keys live in the `.env` file, which is **never** committed to Git.
All API calls are made by the Django server, so keys never reach the browser.
If an API is down, the booking still works and a short notice is shown.

---

## 1. Install and migrate (once)

In PowerShell, in the folder that contains `manage.py`, with the venv active:

```
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py test booking
```

Expected output:
- `migrate` applies `0002_api_integrations` and `0003_single_la_court`.
- `test` ends with `OK` (34 tests).

What the migrations do:
- Add an **email** field to customers.
- Add a Google event ID to bookings.
- Add a table for the admin's Google connection.
- Rename the Labra court to **LA Court** and remove the two empty Tambacan Gymnasium records.

No bookings or payments are deleted.

---

## 2. OpenWeatherMap

1. The key is already in `.env` as `OPENWEATHER_API_KEY`.
2. The court's exact pin isn't on Google Maps, so the forecast uses **Iligan City** (`COURT_WEATHER_CITY`). If you get coordinates later, fill in `COURT_LATITUDE` and `COURT_LONGITUDE`. No code change is needed.
3. Free-plan limits:
   - The forecast covers only **5 days ahead**, in 3-hour steps.
   - Bookings further out show "Forecast will be available 5 days before your booking."

**Test it**
1. Run `python manage.py runserver` and log in as a customer.
2. Go to **Book Court**, pick a date within 5 days, and pick a start time.
3. Under **Weather Forecast** you should see something like `29°C, Light rain · 80% chance of rain` with an icon.

**Troubleshooting**
- *"Weather service key is not active yet"*: new OpenWeatherMap keys can take a while to activate. Wait and try again.

---

## 3. EmailJS (booking confirmation email)

**Do this once in the EmailJS dashboard:**
1. **Account → Security**: turn ON **"Allow EmailJS API for non-browser applications"**. Without this, EmailJS refuses emails sent by Django.
2. **Email Templates → template_pdev7yt → Settings**: set **To Email** to `{{to_email}}`. This sends the email to the customer who booked.

The template variables the system fills in:

| Variable | Example |
|----------|---------|
| `{{customer_name}}` | Juan Cruz |
| `{{booking_id}}` | 12 |
| `{{booking_date}}` | October 26, 2026 |
| `{{booking_time}}` | 10:00 AM – 12:00 PM |
| `{{total_amount}}` | 400.00 (your template already adds ₱) |
| `{{payment_status}}` | Unpaid (new bookings are unpaid) |
| `{{to_email}}` | the customer's email |

**Test it**
1. Register a new customer using an email address you can open. Existing customers can add an email in **Edit Profile**.
2. Book the court.
3. The confirmation page should say "✉️ A confirmation email was sent to …".
4. Check the inbox, and also the **Spam** folder.

**Troubleshooting**
- *"We could not send your confirmation email right now"*:
  - Check the two dashboard settings above.
  - Check the IDs and keys in `.env`.
  - The exact EmailJS reason appears in the `runserver` terminal.
- The free plan allows **200 emails per month**.

---

## 4. Google Calendar (admin)

**Do this once in Google Cloud Console** (project that owns your OAuth client):
1. **APIs & Services → Library → Google Calendar API → Enable.**
2. **OAuth consent screen → Audience → Test users → Add users**: add the admin's Gmail. Only test users can connect while the app is in "Testing".
3. **Credentials → your OAuth client → Authorized redirect URIs**: make sure `http://127.0.0.1:8000/oauth2callback/` is listed. Add your PythonAnywhere address too when you deploy.

**Test it**
1. Open the site at **http://127.0.0.1:8000** (not `localhost`; it must match the redirect URI).
2. Log in as admin. On the Dashboard, the **Google Calendar** card shows "Not connected".
3. Click **Connect Google Calendar** and sign in with the test-user Gmail.
4. Google warns "Google hasn't verified this app". Click **Continue**.
5. Allow calendar access. You return to the dashboard, which shows "Connected as …".
6. Approve a pending booking. The message ends with "Added to Google Calendar."
7. Open Google Calendar: the event "LA Court – Booking #… (Customer name)" is on the booked date and time.
8. Cancel that booking. The event is removed from the calendar.

**Troubleshooting**
- *redirect_uri_mismatch*: the URL in your browser doesn't exactly match the redirect URI. Use `127.0.0.1:8000`.
- *access_denied*: the Gmail isn't listed as a test user.
- *"Google Calendar connection expired. Please reconnect it."*: in Testing mode, Google ends the connection after 7 days. Click Connect again. Reconnect shortly before your demo.

---

## 5. Security notes

- `.env` holds every secret and is listed in `.gitignore`.
- The Google token is stored only for the admin and can be removed with **Disconnect**.
- The weather endpoint returns only forecast data. The API key is never sent to the browser.
- The OAuth `state` value protects the Google callback against forged requests.

---

## 6. Court Schedule & Upcoming Bookings (admin, reads Google Calendar)

The system now also **reads** from Google Calendar (`events.list`), not only writes to it.

**Test it**
1. Log in as admin. On the Dashboard, the **Upcoming Bookings** card lists the next 5 approved bookings, read from Google Calendar.
2. Click **Court Schedule** in the sidebar, or **View full schedule** on the card.
   - **Green** = approved bookings read from Google Calendar.
   - **Amber** = pending bookings from the database (not in Google yet).
   - **Grey** = approved bookings that are missing from Google Calendar (approved before you connected).
3. Click any booking to see its details.
4. Switch between **Month** and **Week**. The search box and the "Show pending" checkbox filter the calendar.
5. To test the fallback, click **Disconnect** on the card and open Court Schedule again. A yellow notice explains that approved bookings are now shown from the database, and everything else keeps working.

Only events created by this system are shown. Personal events in the same Google Calendar are ignored. A schedule read is cached for 1 minute, and the cache is cleared whenever a booking is added or removed.

The calendar uses **FullCalendar 6.1.15** (MIT licence). It's stored inside the project (`booking/static/vendor/fullcalendar/`), so it works without an extra internet download.

## 7. Search & filters (admin)

Manage Bookings, Manage Customers, Payments, Damage Reports and Booking Records each have a search box and filters. Results update as you type, the bar shows "Showing X of Y", and **Clear** resets everything.
