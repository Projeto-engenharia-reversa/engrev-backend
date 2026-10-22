<?php
/**
 * Exportacao de relatorio em CSV.
 *
 * Sobrevivente da versao anterior do sistema, que rodava em PHP com MySQL.
 * Mantido apenas porque o setor financeiro depende do formato exato deste CSV.
 * Nao usa o localStorage do front novo -- le direto do banco legado.
 */

require_once __DIR__ . '/conexao.php';

$inicio = isset($_GET['inicio']) ? $_GET['inicio'] : date('Y-m-01');
$fim    = isset($_GET['fim'])    ? $_GET['fim']    : date('Y-m-d');

$sql = "SELECT c.protocolo,
               c.titulo,
               cl.razao_social,
               cat.nome AS categoria,
               t.nome AS tecnico,
               c.prioridade,
               c.status,
               c.horas_estimadas,
               c.horas_gastas,
               c.aberto_em,
               c.fechado_em
          FROM chamados c
          JOIN clientes cl   ON cl.id  = c.cliente_id
          JOIN categorias cat ON cat.id = c.categoria_id
     LEFT JOIN tecnicos t     ON t.id   = c.tecnico_id
         WHERE c.aberto_em BETWEEN ? AND ?
      ORDER BY c.aberto_em DESC";

$consulta = $conexao->prepare($sql);
$consulta->bind_param('ss', $inicio, $fim);
$consulta->execute();
$resultado = $consulta->get_result();

header('Content-Type: text/csv; charset=utf-8');
header('Content-Disposition: attachment; filename=chamados_' . $inicio . '_' . $fim . '.csv');

$saida = fopen('php://output', 'w');
fputcsv($saida, array(
    'Protocolo', 'Titulo', 'Cliente', 'Categoria', 'Tecnico',
    'Prioridade', 'Status', 'Horas estimadas', 'Horas gastas',
    'Aberto em', 'Fechado em'
), ';');

while ($linha = $resultado->fetch_assoc()) {
    fputcsv($saida, array_values($linha), ';');
}

fclose($saida);
$consulta->close();
$conexao->close();
