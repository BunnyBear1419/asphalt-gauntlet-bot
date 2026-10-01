"""RSL web control-center composition root."""
from .routes.core import CoreRoutesMixin
from .routes.admin import AdminRoutesMixin
from .routes.gauntlet import GauntletRoutesMixin
from .routes.tournament import TournamentRoutesMixin
from .routes.clubs import ClubsRoutesMixin
from .routes.calendar import CalendarRoutesMixin
from .routes.trust import TrustRoutesMixin
from .routes.auth import AuthRoutesMixin
from .routes.player import PlayerRoutesMixin
from .routes.public import PublicRoutesMixin

class WebControlCenter(CoreRoutesMixin, AdminRoutesMixin, GauntletRoutesMixin, TournamentRoutesMixin, ClubsRoutesMixin, CalendarRoutesMixin, TrustRoutesMixin, AuthRoutesMixin, PlayerRoutesMixin, PublicRoutesMixin):
    """Guild-aware player/staff web UI backed by the same MongoDB as Discord."""
    pass
