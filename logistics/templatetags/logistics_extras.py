from django import template
from logistics.templatetags.math_tags import percent
register = template.Library()

@register.inclusion_tag("logistics/templatetags/highlight_months_available.html")
def highlight_months(stockonhand, media_url):
    return { "stockonhand": stockonhand, "MEDIA_URL":media_url }

@register.simple_tag
def percent_cell(a, b):
    val = percent(a, b)
    return '<td title="%(a)s of %(b)s">%(val)s</td><td>%(b)s</td>' % {"a": a, "b": b, "val": val}

@register.filter('klass')
def klass(ob):
    return ob.__class__.__name__

@register.filter
def historical_date_last_stocked(productstock, date):
    return productstock.date_last_stocked(date)


