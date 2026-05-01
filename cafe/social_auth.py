from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from social_core.pipeline.partial import partial
from social_core.exceptions import AuthException
from cafe.models import User, Restaurant, RestaurantSubscription
from cafe.utils.audit_logging import AuditLogger
import logging

logger = logging.getLogger(__name__)

@partial
def create_user_from_google(strategy, details, response, *args, **kwargs):
    """Create user from Google OAuth data"""
    
    # Check if user already exists
    email = details.get('email')
    google_id = response.get('sub')
    
    if not email:
        raise AuthException('Email is required from Google OAuth')
    
    # Check if user exists with this email
    try:
        user = User.objects.get(email=email)
        logger.info(f"User {email} already exists, linking Google account")
        return {'user': user}
    except User.DoesNotExist:
        pass
    
    # Check if user exists with this Google ID
    try:
        user = User.objects.get(google_sub=google_id)
        logger.info(f"User with Google ID {google_id} already exists")
        return {'user': user}
    except User.DoesNotExist:
        pass
    
    # Create new user
    try:
        with transaction.atomic():
            # Generate a unique username from email
            username = email.split('@')[0]
            base_username = username
            counter = 1
            
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1
            
            user = User.objects.create(
                username=username,
                email=email,
                first_name=details.get('given_name', ''),
                last_name=details.get('family_name', ''),
                google_email=email,
                google_sub=google_id,
                is_active=True,
                is_verified=True,  # Google accounts are pre-verified
                role='customer',  # Default role for new users
            )
            
            logger.info(f"Created new user {email} from Google OAuth")
            
            return {'user': user}
    
    except Exception as e:
        logger.error(f"Error creating user from Google OAuth: {e}")
        raise AuthException(f'Failed to create user: {str(e)}')

@partial
def create_trial_subscription(strategy, details, user, *args, **kwargs):
    """Create trial subscription for new users"""
    
    # Only create trial for new users without existing restaurants
    if Restaurant.objects.filter(admin=user).exists():
        logger.info(f"User {user.email} already has restaurants, skipping trial creation")
        return {}
    
    try:
        with transaction.atomic():
            # Create a default restaurant for the trial user
            restaurant = Restaurant.objects.create(
                name=f"{user.first_name or user.username}'s Restaurant",
                slug=f"{user.username.lower()}-restaurant",
                email=user.email,
                phone='',  # Can be filled later
                address='',  # Can be filled later
                is_active=True,
                subscription_status='trial',
            )
            
            # Link user to the restaurant
            user.restaurant = restaurant
            user.role = 'owner'  # Make them the owner
            user.save()
            
            # Create trial subscription
            trial_end_date = timezone.now() + timedelta(days=7)
            subscription = RestaurantSubscription.objects.create(
                restaurant=restaurant,
                plan_type='trial',
                status='active',
                trial_start_date=timezone.now(),
                trial_end_date=trial_end_date,
                auto_renew=False,  # Trial doesn't auto-renew
                billing_cycle='monthly',
                price=0,  # Free trial
            )
            
            logger.info(f"Created trial subscription for user {user.email}, restaurant {restaurant.name}")
            
            # Log the trial creation
            from django.http import HttpRequest
            request = strategy.request if hasattr(strategy, 'request') else None
            if request:
                AuditLogger.log_action(
                    request=request,
                    action_type='CREATE',
                    description=f"Trial subscription created for {restaurant.name}",
                    object_type='RestaurantSubscription',
                    object_id=subscription.id,
                    object_repr=str(restaurant),
                    additional_data={
                        'trial_end_date': trial_end_date.isoformat(),
                        'plan_type': 'trial',
                    }
                )
            
            return {
                'restaurant': restaurant,
                'subscription': subscription,
            }
    
    except Exception as e:
        logger.error(f"Error creating trial subscription: {e}")
        # Don't raise exception here, as it would prevent login
        # Just log the error and continue
        return {}

def check_trial_expiry():
    """Check and expire trial subscriptions"""
    from django.core.management.base import BaseCommand
    from django.utils import timezone
    
    expired_trials = RestaurantSubscription.objects.filter(
        plan_type='trial',
        status='active',
        trial_end_date__lt=timezone.now()
    )
    
    for subscription in expired_trials:
        with transaction.atomic():
            # Update subscription status
            subscription.status = 'expired'
            subscription.save()
            
            # Update restaurant status
            restaurant = subscription.restaurant
            restaurant.subscription_status = 'expired'
            restaurant.save()
            
            # Log the expiration
            logger.info(f"Trial expired for restaurant {restaurant.name}")
            
            # Create audit log
            try:
                from django.http import HttpRequest
                AuditLogger.log_action(
                    request=HttpRequest(),  # System action
                    action_type='SYSTEM_CONFIG',
                    description=f"Trial subscription expired for {restaurant.name}",
                    object_type='RestaurantSubscription',
                    object_id=subscription.id,
                    object_repr=str(restaurant),
                    additional_data={
                        'trial_end_date': subscription.trial_end_date.isoformat(),
                        'expired_date': timezone.now().isoformat(),
                    }
                )
            except Exception as e:
                logger.error(f"Error creating audit log for trial expiration: {e}")
    
    return expired_trials.count()

def get_trial_status(user):
    """Get trial status for a user"""
    try:
        if not user.restaurant:
            return None
        
        subscription = RestaurantSubscription.objects.filter(
            restaurant=user.restaurant,
            plan_type='trial'
        ).first()
        
        if not subscription:
            return None
        
        if subscription.status != 'active':
            return {
                'status': subscription.status,
                'trial_end_date': subscription.trial_end_date,
                'days_remaining': 0,
            }
        
        days_remaining = (subscription.trial_end_date - timezone.now()).days
        
        return {
            'status': 'active',
            'trial_end_date': subscription.trial_end_date,
            'days_remaining': max(0, days_remaining),
        }
    
    except Exception as e:
        logger.error(f"Error getting trial status: {e}")
        return None

def extend_trial(user, days=7):
    """Extend trial for a user (admin function)"""
    try:
        if not user.restaurant:
            return False, "User has no restaurant"
        
        subscription = RestaurantSubscription.objects.filter(
            restaurant=user.restaurant,
            plan_type='trial'
        ).first()
        
        if not subscription:
            return False, "No trial subscription found"
        
        if subscription.status != 'active':
            return False, "Trial is not active"
        
        # Extend trial
        subscription.trial_end_date = timezone.now() + timedelta(days=days)
        subscription.save()
        
        logger.info(f"Extended trial for {user.restaurant.name} by {days} days")
        
        return True, f"Trial extended by {days} days"
    
    except Exception as e:
        logger.error(f"Error extending trial: {e}")
        return False, str(e)
