import json
import logging
from datetime import datetime
from django.conf import settings
from django.utils import timezone
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from django.db import models
from django.http import HttpRequest
from typing import Optional, Dict, Any

User = get_user_model()

logger = logging.getLogger('audit')

# Import AuditLog from models to avoid duplication
from ..models import AuditLog

class AuditLogger:
    """Utility class for audit logging"""
    
    @staticmethod
    def log_action(
        request: HttpRequest,
        action_type: str,
        description: str,
        object_type: str = None,
        object_id: str = None,
        object_repr: str = None,
        changes: Dict[str, Any] = None,
        additional_data: Dict[str, Any] = None
    ):
        """Log an audit action"""
        try:
            user = getattr(request, 'user', None)
            ip_address = AuditLogger.get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            
            audit_log = AuditLog.objects.create(
                user=user if user.is_authenticated else None,
                action_type=action_type,
                action_description=description,
                ip_address=ip_address,
                user_agent=user_agent,
                object_type=object_type or '',
                object_id=str(object_id) if object_id else '',
                object_repr=object_repr or '',
                changes=changes or {},
                additional_data=additional_data or {}
            )
            
            # Also log to standard logger for immediate visibility
            logger.info(
                f"Audit: {action_type} - {user if user.is_authenticated else 'Anonymous'} - "
                f"{description} - IP: {ip_address}"
            )
            
            return audit_log
            
        except Exception as e:
            logger.error(f"Failed to log audit action: {e}")
    
    @staticmethod
    def log_security_event(
        request: HttpRequest,
        event_type: str,
        description: str,
        severity: str = 'INFO',
        additional_data: Dict[str, Any] = None
    ):
        """Log security events"""
        additional_data = additional_data or {}
        additional_data['severity'] = severity
        additional_data['security_event'] = True
        
        return AuditLogger.log_action(
            request=request,
            action_type='SECURITY_EVENT',
            description=f"[{severity}] {description}",
            additional_data=additional_data
        )
    
    @staticmethod
    def log_model_change(
        request: HttpRequest,
        instance: models.Model,
        action_type: str,
        changes: Dict[str, Any] = None
    ):
        """Log model changes"""
        return AuditLogger.log_action(
            request=request,
            action_type=action_type,
            description=f"{action_type} {instance.__class__.__name__}",
            object_type=instance.__class__.__name__,
            object_id=str(instance.pk),
            object_repr=str(instance)[:200],
            changes=changes or {}
        )
    
    @staticmethod
    def get_client_ip(request: HttpRequest) -> str:
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    @staticmethod
    def get_user_activity_summary(user: User, days: int = 30) -> Dict[str, Any]:
        """Get user activity summary"""
        from django.utils import timezone
        from datetime import timedelta
        
        start_date = timezone.now() - timedelta(days=days)
        
        logs = AuditLog.objects.filter(
            user=user,
            timestamp__gte=start_date
        )
        
        return {
            'total_actions': logs.count(),
            'actions_by_type': dict(logs.values_list('action_type').annotate(count=models.Count('action_type'))),
            'last_activity': logs.order_by('-timestamp').first(),
            'unique_ips': logs.values_list('ip_address', flat=True).distinct().count(),
        }

# Django signals for automatic audit logging
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

@receiver(post_save)
def log_model_creation(sender, instance, created, **kwargs):
    """Log model creation"""
    if not created:
        return
    
    # Skip audit logs themselves to prevent infinite loops
    if sender == AuditLog:
        return
    
    # Only log important models
    important_models = [
        'Restaurant', 'User', 'MenuItem', 'Table', 'Room',
        'Order', 'Bill', 'Staff', 'InventoryItem'
    ]
    
    if sender.__name__ in important_models:
        try:
            # This will be called from model save, not from request
            # We'll need to get the current request from thread local
            logger.info(f"Model created: {sender.__name__} - {instance}")
        except Exception as e:
            logger.error(f"Failed to log model creation: {e}")

@receiver(post_delete)
def log_model_deletion(sender, instance, **kwargs):
    """Log model deletion"""
    # Skip audit logs themselves
    if sender == AuditLog:
        return
    
    # Only log important models
    important_models = [
        'Restaurant', 'User', 'MenuItem', 'Table', 'Room',
        'Order', 'Bill', 'Staff', 'InventoryItem'
    ]
    
    if sender.__name__ in important_models:
        try:
            logger.info(f"Model deleted: {sender.__name__} - {instance}")
        except Exception as e:
            logger.error(f"Failed to log model deletion: {e}")

# Middleware for request logging
class AuditLoggingMiddleware:
    """Middleware to log all requests"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Skip logging for static files and health checks
        if request.path.startswith('/static/') or request.path.startswith('/media/') or request.path == '/health/':
            return self.get_response(request)
        
        # Log request start
        start_time = timezone.now()
        
        response = self.get_response(request)
        
        # Log request completion
        duration = (timezone.now() - start_time).total_seconds()
        
        # Only log API requests and sensitive endpoints
        if request.path.startswith('/api/') or any(path in request.path for path in ['/login', '/signup', '/admin']):
            AuditLogger.log_action(
                request=request,
                action_type='API_ACCESS',
                description=f"{request.method} {request.path} - {response.status_code}",
                additional_data={
                    'method': request.method,
                    'path': request.path,
                    'status_code': response.status_code,
                    'duration': duration,
                }
            )
        
        return response

# Security event logging functions
def log_login_attempt(request, username, success=True):
    """Log login attempts"""
    action_type = 'LOGIN' if success else 'LOGIN_FAILED'
    description = f"Login {'successful' if success else 'failed'} for username: {username}"
    
    if not success:
        AuditLogger.log_security_event(
            request=request,
            event_type='LOGIN_FAILED',
            description=description,
            severity='WARNING',
            additional_data={'username': username}
        )
    else:
        AuditLogger.log_action(
            request=request,
            action_type=action_type,
            description=description,
            additional_data={'username': username}
        )

def log_password_change(request, user):
    """Log password changes"""
    AuditLogger.log_security_event(
        request=request,
        event_type='PASSWORD_CHANGE',
        description=f"Password changed for user: {user.username}",
        severity='INFO',
        additional_data={'user_id': user.id}
    )

def log_permission_change(request, user, permissions):
    """Log permission changes"""
    AuditLogger.log_security_event(
        request=request,
        event_type='PERMISSION_CHANGE',
        description=f"Permissions changed for user: {user.username}",
        severity='WARNING',
        additional_data={
            'user_id': user.id,
            'permissions': list(permissions)
        }
    )

def log_data_export(request, export_type, record_count):
    """Log data exports"""
    AuditLogger.log_action(
        request=request,
        action_type='DATA_EXPORT',
        description=f"Exported {record_count} records of type: {export_type}",
        additional_data={
            'export_type': export_type,
            'record_count': record_count
        }
    )

def log_suspicious_activity(request, description, severity='WARNING'):
    """Log suspicious activities"""
    AuditLogger.log_security_event(
        request=request,
        event_type='SUSPICIOUS_ACTIVITY',
        description=description,
        severity=severity,
        additional_data={
            'suspicious': True,
            'timestamp': timezone.now().isoformat()
        }
    )
