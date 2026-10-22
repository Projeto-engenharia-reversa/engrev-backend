"""Acesso ao banco.

`executar` existe porque boa parte das listagens e escrita em SQL direto --
o ORM so e usado nas operacoes de escrita, onde o mapeamento compensa.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10)
Sessao = sessionmaker(bind=engine)


def executar(sql, parametros=None):
    """Roda uma consulta e devolve a lista de dicionarios."""
    with engine.connect() as conexao:
        resultado = conexao.execute(text(sql), parametros or {})
        return [dict(linha._mapping) for linha in resultado]


def sessao_escopo():
    sessao = Sessao()
    try:
        yield sessao
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()
