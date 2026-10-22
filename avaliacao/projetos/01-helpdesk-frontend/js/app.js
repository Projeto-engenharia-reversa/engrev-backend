/**
 * Logica de tela da central de chamados.
 *
 * Cada pagina chama o metodo correspondente no final do <body>. Nao ha
 * roteador: a navegacao e feita por links comuns entre os arquivos .html.
 */

const App = {
  autenticar(email, senha) {
    const tecnico = Storage.ler('tecnicos').find(function (t) {
      return t.email === email && t.ativo;
    });
    if (!tecnico) {
      alert('Tecnico nao encontrado ou inativo.');
      return;
    }
    if (senha.length < 6) {
      alert('Senha invalida.');
      return;
    }
    Storage.abrirSessao(tecnico);
    window.location.href = 'chamados.html';
  },

  async prepararFormularioChamado() {
    await Storage.semear();
    const sessao = Storage.sessaoAtual();
    if (sessao) {
      document.getElementById('session_id').value = sessao.session_id;
    }

    this.preencherSelect('cliente_id', Storage.ler('clientes'), function (c) {
      return c.nome_fantasia || c.razao_social;
    });
    this.preencherSelect('categoria_id', Storage.ler('categorias'), function (c) {
      return c.nome;
    });
    this.preencherSelect('tecnico_id', Storage.ler('tecnicos'), function (t) {
      return t.nome;
    });

    document.getElementById('protocolo').value = this.gerarProtocolo();

    const formulario = document.getElementById('form-chamado');
    formulario.addEventListener('submit', function (evento) {
      evento.preventDefault();
      App.salvarChamado(new FormData(formulario));
    });
  },

  preencherSelect(id, registros, rotulo) {
    const select = document.getElementById(id);
    if (!select) {
      return;
    }
    registros.forEach(function (registro) {
      const opcao = document.createElement('option');
      opcao.value = registro.id;
      opcao.textContent = rotulo(registro);
      select.appendChild(opcao);
    });
  },

  gerarProtocolo() {
    const agora = new Date();
    const ano = agora.getFullYear();
    const sequencial = String(Storage.proximoId('chamados')).padStart(5, '0');
    return 'CH-' + ano + '-' + sequencial;
  },

  salvarChamado(dados) {
    const chamado = new Chamado();
    chamado.protocolo = dados.get('protocolo');
    chamado.titulo = dados.get('titulo');
    chamado.descricao = dados.get('descricao');
    chamado.cliente_id = Number(dados.get('cliente_id'));
    chamado.categoria_id = Number(dados.get('categoria_id'));
    chamado.tecnico_id = Number(dados.get('tecnico_id')) || 0;
    chamado.prioridade = dados.get('prioridade');
    chamado.prazo_limite = dados.get('prazo_limite');
    chamado.horas_estimadas = Number(dados.get('horas_estimadas')) || 0;
    chamado.reincidente = dados.get('reincidente') === 'on';
    chamado.status = 'aberto';
    chamado.aberto_em = new Date().toISOString();

    Storage.inserir('chamados', chamado);
    window.location.href = 'chamados.html';
  },

  listarChamados() {
    const corpo = document.querySelector('#tabela-chamados tbody');
    if (!corpo) {
      return;
    }
    const chamados = Storage.ler('chamados');
    const clientes = Storage.ler('clientes');
    const categorias = Storage.ler('categorias');
    const tecnicos = Storage.ler('tecnicos');

    corpo.innerHTML = '';
    chamados.forEach(function (chamado) {
      const cliente = clientes.find(function (c) { return c.id === chamado.cliente_id; });
      const categoria = categorias.find(function (c) { return c.id === chamado.categoria_id; });
      const tecnico = tecnicos.find(function (t) { return t.id === chamado.tecnico_id; });

      const linha = document.createElement('tr');
      linha.innerHTML =
        '<td>' + chamado.protocolo + '</td>' +
        '<td>' + chamado.titulo + '</td>' +
        '<td>' + (cliente ? cliente.razao_social : '-') + '</td>' +
        '<td>' + (categoria ? categoria.nome : '-') + '</td>' +
        '<td>' + (tecnico ? tecnico.nome : 'nao atribuido') + '</td>' +
        '<td>' + chamado.prioridade + '</td>' +
        '<td>' + chamado.status + '</td>' +
        '<td>' + chamado.aberto_em.slice(0, 10) + '</td>';
      corpo.appendChild(linha);
    });

    document.getElementById('aviso-vazio').hidden = chamados.length > 0;
  },

  aplicarFiltros() {
    const status = document.getElementById('filtro-status').value;
    const prioridade = document.getElementById('filtro-prioridade').value;
    const busca = document.getElementById('filtro-busca').value.toLowerCase();

    const linhas = document.querySelectorAll('#tabela-chamados tbody tr');
    linhas.forEach(function (linha) {
      const texto = linha.textContent.toLowerCase();
      const casaStatus = !status || texto.indexOf(status) !== -1;
      const casaPrioridade = !prioridade || texto.indexOf(prioridade) !== -1;
      const casaBusca = !busca || texto.indexOf(busca) !== -1;
      linha.hidden = !(casaStatus && casaPrioridade && casaBusca);
    });
  },

  listarClientes() {
    const corpo = document.querySelector('#tabela-clientes tbody');
    if (!corpo) {
      return;
    }
    corpo.innerHTML = '';
    Storage.ler('clientes').forEach(function (cliente) {
      const linha = document.createElement('tr');
      linha.innerHTML =
        '<td>' + cliente.razao_social + '</td>' +
        '<td>' + cliente.cnpj + '</td>' +
        '<td>' + cliente.cidade + '/' + cliente.uf + '</td>' +
        '<td>' + (cliente.contrato_ativo ? 'ativo' : 'encerrado') + '</td>';
      corpo.appendChild(linha);
    });

    const formulario = document.getElementById('form-cliente');
    if (formulario) {
      formulario.addEventListener('submit', function (evento) {
        evento.preventDefault();
        App.salvarCliente(new FormData(formulario));
      });
    }
  },

  salvarCliente(dados) {
    const cliente = new Cliente();
    cliente.razao_social = dados.get('razao_social');
    cliente.nome_fantasia = dados.get('nome_fantasia');
    cliente.cnpj = dados.get('cnpj');
    cliente.email_contato = dados.get('email_contato');
    cliente.telefone = dados.get('telefone');
    cliente.cidade = dados.get('cidade');
    cliente.uf = dados.get('uf');
    cliente.cliente_desde = dados.get('cliente_desde');
    cliente.contrato_ativo = dados.get('contrato_ativo') === 'on';
    cliente.observacoes = dados.get('observacoes');

    Storage.inserir('clientes', cliente);
    window.location.reload();
  },

  calcularIndicadores() {
    const chamados = Storage.ler('chamados');
    const abertos = chamados.filter(function (c) { return c.status !== 'fechado'; });
    const fechados = chamados.filter(function (c) { return c.status === 'fechado'; });

    this.definirTexto('ind-abertos', abertos.length);
    this.definirTexto('ind-fechados', fechados.length);

    const foraSla = chamados.filter(function (c) {
      return c.prazo_limite && c.status !== 'fechado' && new Date(c.prazo_limite) < new Date();
    });
    this.definirTexto('ind-fora-sla', foraSla.length);

    if (fechados.length > 0) {
      const soma = fechados.reduce(function (total, c) { return total + (c.horas_gastas || 0); }, 0);
      this.definirTexto('ind-tempo-medio', (soma / fechados.length).toFixed(1) + 'h');
    }
  },

  definirTexto(id, valor) {
    const elemento = document.getElementById(id);
    if (elemento) {
      elemento.textContent = valor;
    }
  },

  exportarCsv() {
    const inicio = document.getElementById('periodo-inicio').value;
    const fim = document.getElementById('periodo-fim').value;
    window.location.href =
      'legacy/exportar_relatorio.php?inicio=' + inicio + '&fim=' + fim;
  }
};
