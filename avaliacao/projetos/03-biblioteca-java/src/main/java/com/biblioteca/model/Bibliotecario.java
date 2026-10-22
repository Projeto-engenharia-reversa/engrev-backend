package com.biblioteca.model;

import java.time.LocalDate;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** Funcionario que registra retiradas e devolucoes no balcao. */
@Entity
@Table(name = "bibliotecarios")
public class Bibliotecario {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "matricula_funcional", nullable = false, length = 20, unique = true)
    private String matriculaFuncional;

    @Column(name = "nome", nullable = false, length = 180)
    private String nome;

    @Column(name = "email", nullable = false, length = 180)
    private String email;

    @Column(name = "turno", length = 20)
    private String turno;

    @Column(name = "admitido_em")
    private LocalDate admitidoEm;

    @Column(name = "ativo")
    private Boolean ativo;

    public Long getId() {
        return id;
    }

    public String getNome() {
        return nome;
    }
}
