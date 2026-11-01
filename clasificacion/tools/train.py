"""Entrenamiento del modelo de Clasificación.

Compara MultinomialNB y LogisticRegression (TF-IDF, validación cruzada de 5
particiones), evalúa el de mayor F1 macro en el conjunto de prueba y guarda
model/model.joblib y model/metrics.json, que carga el servicio al arrancar.

Conjunto de prueba: si data/test_set.csv tiene la columna category_revisada
completa, esas noticias (por url) no se usan para entrenar y su etiqueta real
es category_revisada. Si no, se usa un 20 % estratificado como prueba provisional.

Uso (desde la raíz del repositorio, con las versiones de requirements.txt):
    pip install -r clasificacion/requirements.txt
    git show origin/dataset:dataset.csv > clasificacion/data/dataset.csv
    python clasificacion/tools/train.py
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATASET_FILE = DATA_DIR / "dataset.csv"
TEST_FILE = DATA_DIR / "test_set.csv"
STOPWORDS_FILE = DATA_DIR / "stopwords_es.txt"
MODEL_DIR = ROOT / "model"
MODEL_PATH = MODEL_DIR / "model.joblib"
METRICS_PATH = MODEL_DIR / "metrics.json"

CATEGORIES = {"politica", "economia", "tecnologia", "deportes", "salud", "cultura", "internacional"}
SEED = 42


def load_stopwords() -> list[str]:
    lines = STOPWORDS_FILE.read_text(encoding="utf-8").splitlines()
    return [w.strip() for w in lines if w.strip() and not w.startswith("#")]


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_pipeline(clf, stopwords: list[str]) -> Pipeline:
    tfidf = TfidfVectorizer(stop_words=stopwords, ngram_range=(1, 2), sublinear_tf=True, min_df=2)
    return Pipeline([("tfidf", tfidf), ("clf", clf)])


def candidates() -> dict:
    # C=10 (menos regularización): con C=1 la confianza mediana era 0,35 y casi
    # todo quedaba bajo MIN_SCORE=0.5 como "otros", con F1 macro prácticamente igual.
    return {
        "MultinomialNB": MultinomialNB(),
        "LogisticRegression": LogisticRegression(max_iter=1000, class_weight="balanced", C=10),
    }


def split(dataset: list[dict]):
    """Devuelve (X_train, y_train, X_test, y_test, origen de la prueba)."""
    reviewed = read_csv(TEST_FILE) if TEST_FILE.exists() else []
    complete = reviewed and all(r.get("category_revisada", "").strip() for r in reviewed)
    if complete:
        invalid = {r["category_revisada"] for r in reviewed} - CATEGORIES
        if invalid:
            sys.exit(f"test_set.csv tiene categorías inválidas: {', '.join(sorted(invalid))}")
        test_urls = {r["url"] for r in reviewed}
        train = [r for r in dataset if r["url"] not in test_urls]
        return ([r["text"] for r in train], [r["category"] for r in train],
                [r["text"] for r in reviewed], [r["category_revisada"] for r in reviewed],
                "test_set.csv (revisado a mano)")

    print("AVISO: no hay test_set.csv con category_revisada completa; "
          "se usa un 20 % estratificado como prueba PROVISIONAL.\n")
    texts, labels = [r["text"] for r in dataset], [r["category"] for r in dataset]
    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, stratify=labels, random_state=SEED)
    return X_train, y_train, X_test, y_test, "20 % estratificado (provisional)"


def print_report(labels, per_category, macro, accuracy, matrix) -> None:
    width = max(len(c) for c in labels + ["macro"])
    print(f"{'categoría':<{width}}  precisión  recall     F1  soporte")
    for c in labels:
        m = per_category[c]
        print(f"{c:<{width}}  {m['precision']:9.3f}  {m['recall']:6.3f}  {m['f1']:5.3f}  {m['support']:7d}")
    print(f"{'macro':<{width}}  {macro['precision']:9.3f}  {macro['recall']:6.3f}  {macro['f1']:5.3f}")
    print(f"exactitud: {accuracy:.3f}\n")

    short = [c[:5] for c in labels]
    print("Matriz de confusión (filas = real, columnas = predicha)")
    print(" " * (width + 2) + " ".join(f"{s:>5}" for s in short))
    for c, row in zip(labels, matrix):
        print(f"{c:<{width}}  " + " ".join(f"{v:5d}" for v in row))


def main() -> None:
    if not DATASET_FILE.exists():
        sys.exit("Falta data/dataset.csv: git show origin/dataset:dataset.csv > clasificacion/data/dataset.csv")
    dataset = [r for r in read_csv(DATASET_FILE) if r["category"] in CATEGORIES]
    stopwords = load_stopwords()
    X_train, y_train, X_test, y_test, test_source = split(dataset)
    print(f"Entrenamiento: {len(X_train)} noticias · Prueba: {len(X_test)} ({test_source})\n")

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    cv_scores = {}
    print("Validación cruzada (5 particiones, F1 macro)")
    for name, clf in candidates().items():
        scores = cross_val_score(build_pipeline(clf, stopwords), X_train, y_train,
                                 cv=cv, scoring="f1_macro", n_jobs=-1)
        cv_scores[name] = {"mean": round(scores.mean(), 4), "std": round(scores.std(), 4)}
        print(f"  {name:<18} {scores.mean():.3f} ± {scores.std():.3f}")
    best = max(cv_scores, key=lambda n: cv_scores[n]["mean"])
    print(f"Elegido: {best}\n")

    model = build_pipeline(candidates()[best], stopwords).fit(X_train, y_train)
    predicted = model.predict(X_test)

    labels = sorted(set(y_train) | set(y_test))
    p, r, f, s = precision_recall_fscore_support(y_test, predicted, labels=labels, zero_division=0)
    per_category = {c: {"precision": round(float(p[i]), 4), "recall": round(float(r[i]), 4),
                        "f1": round(float(f[i]), 4), "support": int(s[i])}
                    for i, c in enumerate(labels)}
    mp, mr, mf, _ = precision_recall_fscore_support(y_test, predicted, labels=labels,
                                                    average="macro", zero_division=0)
    macro = {"precision": round(float(mp), 4), "recall": round(float(mr), 4), "f1": round(float(mf), 4)}
    accuracy = round(float(accuracy_score(y_test, predicted)), 4)
    matrix = confusion_matrix(y_test, predicted, labels=labels).tolist()

    print(f"Evaluación en el conjunto de prueba ({test_source})")
    print_report(labels, per_category, macro, accuracy, matrix)

    MODEL_DIR.mkdir(exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    metrics = {
        "algorithm": best,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "sklearn_version": sklearn.__version__,
        "train_size": len(X_train),
        "test_size": len(X_test),
        "test_source": test_source,
        "cv_f1_macro": cv_scores,
        "precision_macro": macro["precision"],
        "recall_macro": macro["recall"],
        "f1_macro": macro["f1"],
        "accuracy": accuracy,
        "per_category": per_category,
        "confusion_matrix": {"labels": labels, "matrix": matrix},
    }
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nGuardado {MODEL_PATH.relative_to(ROOT.parent)} y {METRICS_PATH.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()
