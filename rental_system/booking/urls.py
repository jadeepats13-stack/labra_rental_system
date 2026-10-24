from django.urls import path

from rental_system import settings
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('login/', views.customer_login, name='login'),
    path('customer_dashboard/', views.customer_dashboard,      name='customer_dashboard'),

    path('book_court/',         views.book_court,              name='book_court'),
    path('booking_confirmation/<int:booking_id>/', views.booking_confirmation, name='booking_confirmation'),
    path('weather_forecast/',   views.weather_forecast,        name='weather_forecast'),
    path('cancel_booking/<int:booking_id>/', views.cancel_booking, name='cancel_booking'),

    path('process_payment/',    views.process_payment,         name='process_payment'),
    path('create_paypal_order/', views.create_paypal_order, name='create_paypal_order'),
    path('capture_paypal_order/', views.capture_paypal_order, name='capture_paypal_order'),
    
    path('update_profile/',     views.update_profile,          name='update_profile'),
    path('logout/',             views.logout_view,             name='logout'),
]
