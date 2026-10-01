from django.core.management.base import BaseCommand
from django.utils import timezone
import datetime
from core.views import get_soft_deleted_models

class Command(BaseCommand):
    help = "Permanently deletes items from the recycle bin older than N days."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30, help='Number of days to keep deleted items')

    def handle(self, *args, **options):
        days = options['days']
        cutoff = timezone.now() - datetime.timedelta(days=days)
        total_deleted = 0
        
        models_map = get_soft_deleted_models()
        for name, model in models_map.items():
            qs = model.deleted_objects.filter(deleted_at__lt=cutoff)
            count = qs.count()
            if count > 0:
                for item in qs:
                    item.hard_delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted {count} old {model._meta.verbose_name_plural}"))
                total_deleted += count
                
        self.stdout.write(self.style.SUCCESS(f"Purge complete. Total items deleted: {total_deleted}"))
