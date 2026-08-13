import { useEffect, useRef, useState } from "react";
import "./App.css";
import { WebSpeechTranscriber } from "./lib/transcriber";
import { processTranscript, ocrImage } from "./lib/api";
import type { PipelineResult, Source } from "./lib/types";

// ---------------------------------------------------------------------------
// App = orchestration côté front :
//   voix (transcriber) → transcript éditable → POST /process → affichage
//   du pipeline d'agents avec traçabilité (candidats RAG, confiance, verdict).
// ---------------------------------------------------------------------------

const EXEMPLES = [
  "taxi de la gare à l'hôtel, 34 euros, déplacement client Lyon",
  "déjeuner d'affaires avec un client, 82 euros au bistrot Marceau",
  "cartouches d'encre pour l'imprimante, 45 euros",
  "j'ai déjeuné avec un client au restaurant", // volontairement sans montant
];

export default function App() {
  const [transcript, setTranscript] = useState("");
  const [partial, setPartial] = useState("");
  const [listening, setListening] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [error, setError] = useState("");
  const [source, setSource] = useState<Source | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [zoom, setZoom] = useState(false);
  const [micSupported, setMicSupported] = useState(true);

  const transcriberRef = useRef<WebSpeechTranscriber | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const t = new WebSpeechTranscriber("fr-FR");
    t.onPartial = (txt) => setPartial(txt);
    t.onFinal = (seg) => {
      setPartial("");
      setSource("voix");
      setTranscript((prev) => (prev ? prev + " " : "") + seg.trim());
    };
    t.onError = (msg) => {
      if (msg === "no-speech" || msg === "aborted") return;
      setError(msg);
      setListening(false);
    };
    transcriberRef.current = t;
    setMicSupported(t.supported);
    return () => t.stop();
  }, []);

  // Fermeture de la lightbox au clavier (Échap) : accessibilité.
  useEffect(() => {
    if (!zoom) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setZoom(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoom]);

  const toggleMic = () => {
    setError("");
    const t = transcriberRef.current;
    if (!t || !t.supported) {
      setError("Reconnaissance vocale non supportée par ce navigateur (essayez Chrome).");
      return;
    }
    if (listening) {
      t.stop();
      setListening(false);
    } else {
      setListening(true);
      t.start();
    }
  };

  const traiter = async () => {
    if (!transcript.trim()) return;
    if (listening) toggleMic();
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const r = await processTranscript(transcript.trim());
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur inconnue");
    } finally {
      setLoading(false);
    }
  };

  // Source PHOTO : OCR du justificatif → transcript → même cycle d'agents.
  const runPhoto = async (dataUrl: string) => {
    setSource("photo");
    setPhotoPreview(dataUrl);
    setError("");
    setResult(null);
    setTranscript("");
    setLoading(true);
    try {
      const { transcript: t } = await ocrImage(dataUrl); // étape OCR
      setTranscript(t);
      const r = await processTranscript(t); // le cycle d'agents
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur inconnue");
    } finally {
      setLoading(false);
    }
  };

  const MAX_IMG = 6 * 1024 * 1024; // 6 Mo

  const readAndRun = (blob: Blob) => {
    if (blob.size > MAX_IMG) {
      setError("Image trop lourde (max 6 Mo).");
      return;
    }
    const rd = new FileReader();
    rd.onload = () => runPhoto(String(rd.result));
    rd.onerror = () => setError("Impossible de lire l'image.");
    rd.readAsDataURL(blob);
  };

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = ""; // permet de re-sélectionner le même fichier
    if (f) readAndRun(f);
  };

  // Charge le ticket d'exemple embarqué (démo instantanée).
  const loadTicket = async () => {
    try {
      const res = await fetch("/recu-exemple.png");
      if (!res.ok) throw new Error();
      readAndRun(await res.blob());
    } catch {
      setError("Ticket d'exemple introuvable.");
    }
  };

  // Onboarding : tant qu'on n'a rien lancé, on n'affiche QUE l'entrée + le guide
  // (pas la chaîne d'agents, trop chargée à l'arrivée). Dès « Traiter » → tout apparaît.
  const started = loading || result !== null;

  return (
    <div className={`app ${started ? "" : "is-onboard"}`}>
      <header className="topbar">
        <div className="brand">
          <span className="sq" />
          ARDOISE<span className="brand-med">/ dictée comptable agentique</span>
        </div>
        <div className="statusbar">
          <span className="live" role="status" aria-live="polite">
            <i />
            {loading ? "PROCESSING" : listening ? "REC" : "READY"}
          </span>
        </div>
      </header>

      <main className={`layout ${started ? "" : "onboard"}`}>
        {/* Colonne gauche : le CHOIX de la source (voix / photo / texte) */}
        <aside className="panel side">
          <div className="modes-label">ENTRÉE : 3 sources, 1 seul cycle</div>
          <div className="modes">
            <button
              className={`record ${listening ? "on" : ""}`}
              onClick={toggleMic}
              disabled={loading || !micSupported}
              title={micSupported ? "" : "Non supporté (essayez Chrome)"}
            >
              <span className="rec-icon" />
              {listening ? "Arrêter" : "🎙 Dicter"}
            </button>
            <button
              className="mode-photo"
              onClick={() => fileRef.current?.click()}
              disabled={loading}
            >
              📷 Photo
            </button>
          </div>
          <input ref={fileRef} type="file" accept="image/*" hidden onChange={onFile} />

          {photoPreview && (
            <div className="photo-preview">
              <button className="pp-img" onClick={() => setZoom(true)} title="Agrandir">
                <img src={photoPreview} alt="justificatif" />
                <span className="pp-zoom">⤢ agrandir</span>
              </button>
              <div className="pp-meta">
                <span className={`pp-ok ${transcript && !loading ? "" : "muted"}`}>
                  {loading ? "OCR…" : transcript ? "✓ extrait" : "-"}
                </span>
                <span className="pp-v2">v1 · un justificatif type : multi-formats en v2</span>
              </div>
            </div>
          )}

          {error && (
            <div className="error" role="alert">
              ⚠ {error}
            </div>
          )}

          <textarea
            className="transcript"
            aria-label="Dépense à traiter"
            value={transcript}
            onChange={(e) => {
              setTranscript(e.target.value);
              setSource("texte");
              setPhotoPreview(null);
            }}
            placeholder="…ou tapez la dépense ici."
          />
          <div className={`partial ${partial ? "show" : ""}`}>{partial || "…"}</div>

          <button className="process" onClick={traiter} disabled={loading || !transcript.trim()}>
            {loading ? "Traitement…" : "Traiter →"}
          </button>

          <div className="examples">
            <span>Exemples</span>
            {EXEMPLES.map((ex) => (
              <button
                key={ex}
                className="ex"
                disabled={loading}
                onClick={() => {
                  setTranscript(ex);
                  setSource("texte");
                  setPhotoPreview(null);
                }}
              >
                {ex}
              </button>
            ))}
            <button className="ex ticket" onClick={loadTicket} disabled={loading}>
              📷 ticket de caisse (exemple)
            </button>
          </div>
        </aside>

        {/* Colonne centrale : le livrable, puis le pipeline interactif */}
        <section className="panel main" aria-live="polite">
          {started ? (
            <Result source={source} loading={loading} result={result} />
          ) : (
            <Onboard />
          )}
        </section>
      </main>

      {/* Lightbox : le justificatif en grand (clic hors image ou Échap pour fermer) */}
      {zoom && photoPreview && (
        <div
          className="lightbox"
          role="dialog"
          aria-modal="true"
          aria-label="Justificatif agrandi"
          onClick={() => setZoom(false)}
        >
          <button className="lb-close" onClick={() => setZoom(false)}>
            ✕ fermer
          </button>
          <img src={photoPreview} alt="justificatif" onClick={(e) => e.stopPropagation()} />
        </div>
      )}
    </div>
  );
}

// Horloge live (signature 2xA : le fuseau/heure en barre de statut).

function Onboard() {
  return (
    <div className="onboard-guide">
      <h2>
        Dictez une dépense.
        <br />
        Obtenez l'écriture comptable.
      </h2>
      <p className="onboard-ex">
        Voix, photo ou texte : des agents l'extraient, trouvent le bon <strong>compte comptable</strong>
        {" "}et la vérifient. Vous validez.
      </p>
      <p className="onboard-out">
        Essayez : dites <em>«&nbsp;taxi, 34&nbsp;€&nbsp;»</em>.
      </p>
    </div>
  );
}

// --- La chaîne d'agents : rend le workflow lisible d'un coup d'œil ----------
const CHAIN_STEPS = [
  { key: "extract", n: "01", label: "Extraction" },
  { key: "code", n: "02", label: "Codage" },
  { key: "draft", n: "03", label: "Rédaction" },
  { key: "verify", n: "04", label: "Vérification" },
] as const;

// Doc pédagogique par étape : ce que ça fait (use case) + l'extrait de code réel.
// Clic sur un nœud de la chaîne → on affiche ce bloc.
const STEP_DOCS: Record<string, { title: string; use: string; file: string; code: string }> = {
  ocr: {
    title: "OCR : lire le justificatif",
    use: "Une photo de ticket est lue par un modèle vision (EU) qui en résume la dépense, comme une dictée. L'OCR n'est qu'une entrée de plus vers le même cycle.",
    file: "server/app/llm.py",
    code: `def ocr_expense(image_data_url: str) -> str:
    msg = HumanMessage(content=[
        {"type": "text", "text": _OCR_PROMPT},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ])
    return str(_vision_llm().invoke([msg]).content).strip()`,
  },
  extract: {
    title: "Extraction : comprendre la dépense",
    use: "Un LLM transforme le texte libre en champs structurés (marchand, motif, date, montant) et DÉCLARE ce qu'il ne sait pas (champs_manquants) au lieu de deviner.",
    file: "server/app/agents.py",
    code: `def extract_node(state: GraphState) -> dict:
    # structured() force le LLM à remplir le schéma Extraction
    result: Extraction = structured(Extraction).invoke(prompt)
    return {"extraction": result}
# Extraction impose: est_une_depense (rejet), champs_manquants (pas d'invention)`,
  },
  code: {
    title: "Codage : choisir le compte PCG (RAG + LLM)",
    use: "On récupère par similarité (RAG) les comptes candidats du Plan Comptable ; le LLM en choisit UN parmi eux ; le taux de TVA et la déductibilité viennent du RÉFÉRENTIEL, pas du LLM → il ne peut pas les inventer.",
    file: "server/app/agents.py",
    code: `def code_node(state: GraphState) -> dict:
    query = " ".join(filter(None, [ex.marchand, ex.motif])) or state.transcript
    candidates = get_referential().retrieve(query, k=4)        # ← RAG
    choice = structured(CodingChoice).invoke(prompt)           # ← LLM choisit LE compte
    entry = next((c for c in candidates
                  if c["compte"] == choice.compte), candidates[0])
    coding = Coding(
        compte=entry["compte"], libelle=entry["libelle"],
        tva_taux=float(entry["tva_usuelle"]),    # ← vient du référentiel
        deductible=bool(entry["deductible"]),
        justification=choice.justification, confidence=choice.confidence)
    return {"coding": coding, "retrieved": candidates}`,
  },
  draft: {
    title: "Rédaction : l'écriture comptable (déterministe)",
    use: "Les montants HT / TVA / TTC sont CALCULÉS en Python, jamais générés par le LLM. On ne laisse pas une IA faire l'arithmétique sur de l'argent.",
    file: "server/app/agents.py",
    code: `def draft_node(state: GraphState) -> dict:
    ttc, taux = ex.montant_ttc or 0.0, co.tva_taux or 0.0
    ht = round(ttc / (1 + taux / 100), 2)   # ← calcul, pas de LLM
    tva = round(ttc - ht, 2)
    return {"ecriture": Ecriture(compte_charge=co.compte,
            montant_ht=ht, montant_tva=tva, montant_ttc=round(ttc, 2), ...)}`,
  },
  verify: {
    title: "Vérification : agent de contrôle indépendant",
    use: "Un LLM SÉPARÉ contrôle l'ancrage et la cohérence. Il peut renvoyer corriger (la boucle) ; si un champ essentiel manque (montant), on escalade à l'humain : jamais d'invention.",
    file: "server/app/agents.py",
    code: `def verify_node(state: GraphState) -> dict:
    result: Verification = structured(Verification).invoke(prompt)
    if ex.montant_ttc is None:        # ← garde-fou déterministe
        result.needs_human = True
        result.ok = False
    return {"verification": result}`,
  },
};

// Après traitement, on montre EN PREMIER l'écriture produite + le verdict (le
// livrable), puis la chaîne d'agents comme une simple navigation. Cliquer une
// étape ouvre UNE fiche : ce que l'agent a produit + son code réel à la demande.
// Fini le double affichage (diagramme + 4 cartes) qui noyait l'utilisateur.
function Result({
  source,
  loading,
  result,
}: {
  source: Source | null;
  loading: boolean;
  result: PipelineResult | null;
}) {
  type NodeState = "idle" | "run" | "done" | "ok" | "warn" | "fail";

  const nodeState = (key: string): NodeState => {
    if (loading) return "run";
    if (!result) return "idle";
    if (key !== "verify") return "done";
    // Le nœud de vérif porte le statut global du pipeline.
    return result.status === "validated"
      ? "ok"
      : result.status === "needs_human"
      ? "warn"
      : "fail";
  };

  const [selected, setSelected] = useState<string | null>(null);

  // Sur fin de traitement, on ouvre UNE fiche (l'indice que les étapes sont
  // cliquables) — le codage RAG par défaut, ou l'extraction si rien n'a été codé.
  useEffect(() => {
    if (result && !loading) setSelected(result.coding ? "code" : "extract");
  }, [result, loading]);

  const inLabel = source ? source.toUpperCase() : "ENTRÉE";
  const inIcon = source === "voix" ? "🎙" : source === "photo" ? "📷" : "⌨";

  // Quand la source est une photo, un nœud OCR s'insère AVANT l'extraction.
  const steps =
    source === "photo"
      ? [{ key: "ocr", n: "··", label: "OCR" } as const, ...CHAIN_STEPS]
      : CHAIN_STEPS;

  return (
    <div className="result">
      {/* 1. LE LIVRABLE — écriture + verdict, tout de suite */}
      {result && <Outcome r={result} />}

      {/* 2. LE PIPELINE — stepper interactif (la navigation) */}
      <div className={`chain ${loading ? "is-run" : ""}`}>
        <div className="chain-row">
          <div className={`node in ${source ? "done" : "idle"}`}>
            <span className="node-ic">{inIcon}</span>
            <span className="node-l">{inLabel}</span>
          </div>
          {steps.map((s, i) => (
            <div className="node-group" key={s.key}>
              <span className="conn" style={{ animationDelay: `${i * 0.15}s` }}>
                ::▸
              </span>
              <button
                type="button"
                className={`node ${nodeState(s.key)} ${selected === s.key ? "sel" : ""}`}
                style={{ animationDelay: `${i * 0.2}s` }}
                onClick={() => setSelected(selected === s.key ? null : s.key)}
                aria-expanded={selected === s.key}
                title="Voir ce que fait cette étape"
              >
                <span className="node-n">{s.n}</span>
                <span className="node-l">{s.label}</span>
                <span className="node-s" />
              </button>
            </div>
          ))}
        </div>

        {/* La boucle de retry, dessinée sous la chaîne */}
        <div className="chain-loop">
          <span className="loop-arc" />
          <span className="loop-lbl">
            ↺ boucle de vérification : renvoi en correction si incohérent
            {result && result.retries > 0 ? ` · ${result.retries} exécutée(s)` : " · max 2"}
          </span>
        </div>
      </div>

      {loading && <div className="running">▚ traitement en cours…</div>}

      {/* 3. UNE fiche d'étape à la fois — données produites + code à la demande */}
      {result &&
        (selected ? (
          <StepDetail step={selected} r={result} onClose={() => setSelected(null)} />
        ) : (
          <div className="chain-hint">▸ clique une étape pour voir ce qu'elle produit + le code</div>
        ))}
    </div>
  );
}

// Le livrable : verdict + écriture comptable finale (ce que l'utilisateur obtient).
function Outcome({ r }: { r: PipelineResult }) {
  const cls = r.status === "validated" ? "ok" : r.status === "needs_human" ? "warn" : "fail";
  const label =
    r.status === "validated"
      ? "Écriture validée"
      : r.status === "needs_human"
      ? "À valider par un humain"
      : r.status === "rejected"
      ? "Entrée non reconnue comme une dépense"
      : "Échec";
  const e = r.ecriture;
  return (
    <div className={`outcome ${cls}`}>
      <div className="outcome-verdict">
        <span className="oc-dot" />
        <strong>{label}</strong>
        {r.retries > 0 && <span className="retries">{r.retries} correction(s)</span>}
      </div>
      {e && r.coding && (
        <div className="outcome-entry">
          <div className="oe-account">
            <span className="oe-num">{r.coding.compte}</span>
            <span className="oe-lib">{r.coding.libelle}</span>
          </div>
          <div className="oe-amounts">
            <span>
              <em>HT</em>
              {e.montant_ht.toFixed(2)} €
            </span>
            <span>
              <em>TVA</em>
              {e.montant_tva.toFixed(2)} €
            </span>
            <span className="oe-ttc">
              <em>TTC</em>
              {e.montant_ttc.toFixed(2)} €
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// Fiche d'une étape : ce que l'agent a produit (données) + pourquoi c'est fiable
// + le code réel, révélé à la demande (jamais un mur de code par défaut).
function StepDetail({
  step,
  r,
  onClose,
}: {
  step: string;
  r: PipelineResult;
  onClose: () => void;
}) {
  const doc = STEP_DOCS[step];
  const [showCode, setShowCode] = useState(false);
  useEffect(() => setShowCode(false), [step]); // on replie le code en changeant d'étape
  if (!doc) return null;

  return (
    <div className="step-doc">
      <div className="step-doc__head">
        <strong>{doc.title}</strong>
        <button type="button" className="step-doc__close" onClick={onClose}>
          ✕
        </button>
      </div>

      {/* Ce que cette étape a produit */}
      <div className="step-data">{stepData(step, r)}</div>

      {/* Pourquoi c'est fiable */}
      <p className="step-doc__use">{doc.use}</p>

      {/* Le code réel — à la demande, pas un mur par défaut */}
      <button
        type="button"
        className="code-toggle"
        onClick={() => setShowCode((s) => !s)}
        aria-expanded={showCode}
      >
        {showCode ? "▾ masquer le code" : "▸ voir le code réel"}
        <span className="code-file">{doc.file}</span>
      </button>
      {showCode && (
        <pre className="step-doc__code">
          <code>{doc.code}</code>
        </pre>
      )}
    </div>
  );
}

// Les données produites par une étape (rendu par clé, sans hooks).
function stepData(step: string, r: PipelineResult): React.ReactNode {
  if (step === "ocr") {
    return (
      <p className="step-note">
        Le texte lu sur le justificatif alimente exactement le même cycle qu'une dictée.
      </p>
    );
  }
  if (step === "extract" && r.extraction) {
    const ex = r.extraction;
    return (
      <>
        <div className="grid2">
          <Field k="Marchand" val={ex.marchand} />
          <Field k="Motif" val={ex.motif} />
          <Field k="Date" val={ex.date} />
          <Field k="Montant TTC" val={ex.montant_ttc != null ? `${ex.montant_ttc} €` : null} />
        </div>
        {ex.champs_manquants.length > 0 && (
          <div className="chips warn-chips">
            <span>Manquant :</span>
            {ex.champs_manquants.map((c) => (
              <span key={c} className="chip">
                {c}
              </span>
            ))}
          </div>
        )}
      </>
    );
  }
  if (step === "code" && r.coding) {
    return (
      <>
        <div className="coding-head">
          <div className="compte">{r.coding.compte}</div>
          <div className="compte-lib">
            <strong>{r.coding.libelle}</strong>
            <div className="tva-line">
              TVA {r.coding.tva_taux}% · {r.coding.deductible ? "déductible" : "non déductible"}
            </div>
          </div>
          <Confidence value={r.coding.confidence} />
        </div>
        <p className="justif">{r.coding.justification}</p>
        {r.retrieved.length > 0 && (
          <details className="trace">
            <summary>Traçabilité : {r.retrieved.length} candidats récupérés</summary>
            <ul>
              {r.retrieved.map((c) => (
                <li key={c.compte} className={c.compte === r.coding?.compte ? "chosen" : ""}>
                  <span className="c-num">{c.compte}</span>
                  <span className="c-lib">{c.libelle}</span>
                  <span className="c-score">{c.score}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </>
    );
  }
  if (step === "draft" && r.ecriture) {
    return (
      <>
        <table className="ecriture">
          <tbody>
            <tr>
              <td>{r.ecriture.compte_charge} · charge (HT)</td>
              <td className="num">{r.ecriture.montant_ht.toFixed(2)} €</td>
            </tr>
            <tr>
              <td>{r.ecriture.compte_tva} · TVA déductible</td>
              <td className="num">{r.ecriture.montant_tva.toFixed(2)} €</td>
            </tr>
            <tr className="total">
              <td>TTC</td>
              <td className="num">{r.ecriture.montant_ttc.toFixed(2)} €</td>
            </tr>
          </tbody>
        </table>
        <p className="lib-ecriture">{r.ecriture.libelle_ecriture}</p>
      </>
    );
  }
  if (step === "verify" && r.verification) {
    const v = r.verification;
    return v.ok && v.issues.length === 0 ? (
      <p className="verif-ok">✓ Cohérent, montants et TVA vérifiés, ancré dans la dictée.</p>
    ) : (
      <ul className="issues">
        {v.issues.map((i, idx) => (
          <li key={idx} className={i.severite}>
            <strong>{i.champ}</strong> : {i.probleme}
          </li>
        ))}
        {v.needs_human && <li className="human">→ Escalade à un validateur humain.</li>}
      </ul>
    );
  }
  return null;
}

// --- Petits composants -----------------------------------------------------
function Field({ k, val }: { k: string; val: string | null }) {
  return (
    <div className="field">
      <span className="f-k">{k}</span>
      <span className={`f-v ${val ? "" : "null"}`}>{val ?? "-"}</span>
    </div>
  );
}

function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="conf" title={`Confiance ${pct}%`}>
      <span className="conf-lbl">CONF</span>
      <div className="conf-track">
        <div className="conf-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="conf-txt">{pct}%</span>
    </div>
  );
}
