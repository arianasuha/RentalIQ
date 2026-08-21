# app/management/commands/purge_deleted_data.py
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from core_db.models import Equipment, User

class Command(BaseCommand):
    help = "Permanently purges soft-deleted records past the retention period."

    def handle(self, *args, **options):
        # Retention threshold: 90 days
        cutoff = timezone.now() - timedelta(days=90)

        # 1. Purge Equipment soft-deleted over 90 days ago
        deleted_equipment = Equipment.all_objects.filter(
            is_deleted=True, 
            deleted_at__lt=cutoff
        )
        eq_count = deleted_equipment.count()
        deleted_equipment.delete()  # Hard delete from SQL

        self.stdout.write(self.style.SUCCESS(f"Successfully purged {eq_count} old equipment records."))