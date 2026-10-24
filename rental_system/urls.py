"""
URL configuration for rental_system project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from booking import views
from rental_system import settings



urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('booking.urls')),

    path('admin_dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin_customer_history/<int:customer_id>/', views.admin_customer_history, name='admin_customer_history'),
    
    path('update_court/<int:court_id>/',       views.update_court, name='update_court'),
    path('update_court_status/<int:court_id>/', views.update_court_status, name='update_court_status'),

    path('admin_approve_booking/<int:booking_id>/', views.admin_approve_booking, name='admin_approve_booking'),
    path('admin_complete_booking/<int:booking_id>/', views.admin_complete_booking, name='admin_complete_booking'),
    path('admin_cancel_booking/<int:booking_id>/', views.admin_cancel_booking, name='admin_cancel_booking'),

    path('add_damage/<int:booking_id>/', views.add_damage, name='add_damage'),
    path('no_damage/<int:booking_id>/', views.no_damage, name='no_damage'),
    path('settle_damage/<int:damage_id>/', views.settle_damage, name='settle_damage'),
    
    path('admin_update_profile/', views.admin_update_profile, name='admin_update_profile'),
    path('admin_logout/', views.admin_logout, name='admin_logout'),
    # Google Calendar (admin)
    path('google/connect/', views.google_connect, name='google_connect'),
    path('oauth2callback/', views.google_oauth_callback, name='google_oauth_callback'),
    path('google/disconnect/', views.google_disconnect, name='google_disconnect'),
    path('admin_schedule_events/', views.admin_schedule_events, name='admin_schedule_events'),
    # Check-in (QR code / Confirmation ID)
    path('checkin/verify/', views.checkin_verify, name='checkin_verify'),
    path('checkin/start/', views.checkin_start, name='checkin_start'),
    path('checkin/record_cash/', views.checkin_record_cash, name='checkin_record_cash'),
    path('checkin/sessions/', views.checkin_sessions, name='checkin_sessions'),
    path('checkin/end/', views.checkin_end, name='checkin_end'),
] 

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)