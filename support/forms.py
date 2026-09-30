from django import forms
from .models import Ticket

class TicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ['subject', 'description']
        widgets = {
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'What is the issue about?'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Please describe your issue or question in detail...'}),
        }

class AdminTicketForm(TicketForm):
    class Meta(TicketForm.Meta):
        fields = ['partner', 'subject', 'description']
        widgets = {
            **TicketForm.Meta.widgets,
            'partner': forms.Select(attrs={'class': 'form-select'}),
        }
