from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User


class UserNotificationRead(models.Model):
    """Tracks when a user last read their notifications."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_read')
    last_read_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.user.username} last read at {self.last_read_at}"


class StoredFile(models.Model):
    """A file's bytes, kept in the database so uploads survive redeploys."""
    name = models.CharField(max_length=255, unique=True)
    content = models.BinaryField()
    content_type = models.CharField(max_length=255, blank=True, default='')
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class NotificationLog(models.Model):
    """One delivery attempt of a notification, per channel."""

    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_SKIPPED = 'skipped'
    STATUS_CHOICES = (
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SKIPPED, 'Skipped'),
    )
    CHANNEL_EMAIL = 'email'
    CHANNEL_WHATSAPP = 'whatsapp'
    CHANNEL_CHOICES = (
        (CHANNEL_EMAIL, 'Email'),
        (CHANNEL_WHATSAPP, 'WhatsApp'),
    )

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notification_logs'
    )
    event = models.CharField(max_length=50)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    # Short, redacted reason — never store raw exception payloads here.
    error = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.event} / {self.channel}: {self.status}"


class SoftDeleteQuerySet(models.QuerySet):
    def delete(self, user=None):
        return super().update(is_deleted=True, deleted_at=timezone.now(), deleted_by=user)

    def hard_delete(self):
        return super().delete()

    def restore(self):
        return super().update(is_deleted=False, deleted_at=None, deleted_by=None)

class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)

class AllObjectsManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)

class DeletedObjectsManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=True)

class SoftDeleteModel(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()
    deleted_objects = DeletedObjectsManager()

    class Meta:
        abstract = True

    def soft_delete(self, user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def delete(self, *args, **kwargs):
        # Prevent standard delete entirely unless hard_delete is specifically required?
        # Actually, let's keep soft_delete explicit. If django admin or something calls .delete()
        # on the instance, maybe we want it to soft delete.
        self.soft_delete()
    
    def hard_delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
