package com.biblioteca.model;

/** Categoria do membro, que define o limite de emprestimos simultaneos. */
public enum CategoriaMembro {

    ALUNO_GRADUACAO(3, 14),
    ALUNO_POS(5, 21),
    PROFESSOR(10, 30),
    SERVIDOR(5, 21),
    COMUNIDADE_EXTERNA(2, 7);

    private final int limiteSimultaneo;
    private final int diasDeEmprestimo;

    CategoriaMembro(int limiteSimultaneo, int diasDeEmprestimo) {
        this.limiteSimultaneo = limiteSimultaneo;
        this.diasDeEmprestimo = diasDeEmprestimo;
    }

    public int getLimiteSimultaneo() {
        return limiteSimultaneo;
    }

    public int getDiasDeEmprestimo() {
        return diasDeEmprestimo;
    }
}
