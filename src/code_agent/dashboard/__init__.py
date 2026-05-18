from code_agent.dashboard.metrics import DashboardMetrics, get_metrics
from code_agent.dashboard.routes import register_dashboard_routes

try:
    from code_agent.dashboard.server import DashboardServer
    __all__ = ["DashboardServer", "DashboardMetrics", "get_metrics", "register_dashboard_routes"]
except Exception:
    __all__ = ["DashboardMetrics", "get_metrics", "register_dashboard_routes"]
