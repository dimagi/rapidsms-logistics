#!/usr/bin/env python
# vim: ai ts=4 sts=4 et sw=4 encoding=utf-8

from random import randint
from datetime import datetime
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect, HttpResponse
from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext
from django.utils.translation import ugettext as _
from rapidsms.contrib.locations.models import Location
from logistics.apps.logistics.models import Facility, ProductStock, \
    ProductReportsHelper, Product, ProductType, ProductReport, \
    get_geography, STOCK_ON_HAND_REPORT_TYPE
from logistics.apps.logistics.view_decorators import filter_context, geography_context

def input_stock(request, facility_code, context={}, template="logistics/input_stock.html"):
    # TODO: replace this with something that depends on the current user
    # QUESTION: is it possible to make a dynamic form?
    errors = ''
    rms = get_object_or_404(Facility, code=facility_code)
    productstocks = [p for p in ProductStock.objects.filter(facility=rms).order_by('product')]
    if request.method == "POST":
        # we need to use the helper/aggregator so that when we update
        # the supervisor on resolved stockouts we can do it all in a
        # single message
        prh = ProductReportsHelper(rms, STOCK_ON_HAND_REPORT_TYPE)
        for stock in productstocks:
            try:
                if stock.product.sms_code in request.POST:
                    quantity = request.POST[stock.product.sms_code]
                    if not quantity.isdigit():
                        errors = ", ".join([errors, stock.product.name])
                        continue
                    prh.add_product_stock(stock.product.sms_code, quantity)
                    if "%s_consumption" % stock.product.sms_code in request.POST:
                        consumption = request.POST["%s_consumption" % stock.product.sms_code]
                        if not consumption.isdigit():
                            errors = ", ".join([errors, stock.product.name])
                            continue
                        prh.add_product_consumption(stock.product, consumption)
                    if "%s_is_active" % stock.product.sms_code in request.POST:
                        rms.activate_product(stock.product)
                    else:
                        rms.deactivate_product(stock.product)
            except ValueError, e:
                errors = errors + unicode(e)
        if not errors:
            prh.save()
            return HttpResponseRedirect(reverse(stockonhand_facility, args=(rms.code,)))
        errors = "Please enter all stock on hand and consumption as integers, for example:'100'. " + \
                 "The following fields had problems: " + errors.strip(', ')
    return render_to_response(
        template, {
                'errors': errors,
                'rms': rms,
                'productstocks': productstocks,
                'date': datetime.now()
            }, context_instance=RequestContext(request)
    )

@geography_context
def stockonhand_facility(request, facility_code, context={}, template="logistics/stockonhand_facility.html"):
    """
     this view currently only shows the current stock on hand for a given facility
    """
    facility = get_object_or_404(Facility, code=facility_code)
    stockonhands = ProductStock.objects.filter(facility=facility).order_by('product')
    last_reports = ProductReport.objects.filter(facility=facility).order_by('-report_date')
    if last_reports:
        context['last_reported'] = last_reports[0].report_date
    context['stockonhands'] = stockonhands
    context['facility'] = facility
    return render_to_response(
        template, context, context_instance=RequestContext(request)
    )

@geography_context
@filter_context
def district(request, location_code, context={}, template="logistics/aggregate.html"):
    """
    The district view is unusual. When we do not receive a filter by individual product,
    we show the aggregate report. When we do receive a filter by individual product, we show
    the 'by product' report. Let's see how this goes. 
    """
    context['stockonhands'] = stockonhands = ProductStock.objects.filter(facility__location=context['location'])
    if request.method == "POST" or request.method == "GET":
        # We support GETs so that folks can share this report as a url
        filtered_by_commodity = False
        if 'commodity' in request.REQUEST:
            try:
                selected_commodity = Product.objects.get(sms_code=request.REQUEST['commodity'])
            except Product.DoesNotExist:
                # user selected 'all'
                pass
            else:
                template="logistics/stockonhand_district.html"
                context['selected_commodity'] = selected_commodity
                context['stockonhands'] = stockonhands.filter(product=selected_commodity)
                filtered_by_commodity = True
        if not filtered_by_commodity and 'commoditytype' in request.REQUEST:
            try:
                selected_commoditytype = ProductType.objects.get(code=request.REQUEST['commoditytype'])
            except ProductType.DoesNotExist:
                # user selected 'all'
                pass
            else:
                context['selected_commoditytype'] = selected_commoditytype
                context['stockonhands'] = stockonhands.filter(product__type=selected_commoditytype)
    return render_to_response(
        template, context, context_instance=RequestContext(request)
    )

@geography_context
def reporting(request, context={}, template="logistics/reporting.html"):
    """ which facilities have reported on time and which haven't """
    seven_days_ago = datetime.now() + relativedelta(days=-7)
    context['late_facilities'] = Facility.objects.filter(Q(last_reported__lt=seven_days_ago) | Q(last_reported=None)).order_by('-last_reported')
    context['on_time_facilities'] = Facility.objects.filter(last_reported__gte=seven_days_ago).order_by('-last_reported')
    return render_to_response(
        template, context, context_instance=RequestContext(request)
    )

@geography_context
@filter_context
def aggregate(request, location_code, context={}, template="logistics/aggregate.html"):
    """
    The aggregate view of all children within a geographical region
    where 'children' can either be sub-regions
    OR facilities if no sub-region exists
    """
    #if request.method == "POST" or request.method == "GET":
    #    # We support GETs so that folks can share this report as a url
    #    filtered_by_commodity = False
    #    if 'commodity' in request.REQUEST:
    #context['filter'] = "product=%s&producttype=%s" % (product, producttype)
    return render_to_response(
        template, context, context_instance=RequestContext(request)
    )
