package com.biblioteca.model;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Enumerated;
import jakarta.persistence.EnumType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.OneToMany;
import jakarta.persistence.Table;

/** Pessoa habilitada a retirar livros do acervo. */
@Entity
@Table(name = "membros")
public class Membro {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "matricula", nullable = false, length = 20, unique = true)
    private String matricula;

    @Column(name = "nome", nullable = false, length = 180)
    private String nome;

    @Column(name = "email", nullable = false, length = 180)
    private String email;

    @Column(name = "cpf", length = 14, unique = true)
    private String cpf;

    @Column(name = "telefone", length = 20)
    private String telefone;

    @Column(name = "data_cadastro", nullable = false)
    private LocalDate dataCadastro;

    @Column(name = "validade_carteirinha")
    private LocalDate validadeCarteirinha;

    @Enumerated(EnumType.STRING)
    @Column(name = "categoria", length = 20)
    private CategoriaMembro categoria;

    @Column(name = "bloqueado")
    private Boolean bloqueado;

    @OneToMany(mappedBy = "membro")
    private List<Emprestimo> emprestimos = new ArrayList<>();

    public boolean podeEmprestar() {
        if (Boolean.TRUE.equals(bloqueado)) {
            return false;
        }
        if (validadeCarteirinha != null && validadeCarteirinha.isBefore(LocalDate.now())) {
            return false;
        }
        return emprestimosEmAberto() < categoria.getLimiteSimultaneo();
    }

    public long emprestimosEmAberto() {
        return emprestimos.stream().filter(e -> e.getDevolvidoEm() == null).count();
    }

    public Long getId() {
        return id;
    }

    public String getNome() {
        return nome;
    }

    public CategoriaMembro getCategoria() {
        return categoria;
    }
}
