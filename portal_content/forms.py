import os
from django import forms
from .models import Announcement, Document
from partners.models import PartnerProfile

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'png', 'jpg', 'jpeg'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

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

    def clean_file(self):
        f = self.cleaned_data.get('file')
        if not f:
            return f
        
        # Check size if it's a newly uploaded file
        if hasattr(f, 'size') and f.size > MAX_FILE_SIZE:
            size_mb = f.size / (1024 * 1024)
            raise forms.ValidationError(
                f"File size exceeds the 10 MB limit (uploaded file is {size_mb:.1f} MB)."
            )
            
        # Check extension
        name = getattr(f, 'name', '')
        _, ext = os.path.splitext(name)
        clean_ext = ext.lstrip('.').lower()
        if clean_ext not in ALLOWED_EXTENSIONS:
            allowed_list = ', '.join(sorted(ALLOWED_EXTENSIONS))
            raise forms.ValidationError(
                f"File type '.{clean_ext}' is not permitted. Allowed extensions are: {allowed_list}."
            )
            
        return f
