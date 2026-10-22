package com.biblioteca.repository;

import java.time.LocalDate;
import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import com.biblioteca.model.Emprestimo;

public interface EmprestimoRepository extends JpaRepository<Emprestimo, Long> {

    List<Emprestimo> findByMembroIdAndDevolvidoEmIsNull(Long membroId);

    List<Emprestimo> findByLivroId(Long livroId);

    @Query("SELECT e FROM Emprestimo e "
         + "WHERE e.devolvidoEm IS NULL AND e.previstoPara < :hoje "
         + "ORDER BY e.previstoPara")
    List<Emprestimo> listarAtrasados(@Param("hoje") LocalDate hoje);

    @Query("SELECT e FROM Emprestimo e "
         + "WHERE e.valorMulta > 0 AND e.multaPaga = false")
    List<Emprestimo> listarMultasPendentes();

    long countByMembroIdAndDevolvidoEmIsNull(Long membroId);
}
