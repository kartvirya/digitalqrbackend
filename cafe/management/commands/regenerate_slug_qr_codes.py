from django.core.management.base import BaseCommand
from django.db import transaction
from cafe.models import Table, Room, Restaurant
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Regenerate QR codes for all tables and rooms with new slug-based URL format'

    def add_arguments(self, parser):
        parser.add_argument(
            '--restaurant-slug',
            type=str,
            help='Only regenerate QR codes for a specific restaurant (by slug)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be regenerated without actually doing it',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force regeneration even if QR codes already exist',
        )

    def handle(self, *args, **options):
        self.stdout.write('🔄 Regenerating QR codes with new slug-based URL format...')
        
        restaurant_slug = options.get('restaurant_slug')
        dry_run = options.get('dry_run', False)
        force = options.get('force', False)
        
        # Get restaurants to process
        if restaurant_slug:
            try:
                restaurants = [Restaurant.objects.get(slug=restaurant_slug, is_active=True)]
                self.stdout.write(f"📍 Processing restaurant: {restaurant_slug}")
            except Restaurant.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"❌ Restaurant with slug '{restaurant_slug}' not found")
                )
                return
        else:
            restaurants = Restaurant.objects.filter(is_active=True)
            self.stdout.write(f"📍 Processing {restaurants.count()} active restaurants")
        
        total_tables = 0
        total_rooms = 0
        total_regenerated = 0
        
        for restaurant in restaurants:
            self.stdout.write(f"\n🏪 Processing restaurant: {restaurant.name} ({restaurant.slug})")
            
            # Process tables
            tables = restaurant.tables.all()
            table_count = 0
            table_regenerated = 0
            
            for table in tables:
                total_tables += 1
                table_count += 1
                
                if not force and table.qr_code:
                    self.stdout.write(f"  ⏭️  Table {table.table_number}: QR code already exists (use --force to regenerate)")
                    continue
                
                if dry_run:
                    self.stdout.write(f"  🔄 Table {table.table_number}: Would regenerate QR code")
                    table_regenerated += 1
                else:
                    try:
                        # Delete existing QR code if it exists
                        if table.qr_code:
                            table.qr_code.delete()
                        
                        # Generate new QR code with slug-based URL
                        table.generate_qr_code()
                        
                        # Construct the new URL for verification
                        new_url = f"{table.qr_code.url if table.qr_code else 'N/A'}"
                        expected_url = f"qr_codes/table_{restaurant.slug}_{table.table_number}_qr.png"
                        
                        self.stdout.write(f"  ✅ Table {table.table_number}: QR code regenerated")
                        self.stdout.write(f"     📁 New file: {expected_url}")
                        table_regenerated += 1
                        total_regenerated += 1
                        
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f"  ❌ Table {table.table_number}: Error - {e}")
                        )
            
            # Process rooms
            rooms = restaurant.rooms.all()
            room_count = 0
            room_regenerated = 0
            
            for room in rooms:
                total_rooms += 1
                room_count += 1
                
                if not force and room.qr_code:
                    self.stdout.write(f"  ⏭️  Room {room.room_number}: QR code already exists (use --force to regenerate)")
                    continue
                
                if dry_run:
                    self.stdout.write(f"  🔄 Room {room.room_number}: Would regenerate QR code")
                    room_regenerated += 1
                else:
                    try:
                        # Delete existing QR code if it exists
                        if room.qr_code:
                            room.qr_code.delete()
                        
                        # Generate new QR code with slug-based URL
                        room.generate_qr_code()
                        
                        # Construct the new URL for verification
                        expected_url = f"room_qr_codes/room_{restaurant.slug}_{room.room_number}_qr.png"
                        
                        self.stdout.write(f"  ✅ Room {room.room_number}: QR code regenerated")
                        self.stdout.write(f"     📁 New file: {expected_url}")
                        room_regenerated += 1
                        total_regenerated += 1
                        
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f"  ❌ Room {room.room_number}: Error - {e}")
                        )
            
            # Summary for this restaurant
            self.stdout.write(f"  📊 {restaurant.name} summary:")
            self.stdout.write(f"     Tables: {table_regenerated}/{table_count} regenerated")
            self.stdout.write(f"     Rooms: {room_regenerated}/{room_count} regenerated")
        
        # Final summary
        self.stdout.write(f"\n🎉 Overall Summary:")
        self.stdout.write(f"   📱 Total tables processed: {total_tables}")
        self.stdout.write(f"   🏨 Total rooms processed: {total_rooms}")
        self.stdout.write(f"   🔄 Total QR codes regenerated: {total_regenerated}")
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING("\n⚠️  This was a dry run. Use without --dry-run to actually regenerate QR codes.")
            )
        elif total_regenerated > 0:
            self.stdout.write(
                self.style.SUCCESS(f"\n✅ Successfully regenerated {total_regenerated} QR codes!")
            )
        else:
            self.stdout.write(
                self.style.WARNING("\n⚠️  No QR codes were regenerated. Use --force to override existing codes.")
            )
        
        # URL format examples
        self.stdout.write(f"\n📋 New URL Format Examples:")
        self.stdout.write(f"   Table QR: https://yourapp.com/{restaurant.slug}/?table=UNIQUE_ID")
        self.stdout.write(f"   Room QR:  https://yourapp.com/{restaurant.slug}/?room=UNIQUE_ID")
