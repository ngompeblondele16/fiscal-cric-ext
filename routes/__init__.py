"""Enregistrement des routes de l'application."""
from routes import auth, main, import_routes, lists, export_routes


def register_blueprints(app):
    auth.register(app)
    main.register(app)
    import_routes.register(app)
    lists.register(app)
    export_routes.register(app)
