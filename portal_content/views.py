from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from .models import Announcement, Document
from .forms import AnnouncementForm, DocumentForm

@login_required(login_url='/login/')
def content_list(request):
    announcements = Announcement.objects.filter(is_active=True).order_by('-created_at')
    documents = Document.objects.all().order_by('-uploaded_at')
    
    return render(request, 'portal_content/content_list.html', {
        'announcements': announcements,
        'documents': documents
    })

@login_required(login_url='/login/')
def announcement_create(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('content_list')
        
    if request.method == 'POST':
        form = AnnouncementForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Announcement successfully created!')
            return redirect('content_list')
    else:
        form = AnnouncementForm()
        
    return render(request, 'portal_content/announcement_form.html', {'form': form})

@login_required(login_url='/login/')
def document_create(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('content_list')
        
    if request.method == 'POST':
        form = DocumentForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, 'Document successfully uploaded!')
            return redirect('content_list')
    else:
        form = DocumentForm()
        
    return render(request, 'portal_content/document_form.html', {'form': form})

@login_required(login_url='/login/')
def announcement_list(request):
    if request.user.is_staff:
        announcements = Announcement.objects.all().order_by('-created_at')
    else:
        announcements = Announcement.objects.filter(is_active=True).order_by('-created_at')
    return render(request, 'portal_content/announcement_list.html', {'announcements': announcements})

@login_required(login_url='/login/')
def document_list(request):
    documents = Document.objects.all().order_by('-uploaded_at')
    return render(request, 'portal_content/document_list.html', {'documents': documents})

@login_required(login_url='/login/')
def announcement_update(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    obj = get_object_or_404(Announcement, pk=pk)
    if request.method == 'POST':
        form = AnnouncementForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'Announcement updated!')
            return redirect('announcement_list')
    else:
        form = AnnouncementForm(instance=obj)
    return render(request, 'portal_content/announcement_form.html', {'form': form, 'is_update': True})

@login_required(login_url='/login/')
@require_POST
def announcement_delete(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    obj = get_object_or_404(Announcement, pk=pk)
    obj.soft_delete(request.user)
    messages.success(request, 'Moved to Recycle Bin')
    return redirect('announcement_list')

@login_required(login_url='/login/')
def document_update(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    obj = get_object_or_404(Document, pk=pk)
    if request.method == 'POST':
        form = DocumentForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'Document updated!')
            return redirect('document_list')
    else:
        form = DocumentForm(instance=obj)
    return render(request, 'portal_content/document_form.html', {'form': form, 'is_update': True})

@login_required(login_url='/login/')
@require_POST
def document_delete(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    obj = get_object_or_404(Document, pk=pk)
    obj.soft_delete(request.user)
    messages.success(request, 'Moved to Recycle Bin')
    return redirect('document_list')
