"""Pedidos e seus itens.

`itens_pedido` e a associativa entre `pedidos` e `produtos`, com atributos
proprios (quantidade e preco praticado no momento da compra) -- por isso e uma
entidade e nao uma tabela de juncao pura.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base

STATUS_PEDIDO = (
    "carrinho",
    "aguardando_pagamento",
    "pago",
    "separacao",
    "enviado",
    "entregue",
    "cancelado",
)


class Pedido(Base):
    __tablename__ = "pedidos"

    id = Column(Integer, primary_key=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    endereco_entrega_id = Column(Integer, ForeignKey("enderecos.id"))
    numero = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False)
    valor_frete = Column(Float)
    valor_total = Column(Float, nullable=False)
    observacoes = Column(Text)
    criado_em = Column(DateTime, default=datetime.utcnow)
    enviado_em = Column(DateTime)

    cliente = relationship("Cliente", back_populates="pedidos")
    itens = relationship("ItemPedido", back_populates="pedido")
    pagamentos = relationship("Pagamento", back_populates="pedido")

    def subtotal(self):
        return sum(item.total_linha() for item in self.itens)

    def pago(self):
        return any(p.status == "aprovado" for p in self.pagamentos)


class ItemPedido(Base):
    __tablename__ = "itens_pedido"

    id = Column(Integer, primary_key=True)
    pedido_id = Column(Integer, ForeignKey("pedidos.id"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    quantidade = Column(Integer, nullable=False)
    preco_unitario = Column(Float, nullable=False)

    pedido = relationship("Pedido", back_populates="itens")
    produto = relationship("Produto", back_populates="itens")

    def total_linha(self):
        return self.quantidade * self.preco_unitario
