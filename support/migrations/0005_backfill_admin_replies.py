from django.db import migrations
from django.utils import timezone


def backfill_admin_replies(apps, schema_editor):
    """
    Create one TicketReply per ticket that already carries a legacy
    admin_reply value, so the new conversation thread opens with the
    existing history. The legacy field itself is left untouched.

    Notes:
      * Historical models expose a plain ``objects`` manager, so
        soft-deleted tickets are included too.
      * ``auto_now_add`` overwrites an explicit ``created_at``, so the
        reply is created first and the timestamp patched afterwards.
    """
    Ticket = apps.get_model('support', 'Ticket')
    TicketReply = apps.get_model('support', 'TicketReply')

    tickets = Ticket.objects.filter(admin_reply__isnull=False).exclude(admin_reply__exact='')
    for ticket in tickets.iterator():
        created_at = ticket.updated_at or timezone.now()
        reply = TicketReply.objects.create(
            ticket_id=ticket.pk,
            author=None,
            message=ticket.admin_reply,
            source='portal',
        )
        TicketReply.objects.filter(pk=reply.pk).update(created_at=created_at)


def unpopulate_admin_replies(apps, schema_editor):
    """Remove only the replies created by this migration."""
    TicketReply = apps.get_model('support', 'TicketReply')
    TicketReply.objects.filter(author=None, source='portal').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('support', '0004_ticketreply'),
    ]

    operations = [
        migrations.RunPython(backfill_admin_replies, unpopulate_admin_replies),
    ]
