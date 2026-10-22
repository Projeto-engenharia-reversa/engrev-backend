package com.biblioteca.repository;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import com.biblioteca.model.Membro;

public interface MembroRepository extends JpaRepository<Membro, Long> {

    Optional<Membro> findByMatricula(String matricula);

    Optional<Membro> findByCpf(String cpf);

    List<Membro> findByBloqueadoTrue();

    @Query("SELECT m FROM Membro m WHERE m.validadeCarteirinha < :data")
    List<Membro> listarCarteirinhasVencidas(@Param("data") LocalDate data);
}
