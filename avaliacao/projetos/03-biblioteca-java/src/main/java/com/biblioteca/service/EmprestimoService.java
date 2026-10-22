package com.biblioteca.service;

import java.time.LocalDate;
import java.util.List;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.biblioteca.model.Emprestimo;
import com.biblioteca.model.Livro;
import com.biblioteca.model.Membro;
import com.biblioteca.repository.EmprestimoRepository;
import com.biblioteca.repository.LivroRepository;
import com.biblioteca.repository.MembroRepository;

@Service
public class EmprestimoService {

    private final EmprestimoRepository emprestimoRepository;
    private final LivroRepository livroRepository;
    private final MembroRepository membroRepository;

    public EmprestimoService(EmprestimoRepository emprestimoRepository,
                             LivroRepository livroRepository,
                             MembroRepository membroRepository) {
        this.emprestimoRepository = emprestimoRepository;
        this.livroRepository = livroRepository;
        this.membroRepository = membroRepository;
    }

    @Transactional
    public Emprestimo registrarRetirada(Long livroId, Long membroId, Long bibliotecarioId) {
        Livro livro = livroRepository.findById(livroId)
                .orElseThrow(() -> new IllegalArgumentException("Livro nao encontrado: " + livroId));
        Membro membro = membroRepository.findById(membroId)
                .orElseThrow(() -> new IllegalArgumentException("Membro nao encontrado: " + membroId));

        if (!livro.disponivel()) {
            throw new IllegalStateException("Nenhum exemplar disponivel");
        }
        if (!membro.podeEmprestar()) {
            throw new IllegalStateException("Membro sem direito a novo emprestimo");
        }

        livro.baixarExemplar();
        livroRepository.save(livro);

        Emprestimo emprestimo = new Emprestimo();
        return emprestimoRepository.save(emprestimo);
    }

    @Transactional
    public Emprestimo registrarDevolucao(Long emprestimoId) {
        Emprestimo emprestimo = emprestimoRepository.findById(emprestimoId)
                .orElseThrow(() -> new IllegalArgumentException("Emprestimo nao encontrado"));

        emprestimo.getLivro().devolverExemplar();
        livroRepository.save(emprestimo.getLivro());

        return emprestimoRepository.save(emprestimo);
    }

    public List<Emprestimo> atrasados() {
        return emprestimoRepository.listarAtrasados(LocalDate.now());
    }

    public List<Emprestimo> multasPendentes() {
        return emprestimoRepository.listarMultasPendentes();
    }
}
