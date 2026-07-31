#!/usr/bin/env Rscript
# r_model.R
# --------------------------------------------------------------------------
# Mô hình dự đoán Lotto 5/35 bằng RANDOM FOREST (ngôn ngữ R, gói randomForest).
#
# Ý tưởng (theo phương pháp học máy phân loại nhị phân):
#   - Với MỖI con số, mỗi kỳ quay là 1 mẫu: nhãn KetQua = 1 nếu số đó VỀ ở kỳ
#     này, 0 nếu trượt.
#   - Đặc trưng tính từ dữ liệu TRƯỚC kỳ đó (walk-forward, không rò rỉ):
#       * TanSuat       : số lần đã về (tần suất tích lũy)
#       * SoKyChuaVe    : số kỳ chưa về (chu kỳ "gan")
#       * TanSuatGanDay : số lần về trong W kỳ gần nhất
#   - Huấn luyện randomForest(KetQua ~ .), rồi dự đoán XÁC SUẤT VỀ cho từng số
#     ở trạng thái hiện tại → chọn 5 số chính (1-35) + 1 số đặc biệt (1-12) có
#     xác suất cao nhất.
#
# ==========================  TRUNG THỰC  ==================================
# Xổ số quay độc lập từng kỳ. Random Forest học được các quy luật thống kê của
# quá khứ nhưng KHÔNG có lợi thế thật cho kỳ tới — xác suất jackpot vẫn
# 1/324.632, đặc biệt vẫn 1/12. Đây là mô hình tái lập được để so sánh, không
# phải "mẹo" trúng số.
# ==========================================================================
#
# Dùng:  Rscript scripts/r_model.R --csv data/all.csv --draw 796
# In ra 1 dòng JSON: {"main":[...],"special":x,"trace":"L535-796-R"}

suppressWarnings(suppressMessages(library(randomForest)))

args <- commandArgs(trailingOnly = TRUE)
get_arg <- function(flag, default = NA_character_) {
  i <- match(flag, args)
  if (!is.na(i) && i < length(args)) args[i + 1L] else default
}
csv_path <- get_arg("--csv", "data/all.csv")
target   <- suppressWarnings(as.integer(get_arg("--draw", NA_character_)))

W      <- 30    # cửa sổ "gần đây" (kỳ)
WARMUP <- 50    # bỏ qua các kỳ đầu để đặc trưng đủ ổn định
NTREE  <- 200

df  <- read.csv(csv_path, colClasses = "character", stringsAsFactors = FALSE)
ids <- suppressWarnings(as.integer(df$draw_id))
if (is.na(target)) target <- max(ids, na.rm = TRUE) + 1L

keep <- !is.na(ids) & ids < target        # walk-forward: chỉ kỳ TRƯỚC target
df   <- df[keep, , drop = FALSE]
ord  <- order(ids[keep])
df   <- df[ord, , drop = FALSE]
n    <- nrow(df)

extract <- function(js, key) {
  m <- regmatches(js, regexpr(paste0('"', key, '"[^]]*\\]'), js))
  if (length(m) == 0L) return(integer(0))
  as.integer(regmatches(m, gregexpr("[0-9]+", m))[[1]])
}

# Ma trận xuất hiện A[i,k] = 1 nếu số k về ở kỳ i (cho một pool cỡ K).
build_A <- function(K, getter) {
  A <- matrix(0L, nrow = n, ncol = K)
  for (i in seq_len(n)) {
    v <- getter(df$result_json[i])
    v <- v[v >= 1L & v <= K]
    if (length(v)) A[i, v] <- 1L
  }
  A
}

# Chọn top `topn` số của một pool bằng Random Forest.
predict_pool <- function(A, topn) {
  K <- ncol(A)
  cum <- apply(A, 2, cumsum)                                  # cum[i,k]
  C0  <- rbind(matrix(0L, 1, K), cum[-n, , drop = FALSE])     # = cum[i-1,] (C0[1,]=0)
  freq_before   <- C0
  recent_before <- C0
  if (n > W) recent_before[(W + 1):n, ] <- C0[(W + 1):n, ] - C0[1:(n - W), ]
  gap_before <- (row(C0) - 1L) - {                            # (i-1) - lần về gần nhất trước i
    ls <- matrix(0L, n, K)
    for (k in seq_len(K)) {
      last <- 0L
      for (i in seq_len(n)) { ls[i, k] <- last; if (A[i, k] == 1L) last <- i }
    }
    ls
  }

  idx <- (WARMUP + 1):n
  train <- data.frame(
    TanSuat       = as.vector(freq_before[idx, ]),
    SoKyChuaVe    = as.vector(gap_before[idx, ]),
    TanSuatGanDay = as.vector(recent_before[idx, ]),
    KetQua        = factor(as.vector(A[idx, ]), levels = c(0, 1))
  )

  # Trạng thái HIỆN TẠI (sau toàn bộ n kỳ) → dự đoán cho kỳ target.
  lsf <- integer(K)
  for (k in seq_len(K)) { w <- which(A[, k] == 1L); lsf[k] <- if (length(w)) max(w) else 0L }
  pred_df <- data.frame(
    TanSuat       = cum[n, ],
    SoKyChuaVe    = n - lsf,
    TanSuatGanDay = cum[n, ] - (if (n > W) cum[n - W, ] else rep(0L, K))
  )

  set.seed(target)
  rf   <- randomForest(KetQua ~ TanSuat + SoKyChuaVe + TanSuatGanDay,
                       data = train, ntree = NTREE)
  prob <- predict(rf, newdata = pred_df, type = "prob")[, "1"]
  # phá hòa tái lập
  prob <- prob + runif(K) * 1e-9
  order(prob, decreasing = TRUE)[seq_len(topn)]              # chỉ số = con số (pool 1..K)
}

main_pick <- sort(predict_pool(build_A(35, function(js) extract(js, "numbers")), 5))
special   <- predict_pool(build_A(12, function(js) extract(js, "special_numbers")), 1)[1]

cat(sprintf('{"main":[%s],"special":%d,"trace":"L535-%d-R"}\n',
            paste(main_pick, collapse = ","), special, target))
