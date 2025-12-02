from django.core.management.base import BaseCommand
from cafe.models import Table, Room


class Command(BaseCommand):
    help = 'Regenerate QR codes for all tables and rooms with correct frontend URL'

    def handle(self, *args, **options):
        self.stdout.write('🔄 Regenerating QR codes...')
        
        # Regenerate table QR codes
        tables = Table.objects.all()
        for table in tables:
            try:
                # Delete existing QR code
                if table.qr_code:
                    table.qr_code.delete()
                # Generate new QR code
                table.generate_qr_code()
                self.stdout.write(f'✅ Table {table.table_number}: QR code regenerated')
            except Exception as e:
                self.stdout.write(f'❌ Table {table.table_number}: Error - {e}')
        
        # Regenerate room QR codes
        rooms = Room.objects.all()
        for room in rooms:
            try:
                # Delete existing QR code
                if room.qr_code:
                    room.qr_code.delete()
                # Generate new QR code
                room.generate_qr_code()
                self.stdout.write(f'✅ Room {room.room_number}: QR code regenerated')
            except Exception as e:
                self.stdout.write(f'❌ Room {room.room_number}: Error - {e}')
        
        self.stdout.write(self.style.SUCCESS('🎉 QR code regeneration completed!'))
        from django.conf import settings
        self.stdout.write(f'📱 Frontend URL: {settings.FRONTEND_URL}')
