"""Checkout e acompanhamento de pedidos."""

from flask import Blueprint, jsonify, render_template, request, session

from app.db import executar
from app.models import ItemPedido, Pedido
from app.services import estoque, pagamento_gateway

pedidos_bp = Blueprint("pedidos", __name__)


@pedidos_bp.route("/pedidos")
def meus_pedidos():
    cliente_id = session.get("cliente_id")
    linhas = executar(
        "SELECT numero, status, valor_total, criado_em FROM pedidos "
        "WHERE cliente_id = :cliente ORDER BY criado_em DESC",
        {"cliente": cliente_id},
    )
    return render_template("pedido_lista.html", pedidos=linhas)


@pedidos_bp.route("/pedidos/<numero>")
def detalhe_pedido(numero):
    itens = executar(
        "SELECT i.quantidade, i.preco_unitario, p.nome, p.sku "
        "FROM itens_pedido i "
        "JOIN produtos p ON p.id = i.produto_id "
        "JOIN pedidos ped ON ped.id = i.pedido_id "
        "WHERE ped.numero = :numero",
        {"numero": numero},
    )
    return render_template("pedido_detalhe.html", itens=itens)


@pedidos_bp.route("/checkout", methods=["POST"])
def finalizar_compra():
    cliente_id = session.get("cliente_id")
    carrinho = request.get_json()

    for linha in carrinho["itens"]:
        if not estoque.reservar(linha["produto_id"], linha["quantidade"]):
            return jsonify({"erro": f"sem estoque para o produto {linha['produto_id']}"}), 409

    pedido = Pedido(
        cliente_id=cliente_id,
        endereco_entrega_id=carrinho["endereco_id"],
        numero=_proximo_numero(),
        status="aguardando_pagamento",
        valor_frete=carrinho["frete"],
        valor_total=carrinho["total"],
    )

    for linha in carrinho["itens"]:
        pedido.itens.append(
            ItemPedido(
                produto_id=linha["produto_id"],
                quantidade=linha["quantidade"],
                preco_unitario=linha["preco"],
            )
        )

    resultado = pagamento_gateway.cobrar(pedido, carrinho["pagamento"])
    if not resultado.aprovado:
        return jsonify({"erro": resultado.mensagem}), 402

    return jsonify({"numero": pedido.numero}), 201


@pedidos_bp.route("/relatorios/faturamento")
def faturamento_mensal():
    linhas = executar(
        "SELECT status, valor_total, valor_frete, criado_em FROM pedidos "
        "WHERE status IN ('pago', 'enviado', 'entregue')"
    )
    return jsonify(linhas)


def _proximo_numero():
    linhas = executar("SELECT numero FROM pedidos ORDER BY id DESC")
    if not linhas:
        return "PED-000001"
    ultimo = int(linhas[0]["numero"].split("-")[1])
    return f"PED-{ultimo + 1:06d}"
