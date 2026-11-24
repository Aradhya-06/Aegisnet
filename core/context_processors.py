from . import netenv

NAV = [
    ("core:dashboard", "speedometer2", "Dashboard"),
    ("monitoring:index", "activity", "Network Monitoring"),
    ("communication:index", "arrow-left-right", "TCP / UDP"),
    ("packet_analyzer:index", "search", "Packet Analyzer"),
    ("routing:index", "diagram-3", "Routing Visualizer"),
    ("simulation:index", "cpu", "NS2 Simulation"),
    #("recovery:index", "heart-pulse", "Fault & Recovery"),
    #("ml_extension:index", "graph-up", "ML Prediction (optional)"),
    #("core:about", "info-circle", "Documentation"),
]


def nav(request):
    match = getattr(request, "resolver_match", None)
    current, view = getattr(match, "app_name", ""), getattr(match, "view_name", "")
    # core hosts two pages (dashboard, about) so it must match on the exact view name
    items = [{"url": url, "icon": icon, "label": label,
              "active": view == url if url.startswith("core:") else url.split(":")[0] == current}
             for url, icon, label in NAV]
    return {"nav_items": items, "lab": netenv.lab_status()}
