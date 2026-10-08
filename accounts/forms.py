from django import forms
from django.contrib.auth.models import User
from core.utils import normalize_phone
from partners.forms import WhatsAppPreferencesMixin
from partners.models import PartnerProfile
import re

class PartnerRegistrationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm Password'}))
    company_name = forms.CharField(max_length=200, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Company Name'}))
    phone_number = forms.CharField(max_length=20, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number'}))

    class Meta:
        model = User
        fields = ['username', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email Address'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not email:
            raise forms.ValidationError("Email address is required.")
        email = email.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email address already exists.")
        return email

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        cleaned_number = re.sub(r'[\s\-\+]', '', phone or '')
        if not cleaned_number.isdigit():
            raise forms.ValidationError("Phone number can only contain digits, spaces, -, or +.")
        if len(cleaned_number) < 10 or len(cleaned_number) > 15:
            raise forms.ValidationError("Phone number must be between 10 and 15 digits.")
        if PartnerProfile.objects.filter(phone_number=phone).exists() or PartnerProfile.objects.filter(phone_number=cleaned_number).exists():
            raise forms.ValidationError("A partner with this phone number already exists.")
        return phone

    def clean_company_name(self):
        name = self.cleaned_data.get('company_name')
        if not re.search(r'[a-zA-Z]', name or ''):
            raise forms.ValidationError("Company name must contain alphabets.")
        return name

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password != confirm_password:
            raise forms.ValidationError("Passwords do not match!")
        return cleaned_data

class PartnerProfileUpdateForm(WhatsAppPreferencesMixin, forms.ModelForm):
    class Meta:
        model = PartnerProfile
        fields = [
            'company_name', 'phone_number', 'address',
            'whatsapp_number', 'whatsapp_opt_in', 'notify_email', 'notify_whatsapp',
        ]
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'whatsapp_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+919876543210',
            }),
            'whatsapp_opt_in': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_email': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_whatsapp': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'whatsapp_number': 'WhatsApp number',
            'whatsapp_opt_in': 'I agree to receive WhatsApp notifications',
            'notify_email': 'Notify me by email',
            'notify_whatsapp': 'Notify me by WhatsApp',
        }
        help_texts = {
            'whatsapp_number': 'Include country code, e.g. +919876543210.',
            'whatsapp_opt_in': 'Consent is required before any WhatsApp message is sent.',
        }

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        cleaned_number = re.sub(r'[\s\-\+]', '', phone or '')
        if not cleaned_number.isdigit():
            raise forms.ValidationError("Phone number can only contain digits, spaces, -, or +.")
        if len(cleaned_number) < 10 or len(cleaned_number) > 15:
            raise forms.ValidationError("Phone number must be between 10 and 15 digits.")
        # If changed, check uniqueness without crashing on existing DB duplicates
        if self.instance and self.instance.pk and self.instance.phone_number != phone:
            if PartnerProfile.objects.filter(phone_number=phone).exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("A partner with this phone number already exists.")
        return phone

    def clean_company_name(self):
        name = self.cleaned_data.get('company_name')
        if not re.search(r'[a-zA-Z]', name or ''):
            raise forms.ValidationError("Company name must contain alphabets.")
        return name

class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['email']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not email:
            raise forms.ValidationError("Email address is required.")
        email = email.strip().lower()
        if self.instance and self.instance.pk and (self.instance.email or '').strip().lower() != email:
            if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("A user with this email address already exists.")
        return email
