package com.biblioteca.controller;

import java.util.List;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.biblioteca.model.Emprestimo;
import com.biblioteca.service.EmprestimoService;

@RestController
@RequestMapping("/api/emprestimos")
public class EmprestimoController {

    private final EmprestimoService emprestimoService;

    public EmprestimoController(EmprestimoService emprestimoService) {
        this.emprestimoService = emprestimoService;
    }

    @PostMapping("/retirada")
    public ResponseEntity<Emprestimo> retirar(@RequestBody RetiradaRequest requisicao) {
        Emprestimo emprestimo = emprestimoService.registrarRetirada(
                requisicao.livroId(), requisicao.membroId(), requisicao.bibliotecarioId());
        return ResponseEntity.status(201).body(emprestimo);
    }

    @PostMapping("/{id}/devolucao")
    public ResponseEntity<Emprestimo> devolver(@PathVariable Long id) {
        return ResponseEntity.ok(emprestimoService.registrarDevolucao(id));
    }

    @GetMapping("/atrasados")
    public List<Emprestimo> atrasados() {
        return emprestimoService.atrasados();
    }

    @GetMapping("/multas-pendentes")
    public List<Emprestimo> multasPendentes() {
        return emprestimoService.multasPendentes();
    }

    public record RetiradaRequest(Long livroId, Long membroId, Long bibliotecarioId) {
    }
}
