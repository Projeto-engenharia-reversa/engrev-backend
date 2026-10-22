/**
 * Entidades do dominio da central de chamados.
 *
 * Nao ha backend: estes objetos sao serializados direto no localStorage pelo
 * storage.js. Os campos abaixo espelham exatamente o que os formularios de
 * novo-chamado.html e cliente.html enviam.
 */

class Chamado {
  id = 0;
  protocolo = '';
  titulo = '';
  descricao = '';
  cliente_id = 0;
  categoria_id = 0;
  tecnico_id = 0;
  prioridade = 'media';
  status = 'aberto';
  prazo_limite = '';
  horas_estimadas = 0;
  horas_gastas = 0;
  reincidente = false;
  aberto_em = '';
  fechado_em = '';

  estaAtrasado() {
    if (!this.prazo_limite || this.status === 'fechado') {
      return false;
    }
    return new Date(this.prazo_limite) < new Date();
  }

  descricaoCurta(limite) {
    const max = limite || 80;
    return this.descricao.length > max
      ? this.descricao.slice(0, max) + '...'
      : this.descricao;
  }
}

class Cliente {
  id = 0;
  razao_social = '';
  nome_fantasia = '';
  cnpj = '';
  email_contato = '';
  telefone = '';
  cidade = '';
  uf = '';
  cliente_desde = '';
  contrato_ativo = true;
  observacoes = '';

  rotulo() {
    return this.nome_fantasia || this.razao_social;
  }
}

class Tecnico {
  id = 0;
  nome = '';
  email = '';
  equipe = '';
  ramal = '';
  ativo = true;
  chamados_simultaneos = 5;

  temCapacidade(emAtendimento) {
    return emAtendimento < this.chamados_simultaneos;
  }
}

class Categoria {
  id = 0;
  nome = '';
  descricao = '';
  sla_horas = 24;
  ativo = true;
}

/** Historico de interacao dentro de um chamado. */
class Comentario {
  id = 0;
  chamado_id = 0;
  tecnico_id = 0;
  mensagem = '';
  visivel_cliente = false;
  criado_em = '';
}

const PRIORIDADES = ['baixa', 'media', 'alta', 'critica'];
const STATUS_CHAMADO = ['aberto', 'em_atendimento', 'aguardando_cliente', 'fechado'];
