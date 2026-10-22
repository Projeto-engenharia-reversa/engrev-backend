"""Cadastro de clientes e enderecos de entrega."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base


class Cliente(Base):
    __tablename__ = "clientes"

    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    cpf = Column(String, unique=True)
    telefone = Column(String)
    senha_hash = Column(String, nullable=False)
    aceita_newsletter = Column(Boolean)
    criado_em = Column(DateTime, default=datetime.utcnow)

    enderecos = relationship("Endereco", back_populates="cliente")
    pedidos = relationship("Pedido", back_populates="cliente")

    def nome_curto(self):
        return self.nome.split(" ")[0]


class Endereco(Base):
    __tablename__ = "enderecos"

    id = Column(Integer, primary_key=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    apelido = Column(String)
    logradouro = Column(String, nullable=False)
    numero = Column(String)
    complemento = Column(String)
    bairro = Column(String)
    cidade = Column(String, nullable=False)
    uf = Column(String, nullable=False)
    cep = Column(String, nullable=False)
    principal = Column(Boolean)

    cliente = relationship("Cliente", back_populates="enderecos")

    def formatado(self):
        return f"{self.logradouro}, {self.numero} - {self.bairro}, {self.cidade}/{self.uf}"
