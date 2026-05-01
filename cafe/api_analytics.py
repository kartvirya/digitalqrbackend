from django.db.models import Sum, Count, Avg, Q, F, DateTimeField, ExtractHour
from django.db.models.functions import Trunc
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from cafe.models import Order, MenuItem, OrderItem, User, Restaurant
from cafe.utils.audit_logging import AuditLogger
import logging

logger = logging.getLogger(__name__)

class AnalyticsMixin:
    """Mixin for analytics-related API actions"""
    
    def get_date_range(self, days):
        """Get date range for analytics"""
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        return start_date, end_date
    
    def get_restaurant_queryset(self):
        """Get restaurant queryset based on user permissions"""
        user = self.request.user
        
        if user.is_super_admin or user.is_superuser:
            return Restaurant.objects.filter(is_active=True)
        elif user.restaurant:
            return Restaurant.objects.filter(id=user.restaurant.id, is_active=True)
        else:
            return Restaurant.objects.none()
    
    def get_analytics_data(self, restaurant, days=7):
        """Get comprehensive analytics data for a restaurant"""
        start_date, end_date = self.get_date_range(days)
        
        # Base query for orders in date range
        orders_query = Order.objects.filter(
            restaurant=restaurant,
            created_at__gte=start_date,
            created_at__lte=end_date
        )
        
        # Overview metrics
        total_revenue = orders_query.aggregate(
            total=Sum('total_price')
        )['total'] or Decimal('0')
        
        total_orders = orders_query.count()
        
        # Customer metrics
        customer_data = self.get_customer_metrics(restaurant, start_date, end_date)
        
        # Sales chart data
        sales_chart = self.get_sales_chart_data(orders_query, start_date, end_date)
        
        # Top selling items
        top_items = self.get_top_selling_items(restaurant, start_date, end_date)
        
        # Peak hours
        peak_hours = self.get_peak_hours(restaurant, start_date, end_date)
        
        # Payment methods
        payment_methods = self.get_payment_methods(orders_query)
        
        # Calculate changes from previous period
        previous_start_date = start_date - timedelta(days=days)
        previous_end_date = start_date
        
        previous_orders = Order.objects.filter(
            restaurant=restaurant,
            created_at__gte=previous_start_date,
            created_at__lte=previous_end_date
        )
        
        previous_revenue = previous_orders.aggregate(
            total=Sum('total_price')
        )['total'] or Decimal('0')
        
        previous_orders_count = previous_orders.count()
        
        revenue_change = self.calculate_percentage_change(previous_revenue, total_revenue)
        orders_change = self.calculate_percentage_change(previous_orders_count, total_orders)
        
        return {
            'overview': {
                'totalRevenue': float(total_revenue),
                'totalOrders': total_orders,
                'totalCustomers': customer_data['total_customers'],
                'averageOrderValue': float(total_revenue / total_orders) if total_orders > 0 else 0,
                'revenueChange': revenue_change,
                'ordersChange': orders_change,
                'customersChange': customer_data['change_percentage'],
            },
            'salesChart': sales_chart,
            'topItems': top_items,
            'peakHours': peak_hours,
            'customerMetrics': customer_data,
            'paymentMethods': payment_methods,
        }
    
    def get_customer_metrics(self, restaurant, start_date, end_date):
        """Get customer-related metrics"""
        # Get orders in the current period
        current_orders = Order.objects.filter(
            restaurant=restaurant,
            created_at__gte=start_date,
            created_at__lte=end_date
        )
        
        # Get unique customers
        current_customers = set()
        for order in current_orders:
            if order.name and order.phone:
                current_customers.add(f"{order.name}_{order.phone}")
        
        # Get previous period customers
        previous_start_date = start_date - timedelta(days=(end_date - start_date).days)
        previous_end_date = start_date
        
        previous_orders = Order.objects.filter(
            restaurant=restaurant,
            created_at__gte=previous_start_date,
            created_at__lte=previous_end_date
        )
        
        previous_customers = set()
        for order in previous_orders:
            if order.name and order.phone:
                previous_customers.add(f"{order.name}_{order.phone}")
        
        # Calculate metrics
        new_customers = len(current_customers - previous_customers)
        returning_customers = len(current_customers & previous_customers)
        total_current_customers = len(current_customers)
        
        retention_rate = (returning_customers / total_current_customers * 100) if total_current_customers > 0 else 0
        
        # Calculate change percentage
        previous_total_customers = len(previous_customers)
        change_percentage = self.calculate_percentage_change(
            previous_total_customers, 
            total_current_customers
        )
        
        return {
            'new_customers': new_customers,
            'returning_customers': returning_customers,
            'retention_rate': retention_rate,
            'total_customers': total_current_customers,
            'change_percentage': change_percentage,
        }
    
    def get_sales_chart_data(self, orders_query, start_date, end_date):
        """Get sales data for chart visualization"""
        # Group by date
        daily_sales = orders_query.annotate(
            date=Trunc('created_at', 'day', output_field=DateTimeField())
        ).values('date').annotate(
            revenue=Sum('total_price'),
            orders=Count('id')
        ).order_by('date')
        
        # Fill missing dates with zero values
        sales_data = []
        current_date = start_date.date()
        end_date_only = end_date.date()
        
        sales_dict = {item['date'].date(): item for item in daily_sales}
        
        while current_date <= end_date_only:
            if current_date in sales_dict:
                sales_data.append({
                    'date': current_date.isoformat(),
                    'revenue': float(sales_dict[current_date]['revenue']),
                    'orders': sales_dict[current_date]['orders']
                })
            else:
                sales_data.append({
                    'date': current_date.isoformat(),
                    'revenue': 0,
                    'orders': 0
                })
            current_date += timedelta(days=1)
        
        return sales_data
    
    def get_top_selling_items(self, restaurant, start_date, end_date, limit=10):
        """Get top selling items"""
        top_items = OrderItem.objects.filter(
            order__restaurant=restaurant,
            order__created_at__gte=start_date,
            order__created_at__lte=end_date
        ).values(
            'menu_item__name'
        ).annotate(
            quantity=Sum('quantity'),
            revenue=Sum(F('quantity') * F('price'))
        ).order_by('-quantity')[:limit]
        
        return [
            {
                'name': item['menu_item__name'] or 'Unknown Item',
                'quantity': item['quantity'] or 0,
                'revenue': float(item['revenue'] or 0)
            }
            for item in top_items
        ]
    
    def get_peak_hours(self, restaurant, start_date, end_date):
        """Get peak hours analysis"""
        peak_hours = Order.objects.filter(
            restaurant=restaurant,
            created_at__gte=start_date,
            created_at__lte=end_date
        ).annotate(
            hour=ExtractHour('created_at')
        ).values('hour').annotate(
            orders=Count('id')
        ).order_by('hour')
        
        # Fill missing hours with zero
        hours_data = []
        for hour in range(24):
            hour_data = next((h for h in peak_hours if h['hour'] == hour), None)
            hours_data.append({
                'hour': hour,
                'orders': hour_data['orders'] if hour_data else 0
            })
        
        return hours_data
    
    def get_payment_methods(self, orders_query):
        """Get payment methods distribution"""
        payment_data = orders_query.values('payment_method').annotate(
            count=Count('id')
        ).order_by('-count')
        
        total_orders = orders_query.count()
        
        return [
            {
                'method': item['payment_method'] or 'Unknown',
                'count': item['count'],
                'percentage': (item['count'] / total_orders * 100) if total_orders > 0 else 0
            }
            for item in payment_data
        ]
    
    def calculate_percentage_change(self, old_value, new_value):
        """Calculate percentage change between two values"""
        if old_value == 0:
            return 100 if new_value > 0 else 0
        return ((new_value - old_value) / old_value) * 100

# Add analytics actions to existing viewsets
from cafe.api_views import RestaurantViewSet

@action(detail=True, methods=['get'], url_path='analytics')
def restaurant_analytics(self, request, pk=None):
    """Get analytics data for a specific restaurant"""
    try:
        restaurant = self.get_object()
        
        # Get time range from query params (default to 7 days)
        days = int(request.query_params.get('days', 7))
        
        # Validate days parameter
        if days not in [1, 7, 30, 90]:
            return Response(
                {'error': 'Invalid days parameter. Must be 1, 7, 30, or 90.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        analytics_data = self.get_analytics_data(restaurant, days)
        
        # Log analytics access
        AuditLogger.log_action(
            request=request,
            action_type='DATA_EXPORT',
            description=f"Analytics data exported for {restaurant.name}",
            object_type='Restaurant',
            object_id=restaurant.id,
            object_repr=str(restaurant),
            additional_data={'days': days}
        )
        
        return Response(analytics_data)
        
    except Exception as e:
        logger.error(f"Error getting analytics data: {e}")
        return Response(
            {'error': 'Failed to load analytics data'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# Add the action to RestaurantViewSet
RestaurantViewSet.restaurant_analytics = restaurant_analytics

# Super admin analytics endpoint
@action(detail=False, methods=['get'], url_path='super-admin-analytics')
def super_admin_analytics(self, request):
    """Get analytics data for all restaurants (super admin only)"""
    if not request.user.is_super_admin and not request.user.is_superuser:
        return Response(
            {'error': 'Permission denied'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        restaurants = self.get_restaurant_queryset()
        days = int(request.query_params.get('days', 7))
        
        if days not in [1, 7, 30, 90]:
            return Response(
                {'error': 'Invalid days parameter. Must be 1, 7, 30, or 90.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Aggregate data across all restaurants
        all_analytics = []
        for restaurant in restaurants:
            analytics_data = self.get_analytics_data(restaurant, days)
            analytics_data['restaurant'] = {
                'id': restaurant.id,
                'name': restaurant.name,
                'slug': restaurant.slug
            }
            all_analytics.append(analytics_data)
        
        # Calculate totals
        total_revenue = sum(data['overview']['totalRevenue'] for data in all_analytics)
        total_orders = sum(data['overview']['totalOrders'] for data in all_analytics)
        total_customers = sum(data['overview']['totalCustomers'] for data in all_analytics)
        
        summary = {
            'totalRevenue': total_revenue,
            'totalOrders': total_orders,
            'totalCustomers': total_customers,
            'averageOrderValue': total_revenue / total_orders if total_orders > 0 else 0,
            'restaurantCount': restaurants.count(),
            'restaurants': all_analytics
        }
        
        # Log analytics access
        AuditLogger.log_action(
            request=request,
            action_type='DATA_EXPORT',
            description=f"Super admin analytics data exported for {restaurants.count()} restaurants",
            additional_data={'days': days, 'restaurant_count': restaurants.count()}
        )
        
        return Response(summary)
        
    except Exception as e:
        logger.error(f"Error getting super admin analytics: {e}")
        return Response(
            {'error': 'Failed to load analytics data'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# Add the action to RestaurantViewSet
RestaurantViewSet.super_admin_analytics = super_admin_analytics
