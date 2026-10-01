from django import forms
from .models import Ticket

class TicketForm(forms.ModelForm):
    """Used by Partners to create/edit their own tickets."""
    class Meta:
        model = Ticket
        fields = ['subject', 'description']
        widgets = {
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'What is the issue about?'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Please describe your issue or question in detail...'}),
        }

class AdminTicketForm(forms.ModelForm):
    """Used by Admin to view ticket details, write a reply, and update status."""
    class Meta:
        model = Ticket
        fields = ['partner', 'subject', 'description', 'status', 'admin_reply']
        widgets = {
            'partner': forms.Select(attrs={'class': 'form-select'}),
            'subject': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'admin_reply': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Write your reply to the partner here. They will see this message on their ticket detail page.'
            }),
        }
        labels = {
            'admin_reply': 'Reply to Partner',
        }

