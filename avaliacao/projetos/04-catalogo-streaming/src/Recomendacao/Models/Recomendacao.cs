using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Recomendacao.Models
{
    /// <summary>
    /// Perfil de gosto calculado pelo batch noturno a partir das reproducoes.
    /// </summary>
    public class PerfilGosto
    {
        [Key]
        public int Id { get; set; }

        public int AssinanteId { get; set; }

        public string GeneroPreferido { get; set; }

        public double IndiceDescoberta { get; set; }

        public double IndiceRepeticao { get; set; }

        public DateTime CalculadoEm { get; set; }

        public ICollection<Recomendacao> Recomendacoes { get; set; }
    }

    public class Recomendacao
    {
        [Key]
        public int Id { get; set; }

        [ForeignKey("Perfil")]
        public int PerfilGostoId { get; set; }

        public PerfilGosto Perfil { get; set; }

        public long FaixaId { get; set; }

        public decimal Pontuacao { get; set; }

        public string Motivo { get; set; }

        public bool Exibida { get; set; }

        public bool Aceita { get; set; }

        public DateTime GeradaEm { get; set; }
    }

    public class CampanhaEditorial
    {
        [Key]
        public int Id { get; set; }

        public string Titulo { get; set; }

        public string Curador { get; set; }

        public DateTime InicioEm { get; set; }

        public DateTime FimEm { get; set; }

        public bool Destaque { get; set; }
    }
}
