from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.db.models import Q, Count, Avg, Sum, Max
from datetime import date
import json
from django.utils import timezone
from datetime import date, datetime
from rest_framework.permissions import IsAuthenticatedOrReadOnly
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
    Permission, RolePermission, Payment
)
from .serializers import (
    RestaurantSerializer, UserSerializer, TableSerializer, FloorSerializer, RoomSerializer, MenuItemSerializer, 
    OrderSerializer, RatingSerializer, BillSerializer, OrderCreateSerializer,
    DepartmentSerializer, RoleSerializer, StaffSerializer, StaffCreateSerializer,
    AttendanceSerializer, LeaveSerializer,
    HRDepartmentSerializer, HRPositionSerializer, EmployeeSerializer, EmployeeCreateSerializer, EmployeeDocumentSerializer, PayrollSerializer, LeaveRequestSerializer, PerformanceReviewSerializer, TrainingSerializer, TrainingEnrollmentSerializer,
    PaymentSerializer
)
from .permissions import IsSuperAdmin, IsRestaurantAdmin, IsHRManager, IsStaff, HasPermission, IsRestaurantScoped


class RestaurantViewSet(viewsets.ModelViewSet):
    """ViewSet for Restaurant management"""
    queryset = Restaurant.objects.all().order_by('name')
    serializer_class = RestaurantSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]  # Allow viewing restaurants
        return [permissions.IsAuthenticated()]
    
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
            # Try to get from user's restaurant
            if self.request.user.is_authenticated and self.request.user.restaurant:
                restaurant = self.request.user.restaurant
            else:
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
            else:
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
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        return [IsRestaurantAdmin()]
    
    def get_queryset(self):
        user = self.request.user
        queryset = Table.objects.all()
        
        # Filter by restaurant
        restaurant = getattr(self.request, 'restaurant', None)
        if restaurant:
            queryset = queryset.filter(restaurant=restaurant)
        elif not (user.is_authenticated and (user.is_super_admin or user.is_superuser)):
            # Non-super-admin users must have a restaurant context
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
            else:
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
        if floor_id:
            tables = Table.objects.filter(floor_id=floor_id, is_active=True)
            serializer = self.get_serializer(tables, many=True)
            return Response(serializer.data)
        return Response({'error': 'floor_id parameter is required'}, status=status.HTTP_400_BAD_REQUEST)


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
            else:
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
    
    @action(detail=True, methods=['post'])
    def regenerate_qr(self, request, pk=None):
        table = self.get_object()
        # Delete existing QR code
        if table.qr_code:
            table.qr_code.delete()
        # Generate new QR code
        table.generate_qr_code()
        table.save()
        serializer = self.get_serializer(table)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def update_position(self, request, pk=None):
        table = self.get_object()
        x = request.data.get('x', 0)
        y = request.data.get('y', 0)
        
        table.visual_x = x
        table.visual_y = y
        table.save()
        
        serializer = self.get_serializer(table)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def by_floor(self, request):
        floor_id = request.query_params.get('floor')
        if floor_id:
            tables = Table.objects.filter(floor_id=floor_id).order_by('table_number')
            serializer = self.get_serializer(tables, many=True)
            return Response(serializer.data)
        return Response({'error': 'Floor parameter required'}, status=status.HTTP_400_BAD_REQUEST)


class OrderViewSet(viewsets.ModelViewSet):
    queryset = order.objects.all().order_by('-created_at')
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_permissions(self):
        if self.action in ['create', 'retrieve', 'by_table_unique_id', 'by_room_unique_id', 'clear_table', 'update_status']:
            return [permissions.AllowAny()]  # Allow anonymous order creation, viewing, table/room queries, table clearing, and status updates
        elif self.action == 'list':
            # Allow list if user is authenticated OR if restaurant context is provided via headers
            # This allows admin users to view orders for their restaurant even if session expired
            return [permissions.AllowAny()]  # We'll check authentication/restaurant context in get_queryset
        return [permissions.IsAuthenticated()]
    
    def create(self, request, *args, **kwargs):
        # Allow anonymous order creation using table/room QR
        data = request.data
        try:
            items = data.get('items', [])
            table_unique_id = data.get('table_unique_id')
            room_unique_id = data.get('room_unique_id')
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
            
            if not restaurant:
                return Response({'error': 'Restaurant context is required'}, status=status.HTTP_400_BAD_REQUEST)

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
        queryset = order.objects.all()
        
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
            else:
                # Regular users can see their own orders
                queryset = queryset.filter(phone=user.phone)
        else:
            # Anonymous users need restaurant context
            queryset = queryset.none()
        
        return queryset.order_by('-created_at')
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        try:
            # Get order by ID, with restaurant filtering if context is available
            order_id = pk or request.data.get('order_id')
            if not order_id:
                return Response({'error': 'Order ID is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Try to get order with restaurant context
            restaurant = getattr(request, 'restaurant', None)
            if restaurant:
                try:
                    order_obj = order.objects.get(id=order_id, restaurant=restaurant)
                except order.DoesNotExist:
                    return Response({'error': 'Order not found or does not belong to this restaurant'}, status=status.HTTP_404_NOT_FOUND)
            else:
                # Fallback: try to get order without restaurant filter (for super admin)
                try:
                    order_obj = order.objects.get(id=order_id)
                except order.DoesNotExist:
                    return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
            
            new_status = request.data.get('status')
            
            # Valid order statuses (including completed)
            valid_statuses = ['pending', 'confirmed', 'preparing', 'ready', 'served', 'delivered', 'cancelled', 'completed']
            
            if not new_status:
                return Response({'error': 'Status is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            if new_status not in valid_statuses:
                valid_str = ", ".join(valid_statuses)
                return Response({'error': f'Invalid status. Valid statuses are: {valid_str}'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Update order status
            order_obj.status = new_status
            order_obj.save()
            
            print(f"✅ Order {order_obj.id} status updated to {new_status} by user {request.user.id if request.user.is_authenticated else 'anonymous'}")
            
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
    def mark_paid(self, request, pk=None):
        """Mark an order as paid (typically cash/UPI at table)."""
        try:
            from django.utils import timezone

            order_id = pk or request.data.get('order_id')
            if not order_id:
                return Response({'error': 'Order ID is required'}, status=status.HTTP_400_BAD_REQUEST)

            restaurant = getattr(request, 'restaurant', None)
            if restaurant:
                try:
                    order_obj = order.objects.get(id=order_id, restaurant=restaurant)
                except order.DoesNotExist:
                    return Response({'error': 'Order not found or does not belong to this restaurant'}, status=status.HTTP_404_NOT_FOUND)
            else:
                try:
                    order_obj = order.objects.get(id=order_id)
                except order.DoesNotExist:
                    return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

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
        """Clear table by marking all orders as billed"""
        table_unique_id = request.data.get('table_unique_id')
        room_unique_id = request.data.get('room_unique_id')
        
        if not table_unique_id and not room_unique_id:
            return Response({'error': 'table_unique_id or room_unique_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Mark all orders for this table/room as billed
            if table_unique_id:
                orders_to_clear = order.objects.filter(table_unique_id=table_unique_id, bill_clear=False)
            else:
                orders_to_clear = order.objects.filter(room_unique_id=room_unique_id, bill_clear=False)
            
            # Update all orders to mark them as billed
            orders_to_clear.update(bill_clear=True)
            
            cleared_count = orders_to_clear.count()
            
            return Response({
                'message': f'Table cleared successfully. {cleared_count} orders marked as billed.',
                'cleared_orders': cleared_count
            }, status=status.HTTP_200_OK)
            
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
    
    @action(detail=False, methods=['post'])
    def login(self, request):
        phone = request.data.get('phone')
        password = request.data.get('password')
        restaurant_slug = request.data.get('restaurant_slug')  # Optional restaurant selection
        
        user = authenticate(phone=phone, password=password)
        if user:
            login(request, user)
            serializer = UserSerializer(user)
            data = serializer.data
            
            # Add role and permissions
            data['role'] = user.role
            # Get permissions for the user's role
            role_permissions = RolePermission.objects.filter(role=user.role).select_related('permission')
            data['permissions'] = [rp.permission.codename for rp in role_permissions]
            
            # If user is a restaurant admin, include their restaurant
            if user.restaurant:
                data['restaurant'] = RestaurantSerializer(user.restaurant).data
            # If user is super admin, include available restaurants
            elif user.is_super_admin or user.is_superuser:
                restaurants = Restaurant.objects.filter(is_active=True).order_by('name')
                data['available_restaurants'] = RestaurantSerializer(restaurants, many=True).data
                
                # If restaurant_slug is provided, set it as the selected restaurant
                if restaurant_slug:
                    try:
                        selected_restaurant = Restaurant.objects.get(slug=restaurant_slug, is_active=True)
                        data['selected_restaurant'] = RestaurantSerializer(selected_restaurant).data
                    except Restaurant.DoesNotExist:
                        pass
            
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
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        if not (request.user.is_superuser or request.user.cafe_manager or request.user.is_super_admin):
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Filter by restaurant
        restaurant = getattr(request, 'restaurant', None)
        if not restaurant and request.user.is_authenticated and request.user.restaurant:
            restaurant = request.user.restaurant
        
        if restaurant:
            total_orders = order.objects.filter(restaurant=restaurant).count()
            total_menu_items = menu_item.objects.filter(restaurant=restaurant, is_available=True).count()
            total_tables = Table.objects.filter(restaurant=restaurant, is_active=True).count()
            total_revenue = sum(bill.bill_total for bill in bill.objects.filter(restaurant=restaurant))
            recent_orders = order.objects.filter(restaurant=restaurant).order_by('-created_at')[:5]
            menu_items = menu_item.objects.filter(restaurant=restaurant, is_available=True)[:5]
        else:
            # Super admin can see all data
            total_orders = order.objects.count()
            total_menu_items = menu_item.objects.filter(is_available=True).count()
            total_tables = Table.objects.filter(is_active=True).count()
            total_revenue = sum(bill.bill_total for bill in bill.objects.all())
            recent_orders = order.objects.all().order_by('-created_at')[:5]
            menu_items = menu_item.objects.filter(is_available=True)[:5]
        
        recent_orders_data = []
        for order_obj in recent_orders:
            recent_orders_data.append({
                'id': order_obj.id,
                'total_amount': order_obj.price,
                'status': order_obj.status,
                'table_unique_id': order_obj.table_unique_id
            })
        
        # Get popular items (mock data for now)
        popular_items = []
        for item in menu_items:
            popular_items.append({
                'name': item.name,
                'order_count': 0,  # This would need to be calculated from order history
                'revenue': 0  # This would need to be calculated from order history
            })
        
        return Response({
            'total_orders': total_orders,
            'total_menu_items': total_menu_items,
            'total_tables': total_tables,
            'total_revenue': total_revenue,
            'recent_orders': recent_orders_data,
            'popular_items': popular_items
        })


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
        
        return Response({
            'total_restaurants': total_restaurants,
            'total_orders': total_orders,
            'total_revenue': total_revenue,
            'restaurants': restaurant_stats
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
            return Department.objects.all().order_by('name')
        return Department.objects.filter(is_active=True).order_by('name')

    def perform_create(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can create departments")
        serializer.save()

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
            return Role.objects.all().order_by('department', 'name')
        return Role.objects.filter(is_active=True).order_by('department', 'name')

    def perform_create(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can create roles")
        serializer.save()

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
            roles = Role.objects.filter(department_id=department_id).order_by('name')
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
            return Staff.objects.all().order_by('employee_id')
        return Staff.objects.filter(is_active=True).order_by('employee_id')

    def perform_create(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.cafe_manager):
            raise PermissionDenied("Only administrators can create staff")
        serializer.save()

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
            staff = Staff.objects.filter(department_id=department_id).order_by('employee_id')
            serializer = self.get_serializer(staff, many=True)
            return Response(serializer.data)
        return Response({'error': 'Department parameter required'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def active_staff(self, request):
        staff = Staff.objects.filter(employment_status='active', is_active=True).order_by('employee_id')
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
            return Attendance.objects.all().order_by('-date', '-created_at')
        # Staff can only see their own attendance
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
        if not hasattr(request.user, 'staff_profile'):
            return Response({'error': 'Staff profile not found'}, status=status.HTTP_400_BAD_REQUEST)
        
        today = date.today()
        attendance, created = Attendance.objects.get_or_create(
            staff=request.user.staff_profile,
            date=today,
            defaults={'check_in_time': timezone.now().time(), 'status': 'present'}
        )
        
        if not created:
            attendance.check_in_time = timezone.now().time()
            attendance.status = 'present'
            attendance.save()
        
        serializer = self.get_serializer(attendance)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def check_out(self, request):
        if not hasattr(request.user, 'staff_profile'):
            return Response({'error': 'Staff profile not found'}, status=status.HTTP_400_BAD_REQUEST)
        
        today = date.today()
        try:
            attendance = Attendance.objects.get(staff=request.user.staff_profile, date=today)
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
            return Leave.objects.all().order_by('-start_date')
        # Staff can only see their own leaves
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
