import os
import threading

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth.models import User, Group
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import FileResponse
from django.urls import reverse
from django.utils import timezone
from .models import PartnerProfile, PartnerDocument
from .forms import UserForm, GroupForm, PartnerProfileForm, PartnerDocumentForm
from .utils import get_partner_profile, user_can_access_object
from core.services import notify
from core.services.ocr import process_document

def on_partner_approval_changed(profile):
    """
    Hook called when a partner's approval status changes.
    Notifies the partner when their account has been approved.
    """
    if profile.is_approved and profile.user_id:
        notify(profile.user, 'partner_approval_changed', {'profile': profile})

@login_required(login_url='/login/')
def partner_list(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    query = request.GET.get('q', '')
    partners_qs = PartnerProfile.objects.select_related('user').all().order_by('-created_at')
    
    if query:
        partners_qs = partners_qs.filter(
            Q(company_name__icontains=query) |
            Q(user__username__icontains=query) |
            Q(user__email__icontains=query)
        )
        
    paginator = Paginator(partners_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'partners/partner_list.html', {'page_obj': page_obj})

@login_required(login_url='/login/')
@require_POST
def partner_approve(request, profile_id):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    profile = get_object_or_404(PartnerProfile, id=profile_id)
    is_approved = request.POST.get('is_approved') == 'true'
    profile.is_approved = is_approved
    profile.save()
    on_partner_approval_changed(profile)
    status_text = "Approved" if is_approved else "Rejected"
    messages.success(request, f'Partner {profile.company_name} status updated to {status_text}.')
    return redirect('partner_list')

@login_required(login_url='/login/')
def partner_create(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = PartnerProfileForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Partner Profile successfully created!')
            return redirect('partner_list')
    else:
        form = PartnerProfileForm()
    return render(request, 'partners/partner_form.html', {'form': form})

@login_required(login_url='/login/')
def user_list(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    query = request.GET.get('q', '')
    users_qs = User.objects.filter(is_active=True).prefetch_related('groups').order_by('-date_joined')
    
    if query:
        users_qs = users_qs.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )
        
    paginator = Paginator(users_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'partners/user_list.html', {'page_obj': page_obj})

@login_required(login_url='/login/')
def user_create(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = UserForm(request.POST, current_user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'User successfully created!')
            return redirect('user_list')
    else:
        form = UserForm(current_user=request.user)
    return render(request, 'partners/user_form.html', {'form': form})

@login_required(login_url='/login/')
def group_list(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    query = request.GET.get('q', '')
    groups_qs = Group.objects.prefetch_related('permissions').all().order_by('name')
    
    if query:
        groups_qs = groups_qs.filter(name__icontains=query)
        
    paginator = Paginator(groups_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'partners/group_list.html', {'page_obj': page_obj})

@login_required(login_url='/login/')
def group_create(request):
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = GroupForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Group successfully created!')
            return redirect('group_list')
    else:
        form = GroupForm()
    return render(request, 'partners/group_form.html', {'form': form})

@login_required(login_url='/login/')
def partner_update(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    partner = get_object_or_404(PartnerProfile, pk=pk)
    if request.method == 'POST':
        form = PartnerProfileForm(request.POST, instance=partner)
        if form.is_valid():
            form.save()
            messages.success(request, 'Partner updated!')
            return redirect('partner_list')
    else:
        form = PartnerProfileForm(instance=partner)
    return render(request, 'partners/partner_form.html', {'form': form, 'is_update': True})

@login_required(login_url='/login/')
@require_POST
def partner_delete(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    partner = get_object_or_404(PartnerProfile, pk=pk)
    partner.soft_delete(request.user)
    partner.user.is_active = False
    partner.user.save()
    messages.success(request, 'Moved to Recycle Bin')
    return redirect('partner_list')

@login_required(login_url='/login/')
def user_update(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    u = get_object_or_404(User, pk=pk)

    # Rule 3.2: A non-superuser staff member cannot edit a superuser account
    if u.is_superuser and not request.user.is_superuser:
        messages.error(request, "Only superusers can edit superuser accounts.")
        return redirect('user_list')

    if request.method == 'POST':
        form = UserForm(request.POST, instance=u, current_user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'User updated!')
            return redirect('user_list')
    else:
        form = UserForm(instance=u, current_user=request.user)
    return render(request, 'partners/user_form.html', {'form': form, 'is_update': True})

@login_required(login_url='/login/')
@require_POST
def user_delete(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    u = get_object_or_404(User, pk=pk)
    
    # Rule 3.3: Prevent deleting yourself
    if u == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect('user_list')

    # Rule 3.2: A non-superuser staff member cannot delete a superuser account
    if u.is_superuser and not request.user.is_superuser:
        messages.error(request, "Only superusers can delete superuser accounts.")
        return redirect('user_list')

    # Rule 3.3: The last remaining active superuser can never be deleted
    if u.is_superuser and u.is_active:
        active_superusers = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=u.pk)
        if not active_superusers.exists():
            messages.error(request, "The last remaining active superuser cannot be deleted.")
            return redirect('user_list')
        
    u.is_active = False
    u.save()
    messages.success(request, f"User '{u.username}' moved to Recycle Bin.")
    return redirect('user_list')

@login_required(login_url='/login/')
def group_update(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    g = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        form = GroupForm(request.POST, instance=g)
        if form.is_valid():
            form.save()
            messages.success(request, 'Group updated!')
            return redirect('group_list')
    else:
        form = GroupForm(instance=g)
    return render(request, 'partners/group_form.html', {'form': form, 'is_update': True})

@login_required(login_url='/login/')
@require_POST
def group_delete(request, pk):
    if not request.user.is_staff: return redirect('dashboard')
    g = get_object_or_404(Group, pk=pk)
    g.delete()
    messages.success(request, 'Group deleted!')
    return redirect('group_list')


# =================================================================
# KYC documents & OCR (Phase 3)
# =================================================================

def _schedule_ocr(document_pk):
    """Run OCR on a daemon thread once the upload transaction has committed.

    Render's free tier has no worker process, so the thread is spawned here
    instead of by a queue. ``process_document`` never raises and always
    closes its DB connection.
    """
    transaction.on_commit(
        lambda: threading.Thread(
            target=process_document, args=(document_pk,), daemon=True
        ).start()
    )


def _kyc_redirect_target(user, document):
    """Where to send a user after a download/retry problem (never raises)."""
    if user.is_staff:
        return reverse('kyc_document_detail', args=[document.pk])
    return reverse('kyc_document_list')


@login_required(login_url='/login/')
def kyc_document_list(request):
    """Staff: the KYC review queue. Partner: their own documents + upload."""
    if request.user.is_staff:
        documents = (
            PartnerDocument.objects
            .select_related('partner', 'partner__user', 'reviewed_by')
            .order_by('-uploaded_at')
        )
        review_choices = dict(PartnerDocument.REVIEW_STATUS_CHOICES)
        type_choices = dict(PartnerDocument.DOC_TYPE_CHOICES)

        review_filter = request.GET.get('review', '')
        if review_filter not in review_choices:
            review_filter = ''
        else:
            documents = documents.filter(review_status=review_filter)

        type_filter = request.GET.get('type', '')
        if type_filter not in type_choices:
            type_filter = ''
        else:
            documents = documents.filter(doc_type=type_filter)

        query = request.GET.get('q', '').strip()
        if query:
            documents = documents.filter(partner__company_name__icontains=query)

        paginator = Paginator(documents, 10)
        page_obj = paginator.get_page(request.GET.get('page'))
        return render(request, 'partners/kyc_review_list.html', {
            'page_obj': page_obj,
            'pending_count': PartnerDocument.objects.filter(review_status='pending').count(),
            'review_filter': review_filter,
            'type_filter': type_filter,
            'review_choices': review_choices,
            'type_choices': type_choices,
        })

    profile = get_partner_profile(request.user)
    if not profile or not profile.is_approved:
        messages.warning(request, "Your account is waiting for administrator approval.")
        return redirect('approval_pending')

    documents = PartnerDocument.objects.filter(partner=profile).order_by('-uploaded_at')
    paginator = Paginator(documents, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'partners/kyc_list.html', {
        'page_obj': page_obj,
        'form': PartnerDocumentForm(),
    })


@login_required(login_url='/login/')
@require_POST
def kyc_document_upload(request):
    profile = get_partner_profile(request.user)
    if not profile or not profile.is_approved:
        messages.warning(request, "Your account is waiting for administrator approval.")
        return redirect('approval_pending')

    form = PartnerDocumentForm(request.POST, request.FILES)
    if not form.is_valid():
        for error in form.errors.values():
            messages.error(request, ' '.join(error))
        return redirect('kyc_document_list')

    document = form.save(commit=False)
    document.partner = profile
    document.save()
    _schedule_ocr(document.pk)
    messages.success(request, 'Document uploaded. Text extraction runs in the background.')
    return redirect('kyc_document_list')


@login_required(login_url='/login/')
def kyc_document_detail(request, pk):
    """Staff-only review page: preview, OCR text, suggestions, decisions."""
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')
    document = get_object_or_404(
        PartnerDocument.objects.select_related('partner', 'partner__user', 'reviewed_by'),
        pk=pk,
    )
    return render(request, 'partners/kyc_review_detail.html', {'document': document})


@login_required(login_url='/login/')
def kyc_document_download(request, pk):
    """Download the original file — staff or the owning approved partner only.

    ``?inline=1`` serves the file without the attachment header so the staff
    detail page can preview images and PDFs in the browser.
    """
    document = get_object_or_404(PartnerDocument, pk=pk)

    if not request.user.is_staff:
        profile = get_partner_profile(request.user)
        if not profile or not profile.is_approved:
            messages.error(request, "Your account must be approved to access documents.")
            return redirect('approval_pending')
        if document.partner_id != profile.pk:
            messages.error(request, "You do not have permission to access this document.")
            return redirect('kyc_document_list')

    if not document.file:
        messages.error(request, "File missing from storage.")
        return redirect(_kyc_redirect_target(request.user, document))

    try:
        if not document.file_exists:
            messages.error(request, "File missing from storage.")
            return redirect(_kyc_redirect_target(request.user, document))

        file_handle = document.file.open('rb')
        filename = os.path.basename(document.file.name)
        get_content_type = getattr(document.file.storage, 'get_content_type', None)
        content_type = None
        if callable(get_content_type):
            content_type = get_content_type(document.file.name) or None
        inline = request.GET.get('inline') == '1'
        return FileResponse(
            file_handle,
            as_attachment=not inline,
            filename=filename,
            content_type=content_type,
        )
    except (FileNotFoundError, OSError, ValueError):
        messages.error(request, "File missing from storage.")
        return redirect(_kyc_redirect_target(request.user, document))


@login_required(login_url='/login/')
@require_POST
def kyc_document_retry_ocr(request, pk):
    """POST-only OCR retry for staff or the owning approved partner."""
    document = get_object_or_404(PartnerDocument, pk=pk)
    if not user_can_access_object(request.user, document, partner_field='partner'):
        messages.error(request, 'Unauthorized access.')
        return redirect('kyc_document_list')

    if document.ocr_status == 'processing':
        messages.warning(request, 'Text extraction is already running for this document.')
        return redirect(_kyc_redirect_target(request.user, document))

    document.ocr_status = 'pending'
    document.ocr_error = ''
    document.save(update_fields=['ocr_status', 'ocr_error'])
    _schedule_ocr(document.pk)
    messages.success(request, 'Retrying text extraction in the background.')
    return redirect(_kyc_redirect_target(request.user, document))


@login_required(login_url='/login/')
@require_POST
def kyc_document_review(request, pk):
    """Staff-only approve/reject decision; notifies the partner afterwards."""
    if not request.user.is_staff:
        messages.error(request, 'Unauthorized access.')
        return redirect('dashboard')

    document = get_object_or_404(PartnerDocument, pk=pk)
    action = request.POST.get('action', '')
    if action not in ('approve', 'reject'):
        messages.error(request, 'Unknown review action.')
        return redirect('kyc_document_detail', pk=pk)

    note = (request.POST.get('note') or '').strip()
    document.review_status = 'approved' if action == 'approve' else 'rejected'
    document.reviewed_by = request.user
    document.reviewed_at = timezone.now()
    document.review_note = note
    document.save(update_fields=[
        'review_status', 'reviewed_by', 'reviewed_at', 'review_note',
    ])

    notify(
        document.partner.user,
        'kyc_reviewed',
        {'document': document, 'actor': request.user},
    )
    messages.success(request, f"Document marked as {document.get_review_status_display().lower()}.")
    return redirect('kyc_document_detail', pk=pk)
