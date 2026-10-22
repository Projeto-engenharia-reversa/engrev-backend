"""Rotas do catalogo publico.

Consultas de listagem sao escritas em SQL direto: o ORM gerava N+1 nas paginas
de categoria e o tempo de resposta passava de 2s com o catalogo cheio.
"""

from flask import Blueprint, jsonify, render_template, request

from app.db import executar

catalogo_bp = Blueprint("catalogo", __name__)


@catalogo_bp.route("/produtos")
def listar_produtos():
    categoria = request.args.get("categoria")
    pagina = int(request.args.get("pagina", 1))
    limite = 24

    linhas = executar(
        "SELECT p.id, p.sku, p.nome, p.preco, p.estoque_atual, c.nome AS categoria "
        "FROM produtos p JOIN categorias c ON c.id = p.categoria_id "
        "WHERE p.ativo = TRUE AND c.slug = :slug "
        "ORDER BY p.nome",
        {"slug": categoria},
    )
    inicio = (pagina - 1) * limite
    return render_template("produto_lista.html", produtos=linhas[inicio : inicio + limite])


@catalogo_bp.route("/produtos/<int:produto_id>")
def detalhe_produto(produto_id):
    produto = executar(
        "SELECT id, sku, nome, descricao, preco, estoque_atual, categoria_id "
        "FROM produtos WHERE id = :id",
        {"id": produto_id},
    )
    if not produto:
        return jsonify({"erro": "produto nao encontrado"}), 404
    return render_template("produto_detalhe.html", produto=produto[0])


@catalogo_bp.route("/categorias")
def listar_categorias():
    linhas = executar(
        "SELECT id, nome, slug, ordem_exibicao FROM categorias "
        "WHERE ativa = TRUE ORDER BY ordem_exibicao, nome"
    )
    return jsonify(linhas)


@catalogo_bp.route("/estoque/baixo")
def estoque_baixo():
    """Usado pelo painel interno de reposicao."""
    linhas = executar(
        "SELECT sku, nome, estoque_atual, estoque_minimo, fornecedor_id "
        "FROM produtos WHERE estoque_atual < estoque_minimo AND ativo = TRUE "
        "ORDER BY estoque_atual"
    )
    return render_template("estoque_baixo.html", produtos=linhas)
