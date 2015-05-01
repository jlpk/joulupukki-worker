from pecan import expose, redirect

from webob.exc import status_map

from joulupukki.worker.controllers.stats import StatsController



class RootController(object):
    stats = StatsController()
