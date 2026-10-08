from django import forms
from django.contrib.auth.models import User, Group
from django.core.exceptions import ValidationError
from django.utils import timezone
from core.utils import normalize_phone
from .models import PartnerProfile, PartnerDocument
import os
import re

ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}
MAX_DOCUMENT_SIZE = 5 * 1024 * 1024  # 5 MB


class WhatsAppPreferencesMixin:
    """
    Shared validation for the WhatsApp contact / notification preference
    fields on PartnerProfile. Normalizes the number to E.164, requires a
    valid number when the partner opts in, and stamps whatsapp_opt_in_at
    whenever consent is (re)given.
    """

    def clean_whatsapp_number(self):
        raw = self.cleaned_data.get('whatsapp_number')
        if raw is None or not str(raw).strip():
            return ''
        try:
            normalized = normalize_phone(raw)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)
        # Form-level unique validation (no DB constraint; legacy rows may
        # hold unnormalized duplicates, so only compare normalized values).
        matches = PartnerProfile.objects.filter(whatsapp_number=normalized)
        if getattr(self.instance, 'pk', None):
            matches = matches.exclude(pk=self.instance.pk)
        if matches.exists():
            raise forms.ValidationError("A partner with this WhatsApp number already exists.")
        return normalized

    def clean(self):
        cleaned_data = super().clean()
        if 'whatsapp_opt_in' in cleaned_data:
            opt_in = bool(cleaned_data.get('whatsapp_opt_in'))
            number = cleaned_data.get('whatsapp_number') or ''
            if opt_in and not number:
                self.add_error(
                    'whatsapp_number',
                    "Enter a WhatsApp number to receive WhatsApp notifications, or untick the option."
                )
            # Stamp / clear consent time directly on the instance so it is
            # persisted regardless of how the form is saved.
            if opt_in and number and not self.instance.whatsapp_opt_in_at:
                self.instance.whatsapp_opt_in_at = timezone.now()
            elif not opt_in:
                self.instance.whatsapp_opt_in_at = None
        return cleaned_data


class UserForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Leave blank to keep current password'}),
        required=False,
        help_text="Leave blank if you don't want to change the password."
    )
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'groups', 'is_staff', 'is_superuser', 'is_active']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'groups': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 5}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_superuser': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, current_user=None, **kwargs):
        self.current_user = current_user
        super().__init__(*args, **kwargs)
        # Rule 3.1: Only superusers may see or change is_superuser and is_staff
        if not (self.current_user and self.current_user.is_superuser):
            if 'is_staff' in self.fields:
                self.fields['is_staff'].disabled = True
            if 'is_superuser' in self.fields:
                self.fields['is_superuser'].disabled = True

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not email:
            raise forms.ValidationError("Email address is required.")
        email = email.strip().lower()
        # Form-level unique validation, safe against existing DB duplicates
        if self.instance and self.instance.pk and (self.instance.email or '').strip().lower() != email:
            if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("A user with this email address already exists.")
        elif not self.instance.pk:
            if User.objects.filter(email__iexact=email).exists():
                raise forms.ValidationError("A user with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        instance = getattr(self, 'instance', None)

        # Rule 3.1: For non-superuser staff, ignore is_staff and is_superuser if posted
        if not (self.current_user and self.current_user.is_superuser):
            if instance and instance.pk:
                cleaned_data['is_staff'] = instance.is_staff
                cleaned_data['is_superuser'] = instance.is_superuser
            else:
                cleaned_data['is_staff'] = False
                cleaned_data['is_superuser'] = False

        # Rule 3.3: Nobody can deactivate their own account from the Users page
        if instance and instance.pk and self.current_user and instance.pk == self.current_user.pk:
            if cleaned_data.get('is_active') is False:
                self.add_error('is_active', "You cannot deactivate your own account.")

        # Rule 3.3: The last remaining active superuser can never be demoted or deactivated
        if instance and instance.pk and instance.is_superuser and instance.is_active:
            other_active_superusers = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=instance.pk)
            if not other_active_superusers.exists():
                if cleaned_data.get('is_superuser') is False:
                    self.add_error('is_superuser', "The last remaining active superuser cannot be demoted.")
                if cleaned_data.get('is_active') is False:
                    self.add_error('is_active', "The last remaining active superuser cannot be deactivated.")

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        # Ensure non-superusers cannot set or alter is_staff/is_superuser
        if not (self.current_user and self.current_user.is_superuser):
            if self.instance and self.instance.pk:
                orig = User.objects.get(pk=self.instance.pk)
                user.is_staff = orig.is_staff
                user.is_superuser = orig.is_superuser
            else:
                user.is_staff = False
                user.is_superuser = False

        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
            self.save_m2m()
        return user


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name', 'permissions']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'permissions': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 15}),
        }


class PartnerProfileForm(WhatsAppPreferencesMixin, forms.ModelForm):
    class Meta:
        model = PartnerProfile
        fields = [
            'user', 'company_name', 'phone_number', 'address', 'is_approved',
            'whatsapp_number', 'whatsapp_opt_in', 'notify_email', 'notify_whatsapp',
        ]
        widgets = {
            'user': forms.Select(attrs={'class': 'form-select'}),
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_approved': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'whatsapp_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+919876543210',
            }),
            'whatsapp_opt_in': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_email': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_whatsapp': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'whatsapp_opt_in': 'Opt in to WhatsApp notifications',
            'notify_email': 'Send notifications by email',
            'notify_whatsapp': 'Send notifications by WhatsApp',
        }

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        cleaned_number = re.sub(r'[\s\-\+]', '', phone or '')
        if not cleaned_number.isdigit():
            raise forms.ValidationError("Phone number can only contain digits, spaces, -, or +.")
        if len(cleaned_number) < 10 or len(cleaned_number) > 15:
            raise forms.ValidationError("Phone number must be between 10 and 15 digits.")
        # Form-level unique validation without crashing if existing DB has duplicates
        if self.instance and self.instance.pk and self.instance.phone_number != phone:
            if PartnerProfile.objects.filter(phone_number=phone).exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("A partner with this phone number already exists.")
        elif not getattr(self.instance, 'pk', None):
            if PartnerProfile.objects.filter(phone_number=phone).exists():
                raise forms.ValidationError("A partner with this phone number already exists.")
        return phone

    def clean_company_name(self):
        name = self.cleaned_data.get('company_name')
        if not re.search(r'[a-zA-Z]', name or ''):
            raise forms.ValidationError("Company name must contain alphabets.")
        return name


class PartnerDocumentForm(forms.ModelForm):
    """Upload form for partner KYC / invoice documents (Phase 3)."""

    class Meta:
        model = PartnerDocument
        fields = ['doc_type', 'file']
        widgets = {
            'doc_type': forms.Select(attrs={'class': 'form-select'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def clean_file(self):
        uploaded = self.cleaned_data.get('file')
        if not uploaded:
            return uploaded

        if hasattr(uploaded, 'size') and uploaded.size > MAX_DOCUMENT_SIZE:
            size_mb = uploaded.size / (1024 * 1024)
            raise forms.ValidationError(
                f"File size exceeds the 5 MB limit (uploaded file is {size_mb:.1f} MB)."
            )

        _, ext = os.path.splitext(getattr(uploaded, 'name', ''))
        clean_ext = ext.lstrip('.').lower()
        if clean_ext not in ALLOWED_DOCUMENT_EXTENSIONS:
            allowed_list = ', '.join(sorted(ALLOWED_DOCUMENT_EXTENSIONS))
            raise forms.ValidationError(
                f"File type '.{clean_ext}' is not permitted. Allowed extensions are: {allowed_list}."
            )
        return uploaded
