"""
Custom permission classes for role-based access control
"""
from rest_framework import permissions


class IsSuperAdmin(permissions.BasePermission):
    """Only allows super admins"""
    
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            (request.user.is_super_admin or request.user.role == 'super_admin')
        )


class IsRestaurantAdmin(permissions.BasePermission):
    """Allows restaurant admins and super admins"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Super admin has access
        if request.user.is_super_admin or request.user.role == 'super_admin':
            return True
        
        # Restaurant admin has access
        return request.user.is_restaurant_admin()


class IsHRManager(permissions.BasePermission):
    """Allows HR managers, restaurant admins, and super admins"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Super admin has access
        if request.user.is_super_admin or request.user.role == 'super_admin':
            return True
        
        # Restaurant admin has access
        if request.user.is_restaurant_admin():
            return True
        
        # HR Manager has access
        return request.user.is_hr_manager()


class IsStaff(permissions.BasePermission):
    """Allows staff members, HR managers, restaurant admins, and super admins"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Super admin has access
        if request.user.is_super_admin or request.user.role == 'super_admin':
            return True
        
        # Restaurant admin has access
        if request.user.is_restaurant_admin():
            return True
        
        # HR Manager has access
        if request.user.is_hr_manager():
            return True
        
        # Staff has access
        return request.user.is_staff_member()


class HasPermission(permissions.BasePermission):
    """Check if user has a specific permission"""
    
    def __init__(self, permission_name):
        self.permission_name = permission_name
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        return request.user.has_permission(self.permission_name)


class IsRestaurantScoped(permissions.BasePermission):
    """Ensures user can only access their restaurant's data"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Super admin can access all restaurants
        if request.user.is_super_admin or request.user.role == 'super_admin':
            return True
        
        # Other users must have a restaurant
        return request.user.restaurant is not None
    
    def has_object_permission(self, request, view, obj):
        # Super admin can access all objects
        if request.user.is_super_admin or request.user.role == 'super_admin':
            return True
        
        # Check if object belongs to user's restaurant
        if hasattr(obj, 'restaurant'):
            return obj.restaurant == request.user.restaurant
        
        return False

