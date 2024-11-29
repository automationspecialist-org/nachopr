from django import template
from datetime import timedelta

register = template.Library()

@register.filter
def time_diff_display(diff):
    """Format timedelta or seconds into human readable string"""
    if isinstance(diff, str):
        try:
            # Try to convert string to float (seconds)
            total_seconds = float(diff)
        except (ValueError, TypeError):
            return diff  # Return original string if conversion fails
    elif isinstance(diff, timedelta):
        total_seconds = diff.total_seconds()
    else:
        total_seconds = float(diff)  # Assume it's a number
        
    if total_seconds < 1:
        return f"{int(total_seconds * 1000)} ms"
    else:
        return f"{total_seconds:.2f} s"