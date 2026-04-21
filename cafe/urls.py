from django.urls import path, include
from cafe import views
from cafe.api_views import (
    RestaurantViewSet, SuperAdminDashboardViewSet,
    MenuItemViewSet, TableViewSet, FloorViewSet, RoomViewSet,
    OrderViewSet, RatingViewSet, BillViewSet, AuthViewSet, DashboardViewSet,
    DepartmentViewSet, RoleViewSet, StaffViewSet, AttendanceViewSet, LeaveViewSet,
    HRDepartmentViewSet, HRPositionViewSet, EmployeeViewSet, EmployeeDocumentViewSet,
    PayrollViewSet, LeaveRequestViewSet, PerformanceReviewViewSet, TrainingViewSet,
    TrainingEnrollmentViewSet, PermissionViewSet, RolePermissionViewSet, UserRoleViewSet,
    SubscriptionPlanViewSet, RestaurantSubscriptionViewSet
)
from cafe.inventory_views import (
    SupplierViewSet,
    IngredientViewSet,
    MenuItemRecipeViewSet,
    StockMovementViewSet,
    PurchaseOrderViewSet,
)
from rest_framework.routers import DefaultRouter
from django.conf import settings
from django.conf.urls.static import static

# API Router
router = DefaultRouter()
router.register(r'api/restaurants', RestaurantViewSet)
router.register(r'api/menu', MenuItemViewSet)
router.register(r'api/tables', TableViewSet)
router.register(r'api/orders', OrderViewSet)
router.register(r'api/ratings', RatingViewSet)
router.register(r'api/bills', BillViewSet)
router.register(r'api/auth', AuthViewSet, basename='auth')
router.register(r'api/dashboard', DashboardViewSet, basename='dashboard')
router.register(r'api/super-admin', SuperAdminDashboardViewSet, basename='super-admin')
router.register(r'api/subscription-plans', SubscriptionPlanViewSet, basename='subscription-plans')
router.register(r'api/restaurant-subscriptions', RestaurantSubscriptionViewSet, basename='restaurant-subscriptions')

# HR Management URLs
router.register(r'api/hr-departments', HRDepartmentViewSet)
router.register(r'api/hr-positions', HRPositionViewSet)
router.register(r'api/employees', EmployeeViewSet)
router.register(r'api/employee-documents', EmployeeDocumentViewSet)
router.register(r'api/payrolls', PayrollViewSet)
router.register(r'api/leave-requests', LeaveRequestViewSet)
router.register(r'api/performance-reviews', PerformanceReviewViewSet)
router.register(r'api/trainings', TrainingViewSet)
router.register(r'api/training-enrollments', TrainingEnrollmentViewSet)

# Role Management URLs
router.register(r'api/permissions', PermissionViewSet, basename='permissions')
router.register(r'api/role-permissions', RolePermissionViewSet, basename='role-permissions')
router.register(r'api/user-roles', UserRoleViewSet, basename='user-roles')

router.register(r'api/inventory/suppliers', SupplierViewSet, basename='inventory-suppliers')
router.register(r'api/inventory/ingredients', IngredientViewSet, basename='inventory-ingredients')
router.register(r'api/inventory/recipes', MenuItemRecipeViewSet, basename='inventory-recipes')
router.register(r'api/inventory/movements', StockMovementViewSet, basename='inventory-movements')
router.register(r'api/inventory/purchase-orders', PurchaseOrderViewSet, basename='inventory-purchase-orders')

urlpatterns = [
    # API endpoints
    path('', include(router.urls)),
    
    # Additional API endpoints
    path('api/order-status/<int:order_id>/', views.api_order_status, name='api_order_status'),
    path('api/delete-dish/<int:item_id>/', views.api_delete_dish, name='api_delete_dish'),
    path('api/generate-bill/', views.api_generate_bill, name='api_generate_bill'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
