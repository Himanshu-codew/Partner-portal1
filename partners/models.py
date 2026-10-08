import os

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_delete
from django.dispatch import receiver

from core.models import SoftDeleteModel
from core.storage import DatabaseFileStorage

class PartnerProfile(SoftDeleteModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='partner_profile')
    company_name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=20)
    address = models.TextField(blank=True, null=True)
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # Contact & notification preferences (Phase 2A)
    whatsapp_number = models.CharField(
        max_length=20, blank=True, default='',
        help_text='WhatsApp number in E.164 format, e.g. +919876543210.'
    )
    whatsapp_opt_in = models.BooleanField(default=False)
    whatsapp_opt_in_at = models.DateTimeField(null=True, blank=True)
    notify_email = models.BooleanField(default=True)
    notify_whatsapp = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.company_name}"


class PartnerDocument(SoftDeleteModel):
    """A partner-uploaded KYC / invoice file with OCR suggestions (Phase 3).

    OCR output and ``extracted`` values are read-only SUGGESTIONS for the
    reviewer — they are never written back into any business record. Aadhaar
    numbers are masked out of ``ocr_text`` before it is stored.
    """

    DOC_TYPE_CHOICES = [
        ('PAN', 'PAN card'),
        ('GST', 'GST certificate'),
        ('BANK', 'Bank account proof'),
        ('INVOICE', 'Invoice'),
        ('OTHER', 'Other'),
    ]
    OCR_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ]
    REVIEW_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    partner = models.ForeignKey(
        PartnerProfile, on_delete=models.CASCADE, related_name='kyc_documents'
    )
    doc_type = models.CharField(max_length=10, choices=DOC_TYPE_CHOICES, default='OTHER')
    file = models.FileField(upload_to='kyc/', storage=DatabaseFileStorage)

    ocr_status = models.CharField(
        max_length=10, choices=OCR_STATUS_CHOICES, default='pending'
    )
    ocr_text = models.TextField(blank=True, default='')
    extracted = models.JSONField(default=dict, blank=True)
    ocr_error = models.CharField(max_length=200, blank=True, default='')

    review_status = models.CharField(
        max_length=10, choices=REVIEW_STATUS_CHOICES, default='pending'
    )
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, default='')

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.partner.company_name} - {self.get_doc_type_display()}'

    @property
    def file_exists(self):
        """True only if the file field is set AND the file is actually stored."""
        if not self.file:
            return False
        try:
            return self.file.storage.exists(self.file.name)
        except Exception:
            return False

    @property
    def file_extension(self):
        """Lowercase extension without dot, or '' if no file."""
        if not self.file or not self.file.name:
            return ''
        try:
            import os
            _, ext = os.path.splitext(self.file.name)
            return ext.lstrip('.').lower()
        except Exception:
            return ''

    @property
    def file_size_display(self):
        """Human-readable file size, or '—' if the file is missing/unreadable."""
        if not self.file:
            return '\u2014'
        try:
            size = self.file.size
            if size < 1024:
                return f'{size} B'
            elif size < 1024 ** 2:
                return f'{size / 1024:.1f} KB'
            elif size < 1024 ** 3:
                return f'{size / 1024 ** 2:.1f} MB'
            else:
                return f'{size / 1024 ** 3:.2f} GB'
        except (FileNotFoundError, ValueError, OSError):
            return '\u2014'

    @property
    def preview_kind(self):
        """What the staff detail page can render: 'image', 'pdf' or 'file'."""
        if self.file_extension in ('png', 'jpg', 'jpeg', 'gif', 'webp'):
            return 'image'
        if self.file_extension == 'pdf':
            return 'pdf'
        return 'file'


@receiver(post_delete, sender=PartnerDocument)
def delete_partner_document_file_bytes(sender, instance, **kwargs):
    """Drop the stored bytes only on hard delete (never on soft delete)."""
    try:
        instance.file.delete(save=False)
    except Exception:
        pass
