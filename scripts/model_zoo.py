#!/usr/bin/env python3
"""model_zoo.py — HÀNG LOẠT model dự đoán, viết TAY bằng Python thuần.

Cài đặt theo phong cách kho TheAlgorithms/Python: mỗi thuật toán tự viết từ
đầu, đọc được, KHÔNG phụ thuộc numpy/scikit-learn (môi trường này không có).

Hai họ model:

  * CÓ GIÁM SÁT (supervised) — cùng một bài toán: "số n có xuất hiện ở kỳ tới
    không?". Mỗi (kỳ, số) là một mẫu với 6 đặc trưng lấy từ lịch sử TRƯỚC kỳ đó.
    Model cho điểm mỗi số, lấy top-5.
        logistic_regression, naive_bayes, knn, perceptron, mlp,
        linear_regression, svm, decision_tree, random_forest,
        adaboost, gradient_boosting

  * TỰ THÂN (custom) — không dùng khung nhãn/đặc trưng chung, mỗi model có cách
    sinh điểm riêng.
        markov_chain, k_means, pca, exponential_smoothing, som,
        genetic_algorithm, simulated_annealing, monte_carlo

CẢNH BÁO THẲNG: xổ số 5/35 là các kỳ ĐỘC LẬP. Không model nào ở đây có lợi thế
thật, và backtest trong scripts/backtest_zoo.py sẽ chứng minh điều đó bằng số.
Đây là bộ công cụ để ĐO, không phải để tin.
"""
from __future__ import annotations

import math
import random
from collections import deque

MAIN_MIN, MAIN_MAX = 1, 35
SPECIAL_MIN, SPECIAL_MAX = 1, 12

FEATURE_NAMES = ["freq_all", "freq_50", "freq_200", "gap", "affinity", "in_prev"]
N_FEATURES = len(FEATURE_NAMES)


# ─────────────────────────── ĐẶC TRƯNG (features) ───────────────────────────

def build_feature_cache(draws, pool_min, pool_max, use_special, first_index=0):
    """cache[i][j] = vector đặc trưng của số (pool_min + j) tại kỳ thứ i,
    tính CHỈ từ draws[:i] — không bao giờ nhìn vào kỳ i (chống rò nhãn).

    Một lượt duyệt tiến duy nhất, O(T · |pool|), nên rẻ.
    """
    size = pool_max - pool_min + 1
    total = [0] * size
    cnt50 = [0] * size
    cnt200 = [0] * size
    last_seen = [-1] * size
    cooc = [[0] * size for _ in range(size)]     # đồng xuất hiện / chuyển trạng thái
    win50: deque[list[int]] = deque()
    win200: deque[list[int]] = deque()

    cache: dict[int, list[list[float]]] = {}
    prev_idx: list[int] = []

    for i, d in enumerate(draws):
        if i >= first_index:
            rows = []
            for j in range(size):
                gap = (i - last_seen[j]) if last_seen[j] >= 0 else i
                if prev_idx:
                    aff = sum(cooc[m][j] / (total[m] + 1.0) for m in prev_idx) / len(prev_idx)
                else:
                    aff = 0.0
                rows.append([
                    total[j] / (i + 1.0),
                    cnt50[j] / max(len(win50), 1),
                    cnt200[j] / max(len(win200), 1),
                    min(gap, 100) / 100.0,
                    aff,
                    1.0 if j in prev_idx else 0.0,
                ])
            cache[i] = rows

        appeared = [d.special] if use_special else d.numbers
        idx = [n - pool_min for n in appeared if pool_min <= n <= pool_max]

        for a in idx:                     # cooc: từ kỳ TRƯỚC sang kỳ này
            for b in prev_idx:
                cooc[b][a] += 1
        for j in idx:
            total[j] += 1
            last_seen[j] = i

        win50.append(idx)
        for j in idx:
            cnt50[j] += 1
        if len(win50) > 50:
            for j in win50.popleft():
                cnt50[j] -= 1

        win200.append(idx)
        for j in idx:
            cnt200[j] += 1
        if len(win200) > 200:
            for j in win200.popleft():
                cnt200[j] -= 1

        prev_idx = idx

    return cache


def build_dataset(draws, cache, lo, hi, pool_min, pool_max, use_special):
    """Gộp các kỳ [lo, hi) thành (X, y) cho model có giám sát."""
    size = pool_max - pool_min + 1
    X, y = [], []
    for i in range(lo, hi):
        rows = cache.get(i)
        if rows is None:
            continue
        appeared = [draws[i].special] if use_special else draws[i].numbers
        hit = {n - pool_min for n in appeared}
        for j in range(size):
            X.append(rows[j])
            y.append(1.0 if j in hit else 0.0)
    return X, y


def standardise(X):
    """Chuẩn hoá z-score theo cột; trả (X_chuẩn, mean, std) để áp lại cho test."""
    if not X:
        return X, [0.0] * N_FEATURES, [1.0] * N_FEATURES
    n, f = len(X), len(X[0])
    mean = [sum(r[c] for r in X) / n for c in range(f)]
    std = []
    for c in range(f):
        v = sum((r[c] - mean[c]) ** 2 for r in X) / n
        std.append(math.sqrt(v) or 1.0)
    Z = [[(r[c] - mean[c]) / std[c] for c in range(f)] for r in X]
    return Z, mean, std


def apply_standardise(X, mean, std):
    return [[(r[c] - mean[c]) / std[c] for c in range(len(mean))] for r in X]


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-min(z, 60.0)))
    e = math.exp(max(z, -60.0))
    return e / (1.0 + e)


# ───────────────────── MODEL CÓ GIÁM SÁT (viết tay) ─────────────────────

class LogisticRegression:
    """Hồi quy logistic, gradient descent toàn batch + phạt L2."""

    def __init__(self, lr=0.5, epochs=25, l2=1e-3):
        self.lr, self.epochs, self.l2 = lr, epochs, l2
        self.w, self.b = [], 0.0

    def fit(self, X, y):
        f = len(X[0])
        self.w, self.b = [0.0] * f, 0.0
        n = len(X)
        for _ in range(self.epochs):
            gw, gb = [0.0] * f, 0.0
            for xi, yi in zip(X, y):
                err = _sigmoid(sum(self.w[c] * xi[c] for c in range(f)) + self.b) - yi
                for c in range(f):
                    gw[c] += err * xi[c]
                gb += err
            for c in range(f):
                self.w[c] -= self.lr * (gw[c] / n + self.l2 * self.w[c])
            self.b -= self.lr * gb / n
        return self

    def predict(self, X):
        f = len(self.w)
        return [_sigmoid(sum(self.w[c] * r[c] for c in range(f)) + self.b) for r in X]


class GaussianNaiveBayes:
    """Naive Bayes Gauss: giả định các đặc trưng độc lập trong từng lớp."""

    def __init__(self):
        self.stats, self.prior = {}, {}

    def fit(self, X, y):
        f = len(X[0])
        for cls in (0.0, 1.0):
            rows = [x for x, t in zip(X, y) if t == cls]
            if not rows:
                rows = X
            m = [sum(r[c] for r in rows) / len(rows) for c in range(f)]
            v = [max(sum((r[c] - m[c]) ** 2 for r in rows) / len(rows), 1e-6) for c in range(f)]
            self.stats[cls] = (m, v)
            self.prior[cls] = max(len(rows) / len(X), 1e-9)
        return self

    def _log_post(self, x, cls):
        m, v = self.stats[cls]
        s = math.log(self.prior[cls])
        for c in range(len(x)):
            s += -0.5 * (math.log(2 * math.pi * v[c]) + (x[c] - m[c]) ** 2 / v[c])
        return s

    def predict(self, X):
        out = []
        for x in X:
            a, b = self._log_post(x, 1.0), self._log_post(x, 0.0)
            out.append(_sigmoid(a - b))
        return out


class KNearestNeighbours:
    """k-NN: điểm = tỉ lệ nhãn 1 trong k láng giềng gần nhất (Euclid)."""

    def __init__(self, k=25, subsample=1200, seed=11):
        self.k, self.subsample, self.seed = k, subsample, seed
        self.X, self.y = [], []

    def fit(self, X, y):
        if len(X) > self.subsample:
            rng = random.Random(self.seed)
            idx = rng.sample(range(len(X)), self.subsample)
            self.X = [X[i] for i in idx]
            self.y = [y[i] for i in idx]
        else:
            self.X, self.y = X, y
        return self

    def predict(self, X):
        out = []
        f = len(self.X[0]) if self.X else 0
        for q in X:
            ds = []
            for xi, yi in zip(self.X, self.y):
                d = 0.0
                for c in range(f):
                    t = q[c] - xi[c]
                    d += t * t
                ds.append((d, yi))
            ds.sort(key=lambda p: p[0])
            k = min(self.k, len(ds))
            out.append(sum(t for _, t in ds[:k]) / k if k else 0.0)
        return out


class Perceptron:
    """Perceptron Rosenblatt: cập nhật trực tuyến khi phân loại sai."""

    def __init__(self, lr=0.05, epochs=12, seed=3):
        self.lr, self.epochs, self.seed = lr, epochs, seed
        self.w, self.b = [], 0.0

    def fit(self, X, y):
        f = len(X[0])
        self.w, self.b = [0.0] * f, 0.0
        rng = random.Random(self.seed)
        order = list(range(len(X)))
        for _ in range(self.epochs):
            rng.shuffle(order)
            for i in order:
                xi, target = X[i], (1.0 if y[i] > 0.5 else -1.0)
                act = sum(self.w[c] * xi[c] for c in range(f)) + self.b
                if target * act <= 0:
                    for c in range(f):
                        self.w[c] += self.lr * target * xi[c]
                    self.b += self.lr * target
        return self

    def predict(self, X):
        f = len(self.w)
        return [_sigmoid(sum(self.w[c] * r[c] for c in range(f)) + self.b) for r in X]


class MultilayerPerceptron:
    """Mạng nơ-ron 1 lớp ẩn (tanh) + đầu ra sigmoid, lan truyền ngược SGD."""

    def __init__(self, hidden=5, lr=0.05, epochs=8, seed=5):
        self.h, self.lr, self.epochs, self.seed = hidden, lr, epochs, seed

    def fit(self, X, y):
        rng = random.Random(self.seed)
        f, h = len(X[0]), self.h
        s = 1.0 / math.sqrt(f)
        self.w1 = [[rng.uniform(-s, s) for _ in range(h)] for _ in range(f)]
        self.b1 = [0.0] * h
        self.w2 = [rng.uniform(-s, s) for _ in range(h)]
        self.b2 = 0.0
        order = list(range(len(X)))
        for _ in range(self.epochs):
            rng.shuffle(order)
            for i in order:
                xi, yi = X[i], y[i]
                z = [self.b1[k] + sum(xi[c] * self.w1[c][k] for c in range(f)) for k in range(h)]
                a = [math.tanh(v) for v in z]
                out = _sigmoid(self.b2 + sum(a[k] * self.w2[k] for k in range(h)))
                d_out = out - yi
                d_h = [d_out * self.w2[k] * (1 - a[k] * a[k]) for k in range(h)]
                for k in range(h):
                    self.w2[k] -= self.lr * d_out * a[k]
                self.b2 -= self.lr * d_out
                for c in range(f):
                    xc = xi[c]
                    if xc:
                        for k in range(h):
                            self.w1[c][k] -= self.lr * d_h[k] * xc
                for k in range(h):
                    self.b1[k] -= self.lr * d_h[k]
        return self

    def predict(self, X):
        f, h = len(self.w1), self.h
        out = []
        for xi in X:
            a = [math.tanh(self.b1[k] + sum(xi[c] * self.w1[c][k] for c in range(f)))
                 for k in range(h)]
            out.append(_sigmoid(self.b2 + sum(a[k] * self.w2[k] for k in range(h))))
        return out


class RidgeLinearRegression:
    """Bình phương tối thiểu có phạt ridge, giải bằng khử Gauss (không numpy)."""

    def __init__(self, l2=1e-2):
        self.l2 = l2
        self.w = []

    def fit(self, X, y):
        f = len(X[0]) + 1
        rows = [r + [1.0] for r in X]
        A = [[0.0] * (f + 1) for _ in range(f)]
        for r, t in zip(rows, y):
            for i in range(f):
                ri = r[i]
                if ri:
                    for j in range(f):
                        A[i][j] += ri * r[j]
                    A[i][f] += ri * t
        for i in range(f):
            A[i][i] += self.l2 * len(rows)
        self.w = _solve_gauss(A, f)
        return self

    def predict(self, X):
        f = len(self.w) - 1
        return [sum(self.w[c] * r[c] for c in range(f)) + self.w[f] for r in X]


def _solve_gauss(A, n):
    """Khử Gauss có xoay trục từng phần; trả nghiệm, hoặc 0 nếu suy biến."""
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(A[r][col]))
        if abs(A[piv][col]) < 1e-12:
            return [0.0] * n
        A[col], A[piv] = A[piv], A[col]
        pv = A[col][col]
        for j in range(col, n + 1):
            A[col][j] /= pv
        for r in range(n):
            if r != col and A[r][col]:
                fac = A[r][col]
                for j in range(col, n + 1):
                    A[r][j] -= fac * A[col][j]
    return [A[i][n] for i in range(n)]


class LinearSVM:
    """SVM tuyến tính, mất mát hinge, huấn luyện bằng sub-gradient SGD."""

    def __init__(self, lr=0.02, epochs=10, l2=1e-3, seed=13):
        self.lr, self.epochs, self.l2, self.seed = lr, epochs, l2, seed

    def fit(self, X, y):
        f = len(X[0])
        self.w, self.b = [0.0] * f, 0.0
        rng = random.Random(self.seed)
        order = list(range(len(X)))
        for _ in range(self.epochs):
            rng.shuffle(order)
            for i in order:
                xi, t = X[i], (1.0 if y[i] > 0.5 else -1.0)
                margin = t * (sum(self.w[c] * xi[c] for c in range(f)) + self.b)
                for c in range(f):
                    g = self.l2 * self.w[c] - (t * xi[c] if margin < 1 else 0.0)
                    self.w[c] -= self.lr * g
                if margin < 1:
                    self.b += self.lr * t
        return self

    def predict(self, X):
        f = len(self.w)
        return [sum(self.w[c] * r[c] for c in range(f)) + self.b for r in X]


# ── Cây quyết định trên đặc trưng đã CHIA THÙNG (histogram) ─────────────────
# Chia thùng trước giúp tìm ngưỡng cắt trong O(n·F) thay vì phải sắp xếp lại ở
# mỗi nút — đủ nhanh cho Python thuần.

N_BINS = 16


def _bin_edges(X, f):
    """Ngưỡng chia thùng theo phân vị của từng cột."""
    edges = []
    for c in range(f):
        col = sorted(r[c] for r in X)
        e = []
        for b in range(1, N_BINS):
            e.append(col[min(len(col) - 1, b * len(col) // N_BINS)])
        edges.append(e)
    return edges


def _to_bins(X, edges):
    out = []
    for r in X:
        row = []
        for c, e in enumerate(edges):
            v, b = r[c], 0
            while b < len(e) and v > e[b]:
                b += 1
            row.append(b)
        out.append(row)
    return out


def _grow(Xb, y, idx, depth, max_depth, min_leaf, feats):
    """Cây hồi quy: cắt theo mức giảm tổng bình phương lớn nhất."""
    tot = sum(y[i] for i in idx)
    mean = tot / len(idx)
    if depth >= max_depth or len(idx) < 2 * min_leaf:
        return ("leaf", mean)

    best = None
    for c in feats:
        hs = [0.0] * N_BINS
        hc = [0] * N_BINS
        for i in idx:
            b = Xb[i][c]
            hs[b] += y[i]
            hc[b] += 1
        ls = lc = 0.0
        for b in range(N_BINS - 1):
            ls += hs[b]
            lc += hc[b]
            rc = len(idx) - lc
            if lc < min_leaf or rc < min_leaf:
                continue
            gain = ls * ls / lc + (tot - ls) ** 2 / rc
            if best is None or gain > best[0]:
                best = (gain, c, b)
    if best is None:
        return ("leaf", mean)

    _, c, b = best
    left = [i for i in idx if Xb[i][c] <= b]
    right = [i for i in idx if Xb[i][c] > b]
    if not left or not right:
        return ("leaf", mean)
    return ("split", c, b,
            _grow(Xb, y, left, depth + 1, max_depth, min_leaf, feats),
            _grow(Xb, y, right, depth + 1, max_depth, min_leaf, feats))


def _tree_predict(node, row):
    while node[0] == "split":
        node = node[3] if row[node[1]] <= node[2] else node[4]
    return node[1]


class DecisionTree:
    """Cây quyết định CART (hồi quy trên nhãn 0/1)."""

    def __init__(self, max_depth=4, min_leaf=40):
        self.max_depth, self.min_leaf = max_depth, min_leaf

    def fit(self, X, y):
        f = len(X[0])
        self.edges = _bin_edges(X, f)
        Xb = _to_bins(X, self.edges)
        self.tree = _grow(Xb, y, list(range(len(X))), 0,
                          self.max_depth, self.min_leaf, list(range(f)))
        return self

    def predict(self, X):
        Xb = _to_bins(X, self.edges)
        return [_tree_predict(self.tree, r) for r in Xb]


class RandomForest:
    """Rừng ngẫu nhiên: bagging mẫu + lấy mẫu con đặc trưng ở mỗi cây."""

    def __init__(self, n_trees=15, max_depth=4, min_leaf=30, seed=17):
        self.n_trees, self.max_depth, self.min_leaf, self.seed = n_trees, max_depth, min_leaf, seed

    def fit(self, X, y):
        f = len(X[0])
        self.edges = _bin_edges(X, f)
        Xb = _to_bins(X, self.edges)
        rng = random.Random(self.seed)
        n = len(X)
        m = max(2, int(math.sqrt(f)) + 1)
        self.trees = []
        for _ in range(self.n_trees):
            idx = [rng.randrange(n) for _ in range(n // 2)]     # bootstrap 50%
            feats = rng.sample(range(f), m)
            self.trees.append(_grow(Xb, y, idx, 0, self.max_depth, self.min_leaf, feats))
        return self

    def predict(self, X):
        Xb = _to_bins(X, self.edges)
        return [sum(_tree_predict(t, r) for t in self.trees) / len(self.trees) for r in Xb]


class GradientBoosting:
    """Tăng cường gradient (mất mát bình phương) trên các cây nông."""

    def __init__(self, n_rounds=25, lr=0.1, max_depth=3, min_leaf=40):
        self.n_rounds, self.lr, self.max_depth, self.min_leaf = n_rounds, lr, max_depth, min_leaf

    def fit(self, X, y):
        f = len(X[0])
        self.edges = _bin_edges(X, f)
        Xb = _to_bins(X, self.edges)
        idx = list(range(len(X)))
        self.base = sum(y) / len(y)
        pred = [self.base] * len(y)
        self.trees = []
        for _ in range(self.n_rounds):
            resid = [y[i] - pred[i] for i in idx]
            t = _grow(Xb, resid, idx, 0, self.max_depth, self.min_leaf, list(range(f)))
            self.trees.append(t)
            for i in idx:
                pred[i] += self.lr * _tree_predict(t, Xb[i])
        return self

    def predict(self, X):
        Xb = _to_bins(X, self.edges)
        return [self.base + self.lr * sum(_tree_predict(t, r) for t in self.trees) for r in Xb]


class AdaBoost:
    """AdaBoost SAMME trên gốc cây (decision stump), trọng số mẫu thích nghi."""

    def __init__(self, n_rounds=20, min_leaf=40):
        self.n_rounds, self.min_leaf = n_rounds, min_leaf

    def fit(self, X, y):
        f = len(X[0])
        self.edges = _bin_edges(X, f)
        Xb = _to_bins(X, self.edges)
        n = len(X)
        w = [1.0 / n] * n
        idx = list(range(n))
        self.stumps = []
        for _ in range(self.n_rounds):
            # Nhân nhãn với trọng số: cây hồi quy trên (y-0.5)·w tương đương
            # gốc cây có trọng số, nhưng giữ được cùng bộ máy chia thùng.
            target = [(y[i] - 0.5) * w[i] * n for i in idx]
            stump = _grow(Xb, target, idx, 0, 1, self.min_leaf, list(range(f)))
            err = 0.0
            preds = []
            for i in idx:
                p = 1.0 if _tree_predict(stump, Xb[i]) > 0 else 0.0
                preds.append(p)
                if p != y[i]:
                    err += w[i]
            err = min(max(err, 1e-6), 1 - 1e-6)
            alpha = 0.5 * math.log((1 - err) / err)
            self.stumps.append((stump, alpha))
            z = 0.0
            for i in idx:
                w[i] *= math.exp(-alpha if preds[i] == y[i] else alpha)
                z += w[i]
            w = [v / z for v in w]
            if err > 0.499:                    # gốc cây hết tác dụng — dừng sớm
                break
        return self

    def predict(self, X):
        Xb = _to_bins(X, self.edges)
        out = []
        for r in Xb:
            s = sum(a * (1.0 if _tree_predict(t, r) > 0 else -1.0) for t, a in self.stumps)
            out.append(_sigmoid(s))
        return out


SUPERVISED_MODELS = {
    "logistic_regression": ("Hồi quy logistic", LogisticRegression),
    "naive_bayes":         ("Naive Bayes Gauss", GaussianNaiveBayes),
    "knn":                 ("k láng giềng gần nhất", KNearestNeighbours),
    "perceptron":          ("Perceptron", Perceptron),
    "mlp":                 ("Mạng nơ-ron 1 lớp ẩn", MultilayerPerceptron),
    "linear_regression":   ("Hồi quy tuyến tính ridge", RidgeLinearRegression),
    "svm":                 ("SVM tuyến tính (hinge)", LinearSVM),
    "decision_tree":       ("Cây quyết định", DecisionTree),
    "random_forest":       ("Rừng ngẫu nhiên", RandomForest),
    "gradient_boosting":   ("Tăng cường gradient", GradientBoosting),
    "adaboost":            ("AdaBoost (gốc cây)", AdaBoost),
}


# ─────────────────────── MODEL TỰ THÂN (không dùng X, y) ───────────────────────

def _vectors(draws, lo, hi, pool_min, pool_max, use_special):
    """Mỗi kỳ thành một vector nhị phân độ dài |pool|."""
    size = pool_max - pool_min + 1
    out = []
    for i in range(lo, hi):
        v = [0.0] * size
        appeared = [draws[i].special] if use_special else draws[i].numbers
        for n in appeared:
            if pool_min <= n <= pool_max:
                v[n - pool_min] = 1.0
        out.append(v)
    return out


def markov_chain(draws, t, lo, pool_min, pool_max, use_special, seed):
    """Xích Markov bậc 1: P(số n ở kỳ tới | các số ở kỳ trước)."""
    size = pool_max - pool_min + 1
    trans = [[1.0] * size for _ in range(size)]        # làm mượt Laplace
    for i in range(lo, t - 1):
        a = [n - pool_min for n in ([draws[i].special] if use_special else draws[i].numbers)
             if pool_min <= n <= pool_max]
        b = [n - pool_min for n in ([draws[i + 1].special] if use_special else draws[i + 1].numbers)
             if pool_min <= n <= pool_max]
        for x in a:
            for yv in b:
                trans[x][yv] += 1.0
    prev = [n - pool_min for n in ([draws[t - 1].special] if use_special else draws[t - 1].numbers)
            if pool_min <= n <= pool_max]
    scores = [0.0] * size
    for x in prev:
        row_sum = sum(trans[x])
        for j in range(size):
            scores[j] += trans[x][j] / row_sum
    return scores


def k_means(draws, t, lo, pool_min, pool_max, use_special, seed, k=5, iters=12):
    """Phân cụm k-means các kỳ, rồi dự đoán bằng trung bình các kỳ ĐỨNG SAU
    những kỳ cùng cụm với kỳ gần nhất ("chế độ" nào thường theo sau chế độ nào)."""
    size = pool_max - pool_min + 1
    V = _vectors(draws, lo, t, pool_min, pool_max, use_special)
    if len(V) < k + 2:
        return [0.0] * size
    rng = random.Random(seed)
    cent = [V[i][:] for i in rng.sample(range(len(V)), k)]
    assign = [0] * len(V)
    for _ in range(iters):
        moved = False
        for i, v in enumerate(V):
            best, bd = 0, None
            for c in range(k):
                d = sum((v[j] - cent[c][j]) ** 2 for j in range(size))
                if bd is None or d < bd:
                    best, bd = c, d
            if assign[i] != best:
                assign[i], moved = best, True
        for c in range(k):
            mem = [V[i] for i in range(len(V)) if assign[i] == c]
            if mem:
                cent[c] = [sum(v[j] for v in mem) / len(mem) for j in range(size)]
        if not moved:
            break
    cur = assign[-1]
    succ = [V[i + 1] for i in range(len(V) - 1) if assign[i] == cur]
    if not succ:
        return cent[cur][:]
    return [sum(v[j] for v in succ) / len(succ) for j in range(size)]


def pca_projection(draws, t, lo, pool_min, pool_max, use_special, seed, iters=40):
    """PCA bằng lặp luỹ thừa: chiếu kỳ gần nhất lên trục chính rồi tái dựng."""
    size = pool_max - pool_min + 1
    V = _vectors(draws, lo, t, pool_min, pool_max, use_special)
    if len(V) < 3:
        return [0.0] * size
    mean = [sum(v[j] for v in V) / len(V) for j in range(size)]
    C = [[v[j] - mean[j] for j in range(size)] for v in V]
    rng = random.Random(seed)
    u = [rng.uniform(-1, 1) for _ in range(size)]
    for _ in range(iters):                       # lặp luỹ thừa trên Cᵀ·C
        proj = [sum(row[j] * u[j] for j in range(size)) for row in C]
        nu = [0.0] * size
        for p, row in zip(proj, C):
            if p:
                for j in range(size):
                    nu[j] += p * row[j]
        nrm = math.sqrt(sum(x * x for x in nu)) or 1.0
        u = [x / nrm for x in nu]
    last = C[-1]
    a = sum(last[j] * u[j] for j in range(size))
    return [mean[j] + a * u[j] for j in range(size)]


def exponential_smoothing(draws, t, lo, pool_min, pool_max, use_special, seed, alpha=0.12):
    """Làm mượt hàm mũ đơn trên chuỗi 0/1 của từng số."""
    size = pool_max - pool_min + 1
    lvl = [1.0 / size] * size
    for i in range(lo, t):
        appeared = {n - pool_min for n in
                    ([draws[i].special] if use_special else draws[i].numbers)
                    if pool_min <= n <= pool_max}
        for j in range(size):
            lvl[j] = alpha * (1.0 if j in appeared else 0.0) + (1 - alpha) * lvl[j]
    return lvl


def self_organizing_map(draws, t, lo, pool_min, pool_max, use_special, seed,
                        nodes=6, epochs=3):
    """Bản đồ tự tổ chức Kohonen 1 chiều; dự đoán = trọng số nút khớp nhất."""
    size = pool_max - pool_min + 1
    V = _vectors(draws, lo, t, pool_min, pool_max, use_special)
    if not V:
        return [0.0] * size
    rng = random.Random(seed)
    W = [[rng.uniform(0, 0.3) for _ in range(size)] for _ in range(nodes)]
    total = max(len(V) * epochs, 1)
    step = 0
    for _ in range(epochs):
        for v in V:
            lr = 0.5 * (1 - step / total)
            rad = max(1.0, nodes / 2 * (1 - step / total))
            bmu, bd = 0, None
            for c in range(nodes):
                d = sum((v[j] - W[c][j]) ** 2 for j in range(size))
                if bd is None or d < bd:
                    bmu, bd = c, d
            for c in range(nodes):
                infl = math.exp(-((c - bmu) ** 2) / (2 * rad * rad))
                if infl > 0.01:
                    g = lr * infl
                    for j in range(size):
                        W[c][j] += g * (v[j] - W[c][j])
            step += 1
    last = V[-1]
    bmu, bd = 0, None
    for c in range(nodes):
        d = sum((last[j] - W[c][j]) ** 2 for j in range(size))
        if bd is None or d < bd:
            bmu, bd = c, d
    return W[bmu][:]


def _fitness_table(draws, t, lo, pool_min, pool_max, use_special):
    """Điểm "độ hợp" của mỗi số: pha tần suất gần đây và số kỳ vắng mặt."""
    size = pool_max - pool_min + 1
    recent = [0.0] * size
    last = [-1] * size
    span = max(t - lo, 1)
    for i in range(lo, t):
        for n in ([draws[i].special] if use_special else draws[i].numbers):
            if pool_min <= n <= pool_max:
                j = n - pool_min
                recent[j] += (i - lo + 1) / span
                last[j] = i
    mr = max(recent) or 1.0
    return [0.5 * recent[j] / mr + 0.5 * min(t - last[j] if last[j] >= 0 else t, 60) / 60.0
            for j in range(size)]


def genetic_algorithm(draws, t, lo, pool_min, pool_max, use_special, seed,
                      pop=60, gens=40, k=5):
    """Giải thuật di truyền: tiến hoá tổ hợp k số tối đa hoá điểm độ hợp."""
    size = pool_max - pool_min + 1
    fit_tab = _fitness_table(draws, t, lo, pool_min, pool_max, use_special)
    k = min(k, size)
    rng = random.Random(seed)

    def fit(ind):
        return sum(fit_tab[j] for j in ind)

    population = [tuple(sorted(rng.sample(range(size), k))) for _ in range(pop)]
    for _ in range(gens):
        population.sort(key=fit, reverse=True)
        elite = population[: pop // 4]
        children = []
        while len(children) < pop - len(elite):
            a, b = rng.choice(elite), rng.choice(elite)
            genes = list(set(a) | set(b))
            child = set(rng.sample(genes, min(k, len(genes))))
            while len(child) < k:
                child.add(rng.randrange(size))
            if rng.random() < 0.3:                     # đột biến
                child.discard(rng.choice(sorted(child)))
                child.add(rng.randrange(size))
            children.append(tuple(sorted(child)))
        population = elite + children
    best = max(population, key=fit)
    scores = [0.0] * size
    for rank, j in enumerate(best):
        scores[j] = 1.0 - rank * 1e-6
    return scores


def simulated_annealing(draws, t, lo, pool_min, pool_max, use_special, seed,
                        steps=800, k=5, t0=1.0):
    """Ủ mô phỏng: đi tìm cục bộ trên cùng hàm độ hợp, nhận nước đi xấu theo
    xác suất giảm dần."""
    size = pool_max - pool_min + 1
    fit_tab = _fitness_table(draws, t, lo, pool_min, pool_max, use_special)
    k = min(k, size)
    rng = random.Random(seed)
    cur = set(rng.sample(range(size), k))
    cur_f = sum(fit_tab[j] for j in cur)
    best, best_f = set(cur), cur_f
    for s in range(steps):
        temp = t0 * (1 - s / steps) + 1e-9
        cand = set(cur)
        cand.discard(rng.choice(sorted(cand)))
        while len(cand) < k:
            cand.add(rng.randrange(size))
        cf = sum(fit_tab[j] for j in cand)
        if cf > cur_f or rng.random() < math.exp((cf - cur_f) / temp):
            cur, cur_f = cand, cf
            if cf > best_f:
                best, best_f = set(cand), cf
    scores = [0.0] * size
    for j in best:
        scores[j] = 1.0
    return scores


def monte_carlo(draws, t, lo, pool_min, pool_max, use_special, seed, trials=4000):
    """Monte Carlo: bốc hàng nghìn vé theo phân phối biên thực nghiệm, đếm tần
    suất mỗi số lọt vào các vé điểm cao nhất."""
    size = pool_max - pool_min + 1
    fit_tab = _fitness_table(draws, t, lo, pool_min, pool_max, use_special)
    weights = [w + 0.05 for w in fit_tab]
    rng = random.Random(seed)
    k = min(5, size)
    tally = [0] * size
    kept = max(trials // 20, 1)
    samples = []
    for _ in range(trials):
        pick, pool_w = [], weights[:]
        for _ in range(k):
            tot = sum(pool_w)
            r, acc = rng.random() * tot, 0.0
            for j in range(size):
                acc += pool_w[j]
                if acc >= r:
                    pick.append(j)
                    pool_w[j] = 0.0
                    break
        samples.append((sum(fit_tab[j] for j in pick), pick))
    samples.sort(key=lambda p: p[0], reverse=True)
    for _, pick in samples[:kept]:
        for j in pick:
            tally[j] += 1
    return [c / kept for c in tally]


CUSTOM_MODELS = {
    "markov_chain":          ("Xích Markov bậc 1", markov_chain),
    "k_means":               ("Phân cụm k-means", k_means),
    "pca":                   ("PCA (lặp luỹ thừa)", pca_projection),
    "exponential_smoothing": ("Làm mượt hàm mũ", exponential_smoothing),
    "som":                   ("Bản đồ tự tổ chức (SOM)", self_organizing_map),
    "genetic_algorithm":     ("Giải thuật di truyền", genetic_algorithm),
    "simulated_annealing":   ("Ủ mô phỏng", simulated_annealing),
    "monte_carlo":           ("Monte Carlo", monte_carlo),
}

ALL_MODELS = list(SUPERVISED_MODELS) + list(CUSTOM_MODELS)


def model_label(name: str) -> str:
    if name in SUPERVISED_MODELS:
        return SUPERVISED_MODELS[name][0]
    if name in CUSTOM_MODELS:
        return CUSTOM_MODELS[name][0]
    return name


def top_k(scores: list[float], k: int, pool_min: int, seed_tiebreak: int = 0) -> list[int]:
    """TẤT ĐỊNH: k số điểm cao nhất; hoà thì phá bằng nhiễu có seed.

    Giữ lại để đối chứng — chế độ mặc định giờ là sample_k().
    """
    rng = random.Random(seed_tiebreak)
    ranked = sorted(range(len(scores)),
                    key=lambda j: (-scores[j], rng.random()))
    return sorted(pool_min + j for j in ranked[:k])


DEFAULT_TEMPERATURE = 0.5


def sample_k(scores: list[float], k: int, pool_min: int, seed: int,
             temperature: float = DEFAULT_TEMPERATURE) -> list[int]:
    """NGẪU NHIÊN CÓ TRỌNG SỐ: bốc k số không hoàn lại, xác suất theo điểm model.

    Vì sao tốt hơn top_k:

      * top_k luôn nhả CÙNG một vé cho tới khi lịch sử đổi đủ để đảo thứ hạng.
        Model chấm 35 số nhưng chỉ 5 số trên cùng có cơ hội — 30 số còn lại bị
        loại vĩnh viễn dù điểm chỉ kém chút xíu. Đó là đặt cược tất cả vào phần
        chênh lệch nhỏ nhất, ồn nhất của điểm số.
      * Bốc theo trọng số giữ nguyên thứ hạng của model (số điểm cao vẫn hay
        được chọn hơn) nhưng trải rủi ro ra cả dải, và mỗi kỳ / mỗi seed cho vé
        khác nhau — tái lập được từ seed.

    Điểm được chuẩn hoá min–max về [0,1] trước (điểm thô của svm /
    linear_regression có thể âm), rồi w = exp(z / temperature).
      temperature → 0   : gần như tất định (giống top_k)
      temperature = 0.5 : số điểm cao nhất có trọng số ≈ e² ≈ 7,4 lần thấp nhất
      temperature → ∞   : ngẫu nhiên đều, bỏ qua model
    """
    n = len(scores)
    k = min(k, n)
    rng = random.Random(seed)
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-12:
        return sorted(pool_min + j for j in rng.sample(range(n), k))
    tau = max(temperature, 1e-3)
    w = [math.exp((s - lo) / (hi - lo) / tau) for s in scores]

    picked = []
    for _ in range(k):
        total = sum(w)
        if total <= 0:
            rest = [j for j in range(n) if j not in picked]
            picked.append(rng.choice(rest))
            continue
        r, acc = rng.random() * total, 0.0
        for j in range(n):
            acc += w[j]
            if acc >= r:
                picked.append(j)
                w[j] = 0.0
                break
        else:
            picked.append(max(range(n), key=lambda j: w[j]))
            w[picked[-1]] = 0.0
    return sorted(pool_min + j for j in picked)


def choose(scores: list[float], k: int, pool_min: int, seed: int,
           mode: str = "sample", temperature: float = DEFAULT_TEMPERATURE) -> list[int]:
    """Bộ chọn dùng chung cho mọi model: 'sample' (mặc định) hoặc 'top'."""
    if mode == "top":
        return top_k(scores, k, pool_min, seed_tiebreak=seed)
    return sample_k(scores, k, pool_min, seed, temperature)
