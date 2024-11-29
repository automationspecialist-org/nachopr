from django import template

register = template.Library()

@register.filter
def time_diff_display(diff):
    """Format timedelta into human readable string"""
    total_seconds = diff.total_seconds()
    if total_seconds < 1:
        return f"{int(total_seconds * 1000)} ms"
    else:
        return f"{total_seconds:.2f} s"