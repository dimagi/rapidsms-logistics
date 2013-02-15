import warnings
from rapidsms.conf import settings
from logistics.models import Product

def global_nav_mode(request):
    return {"nav_mode": settings.LOGISTICS_NAVIGATION_MODE }


def custom_settings(request):
    return {"excel_export": settings.LOGISTICS_EXCEL_EXPORT_ENABLED,
            "%s_hack" % settings.COUNTRY: True}

def stock_cutoffs(request):
    return {"months_minimum": settings.LOGISTICS_REORDER_LEVEL_IN_MONTHS,
            "months_maximum": settings.LOGISTICS_MAXIMUM_LEVEL_IN_MONTHS}

def stocked_by(request):
    return {"stocked_by": settings.LOGISTICS_STOCKED_BY, 
            "active_stocks": Product.objects.filter(is_active=True)}

def google_analytics(request):
    if hasattr(settings, 'GOOGLE_ANALYTICS_ID'):
        return {"GOOGLE_ANALYTICS_ID": getattr(settings, 'GOOGLE_ANALYTICS_ID', None)}
    return {"GOOGLE_ANALYTICS_ID": None}

def base_template(request):
    """ 
    For compatibility with the logistics app, which allows users
    to specify a custom 'base template' dynamically
    """ 
    try:
        base_template = settings.BASE_TEMPLATE
    except (ValueError, AttributeError):
        base_template = "layout.html"

    try:
        base_template_split_2 = settings.BASE_TEMPLATE_SPLIT_2
    except (ValueError, AttributeError):
        base_template_split_2 = "layout-split-2.html"

    return {'base_template': base_template,
            'base_template_split_2': base_template_split_2 }

def logo(request):
    try:
        logo_right_url = settings.LOGO_RIGHT_URL
    except AttributeError:
        warnings.warn("No LOGO_RIGHT_URL specified in settings! rapidsms.context_processors.logo")
        logo_right_url = ""
    try:
        logo_left_url = settings.LOGO_LEFT_URL
    except AttributeError:
        warnings.warn("No LOGO_LEFT_URL specified in settings! rapidsms.context_processors.logo")
        logo_left_url = ""
    try:
        site_title = settings.SITE_TITLE
    except AttributeError:
        warnings.warn("No SITE_TITLE specified in settings! rapidsms.context_processors.logo")
        site_title = "RapidSMS"
    try:
        base_template = settings.BASE_TEMPLATE
    except AttributeError:
        warnings.warn("No base_template specified in settings! rapidsms.context_processors.logo")
        base_template = "layout.html"

    try:
        base_template_split_2 = settings.BASE_TEMPLATE_SPLIT_2
    except AttributeError:
        base_template_split_2 = "layout-split-2.html"

    return {'logo_right_url' : logo_right_url,
            'logo_left_url' : logo_left_url,
            'site_title' : site_title,
            'base_template': base_template,
            'base_template_split_2': base_template_split_2 }
