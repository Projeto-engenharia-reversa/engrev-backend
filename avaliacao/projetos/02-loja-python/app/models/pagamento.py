"""Pagamentos de um pedido.

Um pedido pode ter mais de um pagamento: tentativa recusada seguida de nova
tentativa, ou pagamento parcial em vale-compra somado a cartao.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String

from app.models.base import Base


class Pagamento(Base):
    __tablename__ = "pagamentos"

    id = Column(Integer, primary_key=True)
    pedido_id = Column(Integer, ForeignKey("pedidos.id"), nullable=False)
    metodo = Column(String, nullable=False)
    status = Column(String, nullable=False)
    valor = Column(Float, nullable=False)
    parcelas = Column(Integer)
    bandeira = Column(String)
    ultimos_digitos = Column(String)
    codigo_autorizacao = Column(String)
    processado_em = Column(DateTime, default=datetime.utcnow)

    def aprovado(self):
        return self.status == "aprovado"
