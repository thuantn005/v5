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
from strategies import neural_perceptron, pick_topk, dataset_fingerprint, lstm_numpy, lstm_tf


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

    # ── LSTM NumPy ──────────────────────────────────────────────────────────
    try:
        ln_main = lstm_numpy(history, MAIN_MIN, MAIN_MAX, MAIN_K, False)
        ln_spec = lstm_numpy(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True)
        ln_main_pick    = pick_topk(ln_main, MAIN_K)
        ln_special_pick = pick_topk(ln_spec, 1)[0]
        trace_ln = f"lotto535|lstm-numpy|target={target_draw_id}|data={fp}"
        lstm_numpy_entry = {
            "main": ln_main_pick, "special": ln_special_pick,
            "trace": trace_ln, "label": "LSTM NumPy",
        }
    except Exception as _e:
        import logging; logging.getLogger(__name__).warning("lstm_numpy failed: %s", _e)
        lstm_numpy_entry = None

    # ── LSTM TensorFlow (fallback numpy nếu không có TF) ────────────────────
    try:
        lt_main = lstm_tf(history, MAIN_MIN, MAIN_MAX, MAIN_K, False)
        lt_spec = lstm_tf(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True)
        lt_main_pick    = pick_topk(lt_main, MAIN_K)
        lt_special_pick = pick_topk(lt_spec, 1)[0]
        trace_lt = f"lotto535|lstm-tf|target={target_draw_id}|data={fp}"
        lstm_tf_entry = {
            "main": lt_main_pick, "special": lt_special_pick,
            "trace": trace_lt, "label": "LSTM TensorFlow",
        }
    except Exception as _e:
        import logging; logging.getLogger(__name__).warning("lstm_tf failed: %s", _e)
        lstm_tf_entry = None

    per_strategy = {
        "ticket_neural": {
            "main": main_pick, "special": special_pick,
            "trace": trace_np, "label": "Mạng nơ-ron (Perceptron)",
        },
    }
    if lstm_numpy_entry:
        per_strategy["lstm_numpy"] = lstm_numpy_entry
    if lstm_tf_entry:
        per_strategy["lstm_tf"] = lstm_tf_entry

    return {
        "main_numbers": main_pick,
        "special_number": special_pick,
        "confidence": 0.0,
        "per_strategy_picks": per_strategy,
    }

