"""
lstm_numpy_model.py
--------------------
LSTM viết tay bằng numpy thuần — không cần TensorFlow.
Chạy được trên GitHub Actions mặc định (chỉ cần numpy).

Interface:
  predict(history, pool_min, pool_max, k, use_special, params) -> dict[int, float]
  history: list of Draw objects (có .numbers và .special)
"""
from __future__ import annotations
import numpy as np
import logging

logger = logging.getLogger(__name__)

# ── Kiến trúc mặc định ───────────────────────────────────────────────────────
T_DEFAULT   = 20   # số kỳ lịch sử làm chuỗi input
H_DEFAULT   = 24   # hidden size
EPOCHS_DEF  = 80
LR_DEF      = 3e-3
REFIT_DEF   = 34   # refit mỗi N kỳ mới (walk-forward)

# Cache trong process
_CACHE_MAIN = {"P": None, "trained_on": -1}
_CACHE_SPEC = {"P": None, "trained_on": -1}


# ── Encoding ──────────────────────────────────────────────────────────────────
def _enc_main(draw) -> np.ndarray:
    v = np.zeros(35, dtype=np.float32)
    for x in draw.numbers:
        if 1 <= x <= 35:
            v[x - 1] = 1.0
    return v

def _enc_spec(draw) -> np.ndarray:
    v = np.zeros(12, dtype=np.float32)
    if 1 <= draw.special <= 12:
        v[draw.special - 1] = 1.0
    return v

def _make_seqs(history, T: int, enc_fn, out_fn):
    """Tạo (X: N×T×D, Y: N×C) từ lịch sử Draw."""
    X, Y = [], []
    for t in range(T, len(history)):
        X.append([enc_fn(history[t - T + i]) for i in range(T)])
        Y.append(out_fn(history[t]))
    return np.array(X, dtype=np.float32), np.array(Y, dtype=np.float32)


# ── LSTM numpy kernel ─────────────────────────────────────────────────────────
def _sig(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))

def _init(xd: int, h: int, seed: int = 42):
    r = np.random.default_rng(seed)
    s = lambda *sh: (r.standard_normal(sh) * 0.15).astype(np.float32)
    return {
        "W": s(4*h, xd), "U": s(4*h, h), "b": np.zeros(4*h, np.float32),
        "Vm": s(xd, h),  "bm": np.zeros(xd, np.float32),
    }

def _forward(P, X):
    B, Tn, _ = X.shape; H4 = P["b"].size // 4
    hs = np.zeros((Tn+1, B, H4), np.float32)
    cs = np.zeros((Tn+1, B, H4), np.float32)
    gates = []
    for t in range(Tn):
        a = X[:, t] @ P["W"].T + hs[t] @ P["U"].T + P["b"]
        i_ = _sig(a[:, :H4]); f_ = _sig(a[:, H4:2*H4])
        o_ = _sig(a[:, 2*H4:3*H4]); g_ = np.tanh(a[:, 3*H4:])
        cs[t+1] = f_ * cs[t] + i_ * g_
        hs[t+1] = o_ * np.tanh(cs[t+1])
        gates.append((i_, f_, o_, g_))
    zm = hs[-1] @ P["Vm"].T + P["bm"]
    pm = _sig(zm)
    return pm, (hs, cs, gates)

def _loss_grads(P, X, Y):
    B = X.shape[0]; H4 = P["b"].size // 4
    pm, (hs, cs, gates) = _forward(P, X)
    eps = 1e-7
    L = -np.mean(np.sum(Y*np.log(pm+eps) + (1-Y)*np.log(1-pm+eps), axis=1))
    g = {k: np.zeros_like(v) for k, v in P.items()}
    dzm = (pm - Y) / B
    g["Vm"] = dzm.T @ hs[-1]; g["bm"] = dzm.sum(0)
    dh = dzm @ P["Vm"]; dc = np.zeros_like(dh)
    for t in range(X.shape[1]-1, -1, -1):
        i_, f_, o_, g_ = gates[t]; tc = np.tanh(cs[t+1])
        dc = dc + dh * o_ * (1 - tc**2)
        da = np.concatenate([
            (dc*g_)*i_*(1-i_), (dc*cs[t])*f_*(1-f_),
            (dh*tc)*o_*(1-o_),  (dc*i_)*(1-g_**2),
        ], axis=1)
        g["W"] += da.T @ X[:, t]; g["U"] += da.T @ hs[t]; g["b"] += da.sum(0)
        dh = da @ P["U"]; dc = dc * f_
    return L, g

def _train(P, X, Y, epochs: int, lr: float):
    m = {k: np.zeros_like(v) for k, v in P.items()}
    v = {k: np.zeros_like(v_) for k, v_ in P.items()}
    for ep in range(1, epochs+1):
        _, g = _loss_grads(P, X, Y)
        for k in P:
            m[k] = 0.9*m[k] + 0.1*g[k]
            v[k] = 0.999*v[k] + 0.001*g[k]**2
            P[k] -= lr * (m[k]/(1-0.9**ep)) / (np.sqrt(v[k]/(1-0.999**ep))+1e-8)
    return P


# ── Hàm dự đoán chung ────────────────────────────────────────────────────────
def _predict_pool(history, T, H, epochs, lr, refit,
                  enc_fn, out_fn, out_dim, cache, seed=42):
    if len(history) < T + 1:
        return None, cache
    X, Y = _make_seqs(history, T, enc_fn, lambda d: out_fn(d, out_dim))
    need = cache["P"] is None or (len(history) - cache["trained_on"]) >= refit
    if need:
        logger.info("lstm_numpy: refit (history=%d, epochs=%d)", len(history), epochs)
        P = _init(out_dim, H, seed)
        cache["P"] = _train(P, X, Y, epochs, lr)
        cache["trained_on"] = len(history)
    Xq = np.array([[enc_fn(history[-T+i]) for i in range(T)]], np.float32)
    pm, _ = _forward(cache["P"], Xq)
    return pm[0], cache


# ── Public interface ──────────────────────────────────────────────────────────
def predict(history, pool_min=1, pool_max=35, k=5, use_special=False, params=None):
    """
    Trả về dict[int, float]: điểm sigmoid cho từng số trong [pool_min, pool_max].
    Tương thích với interface của strategies.py (history = list of Draw objects).
    """
    p = params or {}
    T      = int(p.get("T", T_DEFAULT))
    H      = int(p.get("H", H_DEFAULT))
    epochs = int(p.get("epochs", EPOCHS_DEF))
    lr     = float(p.get("lr", LR_DEF))
    refit  = int(p.get("refit", REFIT_DEF))

    pool = list(range(pool_min, pool_max + 1))

    if use_special:
        # Đặc biệt: encode 1-12
        def enc(draw):
            v = np.zeros(12, np.float32)
            if 1 <= draw.special <= 12:
                v[draw.special-1] = 1.0
            return v
        def out(draw, d):
            v = np.zeros(d, np.float32)
            if 1 <= draw.special <= d:
                v[draw.special-1] = 1.0
            return v
        out_dim = 12
        pm, _ = _predict_pool(history, T, H, epochs, lr, refit,
                               enc, out, out_dim, _CACHE_SPEC, seed=43)
    else:
        def enc(draw):
            v = np.zeros(35, np.float32)
            for x in draw.numbers:
                if 1 <= x <= 35: v[x-1] = 1.0
            return v
        def out(draw, d):
            v = np.zeros(d, np.float32)
            for x in draw.numbers:
                if 1 <= x <= d: v[x-1] = 1.0
            return v
        out_dim = 35
        pm, _ = _predict_pool(history, T, H, epochs, lr, refit,
                               enc, out, out_dim, _CACHE_MAIN, seed=42)

    if pm is None:
        return {n: 0.0 for n in pool}

    scores = {}
    for n in pool:
        idx = n - 1
        scores[n] = float(pm[idx]) if idx < len(pm) else 0.0
    return scores
