def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def within_budget(tokens: int, budget: int) -> bool:
    return tokens <= budget


# Preço em USD por 1 milhão de tokens, na forma (entrada, saída).
#
# A chave é prefixo do nome do modelo, não substring solta: `"gemini" in model`
# não distingue `flash` de `flash-lite`, e a diferença entre os dois é de 2,5x na
# entrada e 1,5x na saída. Casar do mais específico para o mais genérico resolve
# isso sem uma entrada por variante.
#
# ATENÇÃO À DATA: o preço do `gemini-3.6-flash` (0,75/3,75) é promocional até
# 31/12/2026 e dobra em 2027. Está fixo aqui de propósito, e não interpolado por
# data, porque preço errado em silêncio é pior que preço desatualizado — quem
# revisar isto vê o número e a validade no mesmo lugar.
# Fonte: ai.google.dev/gemini-api/docs/pricing, consultado em 2026-08-25.
_PRECOS_POR_MILHAO: tuple[tuple[str, float, float], ...] = (
    ("claude", 3.00, 15.00),
    ("gpt", 1.50, 6.00),
    ("gemini-3.7-flash-lite", 0.30, 2.50),
    ("gemini-3.7-flash", 0.75, 3.75),
    ("gemini-3.6-flash-lite", 0.30, 2.50),
    ("gemini-3.6-flash", 0.75, 3.75),
    ("gemini-3.5-flash-lite", 0.30, 2.50),
    ("gemini-3.5-flash", 1.50, 9.00),
    ("gemini-3.1-flash-lite", 0.25, 1.50),
    ("gemini-3.1-pro", 2.00, 12.00),
    ("gemini-2.5-flash-lite", 0.10, 0.40),
    ("gemini-2.5-flash", 0.30, 2.50),
    ("gemini-2.5-pro", 1.25, 10.00),
)


def estimate_cost_usd(input_tokens: int, output_tokens: int, model: str = "") -> float:
    """Custo estimado de uma chamada, em dólares.

    Modelo desconhecido devolve 0.0 **de propósito**: um preço chutado entraria no
    banco com a mesma cara de um preço real, e `analysis_runs.total_cost_usd`
    existe justamente para responder quanto a análise custou. Zero é visivelmente
    ausente; um chute, não.

    Era esse o caso do Gemini até aqui — a tabela só tinha Claude e GPT, então
    toda run gravava zero. No tier gratuito isso era verdade; no pago, era falso.
    """
    entrada = saida = 0.0
    # Ordenado por comprimento decrescente: `gemini-3.6-flash-lite` precisa casar
    # antes de `gemini-3.6-flash`, que é prefixo dele.
    for prefixo, custo_entrada, custo_saida in sorted(
        _PRECOS_POR_MILHAO, key=lambda p: -len(p[0])
    ):
        if prefixo in model:
            entrada, saida = custo_entrada, custo_saida
            break
    return round(input_tokens * entrada / 1e6 + output_tokens * saida / 1e6, 6)
