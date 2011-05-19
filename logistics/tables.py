#!/usr/bin/env python
# vim: ai ts=4 sts=4 et sw=4


import settings
from django.core.urlresolvers import reverse
from djtables import Table, Column
from djtables.column import DateColumn

def _edit_link(cell):
    return reverse(
        'facility_edit',
        args=[cell.row.pk])
def _location(cell):
    return cell.object.location

class FacilityTable(Table):
    name = Column(link=_edit_link)
    location = Column(value=_location)

    class Meta:
        order_by = 'location'

def _edit_link(cell):
    return reverse(
        'commodity_edit',
        args=[cell.row.pk])
def _code(cell):
    return cell.object.sms_code
def _type(cell):
    return cell.object.type

class CommodityTable(Table):
    name = Column(link=_edit_link)
    sms_code = Column(value=_code)
    type = Column(value=_type)

    class Meta:
        order_by = 'name'

class ShortMessageTable(Table):

    date = DateColumn(format="H:i d/m/Y", sortable=False)
    text = Column(css_class="message", sortable=False)

    
