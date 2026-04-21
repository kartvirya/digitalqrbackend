from rest_framework import serializers
from .models import (
    Restaurant,
    User,
    Table,
    Floor,
    Room,
    menu_item,
    order,
    rating,
    bill,
    Payment,
    Department,
    Role,
    Staff,
    Attendance,
    Leave,
    HRDepartment,
    HRPosition,
    Employee,
    EmployeeDocument,
    Payroll,
    LeaveRequest,
    PerformanceReview,
    Training,
    TrainingEnrollment,
    Supplier,
    Ingredient,
    IngredientStock,
    MenuItemRecipe,
    StockMovement,
    PurchaseOrder,
    PurchaseOrderLine,
    SubscriptionPlan,
    RestaurantSubscription,
    TenantUsageSnapshot,
    BillingInvoice,
    BillingTransaction,
    PlatformAuditLog,
)
import json


class RestaurantSerializer(serializers.ModelSerializer):
    """Serializer for Restaurant model"""
    stats = serializers.SerializerMethodField()
    
    class Meta:
        model = Restaurant
        fields = [
            'id', 'name', 'slug', 'address', 'phone', 'email',
            'is_active', 'subscription_status', 'lifecycle_status', 'archived_at', 'terminated_at', 'settings',
            'created_at', 'updated_at', 'stats'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_stats(self, obj):
        """Get restaurant statistics"""
        return {
            'tables_count': obj.tables.count(),
            'rooms_count': obj.rooms.count(),
            'menu_items_count': obj.menu_items.count(),
            'orders_count': obj.orders.count(),
            'staff_count': obj.staff_members.count(),
        }


class FloorSerializer(serializers.ModelSerializer):
    table_count = serializers.SerializerMethodField()
    restaurant = RestaurantSerializer(read_only=True)
    restaurant_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    
    class Meta:
        model = Floor
        fields = ['id', 'name', 'description', 'is_active', 'created_at', 'table_count', 'restaurant', 'restaurant_id']
        read_only_fields = ['id', 'created_at']
    
    def get_table_count(self, obj):
        return obj.tables.count()


class UserSerializer(serializers.ModelSerializer):
    staff_profile = serializers.SerializerMethodField()
    restaurant = RestaurantSerializer(read_only=True)
    restaurant_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    django_groups = serializers.SerializerMethodField()
    django_permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'first_name', 'last_name', 'phone', 'cafe_manager',
            'is_superuser', 'is_super_admin', 'order_count', 'staff_profile',
            'restaurant', 'restaurant_id', 'django_groups', 'django_permissions',
        ]
        read_only_fields = ['id', 'order_count']

    def get_django_groups(self, obj):
        return list(obj.groups.order_by('name').values_list('name', flat=True))

    def get_django_permissions(self, obj):
        return sorted(obj.get_all_permissions())
    
    def get_staff_profile(self, obj):
        try:
            staff = obj.staff_profile
            if staff:
                return {
                    'id': staff.id,
                    'employee_id': staff.employee_id,
                    'full_name': staff.full_name,
                    'email': staff.email,
                    'phone': staff.phone,
                    'department': {
                        'id': staff.department.id,
                        'name': staff.department.name
                    },
                    'role': {
                        'id': staff.role.id,
                        'name': staff.role.name
                    },
                    'hire_date': staff.hire_date,
                    'salary': staff.salary,
                    'employment_status': staff.employment_status,
                    'django_groups': list(
                        staff.user.groups.order_by('name').values_list('name', flat=True)
                    ),
                }
            return None
        except:
            return None


class TableSerializer(serializers.ModelSerializer):
    qr_code_url = serializers.SerializerMethodField()
    floor_name = serializers.CharField(source='floor.name', read_only=True)
    room_name = serializers.CharField(source='room.room_name', read_only=True)
    has_active_order = serializers.SerializerMethodField()
    restaurant = RestaurantSerializer(read_only=True)
    restaurant_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    
    class Meta:
        model = Table
        fields = [
            'id', 'table_number', 'table_name', 'capacity', 'is_active', 
            'qr_code', 'qr_code_url', 'qr_unique_id', 'created_at', 
            'visual_x', 'visual_y', 'floor', 'floor_name', 'room', 'room_name',
            'shape', 'width', 'height', 'radius', 'has_active_order',
            'restaurant', 'restaurant_id'
        ]
        read_only_fields = ['id', 'qr_code', 'qr_code_url', 'qr_unique_id', 'created_at']
    
    def get_qr_code_url(self, obj):
        if obj.qr_code:
            return self.context['request'].build_absolute_uri(obj.qr_code.url)
        return None
    
    def get_has_active_order(self, obj):
        from .models import order
        # A table is considered occupied if there is at least one order
        # that is not cancelled and not fully paid.
        active_statuses = ['pending', 'confirmed', 'preparing', 'ready', 'served', 'delivered']
        return order.objects.filter(
            table_unique_id=obj.qr_unique_id,
            status__in=active_statuses,
            payment_status__in=['unpaid', 'pending_payment', 'failed']
        ).exists()


class RoomSerializer(serializers.ModelSerializer):
    qr_code_url = serializers.SerializerMethodField()
    floor_name = serializers.CharField(source='floor.name', read_only=True)
    has_active_order = serializers.SerializerMethodField()
    restaurant = RestaurantSerializer(read_only=True)
    restaurant_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    
    class Meta:
        model = Room
        fields = ['id', 'room_number', 'room_name', 'room_type', 'floor', 'floor_name', 'capacity', 'price_per_night', 'is_active', 'room_status', 'qr_code', 'qr_code_url', 'qr_unique_id', 'description', 'amenities', 'created_at', 'updated_at', 'has_active_order', 'restaurant', 'restaurant_id']
        read_only_fields = ['id', 'qr_code', 'qr_code_url', 'qr_unique_id', 'created_at', 'updated_at']
    
    def get_qr_code_url(self, obj):
        if obj.qr_code:
            return self.context['request'].build_absolute_uri(obj.qr_code.url)
        return None
    
    def get_has_active_order(self, obj):
        from .models import order
        # A room is considered occupied if there is at least one order
        # that is not cancelled and not fully paid.
        active_statuses = ['pending', 'confirmed', 'preparing', 'ready', 'served', 'delivered']
        return order.objects.filter(
            room_unique_id=obj.qr_unique_id,
            status__in=active_statuses,
            payment_status__in=['unpaid', 'pending_payment', 'failed']
        ).exists()


class MenuItemSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    # Use a writable DecimalField for price so create/update can set it.
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    
    class Meta:
        model = menu_item
        fields = ['id', 'name', 'category', 'description', 'image', 'image_url', 'price', 'is_available']
        read_only_fields = ['id']
    
    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class OrderSerializer(serializers.ModelSerializer):
    items_json = serializers.CharField(read_only=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    table = serializers.CharField(read_only=True)
    table_unique_id = serializers.CharField(read_only=True)
    room_unique_id = serializers.CharField(read_only=True)
    order_type = serializers.CharField(read_only=True)
    payment_status = serializers.CharField(read_only=True)
    payment_method = serializers.CharField(read_only=True)
    placed_by_staff_name = serializers.SerializerMethodField()
    assigned_runner_name = serializers.SerializerMethodField()

    class Meta:
        model = order
        fields = [
            'id',
            'name',
            'phone',
            'table',
            'price',
            'currency',
            'tip_amount',
            'status',
            'payment_status',
            'payment_method',
            'estimated_time',
            'created_at',
            'updated_at',
            'special_instructions',
            'items_json',
            'table_unique_id',
            'room_unique_id',
            'order_type',
            'invoice_number',
            'placed_by',
            'placed_by_staff',
            'placed_by_staff_name',
            'assigned_runner',
            'assigned_runner_name',
            'assigned_at',
            'kitchen_notes',
            'stock_consumed_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_placed_by_staff_name(self, obj):
        if obj.placed_by_staff_id:
            return obj.placed_by_staff.full_name
        return None

    def get_assigned_runner_name(self, obj):
        if obj.assigned_runner_id:
            return obj.assigned_runner.full_name
        return None


class RatingSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='name')
    created_at = serializers.DateField(source='r_date')
    updated_at = serializers.DateField(source='r_date')

    class Meta:
        model = rating
        fields = ['id', 'user_name', 'comment', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class BillSerializer(serializers.ModelSerializer):
    order_items = serializers.JSONField()
    
    class Meta:
        model = bill
        fields = [
            'id',
            'order',
            'order_items',
            'name',
            'bill_total',
            'currency',
            'phone',
            'bill_time',
            'table_number',
            'invoice_number',
            'payment_status',
            'payment_method',
            'tip_amount',
        ]
        read_only_fields = ['id', 'bill_time']


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            'id',
            'restaurant',
            'order',
            'bill',
            'provider',
            'provider_payment_id',
            'provider_order_id',
            'amount',
            'currency',
            'status',
            'raw_response',
            'error_message',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class OrderCreateSerializer(serializers.ModelSerializer):
    items_json = serializers.JSONField()
    
    class Meta:
        model = order
        fields = ['id', 'items_json', 'name', 'phone', 'table', 'table_unique_id', 'price', 'special_instructions', 'status', 'estimated_time', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def create(self, validated_data):
        # Set default values for required fields
        validated_data.setdefault('status', 'pending')
        validated_data.setdefault('estimated_time', 20)
        validated_data.setdefault('bill_clear', False)
        return super().create(validated_data)


class DepartmentSerializer(serializers.ModelSerializer):
    staff_count = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = ['id', 'name', 'description', 'is_active', 'created_at', 'updated_at', 'staff_count']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_staff_count(self, obj):
        return obj.staff.count()

class RoleSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)

    class Meta:
        model = Role
        fields = ['id', 'name', 'description', 'department', 'department_name', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

class StaffSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    department_name = serializers.CharField(source='department.name', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)
    profile_picture_url = serializers.SerializerMethodField()
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Staff
        fields = [
            'id', 'employee_id', 'user', 'first_name', 'last_name', 'full_name', 'email', 'phone',
            'date_of_birth', 'gender', 'address', 'emergency_contact_name', 'emergency_contact_phone',
            'department', 'department_name', 'role', 'role_name', 'hire_date', 'salary',
            'employment_status', 'is_active', 'operational_access', 'profile_picture', 'profile_picture_url',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_profile_picture_url(self, obj):
        if obj.profile_picture:
            return self.context['request'].build_absolute_uri(obj.profile_picture.url)
        return None

class StaffCreateSerializer(serializers.ModelSerializer):
    user_data = serializers.DictField(write_only=True)

    class Meta:
        model = Staff
        fields = [
            'employee_id', 'first_name', 'last_name', 'email', 'phone', 'date_of_birth',
            'gender', 'address', 'emergency_contact_name', 'emergency_contact_phone',
            'department', 'role', 'hire_date', 'salary', 'operational_access', 'user_data'
        ]

    def create(self, validated_data):
        user_data = validated_data.pop('user_data')

        user = User.objects.create_user(
            phone=user_data['phone'],
            password=user_data['password'],
        )
        user.role = 'staff'
        user.first_name = validated_data.get('first_name', '')
        user.last_name = validated_data.get('last_name', '')
        user.save(update_fields=['role', 'first_name', 'last_name'])

        staff = Staff.objects.create(user=user, **validated_data)
        if staff.restaurant_id:
            user.restaurant = staff.restaurant
            user.save(update_fields=['restaurant'])
        return staff

class AttendanceSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.full_name', read_only=True)
    staff_employee_id = serializers.CharField(source='staff.employee_id', read_only=True)
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)

    class Meta:
        model = Attendance
        fields = [
            'id', 'staff', 'staff_name', 'staff_employee_id', 'employee', 'employee_name',
            'date', 'check_in_time',
            'check_out_time', 'status', 'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

class LeaveSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.full_name', read_only=True)
    staff_employee_id = serializers.CharField(source='staff.employee_id', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.full_name', read_only=True)
    duration_days = serializers.IntegerField(read_only=True)

    class Meta:
        model = Leave
        fields = [
            'id', 'staff', 'staff_name', 'staff_employee_id', 'leave_type', 'start_date',
            'end_date', 'reason', 'status', 'approved_by', 'approved_by_name', 'approved_at',
            'notes', 'duration_days', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'staff', 'created_at', 'updated_at']

# HR Management Serializers
class HRDepartmentSerializer(serializers.ModelSerializer):
    manager_name = serializers.CharField(source='manager.full_name', read_only=True)
    employee_count = serializers.SerializerMethodField()

    class Meta:
        model = HRDepartment
        fields = [
            'id', 'name', 'description', 'manager', 'manager_name', 
            'is_active', 'created_at', 'updated_at', 'employee_count'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_employee_count(self, obj):
        return obj.employees.count()

class HRPositionSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)

    class Meta:
        model = HRPosition
        fields = [
            'id', 'name', 'department', 'department_name', 'description',
            'salary_range_min', 'salary_range_max', 'is_active', 
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

class EmployeeSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    position_name = serializers.CharField(source='position.name', read_only=True)
    department_name = serializers.CharField(source='department.name', read_only=True)
    profile_picture_url = serializers.SerializerMethodField()
    resume_url = serializers.SerializerMethodField()
    id_proof_url = serializers.SerializerMethodField()
    full_name = serializers.CharField(read_only=True)
    years_of_service = serializers.IntegerField(read_only=True)

    class Meta:
        model = Employee
        fields = [
            'id', 'employee_id', 'personnel_number', 'user', 'first_name', 'last_name', 
            'middle_name', 'gender', 'date_of_birth', 'email', 'phone', 'address', 
            'city', 'state', 'postal_code', 'country', 'position', 'position_name',
            'department', 'department_name', 'hire_date', 'termination_date', 
            'employment_status', 'base_salary', 'current_salary', 'salary_currency',
            'emergency_contact_name', 'emergency_contact_phone', 'emergency_contact_relationship',
            'profile_picture', 'profile_picture_url', 'resume', 'resume_url', 
            'id_proof', 'id_proof_url', 'notes', 'is_active', 'full_name', 
            'years_of_service', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_profile_picture_url(self, obj):
        if obj.profile_picture:
            return self.context['request'].build_absolute_uri(obj.profile_picture.url)
        return None

    def get_resume_url(self, obj):
        if obj.resume:
            return self.context['request'].build_absolute_uri(obj.resume.url)
        return None

    def get_id_proof_url(self, obj):
        if obj.id_proof:
            return self.context['request'].build_absolute_uri(obj.id_proof.url)
        return None

class EmployeeCreateSerializer(serializers.ModelSerializer):
    user_data = serializers.DictField(write_only=True)

    class Meta:
        model = Employee
        fields = [
            'employee_id', 'personnel_number', 'first_name', 'last_name', 'middle_name',
            'gender', 'date_of_birth', 'email', 'phone', 'address', 'city', 'state',
            'postal_code', 'country', 'position', 'department', 'hire_date',
            'base_salary', 'current_salary', 'salary_currency', 'emergency_contact_name',
            'emergency_contact_phone', 'emergency_contact_relationship', 'user_data'
        ]

    def create(self, validated_data):
        user_data = validated_data.pop('user_data')
        
        # Create user account
        user = User.objects.create_user(
            phone=user_data['phone'],
            password=user_data['password']
        )
        
        # Create employee profile
        employee = Employee.objects.create(user=user, **validated_data)
        return employee

class EmployeeDocumentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)

    class Meta:
        model = EmployeeDocument
        fields = [
            'id', 'employee', 'employee_name', 'document_type', 'title', 'file', 
            'file_url', 'description', 'expiry_date', 'is_verified', 'uploaded_at'
        ]
        read_only_fields = ['id', 'uploaded_at']

    def get_file_url(self, obj):
        if obj.file:
            return self.context['request'].build_absolute_uri(obj.file.url)
        return None

class PayrollSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    employee_id = serializers.CharField(source='employee.employee_id', read_only=True)

    class Meta:
        model = Payroll
        fields = [
            'id', 'employee', 'employee_name', 'employee_id', 'month', 'year',
            'basic_salary', 'allowances', 'deductions', 'net_salary', 'payment_date',
            'payment_status', 'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

class LeaveRequestSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    employee_id = serializers.CharField(source='employee.employee_id', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.full_name', read_only=True)
    duration_days = serializers.IntegerField(read_only=True)

    class Meta:
        model = LeaveRequest
        fields = [
            'id', 'employee', 'employee_name', 'employee_id', 'leave_type',
            'start_date', 'end_date', 'reason', 'status', 'approved_by', 
            'approved_by_name', 'approved_at', 'rejection_reason', 'duration_days',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

class PerformanceReviewSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    employee_id = serializers.CharField(source='employee.employee_id', read_only=True)
    reviewer_name = serializers.CharField(source='reviewer.full_name', read_only=True)

    class Meta:
        model = PerformanceReview
        fields = [
            'id', 'employee', 'employee_name', 'employee_id', 'review_period_start',
            'review_period_end', 'reviewer', 'reviewer_name', 'overall_rating',
            'strengths', 'areas_for_improvement', 'goals', 'comments', 'review_date',
            'next_review_date', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

class TrainingSerializer(serializers.ModelSerializer):
    enrollment_count = serializers.SerializerMethodField()

    class Meta:
        model = Training
        fields = [
            'id', 'title', 'description', 'training_type', 'trainer', 'start_date',
            'end_date', 'location', 'max_participants', 'status', 'enrollment_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_enrollment_count(self, obj):
        return obj.enrollments.count()

class TrainingEnrollmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    employee_id = serializers.CharField(source='employee.employee_id', read_only=True)
    training_title = serializers.CharField(source='training.title', read_only=True)
    certificate_url = serializers.SerializerMethodField()

    class Meta:
        model = TrainingEnrollment
        fields = [
            'id', 'employee', 'employee_name', 'employee_id', 'training', 
            'training_title', 'enrollment_date', 'completion_date', 'certificate_issued',
            'certificate_file', 'certificate_url', 'feedback', 'rating'
        ]
        read_only_fields = ['id', 'enrollment_date']

    def get_certificate_url(self, obj):
        if obj.certificate_file:
            return self.context['request'].build_absolute_uri(obj.certificate_file.url)
        return None


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = [
            'id', 'restaurant', 'name', 'phone', 'email', 'address',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class IngredientStockSerializer(serializers.ModelSerializer):
    class Meta:
        model = IngredientStock
        fields = ['id', 'ingredient', 'quantity_on_hand', 'updated_at']
        read_only_fields = ['id', 'updated_at']


class IngredientSerializer(serializers.ModelSerializer):
    quantity_on_hand = serializers.SerializerMethodField()

    class Meta:
        model = Ingredient
        fields = [
            'id', 'restaurant', 'name', 'sku', 'unit', 'reorder_level',
            'is_active', 'quantity_on_hand', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_quantity_on_hand(self, obj):
        try:
            return obj.stock_level.quantity_on_hand
        except IngredientStock.DoesNotExist:
            return None


class MenuItemRecipeSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source='ingredient.name', read_only=True)
    menu_item_name = serializers.CharField(source='menu_item.name', read_only=True)

    class Meta:
        model = MenuItemRecipe
        fields = [
            'id', 'menu_item', 'menu_item_name', 'ingredient', 'ingredient_name', 'quantity',
        ]
        read_only_fields = ['id']


class StockMovementSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source='ingredient.name', read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            'id', 'restaurant', 'ingredient', 'ingredient_name', 'quantity_delta',
            'movement_type', 'order_ref', 'purchase_order_line', 'notes',
            'created_at', 'created_by',
        ]
        read_only_fields = ['id', 'created_at']


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source='ingredient.name', read_only=True)

    class Meta:
        model = PurchaseOrderLine
        fields = [
            'id', 'purchase_order', 'ingredient', 'ingredient_name',
            'quantity_ordered', 'quantity_received', 'unit_cost',
        ]
        read_only_fields = ['id']


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines = PurchaseOrderLineSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            'id', 'restaurant', 'supplier', 'supplier_name', 'status', 'reference',
            'expected_date', 'notes', 'lines', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = [
            'id', 'code', 'name', 'billing_cycle', 'price', 'currency',
            'max_staff', 'max_monthly_orders', 'max_tables', 'modules', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class RestaurantSubscriptionSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source='plan.name', read_only=True)
    plan_code = serializers.CharField(source='plan.code', read_only=True)
    plan_modules = serializers.JSONField(source='plan.modules', read_only=True)

    class Meta:
        model = RestaurantSubscription
        fields = [
            'id', 'restaurant', 'plan', 'plan_name', 'plan_code', 'plan_modules',
            'status', 'trial_ends_at', 'current_period_start', 'current_period_end',
            'is_active', 'metadata', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class TenantUsageSnapshotSerializer(serializers.ModelSerializer):
    restaurant_name = serializers.CharField(source='restaurant.name', read_only=True)

    class Meta:
        model = TenantUsageSnapshot
        fields = [
            'id', 'restaurant', 'restaurant_name', 'month_key',
            'orders_count', 'active_staff_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class BillingInvoiceSerializer(serializers.ModelSerializer):
    restaurant_name = serializers.CharField(source='restaurant.name', read_only=True)
    plan_name = serializers.CharField(source='plan.name', read_only=True)

    class Meta:
        model = BillingInvoice
        fields = [
            'id', 'restaurant', 'restaurant_name', 'subscription', 'plan', 'plan_name',
            'invoice_number', 'amount', 'currency', 'due_date', 'status', 'metadata',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'invoice_number', 'created_at', 'updated_at']


class BillingTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingTransaction
        fields = [
            'id', 'invoice', 'gateway', 'status', 'gateway_reference',
            'request_payload', 'response_payload', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PlatformAuditLogSerializer(serializers.ModelSerializer):
    actor_phone = serializers.CharField(source='actor.phone', read_only=True)
    restaurant_name = serializers.CharField(source='restaurant.name', read_only=True)

    class Meta:
        model = PlatformAuditLog
        fields = [
            'id', 'actor', 'actor_phone', 'restaurant', 'restaurant_name', 'action',
            'target_type', 'target_id', 'before_state', 'after_state', 'metadata', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']
