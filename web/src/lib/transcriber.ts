// transcriber.ts
// ---------------------------------------------------------------------------
// Abstraction de la reconnaissance vocale (STT = Speech To Text).
//
// IDÉE CLÉ : le reste de l'app ne doit RIEN savoir de "qui" transcrit.
// Elle parle à une interface `Transcriber`. Aujourd'hui l'implémentation
// concrète utilise le Web Speech API du navigateur (gratuit, zéro infra).
// Demain, en production, on écrit une autre classe `GradiumTranscriber`
// (ou le moteur médical maison) qui respecte la MÊME interface — et on ne
// touche à aucune ligne de l'UI. C'est le principe d'inversion de dépendance.
// ---------------------------------------------------------------------------

// Ce que l'app attend d'un moteur de transcription, quel qu'il soit.
export interface Transcriber {
  // Démarre l'écoute du micro.
  start(): void;
  // Arrête l'écoute.
  stop(): void;
  // Callbacks branchés par l'app :
  //  - onPartial : texte en cours (instable, se réécrit à chaque mot) → aperçu live
  //  - onFinal   : segment stabilisé par le moteur → on l'ajoute au compte-rendu
  //  - onError   : remonter une erreur à l'UI
  onPartial: (text: string) => void;
  onFinal: (text: string) => void;
  onError: (message: string) => void;
}

// --- Types Web Speech API ---------------------------------------------------
// L'API SpeechRecognition n'est pas dans les types standards de TS, on la
// déclare a minima pour rester typé sans installer de dépendance.
interface SpeechRecognitionResult {
  0: { transcript: string };
  isFinal: boolean;
}
interface SpeechRecognitionEvent {
  resultIndex: number;
  results: { length: number; [i: number]: SpeechRecognitionResult };
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: (e: SpeechRecognitionEvent) => void;
  onerror: (e: { error: string }) => void;
  onend: () => void;
}
// Le constructeur est préfixé `webkit` sur Chrome.
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;
function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

// --- Implémentation navigateur ---------------------------------------------
export class WebSpeechTranscriber implements Transcriber {
  private recognition: SpeechRecognitionLike | null = null;
  private listening = false;

  onPartial: (text: string) => void = () => {};
  onFinal: (text: string) => void = () => {};
  onError: (message: string) => void = () => {};

  constructor(lang = "fr-FR") {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) {
      // Pas de support (Firefox p.ex.) — on laissera l'UI afficher un message.
      return;
    }
    const rec = new Ctor();
    rec.lang = lang;
    rec.continuous = true;      // ne s'arrête pas après une phrase
    rec.interimResults = true;  // on veut l'aperçu live (partial)

    rec.onresult = (e) => {
      // Le moteur peut renvoyer plusieurs segments d'un coup : on sépare
      // ce qui est "final" (stabilisé) de ce qui est encore "partial".
      let partial = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        const text = res[0].transcript;
        if (res.isFinal) this.onFinal(text);
        else partial += text;
      }
      if (partial) this.onPartial(partial);
    };

    rec.onerror = (e) => {
      // Erreur fatale (micro refusé, indisponible…) : on coupe le drapeau AVANT
      // que `onend` ne se déclenche, sinon on relancerait en boucle infinie.
      // "no-speech" est bénin (silence) → on laisse `onend` relancer.
      if (e.error !== "no-speech") this.listening = false;
      this.onError(e.error);
    };

    // Le navigateur coupe l'écoute tout seul après un silence : on relance
    // tant que l'utilisateur n'a pas cliqué "stop" (dictée longue = besoin réel).
    rec.onend = () => {
      if (this.listening) rec.start();
    };

    this.recognition = rec;
  }

  get supported(): boolean {
    return this.recognition !== null;
  }

  start(): void {
    if (!this.recognition) {
      this.onError("Reconnaissance vocale non supportée par ce navigateur.");
      return;
    }
    this.listening = true;
    this.recognition.start();
  }

  stop(): void {
    this.listening = false;
    this.recognition?.stop();
  }
}
