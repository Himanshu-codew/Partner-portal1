from core.models import SoftDeleteModel
from django.db import models

class Announcement(SoftDeleteModel):
    title = models.CharField(max_length=200)
    content = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # If empty → visible to ALL approved partners. If set → only selected partners.
    visible_to = models.ManyToManyField(
        'partners.PartnerProfile',
        blank=True,
        related_name='announcements',
        help_text='Leave empty to show to ALL partners. Select specific partners to make it private.'
    )

    def __str__(self):
        return self.title

class Document(SoftDeleteModel):
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    # If empty → visible to ALL approved partners. If set → only selected partners.
    visible_to = models.ManyToManyField(
        'partners.PartnerProfile',
        blank=True,
        related_name='documents',
        help_text='Leave empty to show to ALL partners. Select specific partners to make it private.'
    )

    def __str__(self):
        return self.title
