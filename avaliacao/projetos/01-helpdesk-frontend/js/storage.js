/**
 * Camada de persistencia sobre o localStorage.
 *
 * Cada "colecao" vira uma chave no localStorage contendo um array serializado.
 * Nao ha migracao de schema: se a estrutura mudar, o usuario limpa o navegador.
 */

const CHAVES = {
  chamados: 'helpdesk.chamados',
  clientes: 'helpdesk.clientes',
  tecnicos: 'helpdesk.tecnicos',
  categorias: 'helpdesk.categorias',
  comentarios: 'helpdesk.comentarios',
  sessao: 'helpdesk.sessao'
};

const Storage = {
  ler(colecao) {
    const bruto = localStorage.getItem(CHAVES[colecao]);
    if (!bruto) {
      return [];
    }
    try {
      return JSON.parse(bruto);
    } catch (erro) {
      console.error('Registro corrompido em ' + colecao, erro);
      return [];
    }
  },

  gravar(colecao, registros) {
    localStorage.setItem(CHAVES[colecao], JSON.stringify(registros));
  },

  proximoId(colecao) {
    const registros = this.ler(colecao);
    if (registros.length === 0) {
      return 1;
    }
    return Math.max.apply(null, registros.map(function (r) { return r.id; })) + 1;
  },

  inserir(colecao, registro) {
    const registros = this.ler(colecao);
    registro.id = this.proximoId(colecao);
    registros.push(registro);
    this.gravar(colecao, registros);
    return registro;
  },

  atualizar(colecao, registro) {
    const registros = this.ler(colecao);
    const indice = registros.findIndex(function (r) { return r.id === registro.id; });
    if (indice === -1) {
      return null;
    }
    registros[indice] = registro;
    this.gravar(colecao, registros);
    return registro;
  },

  remover(colecao, id) {
    const registros = this.ler(colecao).filter(function (r) { return r.id !== id; });
    this.gravar(colecao, registros);
  },

  buscarPorId(colecao, id) {
    return this.ler(colecao).find(function (r) { return r.id === id; }) || null;
  },

  /** Carrega os arquivos de exemplo em data/ na primeira execucao. */
  async semear() {
    if (this.ler('categorias').length > 0) {
      return;
    }
    const categoria = await fetch('data/categoria.json').then(function (r) { return r.json(); });
    const tecnico = await fetch('data/tecnico.json').then(function (r) { return r.json(); });
    this.inserir('categorias', categoria);
    this.inserir('tecnicos', tecnico);
  },

  sessaoAtual() {
    const bruto = localStorage.getItem(CHAVES.sessao);
    return bruto ? JSON.parse(bruto) : null;
  },

  abrirSessao(tecnico) {
    const sessao = {
      session_id: 'sess-' + Date.now(),
      tecnico_id: tecnico.id,
      iniciada_em: new Date().toISOString()
    };
    localStorage.setItem(CHAVES.sessao, JSON.stringify(sessao));
    return sessao;
  },

  encerrarSessao() {
    localStorage.removeItem(CHAVES.sessao);
  }
};
