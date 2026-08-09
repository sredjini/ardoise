// api.ts — Le seul point de contact avec le backend.
import type { PipelineResult } from "./types";

// URL de l'API : configurable via Vite. En production full-stack, même origine.
const API_URL = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? "http://localhost:8000" : "");

// Appel JSON commun : messages d'erreur FR lisibles (serveur down, statut HTTP).
async function postJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("Serveur injoignable — vérifiez que l'API tourne (port 8000).");
  }
  if (res.status === 429) throw new Error("Trop de requêtes — réessayez dans un instant.");
  if (!res.ok) throw new Error(`Erreur serveur (${res.status}).`);
  return res.json();
}

// Envoie le transcript (issu de la voix / photo / texte) au pipeline d'agents
// et renvoie l'état final complet (extraction, codage, écriture, verdict…).
export function processTranscript(transcript: string): Promise<PipelineResult> {
  return postJson<PipelineResult>("/process", { transcript });
}

// Étape OCR : une photo de justificatif (data URL) → une dictée équivalente,
// qui alimente ensuite le MÊME cycle d'agents via processTranscript.
export function ocrImage(dataUrl: string): Promise<{ transcript: string }> {
  return postJson<{ transcript: string }>("/ocr", { image: dataUrl });
}
