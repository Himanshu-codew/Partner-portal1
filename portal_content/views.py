import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.http import FileResponse, Http404
from django.db.models import Q, Count
from django.core.paginator import Paginator

from .models import Announcement, Document
from .forms import AnnouncementForm, DocumentForm
from partners.utils import get_partner_profile

@login_required(login_url='/login/')
def content_list(request):
    if request.user.is_staff:
        announcements = Announcement.objects.filter(is_active=True).order_by('-created_at')
        documents = Document.objects.all().order_by('-uploaded_at')
    else:
        profile = get_partner_profile(request.user)
        if not profile or not profile.is_approved:
            messages.warning(request, "Your account is waiting for administrator approval.")
            return redirect('approval_pending')

        # Public = visible_to count is 0 (empty M2M = show to all)
        # Private = visible_to count > 0 AND this partner is in the list
        announcements = Announcement.objects.filter(is_active=True).annotate(
            vcount=Count('visible_to')
        ).filter(
            Q(vcount=0) | Q(visible_to=profile)
        ).distinct().order_by('-created_at')

        documents = Document.objects.annotate(
            vcount=Count('visible_to')
        ).filter(
            Q(vcount=0) | Q(visible_to=profile)
        ).distinct().order_by('-uploaded_at')

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
        announcements_qs = Announcement.objects.all().prefetch_related('visible_to').order_by('-created_at')
    else:
        profile = get_partner_profile(request.user)
        if not profile or not profile.is_approved:
            messages.warning(request, "Your account is waiting for administrator approval.")
            return redirect('approval_pending')

        announcements_qs = Announcement.objects.filter(is_active=True).annotate(
            vcount=Count('visible_to')
        ).filter(
            Q(vcount=0) | Q(visible_to=profile)
        ).distinct().order_by('-created_at')

    query = request.GET.get('q', '')
    if query:
        announcements_qs = announcements_qs.filter(title__icontains=query)

    paginator = Paginator(announcements_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'portal_content/announcement_list.html', {'page_obj': page_obj})


@login_required(login_url='/login/')
def document_list(request):
    if request.user.is_staff:
        documents_qs = Document.objects.all().prefetch_related('visible_to').order_by('-uploaded_at')
    else:
        profile = get_partner_profile(request.user)
        if not profile or not profile.is_approved:
            messages.warning(request, "Your account is waiting for administrator approval.")
            return redirect('approval_pending')

        documents_qs = Document.objects.annotate(
            vcount=Count('visible_to')
        ).filter(
            Q(vcount=0) | Q(visible_to=profile)
        ).distinct().order_by('-uploaded_at')
            
    query = request.GET.get('q', '')
    if query:
        documents_qs = documents_qs.filter(title__icontains=query)

    paginator = Paginator(documents_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'portal_content/document_list.html', {'page_obj': page_obj})


@login_required(login_url='/login/')
def document_download(request, pk):
    """
    Login-required secure document download view with visibility rule enforcement
    and robust error handling when the file is missing from disk.
    """
    doc = get_object_or_404(Document, pk=pk)

    # Visibility check
    if not request.user.is_staff:
        profile = get_partner_profile(request.user)
        if not profile or not profile.is_approved:
            messages.error(request, "Your account must be approved to access documents.")
            return redirect('approval_pending')

        # If restricted to specific partners, check membership
        if doc.visible_to.exists() and not doc.visible_to.filter(pk=profile.pk).exists():
            messages.error(request, "You do not have permission to access this document.")
            return redirect('document_list')

    # Robust handling for missing file
    if not doc.file:
        messages.error(request, "File missing from storage.")
        return redirect('document_list')

    try:
        if not doc.file_exists:
            messages.error(request, "File missing from storage.")
            return redirect('document_list')
        
        file_handle = doc.file.open('rb')
        filename = os.path.basename(doc.file.name)
        return FileResponse(file_handle, as_attachment=True, filename=filename)
    except (FileNotFoundError, OSError, ValueError):
        messages.error(request, "File missing from storage.")
        return redirect('document_list')


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
