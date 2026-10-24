from django.test import RequestFactory
from booking.views import customer_dashboard
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware
from booking.models import Customer

rf = RequestFactory()
request = rf.get('/')

# apply session middleware
middleware = SessionMiddleware(lambda req: None)
middleware.process_request(request)
request.session.save()

# apply messages middleware
mess = MessageMiddleware(lambda req: None)
mess.process_request(request)

# create / get a test customer
c, _ = Customer.objects.get_or_create(username='testuser', defaults={'firstname':'Test','lastname':'User','password':'x'})
request.session['customer_id'] = c.customer_id

response = customer_dashboard(request)
print('status', response.status_code)
print(response.content.decode('utf-8')[0:1200])
