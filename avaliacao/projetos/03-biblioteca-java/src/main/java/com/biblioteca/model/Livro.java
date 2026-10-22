package com.biblioteca.model;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.JoinTable;
import jakarta.persistence.ManyToMany;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.OneToMany;
import jakarta.persistence.Table;

/**
 * Obra do acervo. Um livro pode ter varios autores e um mesmo autor aparece em
 * varios livros -- dai a tabela de juncao livro_autor.
 */
@Entity
@Table(name = "livros")
public class Livro {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "isbn", length = 17, unique = true)
    private String isbn;

    @Column(name = "titulo", nullable = false, length = 250)
    private String titulo;

    @Column(name = "subtitulo", length = 250)
    private String subtitulo;

    @Column(name = "ano_publicacao")
    private Integer anoPublicacao;

    @Column(name = "numero_paginas")
    private Integer numeroPaginas;

    @Column(name = "preco_reposicao")
    private BigDecimal precoReposicao;

    @Column(name = "adquirido_em")
    private LocalDate adquiridoEm;

    @Column(name = "exemplares_totais", nullable = false)
    private Integer exemplaresTotais;

    @Column(name = "exemplares_disponiveis", nullable = false)
    private Integer exemplaresDisponiveis;

    @Column(name = "ativo")
    private Boolean ativo;

    @ManyToOne
    @JoinColumn(name = "editora_id")
    private Editora editora;

    @ManyToMany
    @JoinTable(
        name = "livro_autor",
        joinColumns = @JoinColumn(name = "livro_id"),
        inverseJoinColumns = @JoinColumn(name = "autor_id")
    )
    private List<Autor> autores = new ArrayList<>();

    @OneToMany(mappedBy = "livro")
    private List<Emprestimo> emprestimos = new ArrayList<>();

    public boolean disponivel() {
        return Boolean.TRUE.equals(ativo) && exemplaresDisponiveis > 0;
    }

    public void baixarExemplar() {
        if (exemplaresDisponiveis <= 0) {
            throw new IllegalStateException("Sem exemplar disponivel para o livro " + isbn);
        }
        exemplaresDisponiveis = exemplaresDisponiveis - 1;
    }

    public void devolverExemplar() {
        if (exemplaresDisponiveis < exemplaresTotais) {
            exemplaresDisponiveis = exemplaresDisponiveis + 1;
        }
    }

    public Long getId() {
        return id;
    }

    public String getTitulo() {
        return titulo;
    }

    public Editora getEditora() {
        return editora;
    }

    public List<Autor> getAutores() {
        return autores;
    }
}
