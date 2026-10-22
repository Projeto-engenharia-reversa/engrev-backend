package com.biblioteca.model;

import java.util.ArrayList;
import java.util.List;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.OneToMany;
import jakarta.persistence.Table;

@Entity
@Table(name = "editoras")
public class Editora {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "nome", nullable = false, length = 150)
    private String nome;

    @Column(name = "cnpj", length = 18, unique = true)
    private String cnpj;

    @Column(name = "cidade", length = 120)
    private String cidade;

    @Column(name = "pais", length = 60)
    private String pais;

    @Column(name = "site", length = 200)
    private String site;

    @Column(name = "contato_email", length = 180)
    private String contatoEmail;

    @OneToMany(mappedBy = "editora")
    private List<Livro> livros = new ArrayList<>();

    public int totalDeTitulos() {
        return livros.size();
    }

    public Long getId() {
        return id;
    }

    public String getNome() {
        return nome;
    }
}
