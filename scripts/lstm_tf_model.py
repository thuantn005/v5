"""
lstm_tf_model.py
-----------------
LSTM TensorFlow/Keras cho Lotto 5/35, tích hợp vào pipeline v5.

- Nếu TensorFlow CÓ: dùng 2-lớp LSTM (64→32) + dropout + early stopping.
- Nếu TensorFlow KHÔNG CÓ: tự động fallback về lstm_numpy_model (không crash).

Interface:
  predict(history, pool_min, pool_max, k, use_special, params) -> dict[int, float]
  history: list of Draw objects
"""
from __future__ import annotations
import logging
import numpy as np

logger = logging.getLogger(__name__)

try:
    import tensorflow as tf
    from tensorflow.keras import layers, Model
    from tensorflow.keras.callbacks import EarlyStopping
    _TF = True
    logger.info("lstm_tf: TensorFlow %s sẵn sàng", tf.__version__)
except ImportError:
    _TF = False
    logger.warning(
        "lstm_tf: TensorFlow không có — fallback về lstm_numpy_model. "
        "Thêm 'tensorflow' vào requirements.txt để dùng TF thật."
    )

# ── Params mặc định ───────────────────────────────────────────────────────────
_DEF = {
    "T": 20, "H1": 64, "H2": 32, "dropout": 0.2,
    "epochs": 1000, "batch": 30, "patience": 200, "refit": 34,
}

_CACHE_MAIN = {"model": None, "trained_on": -1}
_CACHE_SPEC = {"model": None, "trained_on": -1}


# ── Encoding (cùng logic với lstm_numpy_model) ────────────────────────────────
def _enc_main(draw) -> np.ndarray:
    v = np.zeros(35, np.float32)
    for x in draw.numbers:
        if 1 <= x <= 35: v[x-1] = 1.0
    return v

def _enc_spec(draw) -> np.ndarray:
    v = np.zeros(12, np.float32)
    if 1 <= draw.special <= 12: v[draw.special-1] = 1.0
    return v

def _make_seqs_tf(history, T, enc_fn, out_fn):
    X, Y = [], []
    for t in range(T, len(history)):
        X.append([enc_fn(history[t-T+i]) for i in range(T)])
        Y.append(out_fn(history[t]))
    return np.array(X, np.float32), np.array(Y, np.float32)


# ── Keras model ───────────────────────────────────────────────────────────────
def _build(T, xd, out_dim, H1, H2, drop):
    inp = layers.Input((T, xd))
    h = layers.LSTM(H1, return_sequences=True, dropout=drop)(inp)
    h = layers.LSTM(H2, dropout=drop)(h)
    out = layers.Dense(out_dim, activation="sigmoid")(h)
    m = Model(inp, out)
    m.compile("adam", loss="binary_crossentropy")
    return m

def _fit_tf(history, T, xd, out_dim, H1, H2, drop,
             epochs, batch, patience, refit, enc_fn, out_fn, cache, seed_offset=0):
    if len(history) < T + 1:
        return None
    X, Y = _make_seqs_tf(history, T, enc_fn, out_fn)
    need = cache["model"] is None or (len(history) - cache["trained_on"]) >= refit
    if need:
        logger.info("lstm_tf: refit Keras (history=%d)", len(history))
        tf.random.set_seed(42 + seed_offset)
        mdl = _build(T, xd, out_dim, H1, H2, drop)
        mdl.fit(X, Y, epochs=epochs, batch_size=batch, verbose=0,
                validation_split=0.1,
                callbacks=[EarlyStopping(patience=patience, restore_best_weights=True)])
        cache["model"] = mdl; cache["trained_on"] = len(history)
    T_ = cache["model"].input_shape[1]
    Xq = np.array([[enc_fn(history[-T_+i]) for i in range(T_)]], np.float32)
    return cache["model"].predict(Xq, verbose=0)[0]


# ── Fallback numpy ────────────────────────────────────────────────────────────
def _fallback(history, pool_min, pool_max, k, use_special, params):
    try:
        from scripts.lstm_numpy_model import predict as _np
    except ImportError:
        from lstm_numpy_model import predict as _np
    return _np(history, pool_min, pool_max, k, use_special, params)


# ── Public interface ──────────────────────────────────────────────────────────
def predict(history, pool_min=1, pool_max=35, k=5, use_special=False, params=None):
    """Trả về dict[int, float]. Tự động fallback numpy nếu không có TF."""
    if not _TF:
        return _fallback(history, pool_min, pool_max, k, use_special, params)

    p = {**_DEF, **(params or {})}
    T       = int(p["T"]); H1 = int(p["H1"]); H2 = int(p["H2"])
    drop    = float(p["dropout"]); epochs = int(p["epochs"])
    batch   = int(p["batch"]); patience = int(p["patience"]); refit = int(p["refit"])
    pool    = list(range(pool_min, pool_max + 1))

    if use_special:
        pm = _fit_tf(history, T, 12, 12, H1, H2, drop, epochs, batch, patience, refit,
                     _enc_spec, lambda d: _enc_spec(d), _CACHE_SPEC, seed_offset=1)
    else:
        pm = _fit_tf(history, T, 35, 35, H1, H2, drop, epochs, batch, patience, refit,
                     _enc_main, lambda d: _enc_main(d), _CACHE_MAIN, seed_offset=0)

    if pm is None:
        return {n: 0.0 for n in pool}
    return {n: float(pm[n-1]) if (n-1) < len(pm) else 0.0 for n in pool}
