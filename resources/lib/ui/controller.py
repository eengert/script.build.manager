"""Allowlisted native menu routes; no engine or filesystem adapter."""
from enum import Enum

class Route(str, Enum):
    CREATE = 'create'
    INSTALL = 'install'
    REPAIR = 'repair'
    STATUS = 'status'
    SETTINGS = 'settings'
    HELP = 'help'

ROUTES = tuple(Route)
TITLE_IDS = tuple(range(32100, 32106))
CONTEXT_HELP = {Route.CREATE: 1, Route.INSTALL: 2, Route.REPAIR: 3,
                Route.STATUS: 4, Route.SETTINGS: 5}
