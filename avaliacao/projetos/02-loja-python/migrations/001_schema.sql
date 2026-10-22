-- Schema inicial da loja.
-- Aplicado em producao em 2023-02-14. Os modelos SQLAlchemy em app/models/
-- espelham estas tabelas, mas esta e a fonte de verdade do banco.

CREATE TABLE clientes (
    id                SERIAL PRIMARY KEY,
    nome              VARCHAR(180) NOT NULL,
    email             VARCHAR(180) NOT NULL UNIQUE,
    cpf               VARCHAR(14) UNIQUE,
    telefone          VARCHAR(20),
    senha_hash        VARCHAR(255) NOT NULL,
    aceita_newsletter BOOLEAN DEFAULT FALSE,
    criado_em         TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE enderecos (
    id          SERIAL PRIMARY KEY,
    cliente_id  INTEGER NOT NULL REFERENCES clientes (id),
    apelido     VARCHAR(60),
    logradouro  VARCHAR(200) NOT NULL,
    numero      VARCHAR(20),
    complemento VARCHAR(120),
    bairro      VARCHAR(120),
    cidade      VARCHAR(120) NOT NULL,
    uf          CHAR(2) NOT NULL,
    cep         VARCHAR(9) NOT NULL,
    principal   BOOLEAN DEFAULT FALSE
);

CREATE TABLE categorias (
    id             SERIAL PRIMARY KEY,
    nome           VARCHAR(120) NOT NULL,
    slug           VARCHAR(120) NOT NULL UNIQUE,
    descricao      TEXT,
    ordem_exibicao INTEGER DEFAULT 0,
    ativa          BOOLEAN DEFAULT TRUE
);

CREATE TABLE produtos (
    id             SERIAL PRIMARY KEY,
    categoria_id   INTEGER NOT NULL REFERENCES categorias (id),
    fornecedor_id  INTEGER,
    sku            VARCHAR(40) NOT NULL UNIQUE,
    nome           VARCHAR(200) NOT NULL,
    descricao      TEXT,
    preco          NUMERIC(10, 2) NOT NULL,
    peso_kg        NUMERIC(8, 3),
    estoque_atual  INTEGER NOT NULL DEFAULT 0,
    estoque_minimo INTEGER DEFAULT 0,
    ativo          BOOLEAN DEFAULT TRUE
);

CREATE TABLE pedidos (
    id                  SERIAL PRIMARY KEY,
    cliente_id          INTEGER NOT NULL REFERENCES clientes (id),
    endereco_entrega_id INTEGER REFERENCES enderecos (id),
    numero              VARCHAR(20) NOT NULL UNIQUE,
    status              VARCHAR(30) NOT NULL,
    valor_frete         NUMERIC(10, 2) DEFAULT 0,
    valor_total         NUMERIC(10, 2) NOT NULL,
    observacoes         TEXT,
    criado_em           TIMESTAMP NOT NULL DEFAULT NOW(),
    enviado_em          TIMESTAMP
);

CREATE TABLE itens_pedido (
    id             SERIAL PRIMARY KEY,
    pedido_id      INTEGER NOT NULL REFERENCES pedidos (id),
    produto_id     INTEGER NOT NULL REFERENCES produtos (id),
    quantidade     INTEGER NOT NULL,
    preco_unitario NUMERIC(10, 2) NOT NULL
);

CREATE TABLE pagamentos (
    id                  SERIAL PRIMARY KEY,
    pedido_id           INTEGER NOT NULL REFERENCES pedidos (id),
    metodo              VARCHAR(30) NOT NULL,
    status              VARCHAR(30) NOT NULL,
    valor               NUMERIC(10, 2) NOT NULL,
    parcelas            INTEGER DEFAULT 1,
    bandeira            VARCHAR(30),
    ultimos_digitos     CHAR(4),
    codigo_autorizacao  VARCHAR(60),
    processado_em       TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pedidos_cliente ON pedidos (cliente_id);
CREATE INDEX idx_itens_pedido ON itens_pedido (pedido_id);
CREATE INDEX idx_produtos_categoria ON produtos (categoria_id);
