import os
import tempfile
from tablib import Dataset
from datetime import datetime, timedelta
from celery.task import task
from django.core.servers.basehttp import FileWrapper
from django_tablib import ModelDataset, NoObjectsException
from rapidsms.contrib.messagelog.models import Message
from dimagi.utils.dates import DateSpan
from soil import CachedDownload
from soil.util import expose_download
from logistics.models import SupplyPoint, Product, ProductReport
from logistics.reports import ReportingBreakdown

@task
def task_export_messagelog(download_id, request, contact=None, expiry=10*60*60):
    try:
        class MessageDataSet(ModelDataset):
            class Meta:
                def _get_mds_queryset():
                    messages = Message.objects.order_by('-date')
                    if contact:
                        messages = messages.filter(contact__pk=contact)
                    else:
                        if request.location: 
                            messages = messages.filter(contact__supply_point__location__pk__in=\
                                [l.pk for l in request.location.get_descendants_plus_self()]).distinct()
                        if request.datespan:
                            start = request.datespan.computed_startdate
                            end = request.datespan.computed_enddate
                            messages = messages.filter(date__gte=start)\
                                               .filter(date__lte=end)
                    return messages
                queryset = _get_mds_queryset()
    except NoObjectsException:
        data = Dataset().xls
    else:
        data = MessageDataSet().xls
    expose_download(data, expiry, backend=CachedDownload, 
                    mimetype="application/octet-stream",
                    content_disposition='attachment; filename=export.xls',
                    download_id=download_id)

def _get_day_of_week(date, day_of_week):
    weekday_delta = day_of_week - date.weekday()
    return date + timedelta(days=weekday_delta)            

@task
def task_export_periodic_reporting(download_id, request, expiry=10*60*60):
    filename = 'periodic_reporting.xls'
    locations = [pk for pk in request.location.get_descendants_plus_self()]
    base_points = SupplyPoint.objects.filter(location__in=locations, active=True)
    fd, path = tempfile.mkstemp()
    with os.fdopen(fd, "w") as f:
        f.write(", ".join(["start of period", "end of period", "total num facilities", 
                           "# reporting", "# on time", "# late", "# non-reporting"]))
        f.write('\n')
        end_date = _get_day_of_week(datetime.now(), 3)
        start_date = end_date - timedelta(days=7)
        start_of_report = request.datespan.computed_startdate
        end_of_report = request.datespan.computed_enddate
        while start_of_report <= start_date: 
            if end_date >= end_of_report + timedelta(days=7):
                continue
            datespan = DateSpan(start_date, end_date)
            report = ReportingBreakdown(base_points, datespan,  
                                        include_late=True, days_for_late=5)
            late = report.reported_late.count()
            non_reporting = report.non_reporting.count()
            on_time = report.reported_on_time.count()
            total = base_points.count()
            st_list = map(unicode, [start_date, end_date, total, 
                                report.reported.count(), on_time, 
                                late, non_reporting])
            f.write("%s\n".decode('utf8') % ", ".join(st_list))
            end_date = start_date
            start_date = end_date - timedelta(days=7)
    expose_download(FileWrapper(file(path)), expiry,
                    mimetype="application/octet-stream",
                    content_disposition='attachment; filename=%s' % filename,
                    download_id=download_id)
    
@task
def task_export_periodic_stock(download_id, request, program=None, commodity=None, expiry=10*60*60):
    filename = 'periodic_stock.xls'
    fd, path = create_export_periodic_stock(request, program, commodity)
    expose_download(FileWrapper(file(path)), expiry,
                    mimetype="application/octet-stream",
                    content_disposition='attachment; filename=%s' % filename,
                    download_id=download_id)

def create_export_periodic_stock(request, program=None, commodity=None):
    fd, path = tempfile.mkstemp()
    with os.fdopen(fd, "w") as f:
        f.write(", ".join(["start of period", "end of period", "total facilities", 
                           "stock out", "low stock", "adequate stock", "overstock"]))
        f.write('\n')

        end_date = _get_day_of_week(datetime.now(), 3)
        start_date = end_date - timedelta(days=7)
        start_of_report = request.datespan.computed_startdate
        end_of_report = request.datespan.computed_enddate
        while start_of_report <= start_date: 
            if end_date >= end_of_report + timedelta(days=7):
                continue
            datespan = DateSpan(start_date, end_date)
            
            stockout = low = adequate = overstock = total = 0
            safe_add = lambda x, y: x + y if y is not None else x
            filtered_commodities = None
            if commodity:
                filtered_commodities = Product.objects.filter(is_active=True).filter(sms_code=commodity)
            elif program:
                filtered_commodities = Product.objects.filter(is_active=True).filter(type__code=program)
            if filtered_commodities:
                for commodity in filtered_commodities:
                    stockout = safe_add(stockout, 
                                        request.location.stockout_count(product=commodity, 
                                                                        datespan=datespan))
                    low = safe_add(low, 
                                        request.location.emergency_plus_low(product=commodity, 
                                                                            datespan=datespan))
                    adequate = safe_add(adequate, 
                                        request.location.good_supply_count(product=commodity, 
                                                                           datespan=datespan))
                    overstock = safe_add(overstock, 
                                        request.location.overstocked_count(product=commodity, 
                                                                           datespan=datespan))
                    total = stockout+low+adequate+overstock+safe_add(total, 
                            request.location.other_count(product=commodity, datespan=datespan))
            else:
                stockout = safe_add(stockout, 
                                    request.location.stockout_count(datespan=datespan))
                low = safe_add(low, 
                                    request.location.emergency_plus_low(datespan=datespan))
                adequate = safe_add(adequate, 
                                    request.location.good_supply_count(datespan=datespan))
                overstock = safe_add(overstock, 
                                    request.location.overstocked_count(datespan=datespan))
                total = stockout+low+adequate+overstock+safe_add(total, 
                        request.location.other_count(datespan=datespan))
            st_list = map(unicode, [start_date, end_date, total, stockout, low, adequate, overstock])
            f.write("%s\n".decode('utf8') % ", ".join(st_list))
            end_date = start_date 
            start_date = end_date - timedelta(days=7)
    return fd, path

@task
def task_export_reporting(download_id, request, program=None, commodity=None, expiry=10*60*60):
    fd, path = create_export_reporting_file(request, program, commodity)
    expose_download(FileWrapper(file(path)), expiry,
                    mimetype="application/octet-stream",
                    content_disposition='attachment; filename=export_reporting.xls',
                    download_id=download_id)

def create_export_reporting_file(request, program=None, commodity=None):
    # TODO: fix this to work even when there are commas in the name
    queryset = ProductReport.objects.filter(supply_point__location__in=\
                                            request.location.get_descendants(include_self=True))\
      .select_related("supply_point__name", "supply_point__location__parent__name", 
                      "supply_point__location__parent__parent__name", 
                      "product__name", "report_type__name", "message__text")
    if request.datespan: 
        start = request.datespan.computed_startdate
        end = request.datespan.computed_enddate
        queryset = queryset.filter(report_date__gte=start)\
                                   .filter(report_date__lte=end)
    if program and program != 'all':
        queryset = queryset.filter(product__type__code=program)
    if commodity and commodity != 'all': 
        queryset = queryset.filter(product__sms_code=commodity)
    queryset = queryset.order_by('report_date')
    fd, path = tempfile.mkstemp()
    with os.fdopen(fd, "w") as f:
        f.write(", ".join(['ID', 'Location Grandparent', 'Location Parent', 'Facility', 
                         'Commodity', 'Report Type', 
                         'Quantity', 'Date',  'Message']))
        f.write("\n")
        for q in queryset:
            parent = q.supply_point.location.parent.name \
                if q.supply_point.location.parent else None
            grandparent = q.supply_point.location.parent.parent.name \
                if q.supply_point.location.parent.parent else None
            message = q.message.text if q.message else None
            st_list = map(unicode, [q.id, grandparent, parent, q.supply_point.name, 
                                    q.product.name, q.report_type.name, q.quantity, 
                                    q.report_date, message])
            f.write("%s\n".decode('utf8') % ", ".join(st_list))
    return fd, path
