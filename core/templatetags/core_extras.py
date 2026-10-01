from django import template
register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key) if isinstance(dictionary, dict) else None

@register.simple_tag
def get_recycle_bin_count():
    from core.views import get_soft_deleted_models
    count = sum(model.deleted_objects.count() for model in get_soft_deleted_models().values())
    return count
