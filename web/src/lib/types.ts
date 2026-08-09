// types.ts — Le miroir TypeScript des schémas Pydantic du backend.
// Ils doivent rester alignés : c'est le contrat entre le front et l'API.

// Source d'entrée d'une dépense (partagé entre App et Chain).
export type Source = "voix" | "photo" | "texte";

export interface Extraction {
  est_une_depense: boolean;
  marchand: string | null;
  motif: string | null;
  date: string | null;
  montant_ttc: number | null;
  tva_taux: number | null;
  champs_manquants: string[];
}

export interface Coding {
  compte: string;
  libelle: string;
  tva_taux: number;
  deductible: boolean;
  justification: string;
  confidence: number;
}

export interface Ecriture {
  compte_charge: string;
  montant_ht: number;
  compte_tva: string;
  montant_tva: number;
  montant_ttc: number;
  libelle_ecriture: string;
}

export interface Issue {
  champ: string;
  probleme: string;
  severite: "bloquant" | "avertissement";
}

export interface Verification {
  ok: boolean;
  issues: Issue[];
  needs_human: boolean;
  correction_hint: string | null;
}

// Un candidat RAG (pour la traçabilité : « d'où vient le choix de compte »).
export interface Retrieved {
  compte: string;
  libelle: string;
  exemples: string;
  tva_usuelle: number;
  deductible: boolean;
  regle?: string;
  score: number;
}

export interface PipelineResult {
  transcript: string;
  extraction: Extraction | null;
  coding: Coding | null;
  ecriture: Ecriture | null;
  verification: Verification | null;
  retrieved: Retrieved[];
  retries: number;
  status: "validated" | "needs_human" | "rejected" | "failed";
}
