from django import forms
from .models import Announcement, Document
from partners.models import PartnerProfile

class AnnouncementForm(forms.ModelForm):
    visible_to = forms.ModelMultipleChoiceField(
        queryset=PartnerProfile.objects.filter(is_approved=True),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
        label='Visible To (Private)',
        help_text='Leave empty = visible to ALL partners. Select specific partners to make it private.'
    )

    class Meta:
        model = Announcement
        fields = ['title', 'content', 'is_active', 'visible_to']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class DocumentForm(forms.ModelForm):
    visible_to = forms.ModelMultipleChoiceField(
        queryset=PartnerProfile.objects.filter(is_approved=True),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
        label='Visible To (Private)',
        help_text='Leave empty = visible to ALL partners. Select specific partners to make it private.'
    )

    class Meta:
        model = Document
        fields = ['title', 'file', 'visible_to']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
        }
