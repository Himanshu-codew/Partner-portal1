from django import forms
from django.contrib.auth.models import User, Group
from .models import PartnerProfile

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
        
    def save(self, commit=True):
        user = super().save(commit=False)
        # Only set the password if a new one was provided
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
            self.save_m2m() # Required when saving a modelform with many-to-many fields (groups)
        return user

class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name', 'permissions']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'permissions': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 15}),
        }

class PartnerProfileForm(forms.ModelForm):
    class Meta:
        model = PartnerProfile
        fields = ['user', 'company_name', 'phone_number', 'address', 'is_approved']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-select'}),
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_approved': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        import re
        cleaned_number = re.sub(r'[\s\-\+]', '', phone)
        if not cleaned_number.isdigit():
            raise forms.ValidationError("Phone number can only contain digits, spaces, -, or +.")
        if len(cleaned_number) < 10 or len(cleaned_number) > 15:
            raise forms.ValidationError("Phone number must be between 10 and 15 digits.")
        return phone

    def clean_company_name(self):
        name = self.cleaned_data.get('company_name')
        import re
        if not re.search(r'[a-zA-Z]', name):
            raise forms.ValidationError("Company name must contain alphabets.")
        return name
