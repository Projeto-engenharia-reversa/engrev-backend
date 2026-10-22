-- Campanha de cupons de desconto (2023-11).
-- Adiciona o rastro do desconto aplicado no pedido e renomeia a coluna de
-- observacoes, que passou a ser usada tambem pelo time de atendimento.

ALTER TABLE pedidos ADD COLUMN cupom_codigo VARCHAR(30);

ALTER TABLE pedidos ADD COLUMN valor_desconto NUMERIC(10, 2) DEFAULT 0;

ALTER TABLE pedidos RENAME COLUMN observacoes TO anotacoes_internas;

ALTER TABLE produtos ADD COLUMN preco_promocional NUMERIC(10, 2);

ALTER TABLE produtos DROP COLUMN peso_kg;
