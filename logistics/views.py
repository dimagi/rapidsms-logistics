#!/usr/bin/env python
# vim: ai ts=4 sts=4 et sw=4 encoding=utf-8
from __future__ import absolute_import

from logistics.const import Reports

from dimagi.utils import csv 
import json
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import permission_required
from django.db.models import Q
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect, HttpResponse, Http404
from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext
from django.utils.translation import ugettext as _
from django_tablib import ModelDataset
from django_tablib.base import mimetype_map
from django.views.decorators.http import require_POST
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_exempt
from rapidsms.conf import settings
from rapidsms.contrib.locations.models import Location
from rapidsms.contrib.messagelog.views import MessageLogView as RapidSMSMessagLogView
from dimagi.utils.dates import DateSpan
from dimagi.utils.decorators.datespan import datespan_in_request
from email_reports.decorators import magic_token_required
from logistics.charts import stocklevel_plot
from logistics.decorators import place_in_request
from logistics.models import ProductStock, \
    ProductReportsHelper, ProductReport, LogisticsProfile,\
    SupplyPoint, StockTransaction, RequisitionReport
from logistics.util import config
from logistics.view_decorators import filter_context, geography_context
from logistics.reports import ReportingBreakdown
from logistics.reports import get_reporting_and_nonreporting_facilities
from .models import Product, ProductType
from .forms import FacilityForm, CommodityForm
from rapidsms.contrib.messagelog.models import Message
from rapidsms.contrib.messagelog.tables import MessageTable
from rapidsms.models import Backend
from .tables import FacilityTable, CommodityTable, MessageTable
from alerts.models import Notification


def no_ie_allowed(request, template="logistics/no_ie_allowed.html"):
    return render_to_response(template, context_instance=RequestContext(request))

def landing_page(request):
    if 'MSIE' in request.META['HTTP_USER_AGENT']:
        return no_ie_allowed(request)
    
    if settings.LOGISTICS_LANDING_PAGE_VIEW:
        return HttpResponseRedirect(reverse(settings.LOGISTICS_LANDING_PAGE_VIEW))
    
    prof = None 
    try:
        if not request.user.is_anonymous():
            prof = request.user.get_profile()
    except LogisticsProfile.DoesNotExist:
        pass
    
    if prof and prof.supply_point:
        return stockonhand_facility(request, prof.supply_point.code)
    elif prof and prof.location:
        return aggregate(request, prof.location.code)
    return dashboard(request)

def input_stock(request, facility_code, context={}, template="logistics/input_stock.html"):
    # TODO: replace this with something that depends on the current user
    # QUESTION: is it possible to make a dynamic form?
    errors = ''
    rms = get_object_or_404(SupplyPoint, code=facility_code)
    productstocks = [p for p in rms.stocked_productstocks().order_by('product__name')]
    if request.method == "POST":
        # we need to use the helper/aggregator so that when we update
        # the supervisor on resolved stockouts we can do it all in a
        # single message
        prh = ProductReportsHelper(rms, Reports.SOH)
        for stock in productstocks:
            try:
                if stock.product.sms_code in request.POST:
                    quantity = request.POST[stock.product.sms_code].strip()
                    if quantity:
                        if not quantity.isdigit():
                            errors = ", ".join([errors, stock.product.name])
                            continue
                        prh.add_product_stock(stock.product.sms_code, quantity, save=False)
                if "%s_receipt" % stock.product.sms_code in request.POST:
                    receipt = request.POST["%s_receipt" % stock.product.sms_code].strip()
                    if not receipt.isdigit():
                        errors = ", ".join([errors, stock.product.name])
                        continue
                    if int(receipt) != 0:
                        prh.add_product_receipt(stock.product.sms_code, receipt, save=False)
                if "%s_consumption" % stock.product.sms_code in request.POST:
                    consumption = request.POST["%s_consumption" % stock.product.sms_code].strip()
                    if consumption:
                        if not consumption.isdigit():
                            errors = ", ".join([errors, stock.product.name])
                            continue
                        prh.add_product_consumption(stock.product, consumption)
                if "%s_use_auto_consumption" % stock.product.sms_code in request.POST:
                    rms.activate_auto_consumption(stock.product)
                else:
                    rms.deactivate_auto_consumption(stock.product)
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

class JSONDateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return "Date(%d, %d, %d)" % (obj.year, obj.month, obj.day)
        else:
            return json.JSONEncoder.default(self, obj)

@geography_context
@datespan_in_request(default_days=settings.LOGISTICS_REPORTING_CYCLE_IN_DAYS)
def stockonhand_facility(request, facility_code, context={}, template="logistics/stockonhand_facility.html"):
    """
     this view currently only shows the current stock on hand for a given facility
    """
    facility = get_object_or_404(SupplyPoint, code=facility_code)
    last_reports = ProductReport.objects.filter(supply_point=facility).order_by('-report_date')
    transactions = StockTransaction.objects.filter(supply_point=facility)
    if transactions:
        context['last_reported'] = last_reports[0].report_date
        context['chart_data'] = stocklevel_plot(transactions)
    context['facility'] = facility
    context["location"] = facility.location
    context["destination_url"] = "aggregate"
    reqs = RequisitionReport.objects.filter(supply_point=facility).order_by('-report_date')
    if reqs:
        context["last_requisition"] = reqs[0]
    return render_to_response(
        template, context, context_instance=RequestContext(request)
    )

@cache_page(60 * 15)
@geography_context
@filter_context
def facilities_by_product(request, location_code, context={}, template="logistics/by_product.html"):
    """
    The district view is unusual. When we do not receive a filter by individual product,
    we show the aggregate report. When we do receive a filter by individual product, we show
    the 'by product' report. Let's see how this goes. 
    """
    if 'commodity' in request.REQUEST:
        commodity_filter = request.REQUEST['commodity']
        context['commodity_filter'] = commodity_filter
        commodity = get_object_or_404(Product, sms_code=commodity_filter)
        context['selected_commodity'] = commodity
    else:
        raise HttpResponse('Must specify "commodity"')
    location = get_object_or_404(Location, code=location_code)
    stockonhands = ProductStock.objects.filter(Q(supply_point__location__in=location.get_descendants(include_self=True)))
    context['stockonhands'] = stockonhands.filter(product=commodity).order_by('supply_point__name')
    context['location'] = location
    context['hide_product_link'] = True
    context['destination_url'] = "aggregate"
    return render_to_response(
        template, context, context_instance=RequestContext(request)
    )

@csrf_exempt
@cache_page(60 * 15)
@geography_context
@filter_context
@magic_token_required()
@datespan_in_request(default_days=settings.LOGISTICS_REPORTING_CYCLE_IN_DAYS)
def reporting(request, location_code=None, context={}, template="logistics/reporting.html", 
              destination_url="reporting"):
    """ which facilities have reported on time and which haven't """
    if location_code is None:
        location_code = settings.COUNTRY
    if location_code == settings.COUNTRY:
        context['excel_export'] = False
    location = get_object_or_404(Location, code=location_code)
    context['location'] = location
    context['destination_url'] = destination_url
    return render_to_response(
        template, context, context_instance=RequestContext(request)
    )

@csrf_exempt
@cache_page(60 * 15)
@require_POST
def navigate(request):
    location_code = settings.COUNTRY
    destination = "logistics_dashboard"
    querystring = ''
    if 'location' in request.REQUEST and request.REQUEST['location']: 
        location_code = request.REQUEST['location']
    if 'destination_url' in request.REQUEST and request.REQUEST['destination_url']: 
        destination = request.REQUEST['destination_url']
    if 'year' in request.REQUEST and request.REQUEST['year']: 
        querystring += '&year=' + request.REQUEST['year']
    if 'month' in request.REQUEST and request.REQUEST['month']: 
        querystring += '&month=' + request.REQUEST['month']
    if 'to' in request.REQUEST and request.REQUEST['to']: 
        querystring += '&to=' + request.REQUEST['to']
    if 'from' in request.REQUEST and request.REQUEST['from']: 
        querystring += '&from=' + request.REQUEST['from']
    mode = request.REQUEST.get("mode", "url")
    if mode == "url":
        return HttpResponseRedirect(
            reverse(destination, args=(location_code, )))
    elif mode == "param":
        return HttpResponseRedirect(
            "%s?place=%s%s" % (reverse(destination), location_code, querystring))
    elif mode == "direct-param":
        return HttpResponseRedirect(
            "%s?place=%s%s" % (destination, location_code, querystring))

@csrf_exempt
@geography_context
@filter_context
def dashboard(request, location_code=None, context={}, template="logistics/aggregate.html"):
    if location_code is None:
        location_code = settings.COUNTRY
    location = get_object_or_404(Location, code=location_code)
    # if the location has no children, and 1 supply point treat it like
    # a stock on hand request. Otherwise treat it like an aggregate.
    if location.get_children().count() == 0 and location.facilities().count() == 1:
        facility = location.facilities()[0]
        return stockonhand_facility(request, facility.code, context=context)
    return aggregate(request, location_code, context=context)

@csrf_exempt
@cache_page(60 * 15)
@geography_context
@filter_context
@magic_token_required()
@datespan_in_request()
def aggregate(request, location_code=None, context={}, template="logistics/aggregate.html"):
    """
    The aggregate view of all children within a geographical region
    where 'children' can either be sub-regions
    OR facilities if no sub-region exists
    """
    # default to the whole country
    if location_code is None:
        location_code = settings.COUNTRY
    location = get_object_or_404(Location, code=location_code)
    context['location'] = location
    context['default_commodity'] = Product.objects.order_by('name')[0]
    context['facility_count'] = location.child_facilities().count()
    context['destination_url'] = 'aggregate'
    return render_to_response(
        template, context, context_instance=RequestContext(request)
    )

def _get_rows_from_children(children, commodity_filter, commoditytype_filter, datespan=None):
    rows = []
    for child in children:
        row = {}
        row['location'] = child
        row['is_active'] = child.is_active
        row['name'] = child.name
        row['code'] = child.code
        if isinstance(child, SupplyPoint):
            row['url'] = reverse('stockonhand_facility', args=[child.code])
        else:
            row['url'] = reverse('logistics_dashboard', args=[child.code])
        row['stockout_count'] = child.stockout_count(product=commodity_filter, 
                                                     producttype=commoditytype_filter, 
                                                     datespan=datespan)
        row['emergency_plus_low'] = child.emergency_plus_low(product=commodity_filter, 
                                                     producttype=commoditytype_filter, 
                                                     datespan=datespan)
        row['good_supply_count'] = child.good_supply_count(product=commodity_filter, 
                                                     producttype=commoditytype_filter, 
                                                     datespan=datespan)
        row['overstocked_count'] = child.overstocked_count(product=commodity_filter, 
                                                     producttype=commoditytype_filter, 
                                                     datespan=datespan)
        z = lambda x: x if x is not None else 0
        row['total'] = z(row['stockout_count']) + z(row['emergency_plus_low']) + \
          z(row['good_supply_count']) + z(row['overstocked_count'])
        if commodity_filter is not None:
            row['consumption'] = child.consumption(product=commodity_filter, 
                                                   producttype=commoditytype_filter)
        rows.append(row)
    return rows

def get_location_children(location, commodity_filter, commoditytype_filter, datespan=None):
    children = []
    children.extend(location.facilities())
    children.extend(location.get_children())
    return _get_rows_from_children(children, commodity_filter, commoditytype_filter, datespan)

@cache_page(60 * 15)
def export_reporting(request, location_code=None):
    if location_code is None:
        location_code = settings.COUNTRY
    location = get_object_or_404(Location, code=location_code)
    queryset = ProductReport.objects.filter(supply_point__location__in=location.get_descendants(include_self=True))\
      .select_related("supply_point__name", "supply_point__location__parent__name", 
                      "supply_point__location__parent__parent__name", 
                      "product__name", "report_type__name", "message__text").order_by('report_date')
    response = HttpResponse(mimetype=mimetype_map.get(format, 'application/octet-stream'))
    response['Content-Disposition'] = 'attachment; filename=reporting.xls'
    writer = csv.UnicodeWriter(response)
    writer.writerow(['ID', 'Location Grandparent', 'Location Parent', 'Facility', 
                     'Commodity', 'Report Type', 
                     'Quantity', 'Date',  'Message'])
    for q in queryset:
        parent = q.supply_point.location.parent.name if q.supply_point.location.parent else None
        grandparent = q.supply_point.location.parent.parent.name if q.supply_point.location.parent.parent else None
        message = q.message.text if q.message else None
        writer.writerow([q.id, 
                         grandparent, 
                         parent, 
                         q.supply_point.name, 
                         q.product.name, q.report_type.name, 
                         q.quantity, q.report_date, message])
    return response    

def export_stockonhand(request, facility_code, format='xls', filename='stockonhand'):
    class ProductReportDataset(ModelDataset):
        class Meta:
            queryset = ProductReport.objects.filter(supply_point__code=facility_code).order_by('report_date')
    dataset = getattr(ProductReportDataset(), format)
    filename = '%s_%s.%s' % (filename, facility_code, format)
    response = HttpResponse(
        dataset,
        mimetype=mimetype_map.get(format, 'application/octet-stream')
        )
    response['Content-Disposition'] = 'attachment; filename=%s' % filename
    return response

@permission_required('logistics.add_facility')
@transaction.commit_on_success
def facility(req, pk=None, template="logistics/config.html"):
    facility = None
    form = None
    klass = "SupplyPoint"
    if pk is not None:
        facility = get_object_or_404(
            SupplyPoint, pk=pk)
    if req.method == "POST":
        if req.POST["submit"] == "Delete %s" % klass:
            # deactivate instead of delete to preserve users & logs
            facility.deactivate()
            return HttpResponseRedirect(
                "%s?deleted=%s" % (reverse('facility_view'), 
                                   unicode(facility)))
        else:
            form = FacilityForm(instance=facility,
                                data=req.POST)
            if form.is_valid():
                facility = form.save()
                return HttpResponseRedirect(
                    "%s?created=%s" % (reverse('facility_edit', kwargs={'pk':facility.pk}), 
                                       unicode(facility)))
    else:
        form = FacilityForm(instance=facility)
    created = None
    deleted = None
    if req.method == "GET":
        if "created" in req.GET:
            created = req.GET['created']
        elif "deleted" in req.GET:
            deleted = req.GET['deleted']
    return render_to_response(
        template, {
            "created": created, 
            "deleted": deleted, 
            "table": FacilityTable(SupplyPoint.objects.filter(active=True), request=req),
            "form": form,
            "object": facility,
            "klass": klass,
            "klass_view": reverse('facility_view')
        }, context_instance=RequestContext(req)
    )

@permission_required('logistics.add_product')
@transaction.commit_on_success
def activate_commodity(request, sms_code):
    """ 
    hidden URL to reactivate commodities 
    exists for UI testing
    """
    if not request.user.is_superuser:
        return HttpResponse("not enough permissions to complete this transaction")
    commodity = get_object_or_404(Product, sms_code=sms_code)
    commodity.activate()
    return HttpResponse("success")

@permission_required('logistics.add_product')
@transaction.commit_on_success
def commodity(req, pk=None, template="logistics/config.html"):
    form = None
    commodity = None
    klass = "Commodity"
    if pk is not None:
        commodity = get_object_or_404(Product, pk=pk)
    if req.method == "POST":
        if req.POST["submit"] == "Delete %s" % klass:
            commodity.deactivate()
            return HttpResponseRedirect(
                reverse('commodity_view'))
        else:
            form = CommodityForm(
                                 instance=commodity,
                                 data=req.POST)
            if form.is_valid():
                commodity = form.save()
                return HttpResponseRedirect(
                    reverse('commodity_view'))
    else:
        form = CommodityForm(instance=commodity)
    return render_to_response(
        template, {
            "table": CommodityTable(Product.objects.filter(is_active=True), request=req),
            "form": form,
            "object": commodity,
            "klass": klass,
            "klass_view": reverse('commodity_view')
        }, context_instance=RequestContext(req)
    )

def get_facilities():
    return Location.objects.filter(type__slug=config.LocationCodes.FACILITY)

def get_districts():
    return Location.objects.filter(type__slug=config.LocationCodes.DISTRICT)

@cache_page(60 * 15)
@place_in_request()
def district_dashboard(request, template="logistics/district_dashboard.html"):
    districts = get_districts()
    if request.location is None:
        # pick a random location to start
        location_code = settings.COUNTRY
        request.location = get_object_or_404(Location, code=location_code)
        facilities = SupplyPoint.objects.all()
        #request.location = districts[0]
    else:
        facilities = request.location.all_child_facilities()
    report = ReportingBreakdown(facilities, 
                                DateSpan.since(settings.LOGISTICS_DAYS_UNTIL_LATE_PRODUCT_REPORT), 
                                days_for_late = settings.LOGISTICS_DAYS_UNTIL_LATE_PRODUCT_REPORT)
    return render_to_response(template,
                              {"reporting_data": report,
                               "graph_width": 200,
                               "graph_height": 200,
                               "districts": districts.order_by("code"),
                               "location": request.location},
                              context_instance=RequestContext(request))

class LogisticsMessageLogView(RapidSMSMessagLogView):
    def get_context(self, request, context):
        context = super(LogisticsMessageLogView, self).get_context(request, context)
        if request.datespan is not None and request.datespan:
            messages = context['messages_qs']
            messages = messages.filter(date__gte=request.datespan.startdate)\
              .filter(date__lte=request.datespan.end_of_end_day)
            context['messages_qs'] = messages
            context['messages_table'] = MessageTable(messages, request=request)
        return context
    
    @datespan_in_request()
    def get(self, request, context=None, template="messagelog/index.html"):
        """
        NOTE: this truncates the messagelog by default to the last 30 days. 
        To get the complete message log, web users should export to excel 
        """
        return super(LogisticsMessageLogView, self).get(request, context=context, 
                                                        template=template)

def messages_by_carrier(request, template="logistics/messages_by_carrier.html"):
    earliest_msg = Message.objects.all().order_by("date")[0].date
    month = earliest_msg.month
    year = earliest_msg.year
    backends = list(Backend.objects.all())
    counts = {}
    mdates = []
    d = datetime(year, month, 1) + relativedelta(months=1)-relativedelta(seconds=1)
    while d <= datetime.utcnow() + relativedelta(months=1):
        mdates += [d]
        counts[d] = {}
        for b in backends:
            counts[d][b.name] = {}
            counts[d][b.name]["in"] = Message.objects.filter(connection__backend=b, date__month=d.month, date__year=d.year, direction="I").count()
            counts[d][b.name]["out"] = Message.objects.filter(connection__backend=b, date__month=d.month, date__year=d.year, direction="O").count()
        d += relativedelta(months=1)
    mdates.reverse()
    return render_to_response(template,
                              {"backends": backends,
                               "counts": counts,
                               "mdates": mdates},
                              context_instance=RequestContext(request))

class MonthPager(object):
    """
    Utility class to show a month pager, e.g. << August 2011 >>
    """
    def __init__(self, request):
        self.month = int(request.GET.get('month', datetime.utcnow().month))
        self.year = int(request.GET.get('year', datetime.utcnow().year))
        self.begin_date = datetime(year=self.year, month=self.month, day=1)
        self.end_date = (self.begin_date + timedelta(days=32)).replace(day=1) - timedelta(seconds=1) # last second of previous month
        self.prev_month = self.begin_date - timedelta(days=1)
        self.next_month = self.end_date + timedelta(days=1)
        self.show_next = True if self.end_date < datetime.utcnow().replace(day=1) else False
        self.datespan = DateSpan(self.begin_date, self.end_date)


@geography_context
def summary(request, context=None):
    """
    View for generating HTML email reports via email-reports.
    While this can be viewed on the web, primarily this is rendered using a fake
    request object so care should be taken accessing items on the request.
    However request.user will be set.
    """
    context = context or {}
    profile = request.user.get_profile()
    if profile.location_id:
        location = profile.location
    else:
        location = context['geography']
    # Set request location like place_in_request
    # This is needed by some of the alerts
    request.location = location
    facilities = location.all_child_facilities()
    end = datetime.now()
    start = end - timedelta(days=7)
    datespan = DateSpan(start, end)
    report = ReportingBreakdown(facilities, datespan, 
        days_for_late=settings.LOGISTICS_DAYS_UNTIL_LATE_PRODUCT_REPORT)
    products = Product.objects.filter(is_active=True).order_by('type', 'name')
    for product in products:
        counts = {}
        total = 0
        for key in ('stockout_count', 'emergency_plus_low', 'good_supply_count', 'overstocked_count'):
            count = getattr(location, key)(
                product=product.code, datespan=datespan
            )
            counts[key] = count
            total = total + (count or 0)
        counts['total'] = total
        product.counts = counts    
    context.update({
        'location': location,
        'facilities': facilities,
        'facility_count': facilities.count(),
        'report': report,
        'products': products,
        'notifications': Notification.objects.filter(is_open=True, visible_to__user=request.user)
    })
    return render_to_response("logistics/summary.html", context, context_instance=RequestContext(request))
