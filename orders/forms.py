from django import forms
from .models import Order

class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['partner', 'lead', 'order_number', 'amount', 'commission_amount', 'status', 'is_commission_paid']
        widgets = {
            'partner': forms.Select(attrs={'class': 'form-select'}),
            'lead': forms.Select(attrs={'class': 'form-select'}),
            'order_number': forms.TextInput(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'commission_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'is_commission_paid': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        amount = cleaned_data.get('amount')
        commission_amount = cleaned_data.get('commission_amount')
        
        if commission_amount is not None:
            if commission_amount < 0:
                self.add_error('commission_amount', "Commission amount cannot be negative.")
            if amount is not None and commission_amount > amount:
                self.add_error('commission_amount', "Commission amount cannot exceed the order amount.")
                
        return cleaned_data
