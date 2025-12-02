from django.contrib import admin
from .models import Restaurant, User, Table, Floor, Room, menu_item, order, bill

# Register Restaurant model
@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active', 'subscription_status', 'created_at']
    list_filter = ['is_active', 'subscription_status']
    search_fields = ['name', 'slug', 'phone', 'email']
    readonly_fields = ['created_at', 'updated_at']
from cafe.models import *
# Register your models here.

admin.site.register(User)
admin.site.register(menu_item)
admin.site.register(rating)
admin.site.register(order)
admin.site.register(bill)