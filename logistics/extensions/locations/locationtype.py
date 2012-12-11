from __future__ import absolute_import
from django.db import models

class LocationType(models.Model):
    # 1 is first, 2 is next, etc.
    display_order = models.IntegerField(null=True)
    
    class Meta:
        abstract = True
