from django import template

register = template.Library()

@register.filter
def time_diff_display(diff):
    #if diff < 1:
    #    return f"{int(diff * 1000)} ms"
    #else:
    #    return f"{diff:.2f} s"
    return diff