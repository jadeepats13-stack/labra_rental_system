from django.contrib import admin
from .models import Customer, Admin, Court, Booking, Payment, Damage
# Register your models here.

admin.site.register(Customer)
admin.site.register(Admin)
admin.site.register(Court)
admin.site.register(Booking)
admin.site.register(Payment)
admin.site.register(Damage)
