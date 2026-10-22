"""Catalogo: produtos e suas categorias."""

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base


class Categoria(Base):
    __tablename__ = "categorias"

    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True)
    descricao = Column(Text)
    ordem_exibicao = Column(Integer)
    ativa = Column(Boolean)

    produtos = relationship("Produto", back_populates="categoria")


class Produto(Base):
    __tablename__ = "produtos"

    id = Column(Integer, primary_key=True)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=False)
    # O cadastro de fornecedores vive no ERP da matriz; aqui guardamos apenas o
    # codigo de referencia para conciliacao mensal.
    fornecedor_id = Column(Integer)
    sku = Column(String, nullable=False, unique=True)
    nome = Column(String, nullable=False)
    descricao = Column(Text)
    preco = Column(Float, nullable=False)
    peso_kg = Column(Float)
    estoque_atual = Column(Integer, nullable=False)
    estoque_minimo = Column(Integer)
    ativo = Column(Boolean)

    categoria = relationship("Categoria", back_populates="produtos")
    itens = relationship("ItemPedido", back_populates="produto")

    def disponivel(self, quantidade):
        return self.ativo and self.estoque_atual >= quantidade

    def abaixo_do_minimo(self):
        if self.estoque_minimo is None:
            return False
        return self.estoque_atual < self.estoque_minimo
