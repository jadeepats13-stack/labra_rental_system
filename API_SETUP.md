# Labra Basketball Court Rental System: API Setup & Testing

External APIs in this project:

| # | API | What it does in the system | Where in the code |
|---|-----|----------------------------|-------------------|
| 1 | PayPal Sandbox | Online payment for a booking (unchanged) | `booking/views.py` (`create_paypal_order`, `capture_paypal_order`) |
| 2 | OpenWeatherMap | Forecast for the booking date/time (the LA court is outdoors) | `booking/services/weather.py` |
| 3 | EmailJS | Booking confirmation email to the customer | `booking/services/emailjs.py` |
| 4 | Google Calendar | Approved bookings appear in the admin's Google Calendar | `booking/services/google_calendar.py` |
| 5 | goQR.me QR Code API | Check-in QR codes for approved bookings | `booking/services/qr_code.py` |

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
| `{{confirmation_id}}` | LBC-7K3P-9Q2X (Booking Confirmation ID for check-in) |
| `{{qr_code_url}}` | link to the check-in QR image (goQR.me) |

Add the check-in QR to the template (content editor, code view):
```html
<p><strong>Booking Confirmation ID: {{confirmation_id}}</strong></p>
<p><img src="{{qr_code_url}}" alt="Check-in QR code" width="200" height="200"></p>
<p>Show this QR code or Confirmation ID to the staff when you arrive. Your QR code becomes valid once your booking is approved.</p>
```

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

## 8. Customer features (Book Court, My Bookings, Dashboard)

**Book Court**
- An **availability calendar** shows the next 7 days (3 on phones) from 8 AM to 10 PM. Grey = booked, orange = your booking. Other customers' names are never sent to the browser.
- Each day shows the **OpenWeatherMap** forecast (first 5 days). This reuses the cached forecast, so there are no extra API calls.
- Tap an empty time to fill in the date and start time. Tapping a booked block explains why it isn't available.
- After you pick a date, times that are already booked or already passed are **greyed out** in the Start/End dropdowns. The server still double-checks on Confirm.

**My Bookings**
- My Bookings, Booking History and Payments each have a search box and filters.

**Dashboard**
- **Your next game** (ticket card): date stub, time, countdown, status chips, booking facts, the weather ("rain likely" from 50%, "light rain possible" below that), and **Pay ₱…** for unpaid bookings (uses the existing PayPal/cash pop-up).
- **LA Court** card: rate, status, hours free today, Book now.
- **This week at the LA Court**: 7 days with weather and free hours. Click a day to book on it.
- **Reminders** appear only when they apply: unpaid bookings or a missing email.
- "Unpaid Bills" now also counts bookings that don't have a payment record yet, so it matches the reminder.

**Test it:** log in as a customer, open **Book Court** and tap an empty slot. The form fills in, and booked times are greyed out. Confirm the booking, then go back to the **Dashboard**: you should see the unpaid reminder and "Your next game".


## 9. QR Code check-in (goQR.me, external API #5)

**How it works**
- When a customer **books**, the booking gets a unique **Booking Confirmation ID** (e.g. `LBC-FNYN-DM63`). The QR code contains that same ID.
- The QR and ID are included in the **booking confirmation email** (the same EmailJS template, see section 3). Customers can also open them any time with **Check-in QR** (My Bookings) or **Show check-in QR** (Your next game card).
- The QR only **works after the admin approves** the booking. Scanning a pending booking says it is not approved yet.
- Staff open **Check-in** in the admin sidebar and verify the booking in one of two ways. Both find the same booking:
  1. **Scan QR** with the camera. This uses the html5-qrcode library (Apache-2.0), stored in `booking/static/vendor/html5-qrcode/`.
  2. **Enter ID** by typing the Confirmation ID. Dashes and capital letters are optional.
- **Start playing time** starts a countdown that ends at the **reserved end time**, even if the customer arrives late.
- A booking can be started only **once**. This is enforced in the database, so two staff scanning at the same moment can't both start it.
- **End early**: if the customer finishes early, staff click **End playing time now**. The countdown stops, the booking shows **Time ended**, and the rest of the slot becomes free to book.
- When the time runs out (or is ended early), staff click **Complete** in Manage Bookings. Complete only appears after the playing time has ended.

**Check-in rules**
- Approved bookings only, on the booking date.
- From **15 minutes before** the start time until the end time.
- **Unpaid bookings are blocked**. Staff can collect cash and click **Record cash payment**, then start.

**Test it**
1. Run `python manage.py migrate`. This applies `0004_booking_checkin` and `0005_confirmation_codes_for_approved`.
2. As a customer, book a slot that **starts within the next 15 minutes** today and pay for it. The booking email contains the QR and ID. As admin, approve it: the message shows the same `LBC-…` ID.
3. As the customer, open **Show check-in QR**. The QR image comes from goQR.me.
4. As admin, open **Check-in**, then **Scan QR → Start camera**, and hold the QR (on your phone) up to the webcam. The details appear. Click **Start playing time**: a countdown appears under *Court in use*.
5. Type the same ID under **Enter ID**. You should see "Already checked in… playing now", and the booking cannot be started twice.
6. Click **End early → End playing time now**. A short message appears, then Manage Bookings opens with the booking showing **Time ended** and a **Complete** button.
7. Repeat with an **unpaid** booking to see the block and **Record cash payment**.

The browser asks for camera permission the first time. Cameras work on `http://127.0.0.1:8000` and on https sites such as PythonAnywhere.

## 10. Landing page chatbot (Google Gemini, external API #6)

**How it works**
- A chat bubble (**Ask us**) on the landing page opens **Labra Assistant**.
- **Quick buttons** (Free today?, Rate, How to book, Hours, Weather, Location, Payment, Check-in, Contact) answer instantly from our own data. No AI is used, so they always work.
- **Typed questions** go to Google Gemini from our server, together with the court's live facts (rate, hours, free times for 7 days, weather, how booking works). Gemini replies in the visitor's language: English, Tagalog or Bisaya. It is told to use only those facts and never invent prices, rules or free times.
- If Gemini is not set up, fails, or the free quota is used up, the chatbot answers with built-in replies instead.
- The API key is only used on the server and never appears on the page.

**Setup**
1. Open https://aistudio.google.com/apikey and sign in with a Google account. Click **Create API key** (free, no credit card).
2. Add these lines to `.env`:
   ```
   GEMINI_API_KEY=your-key
   GEMINI_MODEL=gemini-flash-lite-latest
   ```
3. Restart the server.

**Limits (change them in .env)**
- `CHATBOT_HOURLY_LIMIT=20`: typed questions per visitor per hour. Quick buttons are not limited.
- `CHATBOT_DAILY_AI_LIMIT=200`: AI answers per day for the whole site, so the free quota is not used up. After that, built-in answers are used.

**Test it**
1. Open the landing page, click **Ask us**, then tap **Rate**. It shows your court's rate.
2. Type `Magkano po kada oras?` or `Naa pa bay bakante karon?`. Gemini replies in the same language.
3. To test the fallback, remove `GEMINI_API_KEY` from `.env` and restart: typed questions still get built-in answers.

**Free tier notes**
- Google gives a small free daily quota that changes over time. Check your limits in AI Studio.
- On the free tier, Google may use chat messages to improve its products, so the chatbot never asks visitors for personal information.
- If PythonAnywhere is used for hosting, `generativelanguage.googleapis.com` is allowed for free accounts (`.googleapis.com` is on its allowlist).

## 11. Email confirmation and forgot password (EmailJS codes)

**How it works**
- After **Sign up**, the account is created but **cannot log in yet**. A **6-digit code** is emailed, and the pop-up asks for it. The right code confirms the email and logs the customer in.
- Logging in with an unconfirmed account sends a new code and opens the same step.
- **Forgot password?** (in the Log in pop-up) asks for the email, sends a 6-digit code, then asks for the code and a new password. The message is the same whether or not an account uses that email, so nobody can check who has an account.
- Codes: valid **10 minutes**, used **once**, **5 wrong tries** then a new code is needed. **Resend** after 60 seconds, at most 5 codes per hour. Codes are stored **hashed**.
- Customers who signed up before this feature are marked as confirmed automatically (migration `0007_email_verification`).
- Admin accounts have no email, so "Forgot password" is for customers only.

**Setup (EmailJS free plan allows 2 templates: the booking email + this "message" template)**
The second template is a general one: it sends the 6-digit codes **and** the landing page contact form.
1. EmailJS dashboard → **Email Templates → Create New Template** (or edit the code template you made earlier).
2. **Subject:** `{{subject}}`
3. **Content:** `{{{message}}}` (three braces, so line breaks show)
4. Template **Settings**: **To Email** `{{to_email}}`, **Reply To** `{{reply_to}}`, **From Name** `Labra Basketball Court`
5. Save, copy the **Template ID**, and add to `.env`:
   ```
   EMAILJS_CODE_TEMPLATE_ID=template_xxxxxxx
   CONTACT_EMAIL=the-inbox-that-should-get-contact-messages@gmail.com
   ```
6. Run `python manage.py migrate`, then restart the server.

**Contact form:** messages are sent by our server (the old in-page EmailJS script is gone), to `CONTACT_EMAIL`, with Reply-To set to the visitor, so pressing Reply in Gmail answers them. Limit: 3 messages per visitor per hour.

**Test it**
1. Sign up with an email you can open. The pop-up asks for the code, and the email arrives (check Spam).
2. Type a wrong code: it says how many tries are left. Paste the right code: you are logged in.
3. Log out, click **Log in → Forgot password?**, enter the same email, use the code and a new password, then log in with it.

The free EmailJS plan has **200 emails per month**, shared by booking emails, the contact form and these codes.
