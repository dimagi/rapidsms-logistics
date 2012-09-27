#!/usr/bin/env python
# vim: ai ts=4 sts=4 et sw=4 encoding=utf-8

from __future__ import absolute_import
from django.conf.urls.defaults import *
from django.views.generic.simple import redirect_to
from logistics import views

urlpatterns = patterns('',
    url(r'^facility/?$',
       views.facility,                           
       name='facility_view'),
    url(r'^facility/(?P<pk>\d+)/edit/?$',
       views.facility,
       name='facility_edit'),
    url(r'^commodity/?$',
       views.commodity,                           
       name='commodity_view'),
    url(r'^commodity/(?P<pk>\d+)/edit/?$',
       views.commodity,
       name='commodity_edit'),
    url(r'^commodity/(?P<sms_code>\w+)/activate/?$',
       views.activate_commodity,
       name='commodity_activate'),
)
