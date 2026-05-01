from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from django.urls import reverse
from django.contrib.auth import login, logout
from social_django.utils import psa
from cafe.social_auth import get_trial_status, check_trial_expiry
from cafe.utils.audit_logging import log_login_attempt, log_login_attempt
import logging

logger = logging.getLogger(__name__)

@api_view(['GET'])
@permission_classes([AllowAny])
def google_auth_url(request):
    """Get Google OAuth authentication URL"""
    try:
        # Build the Google OAuth URL
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth"
        params = {
            'client_id': settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY,
            'redirect_uri': f"{settings.FRONTEND_URL}/auth/google/callback",
            'response_type': 'code',
            'scope': ' '.join(settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE),
            'access_type': 'offline',
            'prompt': 'consent',
        }
        
        # Build query string
        query_string = '&'.join([f"{key}={value}" for key, value in params.items()])
        full_url = f"{auth_url}?{query_string}"
        
        return Response({
            'auth_url': full_url,
            'redirect_uri': params['redirect_uri'],
            'scopes': settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE,
        })
    
    except Exception as e:
        logger.error(f"Error generating Google auth URL: {e}")
        return Response(
            {'error': 'Failed to generate authentication URL'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([AllowAny])
@psa('social:complete')
def google_auth_callback(request, backend):
    """Handle Google OAuth callback"""
    try:
        # The PSA decorator will handle the OAuth flow
        user = request.user
        
        if not user.is_authenticated:
            return Response(
                {'error': 'Authentication failed'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get trial status
        trial_status = get_trial_status(user)
        
        # Log successful login
        log_login_attempt(request, user.email, success=True)
        
        # Generate or get auth token
        from rest_framework.authtoken.models import Token
        token, created = Token.objects.get_or_create(user=user)
        
        response_data = {
            'user': {
                'id': str(user.id),
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role,
                'is_verified': user.is_verified,
                'is_super_admin': user.is_super_admin,
            },
            'token': token.key,
            'trial_status': trial_status,
        }
        
        # Add restaurant info if available
        if user.restaurant:
            response_data['restaurant'] = {
                'id': user.restaurant.id,
                'name': user.restaurant.name,
                'slug': user.restaurant.slug,
                'subscription_status': user.restaurant.subscription_status,
            }
        
        return Response(response_data)
    
    except Exception as e:
        logger.error(f"Error in Google auth callback: {e}")
        log_login_attempt(request, 'unknown', success=False)
        return Response(
            {'error': 'Authentication failed'},
            status=status.HTTP_400_BAD_REQUEST
        )

@api_view(['POST'])
@permission_classes([AllowAny])
def google_auth_token(request):
    """Handle Google OAuth token exchange (alternative flow)"""
    try:
        code = request.data.get('code')
        if not code:
            return Response(
                {'error': 'Authorization code is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # This would typically involve exchanging the code for tokens
        # For now, we'll use the PSA flow
        return Response(
            {'error': 'Token exchange not implemented yet. Use URL flow instead.'},
            status=status.HTTP_501_NOT_IMPLEMENTED
        )
    
    except Exception as e:
        logger.error(f"Error in Google auth token exchange: {e}")
        return Response(
            {'error': 'Token exchange failed'},
            status=status.HTTP_400_BAD_REQUEST
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def trial_status(request):
    """Get trial status for the current user"""
    try:
        trial_status = get_trial_status(request.user)
        
        if not trial_status:
            return Response(
                {'error': 'No trial found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response(trial_status)
    
    except Exception as e:
        logger.error(f"Error getting trial status: {e}")
        return Response(
            {'error': 'Failed to get trial status'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def extend_trial(request):
    """Extend trial (admin only)"""
    try:
        # Only super admins can extend trials
        if not request.user.is_super_admin:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        days = request.data.get('days', 7)
        user_id = request.data.get('user_id')
        
        if not user_id:
            return Response(
                {'error': 'User ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        from cafe.models import User
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        from cafe.social_auth import extend_trial
        success, message = extend_trial(target_user, days)
        
        if success:
            return Response({
                'success': True,
                'message': message,
                'trial_status': get_trial_status(target_user)
            })
        else:
            return Response(
                {'error': message},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    except Exception as e:
        logger.error(f"Error extending trial: {e}")
        return Response(
            {'error': 'Failed to extend trial'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_user(request):
    """Logout user and invalidate token"""
    try:
        # Invalidate the token
        from rest_framework.authtoken.models import Token
        try:
            token = Token.objects.get(user=request.user)
            token.delete()
        except Token.DoesNotExist:
            pass
        
        # Log the logout
        logout(request)
        
        return Response({
            'success': True,
            'message': 'Logged out successfully'
        })
    
    except Exception as e:
        logger.error(f"Error during logout: {e}")
        return Response(
            {'error': 'Logout failed'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_expired_trials(request):
    """Check and expire trial subscriptions (admin only)"""
    try:
        if not request.user.is_super_admin:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        expired_count = check_trial_expiry()
        
        return Response({
            'expired_count': expired_count,
            'message': f'Expired {expired_count} trial subscriptions'
        })
    
    except Exception as e:
        logger.error(f"Error checking expired trials: {e}")
        return Response(
            {'error': 'Failed to check expired trials'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
