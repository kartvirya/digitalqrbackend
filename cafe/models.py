from django.db import models
from django.contrib.auth.models import AbstractUser
from .manager import UserManager
import qrcode
from io import BytesIO
from django.core.files import File
from django.core.files.base import ContentFile
from PIL import Image
import uuid
import json
# Create your models here.


class Restaurant(models.Model):
    """Restaurant/Hotel tenant model for multi-tenancy"""
    SUBSCRIPTION_STATUS_CHOICES = [
        ('active', 'Active'),
        ('trial', 'Trial'),
        ('suspended', 'Suspended'),
        ('cancelled', 'Cancelled'),
    ]
    
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True, help_text="Unique identifier for URLs")
    address = models.TextField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    subscription_status = models.CharField(max_length=20, choices=SUBSCRIPTION_STATUS_CHOICES, default='active')
    settings = models.JSONField(default=dict, blank=True, help_text="Restaurant-specific configuration")
    archived_at = models.DateTimeField(blank=True, null=True)
    terminated_at = models.DateTimeField(blank=True, null=True)
    lifecycle_status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('suspended', 'Suspended'),
            ('archived', 'Archived'),
            ('terminated', 'Terminated'),
        ],
        default='active',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name

    @property
    def active_subscription(self):
        return self.subscriptions.filter(is_active=True).order_by('-created_at').first()

    @property
    def tenant_is_active(self) -> bool:
        if not self.is_active:
            return False
        if self.subscription_status in ('suspended', 'cancelled'):
            return False
        sub = self.active_subscription
        if not sub:
            return self.subscription_status in ('active', 'trial')
        return sub.status in ('active', 'trialing')
    
    class Meta:
        ordering = ['name']
        verbose_name = 'Restaurant'
        verbose_name_plural = 'Restaurants'


class User(AbstractUser):
    ROLE_CHOICES = [
        ('super_admin', 'Super Admin'),
        ('restaurant_admin', 'Restaurant Admin'),
        ('hr_manager', 'HR Manager'),
        ('staff', 'Staff'),
        ('customer', 'Customer'),
    ]

    email = None
    username = None
    phone = models.CharField(max_length=10, unique=True)
    google_sub = models.CharField(max_length=128, unique=True, null=True, blank=True)
    google_email = models.CharField(max_length=255, unique=True, null=True, blank=True)
    phone_verified = models.BooleanField(default=False)
    cafe_manager = models.BooleanField(default=False)  # Legacy field, kept for backward compatibility
    order_count = models.IntegerField(default=0)
    is_super_admin = models.BooleanField(default=False, help_text="Super admin can manage all restaurants")
    restaurant = models.ForeignKey(Restaurant, on_delete=models.SET_NULL, null=True, blank=True, related_name='admins', help_text="Restaurant this user manages (for restaurant admins)")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='customer', help_text="User role in the system")

    objects = UserManager()

    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = []
    
    def __str__(self):
        if self.is_super_admin:
            return f"Super Admin: {self.phone}"
        elif self.restaurant:
            return f"{self.restaurant.name} Admin: {self.phone}"
        return f"User: {self.phone}"
    
    def is_restaurant_admin(self):
        """Check if user is a restaurant admin"""
        return bool(
            self.is_superuser
            or self.is_super_admin
            or self.role in ['restaurant_admin', 'super_admin']
            or self.cafe_manager
            or (self.restaurant and self.role in ['restaurant_admin', 'super_admin'])
        )
    
    def is_hr_manager(self):
        """Check if user is an HR manager"""
        return self.role == 'hr_manager' or (self.is_restaurant_admin() and self.role == 'hr_manager')
    
    def is_staff_member(self):
        """Check if user is a staff member"""
        return self.role == 'staff' or hasattr(self, 'employee_profile')
    
    def has_permission(self, permission_name):
        """Check if user has a specific permission"""
        # Super admin has all permissions
        if self.is_superuser or self.is_super_admin or self.role == 'super_admin':
            return True
        
        # Restaurant admin has all restaurant permissions
        if self.is_restaurant_admin():
            restaurant_permissions = [
                'manage_menu', 'manage_tables', 'manage_rooms', 'manage_floors',
                'manage_orders', 'manage_staff', 'manage_employees', 'manage_payroll',
                'manage_attendance', 'manage_leaves', 'manage_training', 'manage_performance'
            ]
            if permission_name in restaurant_permissions:
                return True
        
        # HR Manager has HR permissions
        if self.is_hr_manager():
            hr_permissions = [
                'manage_employees', 'manage_payroll', 'manage_attendance',
                'manage_leaves', 'manage_training', 'manage_performance'
            ]
            if permission_name in hr_permissions:
                return True
        
        # Staff has operations permissions
        if self.is_staff_member():
            staff_permissions = ['manage_orders', 'view_tables', 'view_kitchen']
            if permission_name in staff_permissions:
                return True
        
        return False


class SubscriptionPlan(models.Model):
    BILLING_CYCLE_CHOICES = [
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
    ]

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    billing_cycle = models.CharField(max_length=20, choices=BILLING_CYCLE_CHOICES, default='monthly')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='INR')
    max_staff = models.IntegerField(default=20)
    max_monthly_orders = models.IntegerField(default=1000)
    max_tables = models.IntegerField(default=50)
    modules = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class RestaurantSubscription(models.Model):
    STATUS_CHOICES = [
        ('trialing', 'Trialing'),
        ('active', 'Active'),
        ('pending_payment', 'Pending Payment'),
        ('failed', 'Failed'),
        ('past_due', 'Past Due'),
        ('suspended', 'Suspended'),
        ('cancelled', 'Cancelled'),
    ]

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trialing')
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.restaurant.name} - {self.plan.name} ({self.status})"


class TenantUsageSnapshot(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='usage_snapshots')
    month_key = models.CharField(max_length=7, help_text='YYYY-MM')
    orders_count = models.IntegerField(default=0)
    active_staff_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['restaurant', 'month_key']]
        ordering = ['-month_key']


class BillingInvoice(models.Model):
    STATUS_CHOICES = [
        ('pending_payment', 'Pending Payment'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('void', 'Void'),
    ]

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='billing_invoices')
    subscription = models.ForeignKey(
        RestaurantSubscription,
        on_delete=models.SET_NULL,
        related_name='billing_invoices',
        null=True,
        blank=True,
    )
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name='billing_invoices')
    invoice_number = models.CharField(max_length=40, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='INR')
    due_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending_payment')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class BillingTransaction(models.Model):
    STATUS_CHOICES = [
        ('initiated', 'Initiated'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]

    invoice = models.ForeignKey(BillingInvoice, on_delete=models.CASCADE, related_name='transactions')
    gateway = models.CharField(max_length=20, default='esewa')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='initiated')
    gateway_reference = models.CharField(max_length=120, blank=True, null=True)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class PlatformAuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='platform_audit_logs')
    restaurant = models.ForeignKey(Restaurant, on_delete=models.SET_NULL, null=True, blank=True, related_name='platform_audit_logs')
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=40, blank=True, default='')
    target_id = models.CharField(max_length=50, blank=True, default='')
    before_state = models.JSONField(default=dict, blank=True)
    after_state = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Permission(models.Model):
    """System permissions for role-based access control"""
    PERMISSION_CATEGORIES = [
        ('restaurant', 'Restaurant Management'),
        ('menu', 'Menu Management'),
        ('tables', 'Table/Room Management'),
        ('orders', 'Order Management'),
        ('employees', 'Employee Management'),
        ('payroll', 'Payroll Management'),
        ('attendance', 'Attendance Management'),
        ('leaves', 'Leave Management'),
        ('training', 'Training Management'),
        ('performance', 'Performance Management'),
        ('hr', 'HR Management'),
    ]
    
    name = models.CharField(max_length=100, unique=True)
    codename = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=PERMISSION_CATEGORIES)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['category', 'name']
        verbose_name = 'Permission'
        verbose_name_plural = 'Permissions'
    
    def __str__(self):
        return f"{self.name} ({self.codename})"


class RolePermission(models.Model):
    """Many-to-many relationship between roles and permissions"""
    ROLE_CHOICES = [
        ('super_admin', 'Super Admin'),
        ('restaurant_admin', 'Restaurant Admin'),
        ('hr_manager', 'HR Manager'),
        ('staff', 'Staff'),
        ('customer', 'Customer'),
    ]
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name='role_permissions')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = [['role', 'permission']]
        ordering = ['role', 'permission']
        verbose_name = 'Role Permission'
        verbose_name_plural = 'Role Permissions'
    
    def __str__(self):
        return f"{self.get_role_display()} - {self.permission.name}"


class Floor(models.Model):
    id = models.AutoField(primary_key=True)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='floors', null=True, blank=True)
    name = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        if self.restaurant:
            return f"{self.restaurant.name} - {self.name}"
        return self.name
    
    class Meta:
        ordering = ['restaurant', 'name']
        unique_together = [['restaurant', 'name']]


class Table(models.Model):
    SHAPE_CHOICES = [
        ('rectangle', 'Rectangle'),
        ('circle', 'Circle'),
    ]
    
    id = models.AutoField(primary_key=True)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='tables', null=True, blank=True)
    table_number = models.CharField(max_length=10)
    table_name = models.CharField(max_length=50, blank=True, null=True)
    capacity = models.IntegerField(default=4)
    is_active = models.BooleanField(default=True)
    qr_code = models.ImageField(upload_to='qr_codes/', blank=True, null=True)
    qr_unique_id = models.CharField(max_length=50, unique=True, default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Visual layout positions
    visual_x = models.IntegerField(default=0)
    visual_y = models.IntegerField(default=0)
    
    # Shape and dimensions
    shape = models.CharField(max_length=20, choices=SHAPE_CHOICES, default='rectangle')
    width = models.IntegerField(default=120)
    height = models.IntegerField(default=80)
    radius = models.IntegerField(default=60)
    
    # Floor and Room relationships
    floor = models.ForeignKey(Floor, on_delete=models.CASCADE, related_name='tables', null=True, blank=True)
    room = models.ForeignKey('Room', on_delete=models.CASCADE, related_name='tables', null=True, blank=True)
    
    class Meta:
        unique_together = [['restaurant', 'table_number']]
    
    def __str__(self):
        return f"Table {self.table_number} - {self.table_name or 'Table'}"
    
    def save(self, *args, **kwargs):
        if not self.qr_unique_id:
            self.qr_unique_id = str(uuid.uuid4())
        super().save(*args, **kwargs)
        # Only generate QR code if restaurant is set
        if self.restaurant and not self.qr_code:
            self.generate_qr_code()
    
    def generate_qr_code(self):
        # Generate QR code with table-specific URL including restaurant slug
        if not self.restaurant:
            # If no restaurant, use default URL format (for backward compatibility)
            from django.conf import settings
            url = f"{settings.FRONTEND_URL}/?table={self.qr_unique_id}"
        else:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            # URL for table-specific ordering - using restaurant slug
            from django.conf import settings
            url = f"{settings.FRONTEND_URL}/r/{self.restaurant.slug}/?table={self.qr_unique_id}"
            qr.add_data(url)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Save the QR code image
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            filename = f"table_{self.restaurant.slug}_{self.table_number}_qr.png"
            
            self.qr_code.save(filename, ContentFile(buffer.getvalue()), save=False)
            self.save(update_fields=['qr_code'])
            return
        
        # Fallback for no restaurant
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        filename = f"table_{self.table_number}_qr.png"
        
        self.qr_code.save(filename, ContentFile(buffer.getvalue()), save=False)
        self.save(update_fields=['qr_code'])


class Room(models.Model):
    ROOM_TYPE_CHOICES = [
        ('single', 'Single Room'),
        ('double', 'Double Room'),
        ('triple', 'Triple Room'),
        ('suite', 'Suite'),
        ('deluxe', 'Deluxe Room'),
        ('presidential', 'Presidential Suite'),
    ]
    
    ROOM_STATUS_CHOICES = [
        ('available', 'Available'),
        ('occupied', 'Occupied'),
        ('maintenance', 'Under Maintenance'),
        ('reserved', 'Reserved'),
        ('cleaning', 'Being Cleaned'),
    ]
    
    id = models.AutoField(primary_key=True)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='rooms', null=True, blank=True)
    room_number = models.CharField(max_length=10)
    room_name = models.CharField(max_length=100, blank=True, null=True)
    room_type = models.CharField(max_length=20, choices=ROOM_TYPE_CHOICES, default='single')
    floor = models.ForeignKey(Floor, on_delete=models.CASCADE, related_name='rooms')
    capacity = models.IntegerField(default=2)
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    room_status = models.CharField(max_length=20, choices=ROOM_STATUS_CHOICES, default='available')
    qr_code = models.ImageField(upload_to='room_qr_codes/', blank=True, null=True)
    qr_unique_id = models.CharField(max_length=50, unique=True, default=uuid.uuid4)
    description = models.TextField(blank=True, null=True)
    amenities = models.TextField(blank=True, null=True)  # JSON string of amenities
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = [['restaurant', 'room_number']]
        ordering = ['restaurant', 'floor', 'room_number']
    
    def __str__(self):
        restaurant_name = self.restaurant.name if self.restaurant else 'No Restaurant'
        return f"{restaurant_name} - Room {self.room_number} - {self.get_room_type_display()}"
    
    def save(self, *args, **kwargs):
        if not self.qr_unique_id:
            self.qr_unique_id = str(uuid.uuid4())
        super().save(*args, **kwargs)
        if not self.qr_code:
            self.generate_qr_code()
    
    def generate_qr_code(self):
        # Generate QR code with room-specific URL including restaurant slug
        if not self.restaurant:
            # If no restaurant, use default URL format (for backward compatibility)
            from django.conf import settings
            url = f"{settings.FRONTEND_URL}/?room={self.qr_unique_id}"
        else:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            # URL for room-specific ordering - using restaurant slug
            from django.conf import settings
            url = f"{settings.FRONTEND_URL}/r/{self.restaurant.slug}/?room={self.qr_unique_id}"
            qr.add_data(url)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Save the QR code image
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            filename = f"room_{self.restaurant.slug}_{self.room_number}_qr.png"
            
            self.qr_code.save(filename, ContentFile(buffer.getvalue()), save=False)
            self.save(update_fields=['qr_code'])
            return
        
        # Fallback for no restaurant
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        filename = f"room_{self.room_number}_qr.png"
        
        self.qr_code.save(filename, ContentFile(buffer.getvalue()), save=False)
        self.save(update_fields=['qr_code'])
    
    class Meta:
        ordering = ['floor', 'room_number']


class menu_item(models.Model):
    id = models.AutoField(primary_key=True)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='menu_items', null=True, blank=True)
    name = models.CharField(max_length=50)
    category = models.CharField(max_length=50)
    description = models.CharField(max_length=250)
    image = models.ImageField(upload_to='fimage', blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    list_order = models.IntegerField(default=0)
    is_available = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['restaurant', 'category', 'name']
    
    def __str__(self):
        if self.restaurant:
            return f"{self.restaurant.name} - {self.name}"
        return self.name


class rating(models.Model):

    name = models.CharField(max_length=30)
    comment = models.CharField(max_length=250)
    r_date = models.DateField()

    def __str__(self):
        return f"{self.name}\'s review"


class order(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('pending_payment', 'Pending Payment'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('unknown', 'Unknown'),
        ('cash', 'Cash'),
        ('card', 'Card'),
        ('upi', 'UPI'),
        ('online_gateway', 'Online Gateway'),
    ]

    id = models.AutoField(primary_key=True)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    items_json = models.CharField(max_length=5000)
    name = models.CharField(max_length=30)
    phone = models.CharField(max_length=10)
    table = models.CharField(max_length=15)
    # Monetary fields
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Grand total for the order")
    currency = models.CharField(max_length=3, default='INR')
    tip_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    bill_clear = models.BooleanField(default=False)
    estimated_time = models.IntegerField()
    special_instructions = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, default='pending')
    # Payment state
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='unpaid')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='unknown')
    paid_at = models.DateTimeField(null=True, blank=True)
    invoice_number = models.CharField(max_length=50, blank=True, null=True, unique=True)
    table_unique_id = models.CharField(max_length=50, null=True, blank=True)
    room_unique_id = models.CharField(max_length=50, null=True, blank=True)  # For room orders
    order_type = models.CharField(max_length=10, choices=[('table', 'Table'), ('room', 'Room')], default='table')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    placed_by = models.CharField(
        max_length=20,
        choices=[('customer', 'Customer'), ('waiter', 'Waiter')],
        default='customer',
    )
    placed_by_staff = models.ForeignKey(
        'Staff',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders_placed',
    )
    assigned_runner = models.ForeignKey(
        'Staff',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders_assigned_to_deliver',
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    kitchen_notes = models.TextField(blank=True, null=True)
    stock_consumed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When BOM stock was deducted for this order (idempotency).',
    )

    class Meta:
        ordering = ['-created_at']
        permissions = [
            ('can_place_waiter_order', 'Can place orders as waiter from tables'),
            ('can_view_kitchen_queue', 'Can view kitchen order queue for restaurant'),
            ('can_update_order_status_kitchen', 'Can advance order status as kitchen'),
            ('can_update_order_status_runner', 'Can advance order status as runner or waiter'),
            ('can_assign_runner', 'Can assign waiter to deliver prepared food'),
        ]
    
    def __str__(self):
        restaurant_name = self.restaurant.name if self.restaurant else 'No Restaurant'
        return f"{restaurant_name} - Order {self.id} - {self.name}"

    @property
    def subtotal(self):
        """Basic subtotal; for now equal to price minus tip."""
        return max(self.price - self.tip_amount, 0)


class bill(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('pending_payment', 'Pending Payment'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('unknown', 'Unknown'),
        ('cash', 'Cash'),
        ('card', 'Card'),
        ('upi', 'UPI'),
        ('online_gateway', 'Online Gateway'),
    ]

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='bills', null=True, blank=True)
    order = models.OneToOneField(order, on_delete=models.CASCADE, related_name='bill', null=True, blank=True)
    order_items = models.CharField(max_length=5000)
    name = models.CharField(default='', max_length=50)
    bill_total = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')
    phone = models.CharField(max_length=10)
    bill_time = models.DateTimeField()
    table_number = models.CharField(max_length=10, blank=True, null=True)
    invoice_number = models.CharField(max_length=50, blank=True, null=True, unique=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='unpaid')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='unknown')
    tip_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        permissions = [
            ('can_mark_paid', 'Can mark bills and orders as paid'),
            ('can_create_bill', 'Can create or regenerate bills'),
        ]

    def __str__(self):
        restaurant_name = self.restaurant.name if self.restaurant else 'No Restaurant'
        return f"{restaurant_name} - Bill {self.id} - {self.name}"


class Payment(models.Model):
    """Payment record linked to orders/bills and external gateways."""
    STATUS_CHOICES = [
        ('created', 'Created'),
        ('pending', 'Pending'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
        ('cancelled', 'Cancelled'),
    ]

    PROVIDER_CHOICES = [
        ('manual', 'Manual / Cash'),
        ('stripe', 'Stripe'),
        ('razorpay', 'Razorpay'),
        ('paypal', 'PayPal'),
        ('other', 'Other'),
    ]

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='payments', null=True, blank=True)
    order = models.ForeignKey(order, on_delete=models.CASCADE, related_name='payments', null=True, blank=True)
    bill = models.ForeignKey(bill, on_delete=models.CASCADE, related_name='payments', null=True, blank=True)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='manual')
    provider_payment_id = models.CharField(max_length=100, blank=True, null=True)
    provider_order_id = models.CharField(max_length=100, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='created')
    raw_response = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_provider_display()} payment {self.id} - {self.status}"


class Department(models.Model):
    id = models.AutoField(primary_key=True)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='departments', null=True, blank=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.restaurant:
            return f"{self.restaurant.name} - {self.name}"
        return self.name

    class Meta:
        ordering = ['restaurant', 'name']
        unique_together = [['restaurant', 'name']]

class Role(models.Model):
    id = models.AutoField(primary_key=True)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='roles', null=True, blank=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='roles')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        restaurant_name = self.restaurant.name if self.restaurant else 'No Restaurant'
        return f"{restaurant_name} - {self.name} - {self.department.name}"

    class Meta:
        ordering = ['restaurant', 'department', 'name']
        unique_together = [['restaurant', 'name', 'department']]

class Staff(models.Model):
    EMPLOYMENT_STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('terminated', 'Terminated'),
        ('on_leave', 'On Leave'),
    ]

    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ]

    OPERATIONAL_ACCESS_CHOICES = [
        ('auto', 'From role title (waiter/chef keywords)'),
        ('waiter', 'Take orders & tables (waiter)'),
        ('kitchen_chef', 'Kitchen queue'),
        ('none', 'No waiter/kitchen portal access'),
    ]

    id = models.AutoField(primary_key=True)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='staff_members', null=True, blank=True)
    employee_id = models.CharField(max_length=20)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='staff_profile')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    address = models.TextField()
    emergency_contact_name = models.CharField(max_length=100)
    emergency_contact_phone = models.CharField(max_length=15)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='staff')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='staff')
    hire_date = models.DateField()
    salary = models.DecimalField(max_digits=10, decimal_places=2)
    employment_status = models.CharField(max_length=20, choices=EMPLOYMENT_STATUS_CHOICES, default='active')
    is_active = models.BooleanField(default=True)
    operational_access = models.CharField(
        max_length=20,
        choices=OPERATIONAL_ACCESS_CHOICES,
        default='auto',
        help_text='Controls waiter/kitchen Django groups for the staff portal (manage-staff).',
    )
    profile_picture = models.ImageField(upload_to='staff_profiles/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        restaurant_name = self.restaurant.name if self.restaurant else 'No Restaurant'
        return f"{restaurant_name} - {self.employee_id} - {self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    class Meta:
        ordering = ['restaurant', 'employee_id']
        unique_together = [['restaurant', 'employee_id']]

class Attendance(models.Model):
    ATTENDANCE_STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('half_day', 'Half Day'),
        ('leave', 'Leave'),
    ]

    id = models.AutoField(primary_key=True)
    employee = models.ForeignKey('Employee', on_delete=models.CASCADE, related_name='attendance_records', null=True, blank=True)
    staff = models.ForeignKey('Staff', on_delete=models.CASCADE, related_name='attendance_records', null=True, blank=True)  # Legacy, will be removed
    date = models.DateField()
    check_in_time = models.TimeField(blank=True, null=True)
    check_out_time = models.TimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=ATTENDANCE_STATUS_CHOICES, default='present')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['employee', 'date']]  # Updated to use employee
        ordering = ['-date', '-created_at']

    def __str__(self):
        employee_name = self.employee.full_name if self.employee else (self.staff.full_name if self.staff else 'Unknown')
        return f"{employee_name} - {self.date} - {self.status}"

class Leave(models.Model):
    LEAVE_TYPE_CHOICES = [
        ('annual', 'Annual Leave'),
        ('sick', 'Sick Leave'),
        ('personal', 'Personal Leave'),
        ('maternity', 'Maternity Leave'),
        ('paternity', 'Paternity Leave'),
        ('other', 'Other'),
    ]

    LEAVE_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.AutoField(primary_key=True)
    employee = models.ForeignKey('Employee', on_delete=models.CASCADE, related_name='leaves', null=True, blank=True)
    staff = models.ForeignKey('Staff', on_delete=models.CASCADE, related_name='leaves', null=True, blank=True)  # Legacy, will be removed
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPE_CHOICES)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=LEAVE_STATUS_CHOICES, default='pending')
    approved_by_employee = models.ForeignKey('Employee', on_delete=models.SET_NULL, null=True, blank=True, related_name='legacy_approved_leaves')
    approved_by = models.ForeignKey('Staff', on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_leaves')  # Legacy
    approved_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        employee_name = self.employee.full_name if self.employee else (self.staff.full_name if self.staff else 'Unknown')
        return f"{employee_name} - {self.leave_type} - {self.start_date} to {self.end_date}"

    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1

# HR Management System Models
class HRDepartment(models.Model):
    """HR Department for organizational structure"""
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='hr_departments', null=True, blank=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    manager = models.ForeignKey('Employee', on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_hr_departments')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['restaurant', 'name']
        unique_together = [['restaurant', 'name']]

    def __str__(self):
        if self.restaurant:
            return f"{self.restaurant.name} - {self.name}"
        return self.name

class HRPosition(models.Model):
    """HR Position/Role for employees"""
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='hr_positions', null=True, blank=True)
    name = models.CharField(max_length=200)
    department = models.ForeignKey(HRDepartment, on_delete=models.CASCADE, related_name='positions')
    description = models.TextField(blank=True)
    salary_range_min = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    salary_range_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['restaurant', 'department__name', 'name']
        unique_together = [['restaurant', 'name', 'department']]

    def __str__(self):
        restaurant_name = self.restaurant.name if self.restaurant else 'No Restaurant'
        return f"{restaurant_name} - {self.department.name} - {self.name}"

class Employee(models.Model):
    """Enhanced Employee model for HR management"""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('terminated', 'Terminated'),
        ('on_leave', 'On Leave'),
        ('probation', 'Probation'),
    ]

    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ]

    # Basic Information
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='employees', null=True, blank=True)
    employee_id = models.CharField(max_length=20, verbose_name="Employee ID")
    personnel_number = models.CharField(max_length=20, verbose_name="Personnel Number")
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='employee_profile', null=True, blank=True)
    
    # Personal Information
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, default='male')
    date_of_birth = models.DateField()
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    
    # Address Information
    address = models.TextField()
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, default='India')
    
    # Employment Information
    position = models.ForeignKey(HRPosition, on_delete=models.CASCADE, related_name='employees')
    department = models.ForeignKey(HRDepartment, on_delete=models.CASCADE, related_name='employees')
    hire_date = models.DateField()
    termination_date = models.DateField(null=True, blank=True)
    employment_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Salary Information
    base_salary = models.DecimalField(max_digits=10, decimal_places=2)
    current_salary = models.DecimalField(max_digits=10, decimal_places=2)
    salary_currency = models.CharField(max_length=3, default='INR')
    
    # Emergency Contact
    emergency_contact_name = models.CharField(max_length=100)
    emergency_contact_phone = models.CharField(max_length=15)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True)
    
    # Documents
    profile_picture = models.ImageField(upload_to='employees/photos/', blank=True, null=True)
    resume = models.FileField(upload_to='employees/resumes/', blank=True, null=True)
    id_proof = models.FileField(upload_to='employees/documents/', blank=True, null=True)
    
    # Additional Information
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['restaurant', 'employee_id']
        unique_together = [
            ['restaurant', 'employee_id'],
            ['restaurant', 'personnel_number']
        ]

    def __str__(self):
        restaurant_name = self.restaurant.name if self.restaurant else 'No Restaurant'
        return f"{restaurant_name} - {self.employee_id} - {self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def years_of_service(self):
        from datetime import date
        if self.termination_date:
            end_date = self.termination_date
        else:
            end_date = date.today()
        return (end_date - self.hire_date).days // 365

class EmployeeDocument(models.Model):
    """Employee documents and certificates"""
    DOCUMENT_TYPES = [
        ('id_proof', 'ID Proof'),
        ('resume', 'Resume'),
        ('certificate', 'Certificate'),
        ('contract', 'Employment Contract'),
        ('other', 'Other'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES)
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='employees/documents/')
    description = models.TextField(blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.employee.full_name} - {self.title}"

class Payroll(models.Model):
    """Employee payroll records"""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payrolls')
    month = models.IntegerField()  # 1-12
    year = models.IntegerField()
    basic_salary = models.DecimalField(max_digits=10, decimal_places=2)
    allowances = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deductions = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_salary = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField()
    payment_status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ], default='pending')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['employee', 'month', 'year']
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.employee.full_name} - {self.month}/{self.year}"

class LeaveRequest(models.Model):
    """Employee leave requests"""
    LEAVE_TYPES = [
        ('annual', 'Annual Leave'),
        ('sick', 'Sick Leave'),
        ('personal', 'Personal Leave'),
        ('maternity', 'Maternity Leave'),
        ('paternity', 'Paternity Leave'),
        ('bereavement', 'Bereavement Leave'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPES)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_leaves')
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee.full_name} - {self.leave_type} ({self.start_date} to {self.end_date})"

    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1

class PerformanceReview(models.Model):
    """Employee performance reviews"""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='performance_reviews')
    review_period_start = models.DateField()
    review_period_end = models.DateField()
    reviewer = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='conducted_reviews')
    overall_rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])  # 1-5 scale
    strengths = models.TextField()
    areas_for_improvement = models.TextField()
    goals = models.TextField()
    comments = models.TextField(blank=True)
    review_date = models.DateField()
    next_review_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-review_date']

    def __str__(self):
        return f"{self.employee.full_name} - {self.review_period_start} to {self.review_period_end}"

class Training(models.Model):
    """Employee training records"""
    TRAINING_TYPES = [
        ('onboarding', 'Onboarding'),
        ('skill_development', 'Skill Development'),
        ('compliance', 'Compliance'),
        ('leadership', 'Leadership'),
        ('technical', 'Technical'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField()
    training_type = models.CharField(max_length=20, choices=TRAINING_TYPES)
    trainer = models.CharField(max_length=100)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    location = models.CharField(max_length=200, blank=True)
    max_participants = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.title} - {self.start_date.date()}"

class TrainingEnrollment(models.Model):
    """Employee training enrollments"""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='training_enrollments')
    training = models.ForeignKey(Training, on_delete=models.CASCADE, related_name='enrollments')
    enrollment_date = models.DateTimeField(auto_now_add=True)
    completion_date = models.DateTimeField(null=True, blank=True)
    certificate_issued = models.BooleanField(default=False)
    certificate_file = models.FileField(upload_to='training/certificates/', blank=True, null=True)
    feedback = models.TextField(blank=True)
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)], null=True, blank=True)

    class Meta:
        unique_together = ['employee', 'training']
        ordering = ['-enrollment_date']

    def __str__(self):
        return f"{self.employee.full_name} - {self.training.title}"


# --- Inventory (restaurant-scoped) ---


class Supplier(models.Model):
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name='suppliers', null=True, blank=True
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['restaurant', 'name']
        unique_together = [['restaurant', 'name']]

    def __str__(self):
        return self.name


class Ingredient(models.Model):
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name='ingredients', null=True, blank=True
    )
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=80, blank=True)
    unit = models.CharField(max_length=30, default='unit', help_text='e.g. kg, L, piece')
    reorder_level = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['restaurant', 'name']
        unique_together = [['restaurant', 'name']]
        permissions = [
            ('can_manage_inventory', 'Manage ingredients, recipes, and stock adjustments'),
            ('can_view_inventory', 'View ingredients and stock levels'),
        ]

    def __str__(self):
        return self.name


class IngredientStock(models.Model):
    ingredient = models.OneToOneField(
        Ingredient, on_delete=models.CASCADE, related_name='stock_level'
    )
    quantity_on_hand = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.ingredient.name}: {self.quantity_on_hand}"


class MenuItemRecipe(models.Model):
    menu_item = models.ForeignKey(menu_item, on_delete=models.CASCADE, related_name='recipe_lines')
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, related_name='recipe_usages')
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        help_text='Ingredient amount consumed per 1 unit of menu item sold',
    )

    class Meta:
        unique_together = [['menu_item', 'ingredient']]

    def __str__(self):
        return f"{self.menu_item.name} ← {self.ingredient.name}"


class StockMovement(models.Model):
    MOVEMENT_PURCHASE = 'purchase'
    MOVEMENT_ADJUSTMENT = 'adjustment'
    MOVEMENT_CONSUMPTION = 'consumption'
    MOVEMENT_REVERSAL = 'reversal'
    MOVEMENT_WASTE = 'waste'
    MOVEMENT_TYPES = [
        (MOVEMENT_PURCHASE, 'Purchase / receive'),
        (MOVEMENT_ADJUSTMENT, 'Manual adjustment'),
        (MOVEMENT_CONSUMPTION, 'Order consumption'),
        (MOVEMENT_REVERSAL, 'Reversal (e.g. cancelled order)'),
        (MOVEMENT_WASTE, 'Waste / spoilage'),
    ]

    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name='stock_movements', null=True, blank=True
    )
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, related_name='movements')
    quantity_delta = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        help_text='Positive adds stock, negative removes',
    )
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    order_ref = models.ForeignKey(
        order, on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_movements'
    )
    purchase_order_line = models.ForeignKey(
        'PurchaseOrderLine', on_delete=models.SET_NULL, null=True, blank=True, related_name='movements'
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.movement_type} {self.ingredient_id} {self.quantity_delta}"


class PurchaseOrder(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_ORDERED = 'ordered'
    STATUS_PARTIAL = 'partially_received'
    STATUS_RECEIVED = 'received'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_ORDERED, 'Ordered'),
        (STATUS_PARTIAL, 'Partially received'),
        (STATUS_RECEIVED, 'Received'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name='purchase_orders', null=True, blank=True
    )
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchase_orders')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    reference = models.CharField(max_length=80, blank=True)
    expected_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        permissions = [
            ('can_manage_purchase_order', 'Create and edit purchase orders'),
            ('can_receive_purchase_order', 'Receive purchase orders into stock'),
        ]

    def __str__(self):
        return f"PO-{self.id} ({self.get_status_display()})"


class PurchaseOrderLine(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='lines')
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name='po_lines')
    quantity_ordered = models.DecimalField(max_digits=14, decimal_places=4)
    quantity_received = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"PO{self.purchase_order_id} {self.ingredient.name}"
