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

class AdminLeadForm(LeadForm):
    class Meta(LeadForm.Meta):
        fields = ['partner', 'customer_name', 'customer_phone', 'product_interest', 'notes']
        widgets = {
            **LeadForm.Meta.widgets,
            'partner': forms.Select(attrs={'class': 'form-select'}),
        }
