"""Fabrica da aplicacao Flask."""

from flask import Flask

from app.routes.catalogo import catalogo_bp
from app.routes.pedidos import pedidos_bp


def criar_app(config=None):
    app = Flask(__name__, template_folder="../templates")
    app.config.from_object(config or "app.config")

    app.register_blueprint(catalogo_bp)
    app.register_blueprint(pedidos_bp)

    @app.errorhandler(404)
    def nao_encontrado(_erro):
        return {"erro": "recurso nao encontrado"}, 404

    return app
