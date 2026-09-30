from django import forms
from .models import Lead

class LeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = ['customer_name', 'customer_phone', 'product_interest', 'notes']
        widgets = {
            'customer_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full Name'}),
            'customer_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number'}),
            'product_interest': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Website Development, SEO'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Any additional details...'}),
        }

    def clean_customer_phone(self):
        phone = self.cleaned_data.get('customer_phone')
        import re
        # Remove spaces, dashes, and plus signs to count actual digits
        cleaned_number = re.sub(r'[\s\-\+]', '', phone)
        if not cleaned_number.isdigit():
            raise forms.ValidationError("Phone number can only contain digits, spaces, -, or +.")
        if len(cleaned_number) < 10 or len(cleaned_number) > 15:
            raise forms.ValidationError("Phone number must be between 10 and 15 digits.")
        return phone

    def clean_customer_name(self):
        name = self.cleaned_data.get('customer_name')
        import re
        if not re.search(r'[a-zA-Z]', name):
            raise forms.ValidationError("Name must contain alphabets (cannot be just numbers or symbols).")
        return name

    def clean_product_interest(self):
        interest = self.cleaned_data.get('product_interest')
        import re
        if interest and not re.search(r'[a-zA-Z]', interest):
            raise forms.ValidationError("Product interest must contain alphabets (cannot be just numbers).")
        return interest

class AdminLeadForm(LeadForm):
    class Meta(LeadForm.Meta):
        fields = ['partner', 'customer_name', 'customer_phone', 'product_interest', 'notes']
        widgets = {
            **LeadForm.Meta.widgets,
            'partner': forms.Select(attrs={'class': 'form-select'}),
        }
