package com.biblioteca.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import com.biblioteca.model.Livro;

public interface LivroRepository extends JpaRepository<Livro, Long> {

    Optional<Livro> findByIsbn(String isbn);

    List<Livro> findByEditoraId(Long editoraId);

    List<Livro> findByTituloContainingIgnoreCase(String trecho);

    @Query("SELECT l FROM Livro l WHERE l.exemplaresDisponiveis = 0 AND l.ativo = true")
    List<Livro> listarEsgotados();

    @Query("SELECT l FROM Livro l JOIN l.autores a WHERE a.id = :autorId")
    List<Livro> listarPorAutor(Long autorId);
}
