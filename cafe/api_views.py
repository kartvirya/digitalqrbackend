from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.db.models import Q, Count, Avg, Sum, Max
from django.contrib.admin.models import LogEntry
from datetime import date
import json
from django.utils import timezone
from datetime import date, datetime, timedelta
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from django.db import transaction
from django.contrib.sessions.models import Session
import os
import sys
import requests
import json
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from decimal import Decimal

from .models import (
    Restaurant, User, Table, Floor, Room, menu_item, order, rating, bill,
    Department, Role, Staff, Attendance, Leave,
    HRDepartment, HRPosition, Employee, EmployeeDocument, Payroll, LeaveRequest, PerformanceReview, Training, TrainingEnrollment,
    Permission, RolePermission, Payment, SubscriptionPlan, RestaurantSubscription, TenantUsageSnapshot,
    BillingInvoice, BillingTransaction, PlatformAuditLog,
)
from .serializers import (
    RestaurantSerializer, UserSerializer, TableSerializer, FloorSerializer, RoomSerializer, MenuItemSerializer, 
    OrderSerializer, RatingSerializer, BillSerializer, OrderCreateSerializer,
    DepartmentSerializer, RoleSerializer, StaffSerializer, StaffCreateSerializer,
    AttendanceSerializer, LeaveSerializer,
    HRDepartmentSerializer, HRPositionSerializer, EmployeeSerializer, EmployeeCreateSerializer, EmployeeDocumentSerializer, PayrollSerializer, LeaveRequestSerializer, PerformanceReviewSerializer, TrainingSerializer, TrainingEnrollmentSerializer,
    PaymentSerializer, SubscriptionPlanSerializer, RestaurantSubscriptionSerializer, TenantUsageSnapshotSerializer,
    BillingInvoiceSerializer, BillingTransactionSerializer, PlatformAuditLogSerializer,
)
from .permissions import (
    IsSuperAdmin,
    IsRestaurantAdmin,
    IsHRManager,
    IsStaff,
    HasPermission,
    IsRestaurantScoped,
    OrderCreatePermission,
    OrderListRetrievePermission,
    OrderUpdateStatusPermission,
    OrderMarkPaidPermission,
    OrderAssignRunnerPermission,
    OrderClearTablePermission,
    order_transition_allowed,
    is_restaurant_power_user,
)
from .inventory_service import consume_stock_for_order, reverse_stock_for_order
from .billing.providers.esewa import EsewaBillingProvider


def resolve_request_restaurant(request):
    restaurant = getattr(request, 'restaurant', None)
    if not restaurant and request.user.is_authenticated and getattr(request.user, 'restaurant', None):
        restaurant = request.user.restaurant
    if not restaurant and request.user.is_authenticated and hasattr(request.user, 'staff_profile'):
        restaurant = getattr(request.user.staff_profile, 'restaurant', None)
    return restaurant


def tenant_scoped_queryset(queryset, request, field_name='restaurant'):
    restaurant = resolve_request_restaurant(request)
    if restaurant:
        return queryset.filter(**{field_name: restaurant})
    if request.user.is_authenticated and (request.user.is_super_admin or request.user.is_superuser):
        return queryset
    return queryset.none()


def get_order_for_write_request(request, order_id):
    """Resolve order for status/payment actions with restaurant scoping."""
    oid = int(order_id)
    restaurant = resolve_request_restaurant(request)
    if restaurant:
        return get_object_or_404(order, id=oid, restaurant=restaurant)
    if request.user.is_authenticated and (
        request.user.is_super_admin or request.user.is_superuser
    ):
        return get_object_or_404(order, id=oid)
    raise PermissionDenied('Restaurant context is required for this action.')


def log_platform_action(
    *,
    actor,
    action,
    restaurant=None,
    target_type='',
    target_id='',
    before_state=None,
    after_state=None,
    metadata=None,
):
    def _safe_json(data):
        if isinstance(data, dict):
            return {k: _safe_json(v) for k, v in data.items()}
        if isinstance(data, list):
            return [_safe_json(v) for v in data]
        if isinstance(data, (datetime, date)):
            return data.isoformat()
        return data

    PlatformAuditLog.objects.create(
        actor=actor if actor and actor.is_authenticated else None,
        restaurant=restaurant,
        action=action,
        target_type=target_type,
        target_id=str(target_id or ''),
        before_state=_safe_json(before_state or {}),
        after_state=_safe_json(after_state or {}),
        metadata=_safe_json(metadata or {}),
    )


class RestaurantViewSet(viewsets.ModelViewSet):
    """ViewSet for Restaurant management"""
    queryset = Restaurant.objects.all().order_by('name')
    serializer_class = RestaurantSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'public_landing']:
            return [permissions.AllowAny()]  # Allow viewing restaurants
        return [permissions.IsAuthenticated()]

    def _default_landing_config(self, restaurant):
        display_name = restaurant.name if restaurant else 'Our Restaurant'
        return {
            'brand_name': display_name,
            'hero_title': f'Welcome to {display_name}',
            'hero_subtitle': 'Delightful dining experiences for hotels and restaurants.',
            'hero_cta_text': 'View Menu',
            'hero_cta_link': '/',
            'about_title': 'About Us',
            'about_text': 'We serve handcrafted food with exceptional hospitality.',
            'address': restaurant.address if restaurant and restaurant.address else '',
            'phone': restaurant.phone if restaurant and restaurant.phone else '',
            'email': restaurant.email if restaurant and restaurant.email else '',
            'opening_hours': 'Mon-Sun: 10:00 AM - 11:00 PM',
            'primary_color': '#d0155c',
            'secondary_color': '#111827',
            'show_gallery': True,
            'gallery_images': [],
            'highlights': [
                {'title': 'Fine Dining', 'description': 'Curated menu with premium ingredients.'},
                {'title': 'Hotel Service', 'description': 'Room dining and concierge support.'},
                {'title': 'Events', 'description': 'Private events and celebrations available.'},
            ],
        }
    
    def get_queryset(self):
        user = self.request.user
        
        # Super admin can see all restaurants
        if user.is_authenticated and (user.is_super_admin or user.is_superuser):
            return Restaurant.objects.all().order_by('name')
        
        # Restaurant admin can only see their own restaurant
        if user.is_authenticated and user.restaurant:
            return Restaurant.objects.filter(id=user.restaurant.id)
        
        # Regular users can see active restaurants
        return Restaurant.objects.filter(is_active=True).order_by('name')
    
    def create(self, request, *args, **kwargs):
        # Only super admin can create restaurants
        if not (request.user.is_super_admin or request.user.is_superuser):
            raise PermissionDenied("Only super administrators can create restaurants")
        
        # Extract admin credentials from request data
        admin_phone = request.data.get('admin_phone')
        admin_password = request.data.get('admin_password')
        admin_first_name = request.data.get('admin_first_name', '')
        admin_last_name = request.data.get('admin_last_name', '')
        
        # Validate admin credentials if provided
        if admin_phone and not admin_password:
            return Response(
                {'error': 'Admin password is required when admin phone is provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if admin_password and not admin_phone:
            return Response(
                {'error': 'Admin phone is required when admin password is provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create the restaurant
        try:
            response = super().create(request, *args, **kwargs)
            restaurant = Restaurant.objects.get(id=response.data['id'])
        except Exception as e:
            return Response(
                {'error': f'Failed to create restaurant: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create restaurant admin user if credentials provided
        if admin_phone and admin_password:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            try:
                # Check if user with this phone already exists
                if User.objects.filter(phone=admin_phone).exists():
                    # Update existing user to be restaurant admin
                    admin_user = User.objects.get(phone=admin_phone)
                    # Don't update if user is already a super admin
                    if admin_user.is_super_admin:
                        return Response(
                            {'error': f'Phone {admin_phone} belongs to a super admin. Cannot assign to restaurant.'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    admin_user.restaurant = restaurant
                    admin_user.cafe_manager = True
                    admin_user.is_staff = True
                    admin_user.set_password(admin_password)
                    if admin_first_name:
                        admin_user.first_name = admin_first_name
                    if admin_last_name:
                        admin_user.last_name = admin_last_name
                    admin_user.save()
                else:
                    # Create new restaurant admin user
                    admin_user = User.objects.create_user(
                        phone=admin_phone,
                        password=admin_password,
                        restaurant=restaurant,
                        cafe_manager=True,
                        is_staff=True,
                        first_name=admin_first_name,
                        last_name=admin_last_name
                    )
                
                # Add admin info to response
                response.data['admin_created'] = True
                response.data['admin_phone'] = admin_phone
            except Exception as e:
                # If admin creation fails, delete the restaurant
                restaurant.delete()
                return Response(
                    {'error': f'Failed to create restaurant admin: {str(e)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        return response
    
    def perform_update(self, serializer):
        restaurant = serializer.instance
        
        # Super admin can update any restaurant
        if self.request.user.is_super_admin or self.request.user.is_superuser:
            serializer.save()
        # Restaurant admin can only update their own restaurant
        elif self.request.user.restaurant and self.request.user.restaurant.id == restaurant.id:
            serializer.save()
        else:
            raise PermissionDenied("You can only update your own restaurant")
    
    def perform_destroy(self, instance):
        # Only super admin can delete restaurants
        if not (self.request.user.is_super_admin or self.request.user.is_superuser):
            raise PermissionDenied("Only super administrators can delete restaurants")
        instance.delete()

    @action(detail=False, methods=['get'])
    def public_landing(self, request):
        slug = request.query_params.get('slug')
        if not slug:
            return Response({'error': 'slug query param is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            restaurant = Restaurant.objects.get(slug=slug, is_active=True)
        except Restaurant.DoesNotExist:
            return Response({'error': 'Restaurant not found'}, status=status.HTTP_404_NOT_FOUND)

        settings_dict = restaurant.settings or {}
        config = settings_dict.get('landing_page', {})
        payload = self._default_landing_config(restaurant)
        payload.update(config)
        payload['slug'] = restaurant.slug
        payload['restaurant_name'] = restaurant.name
        return Response(payload)

    @action(detail=False, methods=['get', 'patch'])
    def landing_config(self, request):
        if not request.user.is_authenticated:
            return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)

        restaurant = None
        slug = request.query_params.get('slug') or request.data.get('slug')
        if request.user.is_super_admin or request.user.is_superuser:
            restaurant_id = request.query_params.get('restaurant_id') or request.data.get('restaurant_id')
            if restaurant_id:
                try:
                    restaurant = Restaurant.objects.get(id=restaurant_id)
                except Restaurant.DoesNotExist:
                    return Response({'error': 'Restaurant not found'}, status=status.HTTP_404_NOT_FOUND)
            elif slug:
                try:
                    restaurant = Restaurant.objects.get(slug=slug, is_active=True)
                except Restaurant.DoesNotExist:
                    return Response({'error': 'Restaurant not found'}, status=status.HTTP_404_NOT_FOUND)
        if not restaurant:
            restaurant = request.user.restaurant

        is_admin_like = bool(
            request.user.is_super_admin
            or request.user.is_superuser
            or getattr(request.user, 'cafe_manager', False)
            or request.user.is_restaurant_admin()
        )

        # Backward-compatibility fallback for admin users without restaurant FK.
        if not restaurant and is_admin_like:
            if slug:
                restaurant = Restaurant.objects.filter(slug=slug, is_active=True).first()
            if not restaurant:
                restaurant = Restaurant.objects.filter(is_active=True).order_by('id').first()

        if not restaurant:
            return Response({'error': 'Restaurant context is required'}, status=status.HTTP_400_BAD_REQUEST)

        if not (request.user.is_super_admin or request.user.is_superuser or request.user.is_restaurant_admin()):
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)

        settings_dict = restaurant.settings or {}
        existing = settings_dict.get('landing_page', {})
        current = self._default_landing_config(restaurant)
        current.update(existing)

        if request.method.lower() == 'get':
            current['slug'] = restaurant.slug
            current['restaurant_name'] = restaurant.name
            return Response(current)

        allowed_fields = {
            'brand_name', 'hero_title', 'hero_subtitle', 'hero_cta_text', 'hero_cta_link',
            'about_title', 'about_text', 'address', 'phone', 'email', 'opening_hours',
            'primary_color', 'secondary_color', 'show_gallery', 'gallery_images', 'highlights'
        }
        updates = {k: v for k, v in request.data.items() if k in allowed_fields}
        current.update(updates)
        settings_dict['landing_page'] = current
        restaurant.settings = settings_dict
        restaurant.save(update_fields=['settings', 'updated_at'])
        current['slug'] = restaurant.slug
        current['restaurant_name'] = restaurant.name
        return Response(current)
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate or deactivate a restaurant"""
        restaurant = self.get_object()
        
        if not (request.user.is_super_admin or request.user.is_superuser):
            raise PermissionDenied("Only super administrators can activate/deactivate restaurants")
        
        restaurant.is_active = not restaurant.is_active
        restaurant.save()
        
        serializer = self.get_serializer(restaurant)
        return Response(serializer.data)


class MenuItemViewSet(viewsets.ModelViewSet):
    queryset = menu_item.objects.filter(is_available=True).order_by('category', 'name')
    serializer_class = MenuItemSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        # For create/update/delete, require restaurant admin or super admin
        return [IsRestaurantAdmin()]
    
    def get_queryset(self):
        queryset = menu_item.objects.filter(is_available=True).order_by('category', 'name')
        
        # Filter by restaurant if available
        restaurant = getattr(self.request, 'restaurant', None)
        if restaurant:
            queryset = queryset.filter(restaurant=restaurant)
        elif (
            self.request.user.is_authenticated
            and hasattr(self.request.user, 'staff_profile')
            and self.request.user.staff_profile.restaurant_id
        ):
            queryset = queryset.filter(restaurant_id=self.request.user.staff_profile.restaurant_id)
        elif self.action in ['list', 'retrieve']:
            # Keep public menu usable even when context headers/slug are missing.
            fallback_restaurant = Restaurant.objects.filter(is_active=True).order_by('id').first()
            if fallback_restaurant:
                queryset = queryset.filter(restaurant=fallback_restaurant)
            else:
                queryset = queryset.none()
        elif not (self.request.user.is_authenticated and (self.request.user.is_super_admin or self.request.user.is_superuser)):
            # Non-super-admin users must have a restaurant context
            queryset = queryset.none()

        return queryset
    
    def perform_create(self, serializer):
        # Check permission
        if not (self.request.user.is_restaurant_admin() or self.request.user.has_permission('manage_menu')):
            raise PermissionDenied("You don't have permission to create menu items")
        
        restaurant = getattr(self.request, 'restaurant', None)
        if not restaurant:
            if self.request.user.is_authenticated and self.request.user.restaurant:
                restaurant = self.request.user.restaurant
            elif (
                self.request.user.is_authenticated
                and (
                    self.request.user.is_superuser
                    or self.request.user.is_super_admin
                    or self.request.user.cafe_manager
                    or self.request.user.is_restaurant_admin()
                )
            ):
                restaurant = Restaurant.objects.filter(is_active=True).order_by('id').first()
            if not restaurant:
                raise PermissionDenied("Restaurant context is required")
        
        # Set list_order if not provided - get the next order number for this restaurant and category
        validated_data = serializer.validated_data
        if 'list_order' not in validated_data or validated_data.get('list_order') is None:
            # Get the max list_order for this restaurant and category
            category = validated_data.get('category', '')
            max_order = menu_item.objects.filter(
                restaurant=restaurant,
                category=category
            ).aggregate(Max('list_order'))['list_order__max'] or 0
            validated_data['list_order'] = max_order + 1
        
        serializer.save(restaurant=restaurant, list_order=validated_data.get('list_order', 0))
    
    def perform_update(self, serializer):
        if not (self.request.user.is_restaurant_admin() or self.request.user.has_permission('manage_menu')):
            raise PermissionDenied("You don't have permission to update menu items")
        serializer.save()
    
    def perform_destroy(self, instance):
        if not (self.request.user.is_restaurant_admin() or self.request.user.has_permission('manage_menu')):
            raise PermissionDenied("You don't have permission to delete menu items")
        instance.delete()


class FloorViewSet(viewsets.ModelViewSet):
    queryset = Floor.objects.all().order_by('name')
    serializer_class = FloorSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        return [IsRestaurantAdmin()]
    
    def get_queryset(self):
        queryset = Floor.objects.all()
        restaurant = getattr(self.request, 'restaurant', None)
        
        if restaurant:
            queryset = queryset.filter(restaurant=restaurant)
        elif self.request.user.is_authenticated and (self.request.user.is_super_admin or self.request.user.is_superuser):
            # Super admin can see all floors
            pass
        elif self.request.user.is_authenticated and hasattr(self.request.user, 'staff_profile'):
            sp = self.request.user.staff_profile
            if sp.restaurant_id:
                queryset = queryset.filter(restaurant_id=sp.restaurant_id)
            else:
                queryset = queryset.none()
        elif not (self.request.user.is_authenticated and (self.request.user.is_superuser or self.request.user.cafe_manager)):
            queryset = queryset.none()

        return queryset.filter(is_active=True).order_by('name')
    
    def perform_create(self, serializer):
        if not (self.request.user.is_restaurant_admin() or self.request.user.has_permission('manage_floors')):
            raise PermissionDenied("You don't have permission to create floors")
        
        restaurant = getattr(self.request, 'restaurant', None)
        if not restaurant:
            if self.request.user.is_authenticated and self.request.user.restaurant:
                restaurant = self.request.user.restaurant
            elif (
                self.request.user.is_authenticated
                and (
                    self.request.user.is_superuser
                    or self.request.user.is_super_admin
                    or self.request.user.cafe_manager
                    or self.request.user.is_restaurant_admin()
                )
            ):
                restaurant = Restaurant.objects.filter(is_active=True).order_by('id').first()
            if not restaurant:
                raise PermissionDenied("Restaurant context is required")
        serializer.save(restaurant=restaurant)
    
    def perform_update(self, serializer):
        if not (self.request.user.is_restaurant_admin() or self.request.user.has_permission('manage_floors')):
            raise PermissionDenied("You don't have permission to update floors")
        serializer.save()
    
    def perform_destroy(self, instance):
        if not (self.request.user.is_restaurant_admin() or self.request.user.has_permission('manage_floors')):
            raise PermissionDenied("You don't have permission to delete floors")
        instance.delete()


class TableViewSet(viewsets.ModelViewSet):
    queryset = Table.objects.all().order_by('table_number')
    serializer_class = TableSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_permissions(self):
        # Read-only discovery for menus / staff take-order (scoped in get_queryset).
        if self.action in ['list', 'retrieve', 'by_floor']:
            return [permissions.AllowAny()]
        return [IsRestaurantAdmin()]
    
    def get_queryset(self):
        user = self.request.user
        queryset = Table.objects.all()
        
        # Filter by restaurant
        restaurant = getattr(self.request, 'restaurant', None)
        if restaurant:
            queryset = queryset.filter(restaurant=restaurant)
        elif user.is_authenticated and (user.is_super_admin or user.is_superuser):
            pass
        elif user.is_authenticated and getattr(user, 'restaurant', None):
            queryset = queryset.filter(restaurant=user.restaurant)
        elif user.is_authenticated and hasattr(user, 'staff_profile'):
            sp = user.staff_profile
            if sp.restaurant_id:
                queryset = queryset.filter(restaurant_id=sp.restaurant_id)
            else:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        # Filter by floor if specified
        floor_id = self.request.query_params.get('floor')
        if floor_id:
            queryset = queryset.filter(floor_id=floor_id)

        if user.is_authenticated and (user.is_superuser or user.cafe_manager or user.is_super_admin):
            return queryset.order_by('table_number')
        return queryset.filter(is_active=True).order_by('table_number')
    
    def perform_create(self, serializer):
        if not (self.request.user.is_restaurant_admin() or self.request.user.has_permission('manage_tables')):
            raise PermissionDenied("You don't have permission to create tables")
        
        restaurant = getattr(self.request, 'restaurant', None)
        if not restaurant:
            if self.request.user.is_authenticated and self.request.user.restaurant:
                restaurant = self.request.user.restaurant
            elif (
                self.request.user.is_authenticated
                and (
                    self.request.user.is_superuser
                    or self.request.user.is_super_admin
                    or self.request.user.cafe_manager
                    or self.request.user.is_restaurant_admin()
                )
            ):
                restaurant = Restaurant.objects.filter(is_active=True).order_by('id').first()
            if not restaurant:
                raise PermissionDenied("Restaurant context is required")
        serializer.save(restaurant=restaurant)
    
    def perform_update(self, serializer):
        if not (self.request.user.is_restaurant_admin() or self.request.user.has_permission('manage_tables')):
            raise PermissionDenied("You don't have permission to update tables")
        serializer.save()
    
    def perform_destroy(self, instance):
        if not (self.request.user.is_restaurant_admin() or self.request.user.has_permission('manage_tables')):
            raise PermissionDenied("You don't have permission to delete tables")
        instance.delete()
    
    @action(detail=True, methods=['get'])
    def qr_code(self, request, pk=None):
        table = self.get_object()
        if table.qr_code:
            return Response({'qr_code_url': request.build_absolute_uri(table.qr_code.url)})
        return Response({'error': 'QR code not generated'}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=['post'])
    def regenerate_qr(self, request, pk=None):
        table = self.get_object()
        table.generate_qr_code()
        return Response({'message': 'QR code regenerated successfully'})
    
    @action(detail=True, methods=['post'])
    def update_position(self, request, pk=None):
        table = self.get_object()
        # Accept both {visual_x, visual_y} and shorthand {x, y}
        visual_x = request.data.get('visual_x', request.data.get('x'))
        visual_y = request.data.get('visual_y', request.data.get('y'))

        if visual_x is not None and visual_y is not None:
            try:
                # Coerce to integers (round if decimal provided)
                x_val = int(round(float(visual_x)))
                y_val = int(round(float(visual_y)))
            except (ValueError, TypeError):
                return Response({'error': 'visual_x and visual_y must be numbers'}, status=status.HTTP_400_BAD_REQUEST)

            table.visual_x = x_val
            table.visual_y = y_val
            table.save()
            serializer = self.get_serializer(table)
            return Response(serializer.data)
        return Response({'error': 'visual_x and visual_y are required'}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def by_floor(self, request):
        floor_id = request.query_params.get('floor_id') or request.query_params.get('floor')
        if not floor_id:
            return Response({'error': 'floor_id parameter is required'}, status=status.HTTP_400_BAD_REQUEST)
        # Use get_queryset() so staff / restaurant scoping matches list (not a global Table.objects leak).
        tables = self.get_queryset().filter(floor_id=floor_id)
        serializer = self.get_serializer(tables, many=True)
        return Response(serializer.data)


class RoomViewSet(viewsets.ModelViewSet):
    queryset = Room.objects.all().order_by('floor', 'room_number')
    serializer_class = RoomSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        return [IsRestaurantAdmin()]
    
    def get_queryset(self):
        user = self.request.user
        queryset = Room.objects.all()
        
        # Filter by restaurant
        restaurant = getattr(self.request, 'restaurant', None)
        if restaurant:
            queryset = queryset.filter(restaurant=restaurant)
        elif not (user.is_authenticated and (user.is_super_admin or user.is_superuser)):
            queryset = queryset.none()
        
        # Filter by floor if specified
        floor_id = self.request.query_params.get('floor')
        if floor_id:
            queryset = queryset.filter(floor_id=floor_id)
        
        # Filter by room status if specified
        room_status = self.request.query_params.get('status')
        if room_status:
            queryset = queryset.filter(room_status=room_status)
        
        if user.is_authenticated and (user.is_superuser or user.cafe_manager or user.is_super_admin):
            return queryset.order_by('floor', 'room_number')
        return queryset.filter(is_active=True).order_by('floor', 'room_number')
    
    def perform_create(self, serializer):
        if not (self.request.user.is_restaurant_admin() or self.request.user.has_permission('manage_rooms')):
            raise PermissionDenied("You don't have permission to create rooms")
        
        restaurant = getattr(self.request, 'restaurant', None)
        if not restaurant:
            if self.request.user.is_authenticated and self.request.user.restaurant:
                restaurant = self.request.user.restaurant
            elif (
                self.request.user.is_authenticated
                and (
                    self.request.user.is_superuser
                    or self.request.user.is_super_admin
                    or self.request.user.cafe_manager
                    or self.request.user.is_restaurant_admin()
                )
            ):
                restaurant = Restaurant.objects.filter(is_active=True).order_by('id').first()
            if not restaurant:
                raise PermissionDenied("Restaurant context is required")
        serializer.save(restaurant=restaurant)
    
    def perform_update(self, serializer):
        if not (self.request.user.is_restaurant_admin() or self.request.user.has_permission('manage_rooms')):
            raise PermissionDenied("You don't have permission to update rooms")
        serializer.save()
    
    def perform_destroy(self, instance):
        if not (self.request.user.is_restaurant_admin() or self.request.user.has_permission('manage_rooms')):
            raise PermissionDenied("You don't have permission to delete rooms")
        instance.delete()
    
    @action(detail=True, methods=['get'])
    def qr_code(self, request, pk=None):
        room = self.get_object()
        if room.qr_code:
            return Response({'qr_code_url': request.build_absolute_uri(room.qr_code.url)})
        return Response({'error': 'QR code not generated'}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=['post'])
    def regenerate_qr(self, request, pk=None):
        room = self.get_object()
        room.generate_qr_code()
        return Response({'message': 'QR code regenerated successfully'})
    
    @action(detail=False, methods=['get'])
    def by_floor(self, request):
        floor_id = request.query_params.get('floor_id') or request.query_params.get('floor')
        if floor_id:
            rooms = Room.objects.filter(floor_id=floor_id, is_active=True)
            serializer = self.get_serializer(rooms, many=True)
            return Response(serializer.data)
        return Response({'error': 'floor_id parameter is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def available(self, request):
        """Get all available rooms"""
        rooms = Room.objects.filter(room_status='available', is_active=True)
        serializer = self.get_serializer(rooms, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def occupied(self, request):
        """Get all occupied rooms"""
        rooms = Room.objects.filter(room_status='occupied', is_active=True)
        serializer = self.get_serializer(rooms, many=True)
        return Response(serializer.data)
    
class OrderViewSet(viewsets.ModelViewSet):
    queryset = order.objects.all().order_by('-created_at')
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action == 'create':
            return [OrderCreatePermission()]
        if self.action in ('list', 'retrieve'):
            return [OrderListRetrievePermission()]
        if self.action == 'update_status':
            return [OrderUpdateStatusPermission(), permissions.IsAuthenticated()]
        if self.action == 'mark_paid':
            return [OrderMarkPaidPermission(), permissions.IsAuthenticated()]
        if self.action == 'assign_runner':
            return [OrderAssignRunnerPermission(), permissions.IsAuthenticated()]
        if self.action == 'clear_table':
            return [OrderClearTablePermission(), permissions.IsAuthenticated()]
        if self.action in ('by_table', 'by_table_unique_id', 'by_room_unique_id', 'my_orders'):
            return [permissions.IsAuthenticated() if self.action == 'my_orders' else permissions.AllowAny()]
        return [permissions.IsAuthenticated()]
    
    def create(self, request, *args, **kwargs):
        # Allow anonymous order creation using table/room QR
        data = request.data
        try:
            items = data.get('items', [])
            table_unique_id = (
                data.get('table_unique_id')
                or request.query_params.get('table_unique_id')
                or request.query_params.get('table')
                or request.headers.get('X-Table-Unique-Id')
            )
            room_unique_id = (
                data.get('room_unique_id')
                or request.query_params.get('room_unique_id')
                or request.query_params.get('room')
                or request.headers.get('X-Room-Unique-Id')
            )
            special_instructions = data.get('special_instructions', '')
            total_amount = data.get('total_amount', 0)

            # Get restaurant from table or room
            restaurant = None
            table_display = ''
            order_type_value = 'table'
            table_number_for_bill = None

            if table_unique_id:
                try:
                    tbl = Table.objects.get(qr_unique_id=table_unique_id)
                    restaurant = tbl.restaurant
                    table_display = tbl.table_number
                    table_number_for_bill = tbl.table_number
                except Table.DoesNotExist:
                    table_display = 'Unknown'
            elif room_unique_id:
                try:
                    rm = Room.objects.get(qr_unique_id=room_unique_id)
                    restaurant = rm.restaurant
                    table_display = f"Room {rm.room_number}"
                    order_type_value = 'room'
                except Room.DoesNotExist:
                    table_display = 'Room'
            
            # Fallback to request restaurant context
            if not restaurant:
                restaurant = getattr(request, 'restaurant', None)
                if not restaurant and request.user.is_authenticated and request.user.restaurant:
                    restaurant = request.user.restaurant
            
            # Final fallback for legacy data where table/room is found but has null restaurant.
            if not restaurant:
                restaurant = Restaurant.objects.filter(is_active=True).order_by('id').first()
            
            if not restaurant:
                return Response({'error': 'Restaurant context is required'}, status=status.HTTP_400_BAD_REQUEST)

            placed_by_val = 'customer'
            placed_by_staff_obj = None
            order_user = None
            if request.user.is_authenticated:
                order_user = request.user
                if request.user.has_perm('cafe.can_place_waiter_order') and hasattr(
                    request.user, 'staff_profile'
                ):
                    raw_pb = (data.get('placed_by') or 'waiter').lower()
                    if raw_pb not in ('customer', 'waiter'):
                        raw_pb = 'waiter'
                    placed_by_val = raw_pb
                    if placed_by_val == 'waiter':
                        placed_by_staff_obj = request.user.staff_profile

            # Build items_json as { item_id: [quantity, name, unit_price] }
            items_map = {}
            order_total = Decimal('0.00')
            for item in items:
                item_id = str(item.get('menu_item'))
                quantity = int(item.get('quantity', 1))
                # Always trust backend menu_item price to avoid mismatches
                try:
                    mi = menu_item.objects.get(id=item_id, restaurant=restaurant)
                    unit_price = mi.price or Decimal('0')
                    name = mi.name
                except menu_item.DoesNotExist:
                    unit_price = Decimal(str(item.get('price', 0) or 0))
                    name = f"Item {item_id}"
                line_total = unit_price * Decimal(quantity)
                order_total += line_total
                # Store numeric price for each item (as float for JSON)
                items_map[item_id] = [quantity, name, float(unit_price)]

            # Create order (unpaid by default)
            new_order = order.objects.create(
                restaurant=restaurant,
                items_json=json.dumps(items_map),
                name=data.get('name', 'Unknown'),
                phone=data.get('phone', '0000000000'),
                table=table_display,
                price=order_total,
                bill_clear=False,
                estimated_time=20,
                special_instructions=special_instructions,
                status='pending',
                payment_status='unpaid',
                payment_method='unknown',
                table_unique_id=table_unique_id,
                room_unique_id=room_unique_id,  # For room orders
                order_type=order_type_value,
                user=order_user,
                placed_by=placed_by_val,
                placed_by_staff=placed_by_staff_obj,
            )

            # Create bill entry
            try:
                from django.utils import timezone
                bill_items = {}
                # For bill, use { item_name: [qty, line_total] } based on backend prices
                for item_id, (qty, name, unit_price) in items_map.items():
                    line_total = Decimal(str(unit_price)) * Decimal(qty)
                    bill_items[name] = [qty, float(line_total)]

                new_bill = bill.objects.create(
                    restaurant=restaurant,
                    order=new_order,
                    order_items=json.dumps(bill_items),
                    name=new_order.name or 'Unknown',
                    bill_total=order_total,
                    currency=new_order.currency,
                    phone=new_order.phone or '0000000000',
                    bill_time=timezone.now(),
                    table_number=table_number_for_bill,
                )
                # Ensure invoice numbers stay aligned (simple strategy: use bill ID)
                invoice_number = f"INV-{new_bill.id}"
                new_bill.invoice_number = invoice_number
                new_bill.save(update_fields=['invoice_number'])
                new_order.invoice_number = invoice_number
                new_order.save(update_fields=['invoice_number'])
            except Exception:
                # Do not fail order creation if bill creation fails
                pass

            serializer = self.get_serializer(new_order)
            headers = self.get_success_headers(serializer.data)
            
            # Emit Socket.IO event for new order via HTTP request
            try:
                requests.post('http://localhost:8001/emit_new_order', 
                            json={'order': serializer.data}, 
                            timeout=1)
                print(f"✅ Socket.IO: New order event emitted for order {serializer.data.get('id')}")
            except Exception as e:
                print(f"❌ Socket.IO emit failed: {e}")
            
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        except Exception as ex:
            import traceback
            error_trace = traceback.format_exc()
            print(f"❌ Order creation error: {str(ex)}")
            print(f"Traceback: {error_trace}")
            return Response({'error': str(ex), 'detail': error_trace}, status=status.HTTP_400_BAD_REQUEST)

    def get_serializer_class(self):
        if self.action == 'create':
            return OrderCreateSerializer
        return OrderSerializer
    
    def get_queryset(self):
        user = self.request.user
        queryset = order.objects.select_related(
            'placed_by_staff', 'assigned_runner', 'restaurant'
        ).all()

        # Filter by restaurant
        restaurant = getattr(self.request, 'restaurant', None)
        if restaurant:
            queryset = queryset.filter(restaurant=restaurant)
        elif user.is_authenticated:
            # Authenticated users: filter by their restaurant or show all if super admin
            if user.is_super_admin or user.is_superuser:
                # Super admin can see all orders
                pass
            elif user.restaurant:
                # Restaurant admin/staff can see their restaurant's orders
                queryset = queryset.filter(restaurant=user.restaurant)
            elif hasattr(user, 'staff_profile') and user.staff_profile.restaurant_id:
                queryset = queryset.filter(restaurant_id=user.staff_profile.restaurant_id)
            else:
                # Regular users can see their own orders
                queryset = queryset.filter(phone=user.phone)
        else:
            # Anonymous QR users: allow access by explicit table/room context.
            table_unique_id = (
                self.request.query_params.get('table_unique_id')
                or self.request.query_params.get('table')
                or self.request.headers.get('X-Table-Unique-Id')
            )
            room_unique_id = (
                self.request.query_params.get('room_unique_id')
                or self.request.query_params.get('room')
                or self.request.headers.get('X-Room-Unique-Id')
            )
            if table_unique_id:
                queryset = queryset.filter(table_unique_id=table_unique_id)
            elif room_unique_id:
                queryset = queryset.filter(room_unique_id=room_unique_id)
            else:
                # Anonymous users without context cannot enumerate orders
                queryset = queryset.none()
        
        return queryset.order_by('-created_at')
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        try:
            order_id = pk or request.data.get('order_id')
            if not order_id:
                return Response({'error': 'Order ID is required'}, status=status.HTTP_400_BAD_REQUEST)

            order_obj = get_order_for_write_request(request, order_id)

            new_status = request.data.get('status')

            valid_statuses = [
                'pending',
                'confirmed',
                'preparing',
                'ready',
                'served',
                'delivered',
                'cancelled',
                'completed',
            ]

            if not new_status:
                return Response({'error': 'Status is required'}, status=status.HTTP_400_BAD_REQUEST)

            if new_status not in valid_statuses:
                valid_str = ', '.join(valid_statuses)
                return Response(
                    {'error': f'Invalid status. Valid statuses are: {valid_str}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            old_status = order_obj.status
            if not order_transition_allowed(request.user, old_status, new_status):
                return Response(
                    {'error': 'You are not allowed to perform this status transition.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if new_status == 'preparing':
                consume_stock_for_order(order_obj, request.user)
            if new_status == 'cancelled':
                reverse_stock_for_order(order_obj, request.user)

            order_obj.status = new_status
            order_obj.save()
            
            print(
                f"✅ Order {order_obj.id} status updated to {new_status} by user {request.user.id if request.user.is_authenticated else 'anonymous'}"
            )
            
            # Emit Socket.IO event for order status update via HTTP request
            try:
                user_type = 'admin' if (request.user.is_authenticated and (request.user.is_superuser or getattr(request.user, 'cafe_manager', False) or request.user.is_restaurant_admin())) else 'staff'
                requests.post('http://localhost:8001/emit_order_update', 
                            json={
                                'order_id': order_obj.id, 
                                'status': new_status, 
                                'user_type': user_type
                            }, 
                            timeout=1)
                print(f"✅ Socket.IO: Order update event emitted for order {order_obj.id}")
            except Exception as e:
                print(f"❌ Socket.IO emit failed: {e}")
            
            serializer = self.get_serializer(order_obj)
            return Response({'success': True, 'status': new_status, 'order': serializer.data}, status=status.HTTP_200_OK)
        except Exception as ex:
            import traceback
            error_trace = traceback.format_exc()
            print(f"❌ Order status update error: {str(ex)}")
            print(f"Traceback: {error_trace}")
            return Response({'error': str(ex), 'detail': error_trace}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def assign_runner(self, request, pk=None):
        """Kitchen assigns a waiter to deliver food for this order."""
        order_obj = get_order_for_write_request(request, pk or request.data.get('order_id'))
        staff_id = request.data.get('staff_id')
        if not staff_id:
            return Response({'error': 'staff_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        runner = get_object_or_404(
            Staff,
            id=int(staff_id),
            restaurant_id=order_obj.restaurant_id,
            employment_status='active',
            is_active=True,
        )
        order_obj.assigned_runner = runner
        order_obj.assigned_at = timezone.now()
        order_obj.save(update_fields=['assigned_runner', 'assigned_at'])
        try:
            requests.post(
                'http://localhost:8001/emit_order_update',
                json={
                    'order_id': order_obj.id,
                    'status': order_obj.status,
                    'user_type': 'staff',
                    'assigned_runner_id': runner.id,
                },
                timeout=1,
            )
        except Exception as e:
            print(f'❌ Socket.IO assign_runner emit failed: {e}')
        serializer = self.get_serializer(order_obj)
        return Response({'success': True, 'order': serializer.data}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """Mark an order as paid (typically cash/UPI at table)."""
        try:
            from django.utils import timezone

            order_id = pk or request.data.get('order_id')
            if not order_id:
                return Response({'error': 'Order ID is required'}, status=status.HTTP_400_BAD_REQUEST)

            order_obj = get_order_for_write_request(request, order_id)

            if order_obj.payment_status == 'paid':
                serializer = self.get_serializer(order_obj)
                return Response({'detail': 'Order is already marked as paid.', 'order': serializer.data}, status=status.HTTP_200_OK)

            payment_method = request.data.get('payment_method', 'cash')
            # Update order payment info
            order_obj.payment_status = 'paid'
            order_obj.payment_method = payment_method
            order_obj.paid_at = timezone.now()
            if order_obj.status in ['pending', 'confirmed', 'preparing', 'ready', 'served', 'delivered']:
                order_obj.status = 'completed'
            order_obj.bill_clear = True
            order_obj.save()

            # Update or create bill
            bill_obj = getattr(order_obj, 'bill', None)
            if bill_obj:
                bill_obj.payment_status = 'paid'
                bill_obj.payment_method = payment_method
                bill_obj.tip_amount = order_obj.tip_amount
                bill_obj.bill_total = order_obj.price
                bill_obj.save()

            # Create Payment audit record
            Payment.objects.create(
                restaurant=order_obj.restaurant,
                order=order_obj,
                bill=bill_obj,
                provider='manual',
                amount=order_obj.price,
                currency=order_obj.currency,
                status='succeeded',
                raw_response={},
            )

            # Notify via Socket.IO that payment completed
            try:
                requests.post(
                    'http://localhost:8001/emit_order_update',
                    json={
                        'order_id': order_obj.id,
                        'status': order_obj.status,
                        'user_type': 'admin',
                        'payment_status': order_obj.payment_status,
                    },
                    timeout=1,
                )
            except Exception as e:
                print(f"❌ Socket.IO payment emit failed: {e}")

            serializer = self.get_serializer(order_obj)
            return Response({'success': True, 'order': serializer.data}, status=status.HTTP_200_OK)
        except Exception as ex:
            import traceback
            error_trace = traceback.format_exc()
            print(f"❌ Order mark_paid error: {str(ex)}")
            print(f"Traceback: {error_trace}")
            return Response({'error': str(ex), 'detail': error_trace}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def by_table(self, request):
        table_number = request.query_params.get('table')
        if table_number:
            orders = order.objects.filter(table=table_number).order_by('-created_at')
            serializer = self.get_serializer(orders, many=True)
            return Response(serializer.data)
        return Response({'error': 'Table parameter required'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def by_table_unique_id(self, request):
        table_unique_id = request.query_params.get('table_unique_id')
        if table_unique_id:
            orders = order.objects.filter(table_unique_id=table_unique_id).order_by('-created_at')
            serializer = self.get_serializer(orders, many=True)
            return Response(serializer.data)
        return Response({'error': 'table_unique_id parameter required'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def by_room_unique_id(self, request):
        room_unique_id = request.query_params.get('room_unique_id')
        if room_unique_id:
            orders = order.objects.filter(room_unique_id=room_unique_id).order_by('-created_at')
            serializer = self.get_serializer(orders, many=True)
            return Response(serializer.data)
        return Response({'error': 'room_unique_id parameter required'}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def my_orders(self, request):
        if not request.user.is_authenticated:
            return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        
        # For regular users, filter by their phone number
        if request.user.is_superuser or request.user.cafe_manager:
            user_orders = order.objects.all().order_by('-created_at')
        else:
            user_orders = order.objects.filter(phone=request.user.phone).order_by('-created_at')
        
        serializer = self.get_serializer(user_orders, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def clear_table(self, request):
        """Clear table by marking all eligible orders as billed.

        Only orders that are already paid/completed can be cleared.
        If there are unpaid/active orders, return an error instead of silently clearing.
        """
        table_unique_id = request.data.get('table_unique_id')
        room_unique_id = request.data.get('room_unique_id')
        
        if not table_unique_id and not room_unique_id:
            return Response({'error': 'table_unique_id or room_unique_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            base_qs = order.objects.all()
            if table_unique_id:
                base_qs = base_qs.filter(table_unique_id=table_unique_id)
            else:
                base_qs = base_qs.filter(room_unique_id=room_unique_id)

            unpaid_orders = base_qs.filter(
                bill_clear=False,
                payment_status__in=['unpaid', 'pending_payment', 'failed', 'refunded'],
            )
            if unpaid_orders.exists():
                ids = list(unpaid_orders.values_list('id', flat=True))
                return Response(
                    {
                        'error': 'Cannot clear table while there are unpaid orders.',
                        'unpaid_order_ids': ids,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Mark all paid/completed orders for this table/room as billed
            if table_unique_id:
                orders_to_clear = base_qs.filter(
                    bill_clear=False,
                    payment_status='paid',
                )
            else:
                orders_to_clear = base_qs.filter(
                    bill_clear=False,
                    payment_status='paid',
                )

            cleared_count = orders_to_clear.count()
            orders_to_clear.update(bill_clear=True)

            return Response(
                {
                    'message': f'Table cleared successfully. {cleared_count} orders marked as billed.',
                    'cleared_orders': cleared_count,
                },
                status=status.HTTP_200_OK,
            )
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RatingViewSet(viewsets.ModelViewSet):
    queryset = rating.objects.all().order_by('-r_date')
    serializer_class = RatingSerializer
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        return [permissions.AllowAny()]  # Allow anonymous reviews
    
    def perform_create(self, serializer):
        user = self.request.user
        if user.is_authenticated:
            # Set the name to user's full name or phone if no name
            user_name = f"{user.first_name} {user.last_name}".strip()
            if not user_name:
                user_name = user.phone
        else:
            # For anonymous users, use a default name
            user_name = "Anonymous Customer"
        serializer.save(name=user_name)


class BillViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = bill.objects.all().order_by('-bill_time')
    serializer_class = BillSerializer
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]  # Allow anonymous access to view bills
        return [permissions.IsAuthenticated()]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by restaurant, but allow unauthenticated requests with context headers
        restaurant = getattr(self.request, 'restaurant', None)
        if restaurant:
            queryset = queryset.filter(restaurant=restaurant)
        elif self.request.user.is_authenticated:
            if self.request.user.is_super_admin or self.request.user.is_superuser:
                pass  # Super admin can see all
            elif self.request.user.restaurant:
                queryset = queryset.filter(restaurant=self.request.user.restaurant)
            else:
                queryset = queryset.none()
        else:
            # For anonymous users with no context, allow using headers/query params
            if 'HTTP_X_RESTAURANT_ID' in self.request.META:
                try:
                    restaurant_id = int(self.request.META['HTTP_X_RESTAURANT_ID'])
                    queryset = queryset.filter(restaurant_id=restaurant_id)
                except (ValueError, TypeError):
                    queryset = queryset.none()
            elif 'HTTP_X_RESTAURANT_SLUG' in self.request.META:
                slug = self.request.META['HTTP_X_RESTAURANT_SLUG']
                queryset = queryset.filter(restaurant__slug=slug)
            else:
                queryset = queryset.none()
        
        # Filter by table_unique_id if provided
        table_unique_id = self.request.query_params.get('table_unique_id')
        if table_unique_id:
            # Get the table number for this unique ID
            try:
                table = Table.objects.get(qr_unique_id=table_unique_id)
                # Filter bills by table number and restaurant
                queryset = queryset.filter(table_number=table.table_number, restaurant=table.restaurant)
            except Table.DoesNotExist:
                # Fallback to phone number filtering
                table_orders = order.objects.filter(table_unique_id=table_unique_id)
                phone_numbers = table_orders.values_list('phone', flat=True).distinct()
                queryset = queryset.filter(phone__in=phone_numbers)
        
        # Filter by room_unique_id if provided
        room_unique_id = self.request.query_params.get('room_unique_id')
        if room_unique_id:
            # Get the room number for this unique ID
            try:
                room = Room.objects.get(qr_unique_id=room_unique_id)
                # For rooms, we'll filter by phone numbers since bills don't have room numbers
                room_orders = order.objects.filter(room_unique_id=room_unique_id, restaurant=room.restaurant)
                phone_numbers = room_orders.values_list('phone', flat=True).distinct()
                queryset = queryset.filter(phone__in=phone_numbers, restaurant=room.restaurant)
            except Room.DoesNotExist:
                # Fallback to phone number filtering
                room_orders = order.objects.filter(room_unique_id=room_unique_id)
                phone_numbers = room_orders.values_list('phone', flat=True).distinct()
                queryset = queryset.filter(phone__in=phone_numbers)
        
        # Also support direct table_number filtering
        table_number = self.request.query_params.get('table_number')
        if table_number:
            queryset = queryset.filter(table_number=table_number)
        
        return queryset


class AuthViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]

    def _serialize_auth_user(self, user, restaurant_slug=None):
        serializer = UserSerializer(user)
        data = serializer.data
        data['role'] = user.role
        role_permissions = RolePermission.objects.filter(role=user.role).select_related('permission')
        data['permissions'] = [rp.permission.codename for rp in role_permissions]

        if user.restaurant:
            data['restaurant'] = RestaurantSerializer(user.restaurant).data
        elif user.is_super_admin or user.is_superuser:
            restaurants = Restaurant.objects.filter(is_active=True).order_by('name')
            data['available_restaurants'] = RestaurantSerializer(restaurants, many=True).data
            if restaurant_slug:
                try:
                    selected_restaurant = Restaurant.objects.get(slug=restaurant_slug, is_active=True)
                    data['selected_restaurant'] = RestaurantSerializer(selected_restaurant).data
                except Restaurant.DoesNotExist:
                    pass
        return data

    def _verify_google_id_token(self, id_token):
        response = requests.get(
            'https://oauth2.googleapis.com/tokeninfo',
            params={'id_token': id_token},
            timeout=10,
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        if payload.get('email_verified') not in ('true', True):
            return None
        return payload

    def _generate_phone_from_sub(self, google_sub):
        digits = ''.join(ch for ch in str(google_sub) if ch.isdigit()) or '0'
        base = ('9' + digits[-9:].rjust(9, '0'))[:10]
        if not User.objects.filter(phone=base).exists():
            return base
        try_num = int(base)
        for _ in range(1000):
            try_num = 9000000000 + ((try_num + 1) % 1000000000)
            candidate = str(try_num)
            if not User.objects.filter(phone=candidate).exists():
                return candidate
        raise ValueError('Unable to allocate phone number for Google signup')
    
    @action(detail=False, methods=['post'])
    def login(self, request):
        phone = request.data.get('phone')
        password = request.data.get('password')
        restaurant_slug = request.data.get('restaurant_slug')  # Optional restaurant selection
        
        user = authenticate(phone=phone, password=password)
        if user:
            login(request, user)
            data = self._serialize_auth_user(user, restaurant_slug=restaurant_slug)
            return Response(data)
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
    
    @action(detail=False, methods=['post'])
    def logout(self, request):
        logout(request)
        return Response({'message': 'Logged out successfully'})
    
    @action(detail=False, methods=['post'])
    def signup(self, request):
        phone = request.data.get('phone')
        password = request.data.get('password')
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')
        
        if User.objects.filter(phone=phone).exists():
            return Response({'error': 'Phone number already registered'}, status=status.HTTP_400_BAD_REQUEST)
        
        user = User.objects.create_user(phone=phone, password=password)
        user.first_name = first_name
        user.last_name = last_name
        user.save()
        
        login(request, user)
        serializer = UserSerializer(user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def google_auth(self, request):
        id_token = request.data.get('id_token')
        mode = str(request.data.get('mode', 'login')).lower()
        if not id_token:
            return Response({'error': 'id_token is required'}, status=status.HTTP_400_BAD_REQUEST)
        if mode not in ('login', 'signup'):
            return Response({'error': 'mode must be login or signup'}, status=status.HTTP_400_BAD_REQUEST)

        google_payload = self._verify_google_id_token(id_token)
        if not google_payload:
            return Response({'error': 'Invalid Google token'}, status=status.HTTP_401_UNAUTHORIZED)

        google_sub = str(google_payload.get('sub', '')).strip()
        google_email = str(google_payload.get('email', '')).strip().lower()
        first_name = google_payload.get('given_name') or ''
        last_name = google_payload.get('family_name') or ''
        if not google_sub:
            return Response({'error': 'Google token missing subject'}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(Q(google_sub=google_sub) | Q(google_email=google_email)).first()

        if mode == 'login' and not user:
            return Response({'error': 'Google account not registered. Please sign up first.'}, status=status.HTTP_404_NOT_FOUND)

        if mode == 'signup' and not user:
            phone = self._generate_phone_from_sub(google_sub)
            user = User.objects.create_user(
                phone=phone,
                password=None,
                first_name=first_name,
                last_name=last_name,
            )
            user.set_unusable_password()
            user.role = 'restaurant_admin'
            user.cafe_manager = True
            user.is_staff = True
            user.google_sub = google_sub
            user.google_email = google_email
            user.save()
        elif user:
            changed = False
            if not user.google_sub:
                user.google_sub = google_sub
                changed = True
            if google_email and user.google_email != google_email:
                user.google_email = google_email
                changed = True
            if first_name and not user.first_name:
                user.first_name = first_name
                changed = True
            if last_name and not user.last_name:
                user.last_name = last_name
                changed = True
            if changed:
                user.save()

        login(request, user)
        data = self._serialize_auth_user(user)
        return Response(data, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['post'])
    def create_hr_manager(self, request):
        """Create an HR Manager account for a restaurant"""
        if not request.user.is_authenticated:
            return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        
        # Only restaurant admins and super admins can create HR managers
        if not (request.user.is_restaurant_admin() or request.user.is_super_admin):
            return Response({'error': 'Only restaurant administrators can create HR managers'}, status=status.HTTP_403_FORBIDDEN)
        
        phone = request.data.get('phone')
        password = request.data.get('password')
        first_name = request.data.get('first_name', '')
        last_name = request.data.get('last_name', '')
        email = request.data.get('email', '')
        restaurant_id = request.data.get('restaurant_id')
        
        if not phone or not password:
            return Response({'error': 'Phone and password are required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get restaurant - use user's restaurant or provided restaurant_id
        restaurant = request.user.restaurant
        if restaurant_id and request.user.is_super_admin:
            try:
                restaurant = Restaurant.objects.get(id=restaurant_id)
            except Restaurant.DoesNotExist:
                return Response({'error': 'Restaurant not found'}, status=status.HTTP_404_NOT_FOUND)
        
        if not restaurant:
            return Response({'error': 'Restaurant context is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user already exists
        if User.objects.filter(phone=phone).exists():
            existing_user = User.objects.get(phone=phone)
            # If user exists but is not HR manager, update them
            if existing_user.role != 'hr_manager':
                existing_user.role = 'hr_manager'
                existing_user.restaurant = restaurant
                existing_user.set_password(password)
                existing_user.first_name = first_name
                existing_user.last_name = last_name
                existing_user.save()
            else:
                return Response({'error': 'HR Manager with this phone number already exists'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            # Create new HR manager user
            hr_manager = User.objects.create_user(
                phone=phone,
                password=password,
                role='hr_manager',
                restaurant=restaurant,
                first_name=first_name,
                last_name=last_name,
                is_staff=True,
            )
        
        return Response({
            'message': 'HR Manager account created successfully',
            'phone': phone,
            'restaurant': RestaurantSerializer(restaurant).data
        }, status=status.HTTP_201_CREATED)
    
    @action(detail=False, methods=['get'])
    def current_user(self, request):
        if request.user.is_authenticated:
            serializer = UserSerializer(request.user)
            data = serializer.data
            
            # Add role and permissions
            data['role'] = request.user.role
            # Get permissions for the user's role
            role_permissions = RolePermission.objects.filter(role=request.user.role).select_related('permission')
            data['permissions'] = [rp.permission.codename for rp in role_permissions]
            
            # Add restaurant context
            restaurant = getattr(request, 'restaurant', None)
            if not restaurant and request.user.restaurant:
                restaurant = request.user.restaurant
            
            if restaurant:
                data['restaurant'] = RestaurantSerializer(restaurant).data
            elif request.user.is_super_admin or request.user.is_superuser:
                # Super admin can see all restaurants
                data['available_restaurants'] = RestaurantSerializer(
                    Restaurant.objects.filter(is_active=True), many=True
                ).data
            
            return Response(data)
        # Return null instead of error for unauthenticated users
        return Response({'user': None}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def staff_login(self, request):
        phone = request.data.get('phone')
        password = request.data.get('password')
        
        if not phone or not password:
            return Response({'success': False, 'message': 'Phone and password are required'}, status=400)
        
        try:
            # Find staff by phone number
            staff = Staff.objects.get(phone=phone)
            
            # Check if the user exists and password is correct
            user = authenticate(request, phone=phone, password=password)
            
            if user is not None and user.id == staff.user.id:
                # Check if staff is active
                if staff.is_active:
                    login(request, user)
                    serializer = StaffSerializer(staff)
                    return Response({
                        'success': True,
                        'staff': serializer.data,
                        'message': 'Login successful'
                    })
                else:
                    return Response({
                        'success': False,
                        'message': 'Your account is inactive. Please contact administrator.'
                    }, status=401)
            else:
                return Response({
                    'success': False,
                    'message': 'Invalid phone number or password'
                }, status=401)
                
        except Staff.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Staff not found with this phone number'
            }, status=404)
        except Exception as e:
            return Response({
                'success': False,
                'message': 'Login failed. Please try again.'
            }, status=500)


class DashboardViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def _resolve_restaurant(self, request):
        return resolve_request_restaurant(request)

    def _require_admin(self, request):
        return request.user.is_superuser or request.user.cafe_manager or request.user.is_super_admin

    @action(detail=False, methods=['get'])
    def stats(self, request):
        if not self._require_admin(request):
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)

        restaurant = self._resolve_restaurant(request)

        if restaurant:
            orders_qs = order.objects.filter(restaurant=restaurant)
            bills_qs = bill.objects.filter(restaurant=restaurant)
            total_menu_items = menu_item.objects.filter(restaurant=restaurant, is_available=True).count()
            total_tables = Table.objects.filter(restaurant=restaurant, is_active=True).count()
            total_rooms = Room.objects.filter(restaurant=restaurant, is_active=True).count()
        else:
            orders_qs = order.objects.all()
            bills_qs = bill.objects.all()
            total_menu_items = menu_item.objects.filter(is_available=True).count()
            total_tables = Table.objects.filter(is_active=True).count()
            total_rooms = Room.objects.filter(is_active=True).count()

        total_orders = orders_qs.count()
        total_revenue = float(sum((b.bill_total or Decimal('0')) for b in bills_qs))
        paid_orders = orders_qs.filter(payment_status='paid').count()
        pending_orders = orders_qs.filter(status__in=['pending', 'confirmed', 'preparing', 'ready', 'served']).count()

        recent_orders_data = [
            {
                'id': o.id,
                'total_amount': float(o.price or 0),
                'price': float(o.price or 0),
                'status': o.status,
                'table_unique_id': o.table_unique_id,
                'created_at': o.created_at,
                'payment_status': o.payment_status,
            }
            for o in orders_qs.order_by('-created_at')[:8]
        ]

        return Response({
            'total_orders': total_orders,
            'total_menu_items': total_menu_items,
            'total_tables': total_tables,
            'total_rooms': total_rooms,
            'total_revenue': total_revenue,
            'paid_orders': paid_orders,
            'pending_orders': pending_orders,
            'recent_orders': recent_orders_data,
        })

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        if not self._require_admin(request):
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)

        restaurant = self._resolve_restaurant(request)
        days = max(7, min(int(request.query_params.get('days', 14)), 90))
        start_dt = timezone.now() - timedelta(days=days - 1)

        if restaurant:
            orders_qs = order.objects.filter(restaurant=restaurant, created_at__gte=start_dt).order_by('created_at')
            bills_qs = bill.objects.filter(restaurant=restaurant, bill_time__gte=start_dt).order_by('bill_time')
        else:
            orders_qs = order.objects.filter(created_at__gte=start_dt).order_by('created_at')
            bills_qs = bill.objects.filter(bill_time__gte=start_dt).order_by('bill_time')

        day_keys = [(timezone.now() - timedelta(days=i)).date() for i in range(days - 1, -1, -1)]
        labels = [d.strftime('%d %b') for d in day_keys]
        orders_by_day = {d: 0 for d in day_keys}
        revenue_by_day = {d: 0.0 for d in day_keys}

        for o in orders_qs:
            key = o.created_at.date()
            if key in orders_by_day:
                orders_by_day[key] += 1

        for b_obj in bills_qs:
            key = b_obj.bill_time.date()
            if key in revenue_by_day:
                revenue_by_day[key] += float(b_obj.bill_total or 0)

        status_rows = orders_qs.values('status').annotate(count=Count('id'))
        status_counts = {row['status']: row['count'] for row in status_rows}

        item_stats = {}
        for o in orders_qs:
            try:
                items = json.loads(o.items_json or '{}')
            except (TypeError, ValueError):
                items = {}
            for _, payload in items.items():
                qty = int(payload[0]) if len(payload) > 0 else 0
                name = str(payload[1]) if len(payload) > 1 else 'Unknown'
                unit_price = Decimal(str(payload[2])) if len(payload) > 2 else Decimal('0')
                if name not in item_stats:
                    item_stats[name] = {'quantity': 0, 'revenue': Decimal('0')}
                item_stats[name]['quantity'] += qty
                item_stats[name]['revenue'] += unit_price * qty

        top_items = sorted(
            [
                {'name': k, 'quantity': v['quantity'], 'revenue': float(v['revenue'])}
                for k, v in item_stats.items()
            ],
            key=lambda x: x['revenue'],
            reverse=True
        )[:8]

        return Response({
            'days': days,
            'labels': labels,
            'orders_series': [orders_by_day[d] for d in day_keys],
            'revenue_series': [round(revenue_by_day[d], 2) for d in day_keys],
            'status_counts': status_counts,
            'top_items': top_items,
        })

    @action(detail=False, methods=['get', 'patch'])
    def billing_config(self, request):
        if not self._require_admin(request):
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)

        restaurant = self._resolve_restaurant(request)
        if not restaurant:
            return Response({'error': 'Restaurant context is required'}, status=status.HTTP_400_BAD_REQUEST)

        settings_dict = restaurant.settings or {}
        existing = settings_dict.get('billing', {})
        default_cfg = {
            'currency': existing.get('currency', 'INR'),
            'vat_enabled': existing.get('vat_enabled', True),
            'vat_percent': float(existing.get('vat_percent', 5.0)),
            'service_charge_enabled': existing.get('service_charge_enabled', False),
            'service_charge_percent': float(existing.get('service_charge_percent', 0.0)),
            'display_tax_breakdown': existing.get('display_tax_breakdown', True),
        }

        if request.method.lower() == 'get':
            return Response(default_cfg)

        payload = request.data or {}
        updated = {
            'currency': str(payload.get('currency', default_cfg['currency'])).upper(),
            'vat_enabled': bool(payload.get('vat_enabled', default_cfg['vat_enabled'])),
            'vat_percent': max(0.0, min(float(payload.get('vat_percent', default_cfg['vat_percent'])), 50.0)),
            'service_charge_enabled': bool(payload.get('service_charge_enabled', default_cfg['service_charge_enabled'])),
            'service_charge_percent': max(
                0.0, min(float(payload.get('service_charge_percent', default_cfg['service_charge_percent'])), 30.0)
            ),
            'display_tax_breakdown': bool(
                payload.get('display_tax_breakdown', default_cfg['display_tax_breakdown'])
            ),
        }
        settings_dict['billing'] = updated
        restaurant.settings = settings_dict
        restaurant.save(update_fields=['settings', 'updated_at'])
        return Response(updated)


class SuperAdminDashboardViewSet(viewsets.ViewSet):
    """Super Admin Dashboard with cross-restaurant analytics"""
    permission_classes = [IsSuperAdmin]
    
    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """Get aggregated stats across all restaurants"""
        restaurants = Restaurant.objects.filter(is_active=True)
        
        total_restaurants = restaurants.count()
        total_orders = order.objects.count()
        total_revenue = sum(bill.bill_total for bill in bill.objects.all())
        
        restaurant_stats = []
        for restaurant in restaurants:
            restaurant_stats.append({
                'id': restaurant.id,
                'name': restaurant.name,
                'slug': restaurant.slug,
                'orders_count': order.objects.filter(restaurant=restaurant).count(),
                'revenue': sum(bill.bill_total for bill in bill.objects.filter(restaurant=restaurant)),
                'tables_count': Table.objects.filter(restaurant=restaurant, is_active=True).count(),
                'menu_items_count': menu_item.objects.filter(restaurant=restaurant, is_available=True).count(),
            })
        
        risk_tenants = Restaurant.objects.filter(
            Q(subscription_status__in=['suspended', 'cancelled']) | Q(lifecycle_status__in=['archived', 'terminated'])
        ).count()
        failed_payments = BillingInvoice.objects.filter(status='failed').count()
        module_blocks = PlatformAuditLog.objects.filter(action='module_blocked').count()

        return Response({
            'total_restaurants': total_restaurants,
            'total_orders': total_orders,
            'total_revenue': total_revenue,
            'restaurants': restaurant_stats,
            'risk_tenants': risk_tenants,
            'failed_payments': failed_payments,
            'module_blocked_attempts': module_blocks,
        })
    
    @action(detail=False, methods=['get'])
    def analytics(self, request):
        """Get cross-restaurant analytics"""
        restaurants = Restaurant.objects.filter(is_active=True)
        
        analytics_data = {
            'restaurants': [],
            'total_revenue_by_month': {},
            'top_restaurants': []
        }
        
        for restaurant in restaurants:
            restaurant_revenue = sum(bill.bill_total for bill in bill.objects.filter(restaurant=restaurant))
            restaurant_orders = order.objects.filter(restaurant=restaurant).count()
            
            analytics_data['restaurants'].append({
                'id': restaurant.id,
                'name': restaurant.name,
                'revenue': restaurant_revenue,
                'orders': restaurant_orders,
            })
        
        # Sort by revenue
        analytics_data['top_restaurants'] = sorted(
            analytics_data['restaurants'],
            key=lambda x: x['revenue'],
            reverse=True
        )[:10]
        
        return Response(analytics_data)

    @action(detail=False, methods=['get'])
    def tenants(self, request):
        restaurants = Restaurant.objects.all().order_by('-created_at')
        payload = []
        for restaurant in restaurants:
            active_sub = (
                RestaurantSubscription.objects.filter(restaurant=restaurant, is_active=True)
                .select_related('plan')
                .order_by('-created_at')
                .first()
            )
            payload.append(
                {
                    'id': restaurant.id,
                    'name': restaurant.name,
                    'slug': restaurant.slug,
                    'is_active': restaurant.is_active,
                    'subscription_status': restaurant.subscription_status,
                    'lifecycle_status': restaurant.lifecycle_status,
                    'archived_at': restaurant.archived_at,
                    'terminated_at': restaurant.terminated_at,
                    'plan': (
                        {
                            'id': active_sub.plan.id,
                            'code': active_sub.plan.code,
                            'name': active_sub.plan.name,
                            'max_monthly_orders': active_sub.plan.max_monthly_orders,
                            'max_staff': active_sub.plan.max_staff,
                            'max_tables': getattr(active_sub.plan, 'max_tables', 50),
                        }
                        if active_sub
                        else None
                    ),
                    'orders_count': order.objects.filter(restaurant=restaurant).count(),
                    'staff_count': Staff.objects.filter(restaurant=restaurant, is_active=True).count(),
                    'tables_count': Table.objects.filter(restaurant=restaurant, is_active=True).count(),
                }
            )
        return Response(payload)

    @action(detail=True, methods=['post'])
    def assign_plan(self, request, pk=None):
        restaurant = get_object_or_404(Restaurant, id=pk)
        plan_id = request.data.get('plan_id')
        status_value = request.data.get('status', 'active')
        plan = get_object_or_404(SubscriptionPlan, id=plan_id, is_active=True)
        before_state = {
            'active_subscription': (
                RestaurantSubscription.objects.filter(restaurant=restaurant, is_active=True)
                .values('id', 'plan_id', 'status')
                .first()
            ),
            'subscription_status': restaurant.subscription_status,
        }

        with transaction.atomic():
            RestaurantSubscription.objects.filter(
                restaurant=restaurant,
                is_active=True,
            ).update(is_active=False, status='cancelled')

            new_sub = RestaurantSubscription.objects.create(
                restaurant=restaurant,
                plan=plan,
                status=status_value,
                is_active=True,
                current_period_start=timezone.now(),
                current_period_end=timezone.now() + timedelta(days=30),
                metadata={'assigned_by': request.user.phone},
            )

            restaurant.subscription_status = 'active' if status_value in ('active', 'trialing') else status_value
            if status_value == 'suspended':
                restaurant.is_active = False
                restaurant.lifecycle_status = 'suspended'
            elif status_value in ('active', 'trialing'):
                restaurant.is_active = True
                restaurant.lifecycle_status = 'active'
            restaurant.save(update_fields=['subscription_status', 'is_active', 'lifecycle_status', 'updated_at'])

            BillingInvoice.objects.create(
                restaurant=restaurant,
                subscription=new_sub,
                plan=plan,
                invoice_number=f"INV-{restaurant.id}-{int(timezone.now().timestamp())}",
                amount=plan.price,
                currency=plan.currency,
                due_date=timezone.now() + timedelta(days=7),
                status='pending_payment' if status_value in ('active', 'trialing') else 'void',
                metadata={'source': 'super_admin_assign_plan'},
            )

        log_platform_action(
            actor=request.user,
            action='plan_assign',
            restaurant=restaurant,
            target_type='subscription',
            target_id=new_sub.id,
            before_state=before_state,
            after_state={'subscription_id': new_sub.id, 'plan_id': plan.id, 'status': new_sub.status},
        )

        return Response(RestaurantSubscriptionSerializer(new_sub).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def suspend_tenant(self, request, pk=None):
        restaurant = get_object_or_404(Restaurant, id=pk)
        before_state = {
            'is_active': restaurant.is_active,
            'subscription_status': restaurant.subscription_status,
            'lifecycle_status': restaurant.lifecycle_status,
        }
        restaurant.is_active = False
        restaurant.subscription_status = 'suspended'
        restaurant.lifecycle_status = 'suspended'
        restaurant.save(update_fields=['is_active', 'subscription_status', 'lifecycle_status', 'updated_at'])
        RestaurantSubscription.objects.filter(restaurant=restaurant, is_active=True).update(
            status='suspended',
        )
        log_platform_action(
            actor=request.user,
            action='tenant_suspend',
            restaurant=restaurant,
            target_type='restaurant',
            target_id=restaurant.id,
            before_state=before_state,
            after_state={
                'is_active': restaurant.is_active,
                'subscription_status': restaurant.subscription_status,
                'lifecycle_status': restaurant.lifecycle_status,
            },
        )
        return Response({'id': restaurant.id, 'status': 'suspended'})

    @action(detail=True, methods=['post'])
    def reactivate_tenant(self, request, pk=None):
        restaurant = get_object_or_404(Restaurant, id=pk)
        before_state = {
            'is_active': restaurant.is_active,
            'subscription_status': restaurant.subscription_status,
            'lifecycle_status': restaurant.lifecycle_status,
        }
        restaurant.is_active = True
        restaurant.subscription_status = 'active'
        restaurant.lifecycle_status = 'active'
        restaurant.archived_at = None
        restaurant.save(update_fields=['is_active', 'subscription_status', 'lifecycle_status', 'archived_at', 'updated_at'])
        RestaurantSubscription.objects.filter(restaurant=restaurant, is_active=True).update(
            status='active',
        )
        log_platform_action(
            actor=request.user,
            action='tenant_reactivate',
            restaurant=restaurant,
            target_type='restaurant',
            target_id=restaurant.id,
            before_state=before_state,
            after_state={
                'is_active': restaurant.is_active,
                'subscription_status': restaurant.subscription_status,
                'lifecycle_status': restaurant.lifecycle_status,
            },
        )
        return Response({'id': restaurant.id, 'status': 'active'})

    @action(detail=True, methods=['post'])
    def archive_tenant(self, request, pk=None):
        restaurant = get_object_or_404(Restaurant, id=pk)
        before_state = {
            'is_active': restaurant.is_active,
            'subscription_status': restaurant.subscription_status,
            'lifecycle_status': restaurant.lifecycle_status,
            'archived_at': restaurant.archived_at,
        }
        restaurant.is_active = False
        restaurant.subscription_status = 'suspended'
        restaurant.lifecycle_status = 'archived'
        restaurant.archived_at = timezone.now()
        restaurant.save(update_fields=['is_active', 'subscription_status', 'lifecycle_status', 'archived_at', 'updated_at'])
        RestaurantSubscription.objects.filter(restaurant=restaurant, is_active=True).update(status='suspended')
        log_platform_action(
            actor=request.user,
            action='tenant_archive',
            restaurant=restaurant,
            target_type='restaurant',
            target_id=restaurant.id,
            before_state=before_state,
            after_state={
                'is_active': restaurant.is_active,
                'subscription_status': restaurant.subscription_status,
                'lifecycle_status': restaurant.lifecycle_status,
                'archived_at': restaurant.archived_at.isoformat() if restaurant.archived_at else None,
            },
        )
        return Response({'id': restaurant.id, 'status': 'archived'})

    @action(detail=True, methods=['post'])
    def restore_tenant(self, request, pk=None):
        restaurant = get_object_or_404(Restaurant, id=pk)
        before_state = {
            'is_active': restaurant.is_active,
            'subscription_status': restaurant.subscription_status,
            'lifecycle_status': restaurant.lifecycle_status,
            'archived_at': restaurant.archived_at,
        }
        restaurant.is_active = True
        restaurant.subscription_status = 'active'
        restaurant.lifecycle_status = 'active'
        restaurant.archived_at = None
        restaurant.save(update_fields=['is_active', 'subscription_status', 'lifecycle_status', 'archived_at', 'updated_at'])
        RestaurantSubscription.objects.filter(restaurant=restaurant, is_active=True).update(status='active')
        log_platform_action(
            actor=request.user,
            action='tenant_restore',
            restaurant=restaurant,
            target_type='restaurant',
            target_id=restaurant.id,
            before_state=before_state,
            after_state={
                'is_active': restaurant.is_active,
                'subscription_status': restaurant.subscription_status,
                'lifecycle_status': restaurant.lifecycle_status,
                'archived_at': restaurant.archived_at,
            },
        )
        return Response({'id': restaurant.id, 'status': 'active'})

    @action(detail=True, methods=['post'])
    def terminate_tenant(self, request, pk=None):
        restaurant = get_object_or_404(Restaurant, id=pk)
        before_state = {
            'is_active': restaurant.is_active,
            'subscription_status': restaurant.subscription_status,
            'lifecycle_status': restaurant.lifecycle_status,
            'terminated_at': restaurant.terminated_at,
        }
        restaurant.is_active = False
        restaurant.subscription_status = 'cancelled'
        restaurant.lifecycle_status = 'terminated'
        restaurant.terminated_at = timezone.now()
        restaurant.save(update_fields=['is_active', 'subscription_status', 'lifecycle_status', 'terminated_at', 'updated_at'])
        RestaurantSubscription.objects.filter(restaurant=restaurant, is_active=True).update(status='cancelled', is_active=False)
        log_platform_action(
            actor=request.user,
            action='tenant_terminate',
            restaurant=restaurant,
            target_type='restaurant',
            target_id=restaurant.id,
            before_state=before_state,
            after_state={
                'is_active': restaurant.is_active,
                'subscription_status': restaurant.subscription_status,
                'lifecycle_status': restaurant.lifecycle_status,
                'terminated_at': restaurant.terminated_at.isoformat() if restaurant.terminated_at else None,
            },
        )
        return Response({'id': restaurant.id, 'status': 'terminated'})

    @action(detail=False, methods=['get'])
    def users(self, request):
        users = User.objects.select_related('restaurant').order_by('-id')[:500]
        payload = []
        for user in users:
            payload.append(
                {
                    'id': user.id,
                    'phone': user.phone,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'role': user.role,
                    'is_super_admin': user.is_super_admin,
                    'is_superuser': user.is_superuser,
                    'cafe_manager': user.cafe_manager,
                    'restaurant': (
                        {
                            'id': user.restaurant.id,
                            'name': user.restaurant.name,
                            'slug': user.restaurant.slug,
                        }
                        if user.restaurant
                        else None
                    ),
                }
            )
        return Response(payload)

    @action(detail=False, methods=['get'])
    def logs(self, request):
        logs = PlatformAuditLog.objects.select_related('actor', 'restaurant').order_by('-created_at')[:200]
        payload = [
            {
                'id': item.id,
                'timestamp': item.created_at,
                'user': item.actor.phone if item.actor else 'system',
                'action_flag': 1,
                'object_repr': f"{item.action}::{item.target_type}:{item.target_id}",
                'change_message': json.dumps(item.metadata or {}),
            }
            for item in logs
        ]
        return Response(payload)

    @action(detail=False, methods=['post'])
    def force_logout_user(self, request):
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        target_user = get_object_or_404(User, id=user_id)
        removed = 0
        for session in Session.objects.all():
            data = session.get_decoded()
            if str(data.get('_auth_user_id')) == str(target_user.id):
                session.delete()
                removed += 1
        log_platform_action(
            actor=request.user,
            action='force_logout_user',
            restaurant=target_user.restaurant,
            target_type='user',
            target_id=target_user.id,
            after_state={'removed_sessions': removed},
        )
        return Response({'user_id': target_user.id, 'removed_sessions': removed})

    @action(detail=False, methods=['get', 'post'])
    def notifications(self, request):
        if request.method.lower() == 'get':
            rows = []
            for restaurant in Restaurant.objects.all().order_by('name'):
                settings_dict = restaurant.settings or {}
                notices = settings_dict.get('super_admin_notifications', [])
                for notice in notices[-5:]:
                    rows.append(
                        {
                            'restaurant_id': restaurant.id,
                            'restaurant_name': restaurant.name,
                            'title': notice.get('title', ''),
                            'message': notice.get('message', ''),
                            'created_at': notice.get('created_at'),
                        }
                    )
            rows.sort(key=lambda n: n.get('created_at') or '', reverse=True)
            return Response(rows[:200])

        title = str(request.data.get('title', '')).strip()
        message = str(request.data.get('message', '')).strip()
        if not title or not message:
            return Response({'error': 'title and message are required'}, status=status.HTTP_400_BAD_REQUEST)
        target_restaurant_id = request.data.get('restaurant_id')
        now_iso = timezone.now().isoformat()
        target_qs = Restaurant.objects.all()
        if target_restaurant_id:
            target_qs = target_qs.filter(id=target_restaurant_id)
        updated = 0
        for restaurant in target_qs:
            settings_dict = restaurant.settings or {}
            notices = settings_dict.get('super_admin_notifications', [])
            notices.append({'title': title, 'message': message, 'created_at': now_iso, 'created_by': request.user.phone})
            settings_dict['super_admin_notifications'] = notices[-50:]
            restaurant.settings = settings_dict
            restaurant.save(update_fields=['settings', 'updated_at'])
            updated += 1
        return Response({'updated_restaurants': updated})

    @action(detail=False, methods=['get'])
    def support(self, request):
        rows = []
        for restaurant in Restaurant.objects.all().order_by('name'):
            active_sub = (
                RestaurantSubscription.objects.filter(restaurant=restaurant, is_active=True)
                .select_related('plan')
                .order_by('-created_at')
                .first()
            )
            rows.append(
                {
                    'restaurant_id': restaurant.id,
                    'name': restaurant.name,
                    'slug': restaurant.slug,
                    'is_active': restaurant.is_active,
                    'subscription_status': restaurant.subscription_status,
                    'contact_phone': restaurant.phone,
                    'contact_email': restaurant.email,
                    'plan_name': active_sub.plan.name if active_sub else None,
                    'open_invoices': BillingInvoice.objects.filter(
                        restaurant=restaurant,
                        status__in=['pending_payment', 'failed'],
                    ).count(),
                    'last_audit_at': (
                        PlatformAuditLog.objects.filter(restaurant=restaurant)
                        .order_by('-created_at')
                        .values_list('created_at', flat=True)
                        .first()
                    ),
                    'needs_attention': (not restaurant.is_active) or (restaurant.subscription_status in ['suspended', 'cancelled']),
                }
            )
        rows.sort(key=lambda r: (not r['needs_attention'], r['name']))
        return Response(rows)


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.all().order_by('name')
    serializer_class = DepartmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated and (user.is_superuser or user.cafe_manager):
            return tenant_scoped_queryset(Department.objects.all(), self.request).order_by('name')
        return tenant_scoped_queryset(Department.objects.filter(is_active=True), self.request).order_by('name')

    def perform_create(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can create departments")
        serializer.save(restaurant=resolve_request_restaurant(self.request))

    def perform_update(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can update departments")
        serializer.save()

    def perform_destroy(self, instance):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can delete departments")
        instance.delete()

class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all().order_by('department', 'name')
    serializer_class = RoleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated and (user.is_superuser or user.cafe_manager):
            return tenant_scoped_queryset(Role.objects.all(), self.request).order_by('department', 'name')
        return tenant_scoped_queryset(Role.objects.filter(is_active=True), self.request).order_by('department', 'name')

    def perform_create(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can create roles")
        serializer.save(restaurant=resolve_request_restaurant(self.request))

    def perform_update(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can update roles")
        serializer.save()

    def perform_destroy(self, instance):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can delete roles")
        instance.delete()

    @action(detail=False, methods=['get'])
    def by_department(self, request):
        department_id = request.query_params.get('department')
        if department_id:
            roles = tenant_scoped_queryset(Role.objects.filter(department_id=department_id), request).order_by('name')
            serializer = self.get_serializer(roles, many=True)
            return Response(serializer.data)
        return Response({'error': 'Department parameter required'}, status=status.HTTP_400_BAD_REQUEST)

class StaffViewSet(viewsets.ModelViewSet):
    queryset = Staff.objects.all().order_by('employee_id')
    serializer_class = StaffSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return StaffCreateSerializer
        return StaffSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated and (user.is_superuser or user.cafe_manager):
            return tenant_scoped_queryset(Staff.objects.all(), self.request).order_by('employee_id')
        return tenant_scoped_queryset(Staff.objects.filter(is_active=True), self.request).order_by('employee_id')

    def perform_create(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can create staff")
        serializer.save(restaurant=resolve_request_restaurant(self.request))

    def perform_update(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can update staff")
        serializer.save()

    def perform_destroy(self, instance):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can delete staff")
        instance.delete()

    @action(detail=False, methods=['get'])
    def by_department(self, request):
        department_id = request.query_params.get('department')
        if department_id:
            staff = tenant_scoped_queryset(Staff.objects.filter(department_id=department_id), request).order_by('employee_id')
            serializer = self.get_serializer(staff, many=True)
            return Response(serializer.data)
        return Response({'error': 'Department parameter required'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def active_staff(self, request):
        staff = tenant_scoped_queryset(
            Staff.objects.filter(employment_status='active', is_active=True),
            request
        ).order_by('employee_id')
        if request.query_params.get('waiters_only'):
            staff = staff.filter(user__groups__name='waiter').distinct()
        serializer = self.get_serializer(staff, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def check_phone(self, request):
        phone = request.query_params.get('phone')
        if not phone:
            return Response({'error': 'Phone parameter required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if phone exists in User model
        user_exists = User.objects.filter(phone=phone).exists()
        # Check if phone exists in Staff model
        staff_exists = Staff.objects.filter(phone=phone).exists()
        
        exists = user_exists or staff_exists
        
        return Response({'exists': exists})

class AttendanceViewSet(viewsets.ModelViewSet):
    queryset = Attendance.objects.all().order_by('-date', '-created_at')
    serializer_class = AttendanceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated and (user.is_superuser or user.cafe_manager):
            return tenant_scoped_queryset(Attendance.objects.all(), self.request).order_by('-date', '-created_at')
        if hasattr(user, 'employee_profile'):
            return Attendance.objects.filter(employee=user.employee_profile).order_by('-date', '-created_at')
        if hasattr(user, 'staff_profile'):
            return Attendance.objects.filter(staff=user.staff_profile).order_by('-date', '-created_at')
        return Attendance.objects.none()

    def perform_create(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            # Staff can only create their own attendance
            if hasattr(self.request.user, 'staff_profile'):
                serializer.save(staff=self.request.user.staff_profile)
            else:
                raise PermissionDenied("You can only create your own attendance")
        else:
            serializer.save()

    def perform_update(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            # Staff can only update their own attendance
            if hasattr(self.request.user, 'staff_profile') and serializer.instance.staff == self.request.user.staff_profile:
                serializer.save()
            else:
                raise PermissionDenied("You can only update your own attendance")
        else:
            serializer.save()

    def perform_destroy(self, instance):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            # Staff can only delete their own attendance
            if hasattr(self.request.user, 'staff_profile') and instance.staff == self.request.user.staff_profile:
                instance.delete()
            else:
                raise PermissionDenied("You can only delete your own attendance")
        else:
            instance.delete()

    @action(detail=False, methods=['post'])
    def check_in(self, request):
        user = request.user
        today = date.today()
        if hasattr(user, 'employee_profile'):
            emp = user.employee_profile
            attendance, created = Attendance.objects.get_or_create(
                employee=emp,
                date=today,
                defaults={'check_in_time': timezone.now().time(), 'status': 'present'},
            )
        elif hasattr(user, 'staff_profile'):
            attendance, created = Attendance.objects.get_or_create(
                staff=user.staff_profile,
                date=today,
                defaults={'check_in_time': timezone.now().time(), 'status': 'present'},
            )
        else:
            return Response({'error': 'Staff or employee profile not found'}, status=status.HTTP_400_BAD_REQUEST)

        if not created:
            attendance.check_in_time = timezone.now().time()
            attendance.status = 'present'
            attendance.save()

        serializer = self.get_serializer(attendance)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def check_out(self, request):
        user = request.user
        today = date.today()
        try:
            if hasattr(user, 'employee_profile'):
                attendance = Attendance.objects.get(employee=user.employee_profile, date=today)
            elif hasattr(user, 'staff_profile'):
                attendance = Attendance.objects.get(staff=user.staff_profile, date=today)
            else:
                return Response({'error': 'Staff or employee profile not found'}, status=status.HTTP_400_BAD_REQUEST)
            attendance.check_out_time = timezone.now().time()
            attendance.save()
            serializer = self.get_serializer(attendance)
            return Response(serializer.data)
        except Attendance.DoesNotExist:
            return Response({'error': 'No attendance record found for today'}, status=status.HTTP_400_BAD_REQUEST)

class LeaveViewSet(viewsets.ModelViewSet):
    queryset = Leave.objects.all().order_by('-start_date')
    serializer_class = LeaveSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated and (user.is_superuser or user.cafe_manager):
            return tenant_scoped_queryset(Leave.objects.all(), self.request).order_by('-start_date')
        if hasattr(user, 'employee_profile'):
            return Leave.objects.filter(employee=user.employee_profile).order_by('-start_date')
        if hasattr(user, 'staff_profile'):
            return Leave.objects.filter(staff=user.staff_profile).order_by('-start_date')
        return Leave.objects.none()

    def perform_create(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            # Staff can only create their own leaves
            if hasattr(self.request.user, 'staff_profile'):
                serializer.save(staff=self.request.user.staff_profile)
            else:
                raise PermissionDenied("You can only create your own leave requests")
        else:
            serializer.save()

    def perform_update(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            # Staff can only update their own leaves
            if hasattr(self.request.user, 'staff_profile') and serializer.instance.staff == self.request.user.staff_profile:
                serializer.save()
            else:
                raise PermissionDenied("You can only update your own leave requests")
        else:
            serializer.save()

    def perform_destroy(self, instance):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            # Staff can only delete their own leaves
            if hasattr(self.request.user, 'staff_profile') and instance.staff == self.request.user.staff_profile:
                instance.delete()
            else:
                raise PermissionDenied("You can only delete your own leave requests")
        else:
            instance.delete()

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can approve leaves")
        
        leave = self.get_object()
        leave.status = 'approved'
        leave.approved_by = self.request.user.staff_profile if hasattr(self.request.user, 'staff_profile') else None
        leave.approved_at = timezone.now()
        leave.save()
        
        serializer = self.get_serializer(leave)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can reject leaves")
        
        leave = self.get_object()
        leave.status = 'rejected'
        leave.approved_by = self.request.user.staff_profile if hasattr(self.request.user, 'staff_profile') else None
        leave.approved_at = timezone.now()
        leave.save()
        
        serializer = self.get_serializer(leave)
        return Response(serializer.data)

# HR Management ViewSets
class HRDepartmentViewSet(viewsets.ModelViewSet):
    queryset = HRDepartment.objects.all().order_by('name')
    serializer_class = HRDepartmentSerializer
    permission_classes = [IsHRManager]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    
    def get_queryset(self):
        queryset = HRDepartment.objects.all()
        restaurant = getattr(self.request, 'restaurant', None)
        
        if restaurant:
            queryset = queryset.filter(restaurant=restaurant)
        elif not (self.request.user.is_authenticated and (self.request.user.is_super_admin or self.request.user.is_superuser)):
            queryset = queryset.none()
        
        return queryset.order_by('name')
    
    def perform_create(self, serializer):
        if not (self.request.user.is_hr_manager() or self.request.user.has_permission('manage_employees')):
            raise PermissionDenied("You don't have permission to create HR departments")
        
        restaurant = getattr(self.request, 'restaurant', None)
        if not restaurant:
            if self.request.user.is_authenticated and self.request.user.restaurant:
                restaurant = self.request.user.restaurant
            else:
                raise PermissionDenied("Restaurant context is required")
        serializer.save(restaurant=restaurant)

    @action(detail=True, methods=['get'])
    def employees(self, request, pk=None):
        department = self.get_object()
        employees = department.employees.all()
        serializer = EmployeeSerializer(employees, many=True, context={'request': request})
        return Response(serializer.data)

class HRPositionViewSet(viewsets.ModelViewSet):
    queryset = HRPosition.objects.all().order_by('department__name', 'name')
    serializer_class = HRPositionSerializer
    permission_classes = [IsHRManager]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['department', 'is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'department__name', 'created_at']
    
    def get_queryset(self):
        queryset = HRPosition.objects.all()
        restaurant = getattr(self.request, 'restaurant', None)
        
        if restaurant:
            queryset = queryset.filter(restaurant=restaurant)
        elif not (self.request.user.is_authenticated and (self.request.user.is_super_admin or self.request.user.is_superuser)):
            queryset = queryset.none()
        
        return queryset.order_by('department__name', 'name')
    
    def perform_create(self, serializer):
        if not (self.request.user.is_hr_manager() or self.request.user.has_permission('manage_employees')):
            raise PermissionDenied("You don't have permission to create HR positions")
        
        restaurant = getattr(self.request, 'restaurant', None)
        if not restaurant:
            if self.request.user.is_authenticated and self.request.user.restaurant:
                restaurant = self.request.user.restaurant
            else:
                raise PermissionDenied("Restaurant context is required")
        serializer.save(restaurant=restaurant)

    @action(detail=True, methods=['get'])
    def employees(self, request, pk=None):
        position = self.get_object()
        employees = position.employees.all()
        serializer = EmployeeSerializer(employees, many=True, context={'request': request})
        return Response(serializer.data)

class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.all().order_by('employee_id')
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['department', 'position', 'employment_status', 'is_active', 'gender']
    search_fields = ['employee_id', 'first_name', 'last_name', 'email', 'phone']
    ordering_fields = ['employee_id', 'first_name', 'last_name', 'hire_date', 'created_at']

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [IsHRManager()]  # HR managers and above can view
        return [IsHRManager()]  # HR managers and above can modify

    def get_serializer_class(self):
        if self.action == 'create':
            return EmployeeCreateSerializer
        return EmployeeSerializer
    
    def get_queryset(self):
        queryset = Employee.objects.all()
        restaurant = getattr(self.request, 'restaurant', None)
        
        if restaurant:
            queryset = queryset.filter(restaurant=restaurant)
        elif not (self.request.user.is_authenticated and (self.request.user.is_super_admin or self.request.user.is_superuser)):
            queryset = queryset.none()
        
        return queryset.order_by('employee_id')
    
    def perform_create(self, serializer):
        if not (self.request.user.is_hr_manager() or self.request.user.has_permission('manage_employees')):
            raise PermissionDenied("You don't have permission to create employees")
        
        restaurant = getattr(self.request, 'restaurant', None)
        if not restaurant:
            if self.request.user.is_authenticated and self.request.user.restaurant:
                restaurant = self.request.user.restaurant
            else:
                raise PermissionDenied("Restaurant context is required")
        serializer.save(restaurant=restaurant)
    
    def perform_update(self, serializer):
        if not (self.request.user.is_hr_manager() or self.request.user.has_permission('manage_employees')):
            raise PermissionDenied("You don't have permission to update employees")
        serializer.save()
    
    def perform_destroy(self, instance):
        if not (self.request.user.is_hr_manager() or self.request.user.has_permission('manage_employees')):
            raise PermissionDenied("You don't have permission to delete employees")
        instance.delete()

    @action(detail=False, methods=['get'])
    def active_employees(self, request):
        queryset = self.get_queryset()
        employees = queryset.filter(employment_status='active', is_active=True)
        serializer = self.get_serializer(employees, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def department_stats(self, request):
        queryset = self.get_queryset()
        stats = queryset.values('department__name').annotate(
            count=Count('id'),
            active_count=Count('id', filter=Q(employment_status='active')),
            avg_salary=Avg('current_salary')
        )
        return Response(stats)

    @action(detail=True, methods=['get'])
    def documents(self, request, pk=None):
        employee = self.get_object()
        documents = employee.documents.all()
        serializer = EmployeeDocumentSerializer(documents, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def payroll_history(self, request, pk=None):
        employee = self.get_object()
        payrolls = employee.payrolls.all()
        serializer = PayrollSerializer(payrolls, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def leave_history(self, request, pk=None):
        employee = self.get_object()
        leaves = employee.leave_requests.all()
        serializer = LeaveRequestSerializer(leaves, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def performance_reviews(self, request, pk=None):
        employee = self.get_object()
        reviews = employee.performance_reviews.all()
        serializer = PerformanceReviewSerializer(reviews, many=True)
        return Response(serializer.data)

class EmployeeDocumentViewSet(viewsets.ModelViewSet):
    queryset = EmployeeDocument.objects.all().order_by('-uploaded_at')
    serializer_class = EmployeeDocumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['employee', 'document_type', 'is_verified']
    search_fields = ['title', 'description']
    ordering_fields = ['uploaded_at', 'title']

    @action(detail=False, methods=['get'])
    def unverified(self, request):
        documents = EmployeeDocument.objects.filter(is_verified=False)
        serializer = self.get_serializer(documents, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        document = self.get_object()
        document.is_verified = True
        document.save()
        serializer = self.get_serializer(document)
        return Response(serializer.data)

class PayrollViewSet(viewsets.ModelViewSet):
    queryset = Payroll.objects.all().order_by('-year', '-month')
    serializer_class = PayrollSerializer
    permission_classes = [IsHRManager]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['employee', 'payment_status', 'year', 'month']
    search_fields = ['employee__first_name', 'employee__last_name', 'employee__employee_id']
    ordering_fields = ['payment_date', 'net_salary', 'created_at']
    
    def get_queryset(self):
        queryset = Payroll.objects.all()
        restaurant = getattr(self.request, 'restaurant', None)
        
        if restaurant:
            queryset = queryset.filter(employee__restaurant=restaurant)
        elif not (self.request.user.is_authenticated and (self.request.user.is_super_admin or self.request.user.is_superuser)):
            queryset = queryset.none()
        
        return queryset.order_by('-year', '-month')
    
    def perform_create(self, serializer):
        if not (self.request.user.is_hr_manager() or self.request.user.has_permission('manage_payroll')):
            raise PermissionDenied("You don't have permission to create payroll records")
        serializer.save()
    
    def perform_update(self, serializer):
        if not (self.request.user.is_hr_manager() or self.request.user.has_permission('manage_payroll')):
            raise PermissionDenied("You don't have permission to update payroll records")
        serializer.save()
    
    def perform_destroy(self, instance):
        if not (self.request.user.is_hr_manager() or self.request.user.has_permission('manage_payroll')):
            raise PermissionDenied("You don't have permission to delete payroll records")
        instance.delete()

    @action(detail=False, methods=['get'])
    def monthly_summary(self, request):
        month = request.query_params.get('month')
        year = request.query_params.get('year')
        
        if not month or not year:
            return Response({'error': 'Month and year parameters required'}, status=400)
        
        payrolls = Payroll.objects.filter(month=month, year=year)
        total_payroll = payrolls.aggregate(
            total_basic=Sum('basic_salary'),
            total_allowances=Sum('allowances'),
            total_deductions=Sum('deductions'),
            total_net=Sum('net_salary'),
            employee_count=Count('employee', distinct=True)
        )
        
        return Response({
            'month': month,
            'year': year,
            'summary': total_payroll,
            'payrolls': PayrollSerializer(payrolls, many=True).data
        })

    @action(detail=False, methods=['post'])
    def bulk_create(self, request):
        payroll_data = request.data.get('payrolls', [])
        created_payrolls = []
        
        for data in payroll_data:
            serializer = self.get_serializer(data=data)
            if serializer.is_valid():
                payroll = serializer.save()
                created_payrolls.append(payroll)
        
        return Response({
            'message': f'Created {len(created_payrolls)} payroll records',
            'payrolls': PayrollSerializer(created_payrolls, many=True).data
        })

class LeaveRequestViewSet(viewsets.ModelViewSet):
    queryset = LeaveRequest.objects.all().order_by('-created_at')
    serializer_class = LeaveRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['employee', 'leave_type', 'status']
    search_fields = ['employee__first_name', 'employee__last_name', 'reason']
    ordering_fields = ['start_date', 'end_date', 'created_at']

    @action(detail=False, methods=['get'])
    def pending_approvals(self, request):
        leaves = LeaveRequest.objects.filter(status='pending')
        serializer = self.get_serializer(leaves, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        leave = self.get_object()
        leave.status = 'approved'
        leave.approved_by = request.user.employee_profile
        leave.approved_at = timezone.now()
        leave.save()
        serializer = self.get_serializer(leave)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        leave = self.get_object()
        leave.status = 'rejected'
        leave.rejection_reason = request.data.get('reason', '')
        leave.approved_by = request.user.employee_profile
        leave.approved_at = timezone.now()
        leave.save()
        serializer = self.get_serializer(leave)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def leave_stats(self, request):
        stats = LeaveRequest.objects.values('leave_type').annotate(
            total_requests=Count('id'),
            approved_requests=Count('id', filter=Q(status='approved')),
            rejected_requests=Count('id', filter=Q(status='rejected')),
            pending_requests=Count('id', filter=Q(status='pending'))
        )
        return Response(stats)

class PerformanceReviewViewSet(viewsets.ModelViewSet):
    queryset = PerformanceReview.objects.all().order_by('-review_date')
    serializer_class = PerformanceReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['employee', 'reviewer', 'overall_rating']
    search_fields = ['employee__first_name', 'employee__last_name']
    ordering_fields = ['review_date', 'overall_rating', 'created_at']

    @action(detail=False, methods=['get'])
    def overdue_reviews(self, request):
        today = timezone.now().date()
        overdue = PerformanceReview.objects.filter(next_review_date__lt=today)
        serializer = self.get_serializer(overdue, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def performance_stats(self, request):
        stats = PerformanceReview.objects.aggregate(
            avg_rating=Avg('overall_rating'),
            total_reviews=Count('id'),
            high_performers=Count('id', filter=Q(overall_rating__gte=4)),
            low_performers=Count('id', filter=Q(overall_rating__lte=2))
        )
        return Response(stats)

class TrainingViewSet(viewsets.ModelViewSet):
    queryset = Training.objects.all().order_by('-start_date')
    serializer_class = TrainingSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['training_type', 'status']
    search_fields = ['title', 'description', 'trainer']
    ordering_fields = ['start_date', 'end_date', 'created_at']

    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        today = timezone.now()
        upcoming = Training.objects.filter(start_date__gt=today, status='scheduled')
        serializer = self.get_serializer(upcoming, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def ongoing(self, request):
        today = timezone.now()
        ongoing = Training.objects.filter(
            start_date__lte=today, 
            end_date__gte=today, 
            status='in_progress'
        )
        serializer = self.get_serializer(ongoing, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def enrollments(self, request, pk=None):
        training = self.get_object()
        enrollments = training.enrollments.all()
        serializer = TrainingEnrollmentSerializer(enrollments, many=True, context={'request': request})
        return Response(serializer.data)

class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing available permissions"""
    queryset = Permission.objects.all().order_by('category', 'name')
    serializer_class = None  # We'll create a simple serializer inline
    permission_classes = [IsSuperAdmin]
    
    def list(self, request):
        try:
            permissions = Permission.objects.all().order_by('category', 'name')
            data = []
            for perm in permissions:
                data.append({
                    'id': perm.id,
                    'name': perm.name,
                    'codename': perm.codename,
                    'description': perm.description,
                    'category': perm.category,
                })
            return Response(data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def retrieve(self, request, pk=None):
        try:
            permission = Permission.objects.get(pk=pk)
            return Response({
                'id': permission.id,
                'name': permission.name,
                'codename': permission.codename,
                'description': permission.description,
                'category': permission.category,
            })
        except Permission.DoesNotExist:
            return Response({'error': 'Permission not found'}, status=status.HTTP_404_NOT_FOUND)


class RolePermissionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing role permissions"""
    queryset = RolePermission.objects.all().order_by('role', 'permission__category', 'permission__name')
    serializer_class = None  # We'll create a simple serializer inline
    permission_classes = [IsSuperAdmin]
    
    def list(self, request):
        try:
            role = request.query_params.get('role')
            if role:
                role_permissions = RolePermission.objects.filter(role=role).select_related('permission')
            else:
                role_permissions = RolePermission.objects.all().select_related('permission')
            
            data = []
            for rp in role_permissions:
                data.append({
                    'id': rp.id,
                    'role': rp.role,
                    'permission': {
                        'id': rp.permission.id,
                        'name': rp.permission.name,
                        'codename': rp.permission.codename,
                        'category': rp.permission.category,
                    }
                })
            return Response(data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def create(self, request):
        role = request.data.get('role')
        permission_id = request.data.get('permission_id')
        
        if not role or not permission_id:
            return Response({'error': 'role and permission_id are required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            permission = Permission.objects.get(pk=permission_id)
            role_permission, created = RolePermission.objects.get_or_create(
                role=role,
                permission=permission
            )
            if created:
                return Response({
                    'id': role_permission.id,
                    'role': role_permission.role,
                    'permission': {
                        'id': permission.id,
                        'name': permission.name,
                        'codename': permission.codename,
                    }
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({'error': 'Role permission already exists'}, status=status.HTTP_400_BAD_REQUEST)
        except Permission.DoesNotExist:
            return Response({'error': 'Permission not found'}, status=status.HTTP_404_NOT_FOUND)
    
    def destroy(self, request, pk=None):
        try:
            role_permission = RolePermission.objects.get(pk=pk)
            role_permission.delete()
            return Response({'message': 'Role permission removed'}, status=status.HTTP_204_NO_CONTENT)
        except RolePermission.DoesNotExist:
            return Response({'error': 'Role permission not found'}, status=status.HTTP_404_NOT_FOUND)


class UserRoleViewSet(viewsets.ViewSet):
    """ViewSet for managing user roles"""
    permission_classes = [IsSuperAdmin]
    
    @action(detail=False, methods=['get'])
    def users_by_role(self, request):
        role = request.query_params.get('role')
        if not role:
            return Response({'error': 'role parameter is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        users = User.objects.filter(role=role)
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def assign_role(self, request, pk=None):
        """Assign a role to a user"""
        try:
            user = User.objects.get(pk=pk)
            new_role = request.data.get('role')
            
            if not new_role:
                return Response({'error': 'role is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            if new_role not in [choice[0] for choice in User.ROLE_CHOICES]:
                return Response({'error': 'Invalid role'}, status=status.HTTP_400_BAD_REQUEST)
            
            user.role = new_role
            user.save()
            
            serializer = UserSerializer(user)
            return Response(serializer.data)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)


class TrainingEnrollmentViewSet(viewsets.ModelViewSet):
    queryset = TrainingEnrollment.objects.all().order_by('-enrollment_date')
    serializer_class = TrainingEnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['employee', 'training', 'certificate_issued']
    search_fields = ['employee__first_name', 'employee__last_name', 'training__title']
    ordering_fields = ['enrollment_date', 'completion_date']

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        enrollment = self.get_object()
        enrollment.completion_date = timezone.now()
        enrollment.save()
        serializer = self.get_serializer(enrollment)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def issue_certificate(self, request, pk=None):
        enrollment = self.get_object()
        enrollment.certificate_issued = True
        if 'certificate_file' in request.FILES:
            enrollment.certificate_file = request.FILES['certificate_file']
        enrollment.save()
        serializer = self.get_serializer(enrollment)
        return Response(serializer.data)


class SubscriptionPlanViewSet(viewsets.ModelViewSet):
    queryset = SubscriptionPlan.objects.all().order_by('name')
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsSuperAdmin]


class RestaurantSubscriptionViewSet(viewsets.ModelViewSet):
    queryset = RestaurantSubscription.objects.select_related('restaurant', 'plan').all()
    serializer_class = RestaurantSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_super_admin or self.request.user.is_superuser:
            restaurant_id = self.request.query_params.get('restaurant_id')
            if restaurant_id:
                qs = qs.filter(restaurant_id=restaurant_id)
            return qs
        return tenant_scoped_queryset(qs, self.request)

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'current', 'usage']:
            return [permissions.IsAuthenticated()]
        if self.request.user.is_super_admin or self.request.user.is_superuser:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]

    @action(detail=False, methods=['get'])
    def current(self, request):
        restaurant = resolve_request_restaurant(request)
        if not restaurant and not (request.user.is_super_admin or request.user.is_superuser):
            return Response({'error': 'Restaurant context is required'}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.is_super_admin or request.user.is_superuser:
            restaurant_id = request.query_params.get('restaurant_id')
            if restaurant_id:
                restaurant = get_object_or_404(Restaurant, id=restaurant_id)
        if not restaurant:
            return Response({'error': 'Restaurant not found'}, status=status.HTTP_404_NOT_FOUND)

        current = (
            RestaurantSubscription.objects.filter(restaurant=restaurant, is_active=True)
            .select_related('plan')
            .order_by('-created_at')
            .first()
        )
        if not current:
            return Response({'restaurant_id': restaurant.id, 'subscription': None})
        return Response({'restaurant_id': restaurant.id, 'subscription': self.get_serializer(current).data})

    @action(detail=False, methods=['get'])
    def usage(self, request):
        restaurant = resolve_request_restaurant(request)
        if request.user.is_super_admin or request.user.is_superuser:
            restaurant_id = request.query_params.get('restaurant_id')
            if restaurant_id:
                restaurant = get_object_or_404(Restaurant, id=restaurant_id)
        if not restaurant:
            return Response({'error': 'Restaurant context is required'}, status=status.HTTP_400_BAD_REQUEST)

        month_key = timezone.now().strftime('%Y-%m')
        orders_count = order.objects.filter(restaurant=restaurant, created_at__startswith=month_key).count()
        active_staff_count = Staff.objects.filter(restaurant=restaurant, is_active=True).count()
        snap, _ = TenantUsageSnapshot.objects.update_or_create(
            restaurant=restaurant,
            month_key=month_key,
            defaults={'orders_count': orders_count, 'active_staff_count': active_staff_count},
        )
        serializer = TenantUsageSnapshotSerializer(snap)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def billing_summary(self, request):
        restaurant = resolve_request_restaurant(request)
        if request.user.is_super_admin or request.user.is_superuser:
            restaurant_id = request.query_params.get('restaurant_id')
            if restaurant_id:
                restaurant = get_object_or_404(Restaurant, id=restaurant_id)
        if not restaurant:
            return Response({'error': 'Restaurant context is required'}, status=status.HTTP_400_BAD_REQUEST)

        invoices = BillingInvoice.objects.filter(restaurant=restaurant).order_by('-created_at')[:20]
        active_sub = restaurant.active_subscription
        return Response(
            {
                'restaurant_id': restaurant.id,
                'subscription': RestaurantSubscriptionSerializer(active_sub).data if active_sub else None,
                'invoices': BillingInvoiceSerializer(invoices, many=True).data,
            }
        )

    @action(detail=True, methods=['post'])
    def pay_now(self, request, pk=None):
        sub = self.get_object()
        if not (request.user.is_super_admin or request.user.is_superuser):
            restaurant = resolve_request_restaurant(request)
            if not restaurant or restaurant.id != sub.restaurant_id:
                return Response({'error': 'Restaurant context is required'}, status=status.HTTP_403_FORBIDDEN)

        invoice = BillingInvoice.objects.filter(subscription=sub).order_by('-created_at').first()
        if not invoice:
            invoice = BillingInvoice.objects.create(
                restaurant=sub.restaurant,
                subscription=sub,
                plan=sub.plan,
                invoice_number=f"INV-{sub.restaurant_id}-{int(timezone.now().timestamp())}",
                amount=sub.plan.price,
                currency=sub.plan.currency,
                due_date=timezone.now() + timedelta(days=7),
                status='pending_payment',
                metadata={'source': 'pay_now_action'},
            )
        provider = EsewaBillingProvider()
        init = provider.initiate_payment(
            invoice=invoice,
            success_url=request.data.get('success_url', ''),
            failure_url=request.data.get('failure_url', ''),
        )
        tx = BillingTransaction.objects.create(
            invoice=invoice,
            gateway='esewa',
            status='initiated',
            gateway_reference=init['transaction_ref'],
            request_payload=init['payload'],
        )
        return Response({'invoice': BillingInvoiceSerializer(invoice).data, 'transaction': BillingTransactionSerializer(tx).data})

    @action(detail=False, methods=['post'])
    def verify_payment(self, request):
        tx_id = request.data.get('transaction_id')
        tx = get_object_or_404(BillingTransaction.objects.select_related('invoice', 'invoice__subscription'), id=tx_id)
        provider = EsewaBillingProvider()
        result = provider.verify_payment(transaction=tx, payload=request.data)
        if result['success']:
            tx.status = 'success'
            tx.response_payload = request.data
            tx.save(update_fields=['status', 'response_payload', 'updated_at'])
            tx.invoice.status = 'paid'
            tx.invoice.save(update_fields=['status', 'updated_at'])
            sub = tx.invoice.subscription
            if sub:
                sub.status = 'active'
                sub.save(update_fields=['status', 'updated_at'])
                sub.restaurant.subscription_status = 'active'
                sub.restaurant.is_active = True
                sub.restaurant.lifecycle_status = 'active'
                sub.restaurant.save(update_fields=['subscription_status', 'is_active', 'lifecycle_status', 'updated_at'])
        else:
            tx.status = 'failed'
            tx.response_payload = request.data
            tx.save(update_fields=['status', 'response_payload', 'updated_at'])
            tx.invoice.status = 'failed'
            tx.invoice.save(update_fields=['status', 'updated_at'])
        return Response({'transaction': BillingTransactionSerializer(tx).data})
