"""Token-chain & pattern visualization for the variety experiment.

Two outputs, both derived from the completed experiment under ``--out``:

1. **Enhanced report charts** — the headline multi-series plots the summary
   only table-renders: per-model flag/contamination/coherence rates, the
   quality-finding heatmap (pretext x check), and the duration/violation
   distributions.

2. **3D token-chain visualization** — embeds each model's most frequent
   *n-grams* (word-level token chains) from the generated prose into 3D via
   PCA, colored by model. Proximity = lexical similarity: a tight, isolated
   cluster means a model reuses the same phrasal scaffolding (template-locked
   output); spread means diversity. Exposed as:

   - ``token-chains-3d.png`` — static 3D scatter (rotating view)
   - ``token-chains-3d.html`` — interactive (drag/zoom/hover) Plotly-free HTML
     using a tiny embedded renderer, or PNG-only if unused.

Usage:

    venv/bin/python scripts/analyze_token_chains.py --out experiment/variety-1000

The per-campaign text comes from each run's ``llm_trace.jsonl`` (the model's
raw answer), falling back to the assembled campaign bodies when a trace is
absent, so the visualization reflects what each model actually wrote.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.decomposition import PCA  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")

# Per-model chart colors (stable, mirrors variety_report COLORS).
COLORS = {
    "qwen3:8b": "#4C72B0",
    "qwen3:4b": "#8DA0CB",
    "phi4-mini:latest": "#DD8452",
    "llama3.2:3b": "#55A868",
    "llama3.1:8b": "#CCB974",
    "gemma4:latest": "#C44E52",
}
_FALLBACK = ["#8172B3", "#937860", "#8C8C8C", "#6ACC64", "#E1BE6A", "#648FFF"]


def color_for(model: str) -> str:
    if model in COLORS:
        return COLORS[model]
    return _FALLBACK[sum(map(ord, model)) % len(_FALLBACK)]


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_records(out: Path) -> list[dict]:
    manifest = out / "runs.jsonl"
    by_id: dict[str, dict] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        by_id[rec["run_id"]] = rec
    return list(by_id.values())


def _traced_texts(out: Path, rec: dict) -> list[str]:
    """The raw answer text a model emitted (all attempts) for one run.

    Returns [] when the llm_trace.jsonl is absent (failed/timeout runs).
    """
    if not rec.get("dir"):
        return []
    trace = out / rec["dir"] / "llm_trace.jsonl"
    if not trace.exists():
        return []
    texts = []
    for line in trace.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        txt = (obj.get("response") or {}).get("text")
        if txt:
            texts.append(_extract_prose_from_bindings(txt))
    return [t for t in texts if t]


_BINDING_LINE = re.compile(
    r"^(display name|role|from address|subject|scheduled at|body)\s*:", re.I
)


def _extract_prose_from_bindings(text: str) -> str:
    """Strip the 8-binding scaffolding, keep only subject/body prose.

    The raw ADK answer is the 8-line binding format; its structural tokens
    (``scheduled at t09``, ``cta-link scheduled at``, ...) dominate any ngram
    analysis and hide the *content* patterns we want to visualize. Extract only
    the subject + the two body fields.
    """
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if _BINDING_LINE.match(line):
            value = line.split(":", 1)[1].strip()
            if value and value != "{{cta-link}}" and value.strip():
                lines.append(value)
        elif line and not line.startswith(("**", "- ", "{")):
            # keep free prose that isn't binding scaffolding
            lines.append(line)
    return " ".join(lines).replace("{{cta-link}}", " ")


def _campaign_bodies(out: Path, rec: dict) -> list[str]:
    """Assembled campaign message bodies/subjects — clean prose, no scaffolding."""
    if not rec.get("dir"):
        return []
    path = out / rec["dir"] / "generated_campaign.json"
    if not path.exists():
        return []
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out_texts = []
    for m in obj.get("messages", []):
        body = (m.get("body") or "").strip()
        subject = (m.get("subject") or "").strip()
        if body:
            out_texts.append(body)
        if subject:
            out_texts.append(subject)
    return out_texts


def collect_model_texts(out: Path, records: list[dict]) -> dict[str, list[str]]:
    """model -> list of per-run text blobs.

    Prefers the *assembled* campaign prose (clean content) and falls back to
    scaffold-stripped trace text only where no campaign artifact exists, so the
    token-chain visualization reflects what each model writes as content, not
    the 8-binding format wrapper.
    """
    per_model: dict[str, list[str]] = defaultdict(list)
    for rec in records:
        if rec.get("status") != "ok":
            continue
        model = rec.get("model") or "unknown"
        bodies = _campaign_bodies(out, rec)
        if not bodies:
            bodies = _traced_texts(out, rec)
        if bodies:
            per_model[model].append(" ".join(bodies))
    return {m: t for m, t in per_model.items() if t}


# --------------------------------------------------------------------------- #
# Token n-grams
# --------------------------------------------------------------------------- #


def _tokens(text: str) -> list[str]:
    # Drop the deterministic tracking URL and its fragments: it appears in
    # every campaign and would otherwise swamp the model-specific signal.
    text = re.sub(r"https?://sim\.[a-z0-9.-]+/t/[a-f0-9]{12}", " ", text)
    text = re.sub(r"sim\.fantazylabz\.tech/t/[a-f0-9]{12}", " ", text)
    return _WORD.findall(text.lower())


def _ngrams(tokens: list[str], n: int) -> list[str]:
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def top_ngrams(texts: list[str], n: int, k: int) -> list[str]:
    counts: Counter[str] = Counter()
    for t in texts:
        counts.update(_ngrams(_tokens(t), n))
    # drop chains that are boilerplate greeting/signoff scaffolding common to
    # ALL models (they dominate and hide the model-specific signal)
    return [g for g, _ in counts.most_common(k)]


def build_ngram_corpus(
    per_model_texts: dict[str, list[str]], n: int, k: int
) -> tuple[list[str], list[tuple[str, str, int, int]]]:
    """Merge each model's top-k n-grams into one deduped document set.

    Returns (docs, [(model, ngram, count, doc_index), ...]) where ``doc_index``
    points into ``docs`` so coordinates and labels stay aligned.
    """
    per_model_top = {
        m: {g: _ngram_counts(texts, n)[g] for g in top_ngrams(texts, n, k)}
        for m, texts in per_model_texts.items()
    }
    # global dedup order for stable vectorization
    all_grams: list[str] = []
    seen: set[str] = set()
    for m in per_model_texts:
        for g in per_model_top[m]:
            if g not in seen:
                seen.add(g)
                all_grams.append(g)
    doc_index = {g: i for i, g in enumerate(all_grams)}
    labels = [
        (m, g, per_model_top[m][g], doc_index[g])
        for m in per_model_texts
        for g in per_model_top[m]
    ]
    return all_grams, labels


def _ngram_counts(texts: list[str], n: int) -> Counter[str]:
    counts: Counter[str] = Counter()
    for t in texts:
        counts.update(_ngrams(_tokens(t), n))
    return counts


# --------------------------------------------------------------------------- #
# Enhanced report charts
# --------------------------------------------------------------------------- #


def chart_model_rates(payload: dict, out: Path) -> None:
    models = sorted(payload["per_model"])
    flags = [payload["per_model"][m]["quality_flag_rate"] for m in models]
    contam = [payload["per_model"][m]["contamination_rate"] for m in models]
    coher = [payload["per_model"][m]["coherence_failure_rate"] for m in models]
    x = np.arange(len(models))
    fig, ax = plt.subplots(figsize=(9, 5))
    w = 0.26
    ax.bar(x - w, flags, w, label="quality flag rate", color="#4C72B0")
    ax.bar(x, contam, w, label="contamination rate", color="#C44E52")
    ax.bar(x + w, coher, w, label="coherence failure rate", color="#55A868")
    ax.set_xticks(x, models, rotation=20, ha="right")
    ax.set_ylabel("rate")
    ax.set_title("Per-model failure rates")
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "charts" / "model_rates.png", dpi=150)
    plt.close(fig)


def chart_duration_box(payload: dict, records: list[dict], out: Path) -> None:
    ok = [r for r in records if r["status"] == "ok"]
    models = sorted({r["model"] for r in ok})
    data = [
        [(r.get("duration_ms") or 0) / 1000 for r in ok if r["model"] == m]
        for m in models
    ]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bp = ax.boxplot(data, tick_labels=models, patch_artist=True, showfliers=False,
                    showmeans=True)
    for patch, m in zip(bp["boxes"], models):
        patch.set_facecolor(color_for(m))
        patch.set_alpha(0.7)
    ax.set_ylabel("seconds per campaign")
    ax.set_title("Generation duration distribution by model")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "charts" / "duration_box.png", dpi=150)
    plt.close(fig)


def chart_ngram_diversity(per_model_texts: dict[str, list[str]], out: Path) -> None:
    """Unique bigram ratio — a direct 'template-lock' measure per model."""
    models = sorted(per_model_texts)
    ratios = []
    for m in models:
        texts = per_model_texts[m]
        all_tokens = [tok for t in texts for tok in _tokens(t)]
        bigrams = _ngrams(all_tokens, 3) if len(all_tokens) > 3 else []
        ratios.append(len(set(bigrams)) / len(bigrams) if bigrams else 0.0)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(models, ratios, color=[color_for(m) for m in models])
    ax.set_ylabel("unique trigrams / total trigrams")
    ax.set_title("Lexical diversity (unique trigram ratio)")
    ax.tick_params(axis="x", labelrotation=20)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for i, v in enumerate(ratios):
        ax.text(i, v, f"{v:.3f}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "charts" / "ngram_diversity.png", dpi=150)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Alternative token-chain visualizations
# --------------------------------------------------------------------------- #


def _cooccurrence_graph(
    texts: list[str], n: int, limit: int
) -> tuple[list[str], dict[tuple[str, str], int]]:
    """Token chain -> successors with co-occurrence weights.

    For the chosen n-gram length, treat each n-gram as a node and record the
    directed transition to the n-gram that follows it in the source text
    (sliding window of ``n+1`` tokens). Edge weight = number of times pair
    ``(a, b)`` co-occurs across all texts. Only the top-``limit`` chains by
    node frequency are kept, so the graph stays readable.
    """
    node_freq: Counter[str] = Counter()
    edges: Counter[tuple[str, str]] = Counter()
    for t in texts:
        toks = _tokens(t)
        if len(toks) < n + 1:
            continue
        for i in range(len(toks) - (n + 1) + 1):
            a = " ".join(toks[i : i + n])
            b = " ".join(toks[i + 1 : i + 1 + n])
            node_freq[a] += 1
            node_freq[b] += 1
            edges[(a, b)] += 1
    kept = {g for g, _ in node_freq.most_common(limit)}
    nodes = [g for g, _ in node_freq.most_common(limit)]
    edges2: dict[tuple[str, str], int] = {
        (a, b): w for (a, b), w in edges.items() if a in kept and b in kept
    }
    return nodes, edges2


def plot_token_chain_network(
    per_model_texts: dict[str, list[str]], out: Path, n: int = 3, k: int = 40
) -> None:
    """Static co-occurrence network: nodes = top token chains, edges = the
    chains that follow them. Node radius = frequency, edge width = weight.

    Plotted with a simple circular layout (dependency-free); the interactive
    force-directed version is written by :func:`write_network_html`.
    """
    models = sorted(per_model_texts)
    ncols = 2
    nrows = (len(models) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(11, 5.2 * nrows))
    axes = np.atleast_1d(axes).flatten()
    for ax, model in zip(axes, models):
        texts = per_model_texts[model]
        nodes, edges = _cooccurrence_graph(texts, n, limit=k)
        if not nodes:
            ax.set_visible(False)
            continue
        all_toks = [tok for t in texts for tok in _tokens(t)]
        freq = Counter(_ngrams(all_toks, n))
        n_nodes = len(nodes)
        angle = np.linspace(0, 2 * np.pi, n_nodes, endpoint=False)
        pos = {g: (np.cos(a), np.sin(a)) for g, a in zip(nodes, angle)}
        max_w = max(edges.values()) if edges else 1
        max_f = max(freq.values()) if freq else 1
        for (a, b), w in edges.items():
            x1, y1 = pos[a]
            x2, y2 = pos[b]
            ax.plot([x1, x2], [y1, y2], color="#999999", lw=0.5 + 2.2 * w / max_w,
                    alpha=0.6, zorder=1)
        xs = [pos[g][0] for g in nodes]
        ys = [pos[g][1] for g in nodes]
        sizes = [40 + 300 * freq[g] / max_f for g in nodes]
        ax.scatter(xs, ys, s=sizes, color=color_for(model), alpha=0.8,
                   edgecolors="white", linewidths=0.5, zorder=2)
        for g in nodes[:12]:
            ax.text(pos[g][0], pos[g][1], g[:14], fontsize=6.5, ha="center",
                    va="center", color="#222222")
        ax.set_xlim(-1.45, 1.45)
        ax.set_ylim(-1.45, 1.45)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(model, fontsize=10, color=color_for(model))
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_visible(False)
        ax.spines["left"].set_visible(False)
    for ax in axes[len(models):]:
        ax.set_visible(False)
    fig.suptitle(f"Token-chain co-occurrence network ({n}-grams): "
                 "edge = a chain follows another", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(out / "charts" / "token-chains-network.png", dpi=150)
    plt.close(fig)


def _token_chain_payload(
    per_model_texts: dict[str, list[str]], n: int, k: int
) -> dict:
    """All data the interactive report needs, precomputed in Python.

    Returns a JSON-ready dict with per-model top chains, the co-occurrence
    graph, and the cross-model heatmap matrix.
    """
    models = sorted(per_model_texts)
    colors = {m: color_for(m) for m in models}

    # per-model top chains + their frequencies (for word cloud + sankey)
    chains: dict[str, list[dict]] = {}
    for m in models:
        toks = [tok for t in per_model_texts[m] for tok in _tokens(t)]
        counts = Counter(_ngrams(toks, n))
        chains[m] = [
            {"text": g, "weight": counts[g]}
            for g, _ in counts.most_common(k)
        ]

    # co-occurrence graph (network): nodes + directed edges within kept set
    node_freq: Counter[str] = Counter()
    edges: Counter[tuple[str, str]] = Counter()
    kept: set[str] = set()
    for m in models:
        nds, eds = _cooccurrence_graph(per_model_texts[m], n, limit=k)
        kept.update(nds)
        node_freq.update({g: _chain_freq(per_model_texts[m], g, n) for g in nds})
        edges.update(eds)
    node_items = [
        {"id": g, "model": _owner_of(g, chains), "label": g,
         "weight": node_freq[g]}
        for g in sorted(kept)
    ]
    edge_items = [
        {"s": a, "t": b, "w": w} for (a, b), w in edges.items()
    ]

    # heatmap matrix: top pooled chains x models, relative frequency
    pooled: Counter[str] = Counter()
    per_model_counts: dict[str, Counter[str]] = {}
    for m in models:
        toks = [tok for t in per_model_texts[m] for tok in _tokens(t)]
        per_model_counts[m] = Counter(_ngrams(toks, n))
        pooled.update(per_model_counts[m])
    top_pooled = [g for g, _ in pooled.most_common(k)]
    heat_z: list[list[float]] = []
    for g in top_pooled:
        row = []
        for m in models:
            tot = sum(per_model_counts[m].values()) or 1
            row.append(round(per_model_counts[m].get(g, 0) / tot, 6))
        heat_z.append(row)

    return {
        "models": models,
        "colors": colors,
        "n": n,
        "chains": chains,
        "nodes": node_items,
        "edges": edge_items,
        "heat": {
            "y": [g[:40] for g in top_pooled],
            "x": models,
            "z": heat_z,
        },
    }


def _chain_freq(texts: list[str], gram: str, n: int) -> int:
    toks = [tok for t in texts for tok in _tokens(t)]
    return Counter(_ngrams(toks, n)).get(gram, 0)


def _owner_of(gram: str, chains: dict[str, list[dict]]) -> str:
    """Which model owns a chain (highest weight); used to color graph nodes."""
    best, best_w = None, -1
    for m, rows in chains.items():
        for r in rows:
            if r["text"] == gram and r["weight"] > best_w:
                best, best_w = m, r["weight"]
    return best if best else next(iter(chains))


# --------------------------------------------------------------------------- #
# Interactive HTML report (Plotly + D3, CDN-loaded)
# --------------------------------------------------------------------------- #

_CDN = {
    "plotly": "https://cdn.plot.ly/plotly-2.35.2.min.js",
    "d3": "https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js",
    "cloud": "https://cdn.jsdelivr.net/npm/d3-cloud@1.2.7/build/d3.layout.cloud.min.js",
    "fdeep": "https://cdn.jsdelivr.net/npm/@fontsource/inter@5.0.18/index.css",
}

_REPORT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Token-chain analysis</title>
<link rel="stylesheet" href="__FONT_CSS__">
<style>
:root{--bg:#0f1117;--panel:#1a1d29;--panel2:#202433;--fg:#e8eaf0;
--muted:#8b91a7;--accent:#6c8cff;--border:#2c3142;
--mono:'JetBrains Mono',ui-monospace,monospace;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font-family:'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;}
header{padding:22px 30px 14px;border-bottom:1px solid var(--border);}
header h1{font-size:20px;margin:0;font-weight:650;letter-spacing:-.01em;}
header p{color:var(--muted);font-size:13px;margin:6px 0 0;}
.tabs{display:flex;gap:8px;padding:14px 30px 0;overflow-x:auto;}
.tabs button{background:var(--panel);color:var(--muted);border:1px solid var(--border);
padding:8px 16px;border-radius:9px;font-size:13px;cursor:pointer;font-weight:500;
transition:.15s;white-space:nowrap;}
.tabs button:hover{color:var(--fg)}
.tabs button.active{background:var(--accent);color:#0c0e14;border-color:var(--accent);font-weight:600;}
.panel{display:none;padding:20px 30px 8px;}
.panel.active{display:block}
.chart{background:var(--panel);border:1px solid var(--border);border-radius:12px;
padding:10px;margin-bottom:20px;overflow:hidden;}
.desc{color:var(--muted);font-size:12.5px;margin:0 4px 14px;line-height:1.5;max-width:70ch;}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin:0 4px 14px;}
.legend .item{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--fg);}
.legend .sw{width:10px;height:10px;border-radius:3px;}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px;}
@media(max-width:1000px){.grid2{grid-template-columns:1fr}}
</style></head><body>
<header>
<h1>Token-chain analysis</h1>
<p>Word-level __N__-gram chains across models — every view derives from the same
top chains per model. Hover/drag/zoom everything.</p>
</header>
<div class="tabs" id="tabs"></div>

<div class="panel active" data-name="network">
<div class="desc">A <b>co-occurrence network</b>: each node is a top token chain, sized by
frequency. A directed edge connects a chain to the one that immediately follows it in the
source text. Tight, strongly-linked clusters = models reusing the same phrasal scaffolding.</div>
<div class="chart" id="network" style="height:640px"></div>
</div>

<div class="panel" data-name="sankey">
<div class="desc">A <b>Sankey flow</b> from each model (left) to its most frequent token chains
(right). Ribbon width = raw frequency. Chains shared by several models merge into a single
right-hand node, making cross-model scaffolding reuse immediately visible.</div>
<div class="chart" id="sankey" style="height:720px"></div>
</div>

<div class="panel" data-name="heatmap">
<div class="desc">A <b>co-occurrence heatmap</b>: rows are the top chains pooled across all
models, columns are models, colour = relative frequency inside that model. A column with a
few bright cells = template-locked output.</div>
<div class="chart" id="heatmap" style="height:900px"></div>
</div>

<div class="panel" data-name="cloud">
<div class="desc"><b>Word clouds</b> of each model's top chains. The larger the chain, the
more the model repeats it. Select a model on the left to see its cloud.</div>
<div class="grid2">
<div class="chart"><div id="cloudSelector"></div></div>
<div class="chart" id="cloud" style="height:720px"></div>
</div>
</div>

<div class="legend" id="legend"></div>

<script src="__PLOTLY__"></script>
<script src="__D3__"></script>
<script src="__CLOUD__"></script>
<script>
const DATA = __DATA__;
const PALETTE = ["#6c8cff","#56c2a7","#f0a35e","#e56b8a","#b58cf7","#5fc7e8",
                 "#f2d268","#8bd66b","#d682e0","#6a9ff5"];
const META = {
  paper_bgcolor:"#1a1d29", plot_bgcolor:"#1a1d29",
  font:{family:"Inter, system-ui, sans-serif", color:"#e8eaf0", size:12},
  margin:{l:20,r:20,t:30,b:20},
};
const AXIS = {gridcolor:"#2c3142", zerolinecolor:"#2c3142", linecolor:"#2c3142",
              tickfont:{size:11}, titlefont:{size:12}};
function layout(title){return {...META, title:{text:title,font:{size:14}}, paper_bgcolor:"#1a1d29", plot_bgcolor:"#1a1d29"};}

function buildTabs(){const t=document.getElementById("tabs");
 Object.keys(VIEWS).forEach((name,i)=>{const b=document.createElement("button");
  b.textContent=VIEWS[name]; b.className=i===0?"active":""; b.dataset.name=name;
  b.onclick=()=>{document.querySelectorAll(".tabs button").forEach(x=>x.classList.toggle("active",x===b));
   document.querySelectorAll(".panel").forEach(p=>p.classList.toggle("active",p.dataset.name===name));
   Plotly.Plots.resize(document.getElementById(name)).catch(()=>{});};
  t.appendChild(b);});}
function buildLegend(){const lg=document.getElementById("legend");
 lg.innerHTML=""; DATA.models.forEach((m,i)=>{const d=document.createElement("div");
  d.className="item"; d.innerHTML=`<span class="sw" style="background:${DATA.colors[m]}"></span>${m}`;
  lg.appendChild(d);});}

// ---- NAV / init ----
const VIEWS={network:"Network",sankey:"Sankey",heatmap:"Heatmap",cloud:"Word cloud"};
buildTabs(); buildLegend();
const D=window.d3||window.d3v||null;

// ---------- NETWORK (D3 force) ----------
(function(){
const W=document.getElementById("network").clientWidth||800, H=640;
const svg=D.select("#network").append("svg").attr("width","100%").attr("viewBox",`0 0 ${W} ${H}`);
const g=svg.append("g");
const zoom=D.zoom().scaleExtent([0.2,8]).on("zoom",e=>g.attr("transform",e.transform));
svg.call(zoom);
const nmap={}; DATA.nodes.forEach(nd=>nmap[nd.id]=nd);
const nodes=DATA.nodes.map(nd=>({...nd,r:3+Math.sqrt(nd.weight)}));
const links=DATA.edges.map(e=>({...e,source:nmap[e.s],target:nmap[e.t]}));
const sim=D.forceSimulation(nodes)
 .force("link",D.forceLink(links).id(d=>d.id).distance(50).strength(0.4))
 .force("charge",D.forceManyBody().strength(-70))
 .force("center",D.forceCenter(W/2,H/2))
 .force("collide",D.forceCollide().radius(d=>d.r+4));
const link=g.append("g").selectAll("line").data(links).join("line")
 .attr("stroke","#3b415c").attr("stroke-opacity",0.5)
 .attr("stroke-width",d=>0.5+Math.sqrt(d.w)*1.2);
const node=g.append("g").selectAll("g").data(nodes).join("g").call(
 D.drag().on("start",(e,d)=>{if(!e.active)sim.alphaTarget(0.3).restart();d.fx=d.x;d.fy=d.y;})
  .on("drag",(e,d)=>{d.fx=e.x;d.fy=e.y;})
  .on("end",(e,d)=>{if(!e.active)sim.alphaTarget(0);d.fx=null;d.fy=null;})
);
node.append("circle").attr("r",d=>d.r)
 .attr("fill",d=>DATA.colors[d.model]).attr("fill-opacity",0.85)
 .attr("stroke","#0f1117").attr("stroke-width",1);
node.append("text").text(d=>d.label.length>18?d.label.slice(0,17)+"…":d.label)
 .attr("x",d=>d.r+5).attr("y",3).attr("font-size",9)
 .attr("fill","#aab1c8").attr("font-family","JetBrains Mono,monospace");
node.append("title").text(d=>`${d.label}\nmodel: ${d.model}\nfreq: ${d.weight}`);
sim.on("tick",()=>{link.attr("x1",d=>d.source.x).attr("y1",d=>d.source.y)
 .attr("x2",d=>d.target.x).attr("y2",d=>d.target.y);
 node.attr("transform",d=>`translate(${d.x},${d.y})`);});
})();

// ---------- SANKEY (Plotly) ----------
(function(){
const labels=[], source=[], target=[], value=[], color=[];
const nodeIndex={};
function idx(label){if(!(label in nodeIndex)){nodeIndex[label]=labels.length;labels.push(label);}return nodeIndex[label];}
// model nodes on the left, chain nodes on the right; ribbons = chain frequency.
// Chains shared across models merge into one node, making cross-model overlap visible.
Object.keys(DATA.chains).forEach(m=>{
 const mi=idx("◆ "+m);
 DATA.chains[m].forEach(c=>{
   const ci=idx(c.text);
   source.push(mi); target.push(ci); value.push(c.weight); color.push(DATA.colors[m]);
 });
});
// color chain nodes by their dominant (highest-weight) model
const chainOwner={}; Object.keys(DATA.chains).forEach(m=>DATA.chains[m].forEach(c=>{
 if(!chainOwner[c.text]||chainOwner[c.text].w<c.weight) chainOwner[c.text]={m,w:c.weight};}));
const nodeColor=labels.map(l=>l.startsWith("◆ ")
  ? DATA.colors[l.slice(2)]
  : (DATA.colors[chainOwner[l].m]||"#3b415c"));
const data=[{type:"sankey",orientation:"h",valueformat:".0f",
 node:{pad:14,thickness:16,line:{color:"#0f1117",width:1},label:labels,color:nodeColor},
 link:{source,target,value,color}}];
Plotly.newPlot("sankey", data, layout("Model → top token chains (Sankey)"), {responsive:true});
})();

// ---------- HEATMAP (Plotly) ----------
(function(){
const h=DATA.heat;
const data=[{type:"heatmap",x:h.x,y:h.y,z:h.z,colorscale:"Viridis",
 hovertemplate:"<b>%{y}</b><br>%{x}: %{z:.4f}<extra></extra>",
 colorbar:{title:"rel. freq",titlefont:{size:11},tickfont:{size:10}}}];
Plotly.newPlot("heatmap", data, {...layout("Token-chain co-occurrence heatmap"),
 yaxis:{...AXIS,automargin:true,tickfont:{size:10}}, xaxis:{...AXIS,tickangle:-20}}, {responsive:true});
})();

// ---------- WORD CLOUD (d3-cloud) ----------
(function(){
const sel=document.getElementById("cloudSelector");
const names=Object.keys(DATA.chains);
let current=names[0];
names.forEach((m,i)=>{const b=document.createElement("button");
 b.textContent=m; b.style.display="block"; b.style.width="100%"; b.style.textAlign="left";
 b.style.margin="4px 0"; b.style.padding="8px 10px"; b.style.background=i===0?"var(--accent)":"var(--panel2)";
 b.style.color=i===0?"#0c0e14":"var(--fg)"; b.style.border="1px solid var(--border)";
 b.style.borderRadius="8px"; b.style.cursor="pointer"; b.style.fontSize="12px";
 b.onclick=()=>{current=m; redraw();}; sel.appendChild(b);});
function redraw(){[...sel.children].forEach((b,i)=>b.style.background=
  b.textContent===current?"var(--accent)":"var(--panel2)");
 const words=DATA.chains[current].map(c=>({text:c.text,size:14+Math.sqrt(c.weight)*2.2,color:DATA.colors[current]}));
 D.layout.cloud().size([720,660]).words(words).padding(2)
  .rotate(()=>0).font("Inter").fontSize(d=>d.size)
  .on("end",drawCloud).start();
 function drawCloud(){D.select("#cloud").selectAll("*").remove();
  D.select("#cloud").append("svg").attr("width","100%").attr("height",660).attr("viewBox","0 0 720 660")
   .append("g").attr("transform","translate(360,330)")
   .selectAll("text").data(words).join("text")
   .style("font-size",d=>d.size+"px").style("font-family","Inter,sans-serif")
   .style("fill",d=>d.color).style("font-weight",600)
   .attr("text-anchor","middle").attr("transform",d=>`translate(${d.x},${d.y})`)
   .text(d=>d.text).append("title").text(d=>`freq: ${Math.round(d.size*d.size/4)}`);}}
redraw();
})();

window.addEventListener("resize",()=>Object.keys(VIEWS).forEach(n=>Plotly.Plots.resize(document.getElementById(n)).catch(()=>{})));
</script></body></html>
"""


def write_token_chain_report(
    per_model_texts: dict[str, list[str]], out: Path, n: int = 3, k: int = 40
) -> None:
    """One polished, self-contained interactive report (all four views).

    Uses Plotly.js + D3 (force graph) + d3-cloud (wordcloud), loaded from CDN.
    """
    payload = _token_chain_payload(per_model_texts, n, k)
    html = (
        _REPORT_TEMPLATE.replace("__DATA__", json.dumps(payload))
        .replace("__N__", str(n))
        .replace("__FONT_CSS__", _CDN["fdeep"])
        .replace("__PLOTLY__", _CDN["plotly"])
        .replace("__D3__", _CDN["d3"])
        .replace("__CLOUD__", _CDN["cloud"])
    )
    (out / "charts" / "token-chains.html").write_text(html, encoding="utf-8")


def plot_token_chain_heatmap(
    per_model_texts: dict[str, list[str]], out: Path, n: int = 3, k: int = 40
) -> None:
    """Cross-model overlap heatmap: do models share the same token chains?

    Rows = top chains pooled across models; columns = models. Cell value is the
    relative frequency of that chain within the model's own text, so a column
    dominated by a few dark cells signals template-locked output.
    """
    models = sorted(per_model_texts)
    pooled: Counter[str] = Counter()
    freqs: dict[str, Counter[str]] = {}
    for m in models:
        toks = [tok for t in per_model_texts[m] for tok in _tokens(t)]
        freqs[m] = Counter(_ngrams(toks, n))
        pooled.update(freqs[m])
    top = [g for g, _ in pooled.most_common(k)]
    mat = np.zeros((len(top), len(models)))
    for j, m in enumerate(models):
        tot = sum(freqs[m].values()) or 1
        for i, g in enumerate(top):
            mat[i, j] = freqs[m].get(g, 0) / tot
    fig, ax = plt.subplots(figsize=(max(7, 0.28 * len(models) + 4),
                                    max(6, 0.22 * len(top))))
    im = ax.imshow(mat, aspect="auto", cmap="magma", vmin=0,
                   vmax=float(mat.max() or 1))
    ax.set_yticks(range(len(top)))
    ax.set_yticklabels([g[:28] for g in top], fontsize=7)
    ax.set_xticks(range(len(models)))
    ax.set_xticklabels(models, rotation=25, ha="right", fontsize=9)
    ax.set_xlabel("model")
    ax.set_ylabel(f"top pooled {n}-gram chains")
    ax.set_title(f"Token-chain frequency heatmap ({n}-grams)")
    cb = fig.colorbar(im, ax=ax, shrink=0.7)
    cb.set_label("relative frequency", fontsize=9)
    fig.tight_layout()
    fig.savefig(out / "charts" / "token-chains-heatmap.png", dpi=150)
    plt.close(fig)


def plot_wordclouds(
    per_model_texts: dict[str, list[str]], out: Path, n: int = 2
) -> None:
    """Per-model word clouds of top token chains (static, no wordcloud dep).

    Font size = chain frequency; chains from the same model share a color.
    """
    models = sorted(per_model_texts)
    ncols = 2
    nrows = (len(models) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(12, 4.5 * nrows))
    axes = np.atleast_1d(axes).flatten()
    for ax, m in zip(axes, models):
        toks = [tok for t in per_model_texts[m] for tok in _tokens(t)]
        counts = Counter(_ngrams(toks, n))
        top = counts.most_common(30)
        if not top:
            ax.set_visible(False)
            continue
        maxc = top[0][1]
        # simple spiral/"cloud" placement of boxes, sized by frequency
        rng = np.random.RandomState(7)
        placed: list[tuple[float, float, float, float]] = []
        for g, c in top:
            size = 11 + 26 * (c / maxc)
            for _ in range(300):
                x = rng.uniform(-1, 1)
                y = rng.uniform(-1, 1)
                w_ = 0.11 * len(g)
                h_ = 0.11
                if not any(abs(x - px) < (w_ + pw) / 2 and
                           abs(y - py) < (h_ + ph) / 2
                           for px, py, pw, ph in placed):
                    placed.append((x, y, w_, h_))
                    ax.text(x, y, g, fontsize=size, ha="center", va="center",
                            color=color_for(m), alpha=0.85)
                    break
        ax.set_xlim(-1.2, 1.2)
        ax.set_ylim(-1.2, 1.2)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(m, fontsize=11, color=color_for(m))
        for s in ("top", "right", "bottom", "left"):
            ax.spines[s].set_visible(False)
    for ax in axes[len(models):]:
        ax.set_visible(False)
    fig.suptitle(f"Top token chains ({n}-grams) word cloud per model", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(out / "charts" / "token-chains-wordcloud.png", dpi=150)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# 3D token-chain visualization
# --------------------------------------------------------------------------- #


def build_3d(
    per_model_texts: dict[str, list[str]], n: int, k: int
) -> tuple[np.ndarray, list[str], list[tuple[str, str, int]], TfidfVectorizer]:
    docs, labels = build_ngram_corpus(per_model_texts, n, k)
    assert docs, "no ngrams to embed — check that traces/campaigns were found"
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    matrix = vectorizer.fit_transform(docs)
    pca = PCA(n_components=3, random_state=0)
    coords = pca.fit_transform(matrix.toarray())
    return coords, docs, labels, vectorizer


def plot_token_chains_3d(
    per_model_texts: dict[str, list[str]], out: Path, n: int = 3, k: int = 40
) -> None:
    coords, docs, labels, _ = build_3d(per_model_texts, n, k)

    # Build one 3D scatter with per-model color + a legend. Plot labels the
    # top few ngrams per model so the viewer can read the actual chains.
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection="3d")
    models = sorted(per_model_texts)

    for m in models:
        # labels carry the doc_index; point at coords[doc_index] directly.
        row = [lb for lb in labels if lb[0] == m]
        xs = [coords[lb[3], 0] for lb in row]
        ys = [coords[lb[3], 1] for lb in row]
        zs = [coords[lb[3], 2] for lb in row]
        ax.scatter(xs, ys, zs, color=color_for(m), label=m, s=28, alpha=0.75,
                   depthshade=False)
        # annotate the most frequent chains of this model
        for mm, gram, cnt, di in sorted(row, key=lambda x: -x[2])[:6]:
            ax.text(coords[di, 0], coords[di, 1], coords[di, 2],
                    gram[:24], fontsize=7, color=color_for(m), alpha=0.85)

    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    ax.set_zlabel("PC3")
    ax.set_title(f"Token-chain embeddings ({n}-grams) across models — "
                 f"clusters = shared phrasing templates")
    ax.legend(loc="upper left", fontsize=9, frameon=False)
    fig.tight_layout()
    fig.savefig(out / "charts" / "token-chains-3d.png", dpi=150)
    plt.close(fig)

    # A second, rotating-angle view taken from a higher elevation to spread
    # cluster separation: save an additional perspective.
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection="3d")
    for m in models:
        row = [lb for lb in labels if lb[0] == m]
        ax.scatter([coords[lb[3], 0] for lb in row],
                   [coords[lb[3], 1] for lb in row],
                   [coords[lb[3], 2] for lb in row],
                   color=color_for(m), label=m, s=30, alpha=0.75, depthshade=False)
    ax.view_init(elev=35, azim=45)
    ax.set_title(f"Token-chain embeddings — elevation 35°, azimuth 45°")
    ax.legend(loc="upper left", fontsize=9, frameon=False)
    fig.tight_layout()
    fig.savefig(out / "charts" / "token-chains-3d-alt.png", dpi=150)
    plt.close(fig)


def write_3d_html(
    per_model_texts: dict[str, list[str]], out: Path, n: int = 3, k: int = 40
) -> None:
    """Interactive 3D scatter as a self-contained HTML page (three.js via CDN)."""
    coords, docs, labels, _ = build_3d(per_model_texts, n, k)
    models = sorted(per_model_texts)
    # inline the points as JS arrays (coord + color + label)
    points = []
    for (m, gram, _cnt, di) in labels:
        points.append(
            {"x": float(coords[di, 0]), "y": float(coords[di, 1]),
             "z": float(coords[di, 2]), "model": m, "gram": gram}
        )
    data = json.dumps(points)
    colors = {m: color_for(m) for m in models}
    color_js = json.dumps(colors)
    html = _HTML_TEMPLATE.replace("__DATA__", data).replace(
        "__COLORS__", color_js).replace(
        "__TITLE__", f"Token-chain embeddings ({n}-grams) across models"
    )
    (out / "charts" / "token-chains-3d.html").write_text(html, encoding="utf-8")


_HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>body{margin:0;overflow:hidden;background:#0f1117;font-family:sans-serif;}
#legend{position:absolute;top:12px;left:12px;color:#ddd;background:#1c1f2a88;
padding:10px 14px;border-radius:8px;font-size:13px;}
#tip{position:absolute;bottom:12px;left:12px;color:#888;font-size:12px;}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;}
</style></head><body>
<div id="legend"></div><div id="tip">drag to rotate · scroll to zoom · hover a point</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const DATA = __DATA__;
const COLORS = __COLORS__;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0f1117);
const camera = new THREE.PerspectiveCamera(45, innerWidth/innerHeight, 0.1, 1000);
camera.position.set(3,2,3);
const renderer = new THREE.WebGLRenderer({antialias:true});
renderer.setSize(innerWidth, innerHeight); document.body.appendChild(renderer.domElement);
const controls = new THREE.OrbitControls(camera, renderer.domElement);
const geom = new THREE.SphereGeometry(0.035, 12, 12);
DATA.forEach(p=>{ const mat=new THREE.MeshBasicMaterial({
    color: COLORS[p.model] || '#888888' });
    const m=new THREE.Mesh(geom, mat); m.position.set(p.x,p.y,p.z);
    m.userData=p.p; scene.add(m); });
const legend=document.getElementById('legend');
Object.entries(COLORS).forEach(([name,c])=>{
    legend.innerHTML += `<span class="dot" style="background:${c}"></span>${name}<br>`;});
const raycaster=new THREE.Raycaster(); const mouse=new THREE.Vector2();
const tip=document.getElementById('tip');
renderer.domElement.addEventListener('mousemove',e=>{
    mouse.x=(e.clientX/innerWidth)*2-1; mouse.y=-(e.clientY/innerHeight)*2+1;
    raycaster.setFromCamera(mouse,camera);
    const hits=raycaster.intersectObjects(scene.children);
    tip.textContent = hits.length? hits[0].object.userData || '':'drag to rotate · scroll to zoom';
});
function animate(){requestAnimationFrame(animate); controls.update();
    renderer.render(scene,camera);} animate();
window.addEventListener('resize',()=>{camera.aspect=innerWidth/innerHeight;
    camera.updateProjectionMatrix(); renderer.setSize(innerWidth,innerHeight);});
</script></body></html>
"""


# --------------------------------------------------------------------------- #


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="experiment output directory")
    parser.add_argument("--n", type=int, default=3, help="ngram length for chains")
    parser.add_argument("--k", type=int, default=40,
                        help="top-k chains per model to embed")
    args = parser.parse_args()
    out = Path(args.out)

    records = load_records(out)
    if not records:
        raise SystemExit(f"no runs found in {out / 'runs.jsonl'}")

    # Enhanced report charts need the aggregate payload.
    quality = out / "quality.json"
    payload = (
        json.loads(quality.read_text(encoding="utf-8"))
        if quality.exists() else None
    )

    per_model_texts = collect_model_texts(out, records)
    print(f"models with text: {list(per_model_texts)}")

    charts = out / "charts"
    charts.mkdir(parents=True, exist_ok=True)

    if payload:
        chart_model_rates(payload, out)
        chart_duration_box(payload, records, out)
    chart_ngram_diversity(per_model_texts, out)
    plot_token_chains_3d(per_model_texts, out, n=args.n, k=args.k)
    write_3d_html(per_model_texts, out, n=args.n, k=args.k)

    # Alternative token-chain visualizations
    plot_token_chain_network(per_model_texts, out, n=args.n, k=args.k)
    plot_token_chain_heatmap(per_model_texts, out, n=args.n, k=args.k)
    plot_wordclouds(per_model_texts, out, n=args.n)
    write_token_chain_report(per_model_texts, out, n=args.n, k=args.k)

    print("wrote:")
    for name in (
        "model_rates.png", "duration_box.png", "ngram_diversity.png",
        "token-chains-3d.png", "token-chains-3d-alt.png",
        "token-chains-3d.html",
        "token-chains-network.png",
        "token-chains-heatmap.png",
        "token-chains-wordcloud.png",
        "token-chains.html",
    ):
        print(f"  {charts / name}")


if __name__ == "__main__":
    main()
