"""
lstm_experiment.py — Thí nghiệm LSTM học tập cho Lotto 5/35
===========================================================

MỤC ĐÍCH
--------
Cho phép bạn TỰ TAY huấn luyện một LSTM trên chuỗi các kỳ quay và QUAN SÁT
tận mắt hành vi của nó — đúng như các lưu ý kỹ thuật:

  * Hàm loss (mean_squared_error) sẽ CHỮNG LẠI ở một mức nào đó → dấu hiệu
    toán học cho thấy mô hình không tìm được mối liên hệ hàm số giữa các kỳ.
  * Dự đoán HỘI TỤ về "trung bình" các số hay xuất hiện → không phải tín hiệu.
  * Đổi SEQ_LENGTH (5 / 10 / 20) để xem "độ dài trí nhớ" ảnh hưởng ra sao.

⚠️  CẢNH BÁO TRUNG THỰC
-----------------------
Xổ số Vietlott quay NGẪU NHIÊN ĐỘC LẬP. Script này KHÔNG — và không thể —
dự đoán được kết quả tương lai. Nó là CÔNG CỤ HỌC TẬP để bạn thấy chính xác
VÌ SAO mô hình không dự đoán được. Mọi con số nó in ra có xác suất trúng y
hệt chọn ngẫu nhiên (mỗi bộ 5 số: 1/324.632). Hãy chơi có trách nhiệm.

Script này ĐỘC LẬP với pipeline tự động — không được workflow gọi, không ảnh
hưởng dự đoán/thông báo hằng ngày.

CÁCH DÙNG
---------
  # 1) Tạo file số sạch (chỉ gồm các cột số) từ dữ liệu dự án:
  python scripts/lstm_experiment.py --export-clean data/all.csv lotto_data.csv

  # 2) Chạy thí nghiệm (đổi --seq-length để thử "trí nhớ" khác nhau):
  python scripts/lstm_experiment.py --data lotto_data.csv --seq-length 10 --epochs 200
"""
from __future__ import annotations

import argparse
import csv
import sys

import numpy as np

# 5 số chính (1..35) + 1 số đặc biệt (1..12)
N_MAIN, MAIN_MAX = 5, 35
SPECIAL_MAX = 12
# Hệ số chuẩn hoá từng cột về [0,1] để LSTM huấn luyện ổn định.
SCALE = np.array([MAIN_MAX] * N_MAIN + [SPECIAL_MAX], dtype=np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# Bước 0 (tuỳ chọn): xuất file số sạch từ data/all.csv của dự án
# ─────────────────────────────────────────────────────────────────────────────
def export_clean(src_path: str, out_path: str) -> None:
    """Đọc data/all.csv (định dạng dự án, có JSON) và ghi ra một CSV SẠCH chỉ
    gồm các cột số: n1..n5, special — mỗi dòng là một kỳ, theo thứ tự thời gian."""
    try:
        from model import parse_draws
    except ImportError:
        from scripts.model import parse_draws

    with open(src_path, newline="", encoding="utf-8") as f:
        draws = parse_draws(list(csv.DictReader(f)))

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["n1", "n2", "n3", "n4", "n5", "special"])
        for d in draws:
            nums = sorted(d.numbers)
            if len(nums) == N_MAIN and d.special is not None:
                w.writerow(nums + [d.special])
    print(f"Đã ghi {out_path} (chỉ gồm cột số) từ {len(draws)} kỳ trong {src_path}.")


# ─────────────────────────────────────────────────────────────────────────────
# Nạp dữ liệu số + tạo chuỗi
# ─────────────────────────────────────────────────────────────────────────────
def load_numeric_csv(path: str) -> np.ndarray:
    """Đọc CSV chỉ-gồm-số. Bỏ qua dòng tiêu đề nếu có. Trả về mảng (n_kỳ, 6)."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.reader(f):
            if not r:
                continue
            try:
                rows.append([float(x) for x in r])
            except ValueError:
                # dòng tiêu đề (chữ) → bỏ qua
                continue
    if not rows:
        sys.exit(f"Lỗi: {path} không có dòng số nào hợp lệ.")
    arr = np.array(rows, dtype=np.float32)
    return arr


def make_sequences(data_scaled: np.ndarray, seq_length: int):
    """Cửa sổ trượt: dùng SEQ_LENGTH kỳ liên tiếp để dự đoán kỳ kế tiếp."""
    X, Y = [], []
    for i in range(len(data_scaled) - seq_length):
        X.append(data_scaled[i:i + seq_length])
        Y.append(data_scaled[i + seq_length])
    return np.array(X, np.float32), np.array(Y, np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# Thí nghiệm chính
# ─────────────────────────────────────────────────────────────────────────────
def run_experiment(data_path: str, seq_length: int, epochs: int, batch: int) -> None:
    try:
        import tensorflow as tf
        from tensorflow.keras import layers, Sequential
    except ImportError:
        sys.exit(
            "Cần TensorFlow để chạy thí nghiệm này.\n"
            "  pip install tensorflow\n"
            "(Trên GitHub Actions của bạn đã có sẵn theo requirements.txt.)"
        )

    raw = load_numeric_csv(data_path)
    n_features = raw.shape[1]
    scale = SCALE[:n_features] if n_features <= len(SCALE) else raw.max(axis=0)
    data_scaled = raw / scale

    if len(data_scaled) <= seq_length + 1:
        sys.exit(f"Không đủ kỳ ({len(data_scaled)}) cho seq_length={seq_length}.")

    X, Y = make_sequences(data_scaled, seq_length)
    print(f"Dữ liệu: {len(raw)} kỳ, {n_features} cột số | "
          f"SEQ_LENGTH={seq_length} → {len(X)} mẫu huấn luyện\n")

    tf.random.set_seed(42)
    model = Sequential([
        layers.Input((seq_length, n_features)),
        layers.LSTM(50, return_sequences=True),
        layers.LSTM(50),
        layers.Dense(n_features),
    ])
    model.compile(optimizer="adam", loss="mean_squared_error")

    print("=== Huấn luyện (theo dõi loss để thấy nó CHỮNG LẠI) ===")
    hist = model.fit(X, Y, epochs=epochs, batch_size=batch, verbose=0,
                     validation_split=0.1)
    loss = hist.history["loss"]

    # In quỹ đạo loss để bạn thấy nó chững lại
    marks = sorted(set([0, epochs // 4, epochs // 2, 3 * epochs // 4, epochs - 1]))
    for e in marks:
        if 0 <= e < len(loss):
            print(f"  epoch {e + 1:4d}: loss = {loss[e]:.6f}")
    improve = (loss[0] - loss[-1]) / loss[0] * 100 if loss[0] else 0.0
    print(f"  → loss giảm tổng cộng {improve:.1f}% rồi CHỮNG LẠI: mô hình không "
          f"tìm được liên hệ hàm số giữa các kỳ.\n")

    # Dự đoán "kỳ kế tiếp"
    last = data_scaled[-seq_length:][None, ...]
    pred_scaled = model.predict(last, verbose=0)[0]
    pred = pred_scaled * scale

    # So sánh với TRUNG BÌNH lịch sử để thấy sự hội tụ
    hist_mean = raw.mean(axis=0)
    print("=== Dự đoán 'kỳ kế tiếp' (KHÔNG có giá trị dự báo) ===")
    cols = [f"n{i+1}" for i in range(N_MAIN)] + ["special"]
    for i in range(n_features):
        name = cols[i] if i < len(cols) else f"c{i}"
        print(f"  {name:8s}: dự đoán = {pred[i]:5.2f}   | trung bình lịch sử = {hist_mean[i]:5.2f}")
    diff = float(np.mean(np.abs(pred - hist_mean)))
    print(f"  → Khoảng cách trung bình tới giá trị trung bình lịch sử: {diff:.2f}")
    print("  → Dự đoán HỘI TỤ về trung bình quá khứ = đúng biểu hiện 'không học "
          "được gì có tính dự báo'.\n")

    print("⚠️  Nhắc lại: mọi bộ số có xác suất trúng như nhau (1/324.632). "
          "Đây là thí nghiệm học tập, KHÔNG phải công cụ dự đoán. Chơi có trách nhiệm.")


def main():
    ap = argparse.ArgumentParser(description="Thí nghiệm LSTM học tập cho Lotto 5/35.")
    ap.add_argument("--export-clean", nargs=2, metavar=("SRC", "OUT"),
                    help="Xuất file số sạch từ data/all.csv rồi thoát.")
    ap.add_argument("--data", default="lotto_data.csv",
                    help="File CSV chỉ-gồm-số (mặc định: lotto_data.csv).")
    ap.add_argument("--seq-length", type=int, default=10,
                    help="Độ dài 'trí nhớ' nhìn về quá khứ (thử 5/10/20).")
    ap.add_argument("--epochs", type=int, default=200)
    ap.add_argument("--batch", type=int, default=32)
    args = ap.parse_args()

    if args.export_clean:
        export_clean(args.export_clean[0], args.export_clean[1])
        return
    run_experiment(args.data, args.seq_length, args.epochs, args.batch)


if __name__ == "__main__":
    main()
