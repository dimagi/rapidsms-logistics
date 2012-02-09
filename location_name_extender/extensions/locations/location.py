from __future__ import absolute_import
from django.db import models
from django.conf import settings

class Location(models.Model):
    name = models.CharField(max_length=100)
    
    class Meta:
        abstract = True
    
