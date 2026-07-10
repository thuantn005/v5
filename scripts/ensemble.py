"""
ensemble.py
------------
Simplified: generates ONE ticket per draw using the top-performing strategy
from walk-forward backtesting across 694 draws — Neural Perceptron.

  neural_perceptron: avg_hits=0.7565  p=0.1304  (random baseline: 0.7143)

The transition weight matrix W[output][input] is trained on the last 100
draws: W[n][m] ≈ P(n appears next | m appeared last draw). Pick score =
0.7 × W × last_draw_binary + 0.3 × prior frequency.

Honest caveat: p=0.130 is not significant even without Bonferroni correction
— the edge is real-but-unproven at this sample size. The ticket is published
alongside random_fair so the comparison is always visible.
"""

from model import MAIN_MIN, MAIN_MAX, SPECIAL_MIN, SPECIAL_MAX, MAIN_K, SPECIAL_K
from strategies import neural_perceptron, pick_topk, dataset_fingerprint


def load_tuned_params():
    return {}


def ensemble_predict(history, tuned_params=None):
    if not history:
        raise ValueError("need at least one prior draw to derive a target_draw_id")
    width = len(history[-1].draw_id)
    target_draw_id = str(int(history[-1].draw_id) + 1).zfill(width)
    fp = dataset_fingerprint(history)

    np_main = neural_perceptron(history, MAIN_MIN, MAIN_MAX, MAIN_K, False)
    np_spec = neural_perceptron(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True)
    trace_np = f"lotto535|neural-perceptron|target={target_draw_id}|data={fp}"

    main_pick = pick_topk(np_main, MAIN_K)
    special_pick = pick_topk(np_spec, 1)[0]

    return {
        "main_numbers": main_pick,
        "special_number": special_pick,
        "confidence": 0.0,
        "per_strategy_picks": {
            "ticket_neural": {
                "main": main_pick,
                "special": special_pick,
                "trace": trace_np,
                "label": "Mạng nơ-ron (Perceptron)",
            }
        },
    }
