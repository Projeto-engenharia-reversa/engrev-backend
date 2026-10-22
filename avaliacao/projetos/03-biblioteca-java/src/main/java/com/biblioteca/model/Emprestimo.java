package com.biblioteca.model;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;

/**
 * Retirada de um exemplar por um membro. A multa e calculada na devolucao e
 * congelada na coluna -- recalcular depois mudaria valores ja cobrados.
 */
@Entity
@Table(name = "emprestimos")
public class Emprestimo {

    private static final BigDecimal MULTA_POR_DIA = new BigDecimal("1.50");

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne
    @JoinColumn(name = "livro_id", nullable = false)
    private Livro livro;

    @ManyToOne
    @JoinColumn(name = "membro_id", nullable = false)
    private Membro membro;

    @ManyToOne
    @JoinColumn(name = "bibliotecario_id")
    private Bibliotecario bibliotecario;

    @Column(name = "retirado_em", nullable = false)
    private LocalDate retiradoEm;

    @Column(name = "previsto_para", nullable = false)
    private LocalDate previstoPara;

    @Column(name = "devolvido_em")
    private LocalDate devolvidoEm;

    @Column(name = "renovacoes")
    private Integer renovacoes;

    @Column(name = "valor_multa")
    private BigDecimal valorMulta;

    @Column(name = "multa_paga")
    private Boolean multaPaga;

    @Column(name = "observacao", length = 500)
    private String observacao;

    public boolean atrasado() {
        LocalDate referencia = devolvidoEm != null ? devolvidoEm : LocalDate.now();
        return referencia.isAfter(previstoPara);
    }

    public long diasDeAtraso() {
        if (!atrasado()) {
            return 0;
        }
        LocalDate referencia = devolvidoEm != null ? devolvidoEm : LocalDate.now();
        return ChronoUnit.DAYS.between(previstoPara, referencia);
    }

    public BigDecimal calcularMulta() {
        return MULTA_POR_DIA.multiply(BigDecimal.valueOf(diasDeAtraso()));
    }

    public LocalDate getDevolvidoEm() {
        return devolvidoEm;
    }

    public Livro getLivro() {
        return livro;
    }

    public Membro getMembro() {
        return membro;
    }
}
