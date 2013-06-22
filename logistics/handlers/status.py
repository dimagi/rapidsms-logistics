#!/usr/bin/env python
# vim: ai ts=4 sts=4 et sw=4 encoding=utf-8

from rapidsms.contrib.handlers.handlers.keyword import KeywordHandler
from logistics.models import ProductReport
from logistics.util import config
from logistics.handlers import logistics_keyword

class Stop(KeywordHandler):
    """
    Stop handler for when a user wants to stop receiving reminders
    """

    keyword = logistics_keyword("sta|stat|status")
    
    def help(self):
        self.handle("")

    def handle(self, text):
        if self.msg.contact is None:
            self.respond(config.Messages.REGISTER_MESSAGE)
            return
        if self.msg.contact.role is None:
            self.respond("You have not been registered to a role. Please contact your DHIO or RHIO to fix your registration.")
            return
        if config.Responsibilities.REPORTEE_RESPONSIBILITY in self.msg.contact.role.responsibilities.values_list('code', flat=True):
            # if a super, show last report from your facility
            if self.msg.contact.supply_point is None:
                self.respond("You are not registered to a facility. Please contact your DHIO or RHIO for assistance.")
                return
            reports = ProductReport.objects.filter(supply_point=self.msg.contact.supply_point)
            if not reports:
                self.respond("Your facility has not submitted any stock reports yet.")
                return
            resp = "Last Report: '%(report)s' on %(date)s"
        else:
            # else if a reporter, show your last report
            reports = ProductReport.objects.filter(message__contact=self.msg.contact)
            if not reports:
                self.respond("You have not submitted any stock reports yet.")
                return
            resp = "You sent '%(report)s' on %(date)s "
        last_report = reports.order_by("-report_date")[0]
        if last_report.message is None:
            resp = "Last report:  %(quantity)s %(product)s %(type)s at %(facility)s, submitted on %(date)s from the website ewsghana.com"
            self.respond(resp % {'quantity': last_report.quantity, 
                                 'product': last_report.product, 
                                 'type': last_report.report_type, 
                                 'facility': last_report.supply_point, 
                                 'date': last_report.report_date.strftime('%h %d')})
            return
        self.respond(resp % {'report': last_report.message.text, 
                              'date': last_report.report_date.strftime('%h %d')})

