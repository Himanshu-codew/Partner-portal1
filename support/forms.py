from django import forms
from .models import Ticket, TicketReply


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
    """Used by Admin to edit ticket fields and update status."""
    class Meta:
        model = Ticket
        fields = ['partner', 'subject', 'description', 'status']
        widgets = {
            'partner': forms.Select(attrs={'class': 'form-select'}),
            'subject': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }


class TicketReplyForm(forms.ModelForm):
    """One message posted to a ticket's conversation thread."""

    message = forms.CharField(
        max_length=5000,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'maxlength': '5000',
            'placeholder': 'Write your reply...',
        }),
    )

    class Meta:
        model = TicketReply
        fields = ['message']
