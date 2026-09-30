from django import forms
from .models import Order

class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['partner', 'lead', 'order_number', 'amount', 'commission_amount', 'status']
        widgets = {
            'partner': forms.Select(attrs={'class': 'form-select'}),
            'lead': forms.Select(attrs={'class': 'form-select'}),
            'order_number': forms.TextInput(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'commission_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }
