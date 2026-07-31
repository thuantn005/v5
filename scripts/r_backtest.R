#!/usr/bin/env Rscript
# r_backtest.R
# --------------------------------------------------------------------------
# Backtest WALK-FORWARD cho mô hình Random Forest (scripts/r_model.R):
# với N kỳ gần nhất, mỗi kỳ chỉ dùng dữ liệu TRƯỚC kỳ đó để huấn luyện RF rồi
# dự đoán, sau đó đối chiếu với kết quả thật. So sánh với mốc NGẪU NHIÊN:
#   - số chính: kỳ vọng 5 x 5/35 = 0.7143 số trúng/kỳ
#   - đặc biệt: 1/12 = 0.0833
#
# Dùng:  Rscript scripts/r_backtest.R --csv data/all.csv --n 50 [--ntree 150]

suppressWarnings(suppressMessages(library(randomForest)))

args <- commandArgs(trailingOnly = TRUE)
get_arg <- function(flag, d = NA_character_) {
  i <- match(flag, args); if (!is.na(i) && i < length(args)) args[i + 1L] else d
}
csv_path <- get_arg("--csv", "data/all.csv")
N        <- suppressWarnings(as.integer(get_arg("--n", "50")))
NTREE    <- suppressWarnings(as.integer(get_arg("--ntree", "150")))
W <- 30; WARMUP <- 50

df  <- read.csv(csv_path, colClasses = "character", stringsAsFactors = FALSE)
ids <- suppressWarnings(as.integer(df$draw_id))
ok  <- !is.na(ids); df <- df[ok, ]; ids <- ids[ok]
ord <- order(ids); df <- df[ord, ]; ids <- ids[ord]
n_all <- nrow(df)

extract <- function(js, key) {
  m <- regmatches(js, regexpr(paste0('"', key, '"[^]]*\\]'), js))
  if (length(m) == 0L) return(integer(0))
  as.integer(regmatches(m, gregexpr("[0-9]+", m))[[1]])
}
build_A <- function(K, key) {
  A <- matrix(0L, n_all, K)
  for (i in seq_len(n_all)) {
    v <- extract(df$result_json[i], key); v <- v[v >= 1L & v <= K]
    if (length(v)) A[i, v] <- 1L
  }
  A
}
A_main <- build_A(35, "numbers")
A_spec <- build_A(12, "special_numbers")

# Dự đoán top `topn` số cho kỳ NGAY SAU lịch sử `Ah` (walk-forward, đồng nhất
# với r_model.R). `seed` để tái lập.
rf_predict <- function(Ah, topn, seed) {
  n <- nrow(Ah); K <- ncol(Ah)
  if (n <= WARMUP + 1) return(sort(sample.int(K, topn)))  # quá ít lịch sử
  cum <- apply(Ah, 2, cumsum)
  C0  <- rbind(matrix(0L, 1, K), cum[-n, , drop = FALSE])
  freq_before <- C0; recent_before <- C0
  if (n > W) recent_before[(W + 1):n, ] <- C0[(W + 1):n, ] - C0[1:(n - W), ]
  ls <- matrix(0L, n, K)
  for (k in seq_len(K)) { last <- 0L; col <- Ah[, k]
    for (i in seq_len(n)) { ls[i, k] <- last; if (col[i] == 1L) last <- i } }
  gap_before <- (row(C0) - 1L) - ls
  idx <- (WARMUP + 1):n
  train <- data.frame(
    TanSuat = as.vector(freq_before[idx, ]),
    SoKyChuaVe = as.vector(gap_before[idx, ]),
    TanSuatGanDay = as.vector(recent_before[idx, ]),
    KetQua = factor(as.vector(Ah[idx, ]), levels = c(0, 1)))
  lsf <- integer(K)
  for (k in seq_len(K)) { w <- which(Ah[, k] == 1L); lsf[k] <- if (length(w)) max(w) else 0L }
  pred_df <- data.frame(TanSuat = cum[n, ], SoKyChuaVe = n - lsf,
                        TanSuatGanDay = cum[n, ] - (if (n > W) cum[n - W, ] else rep(0L, K)))
  set.seed(seed)
  rf <- randomForest(KetQua ~ TanSuat + SoKyChuaVe + TanSuatGanDay, data = train, ntree = NTREE)
  prob <- predict(rf, pred_df, type = "prob")[, "1"] + runif(K) * 1e-9
  sort(order(prob, decreasing = TRUE)[seq_len(topn)])
}

start <- max(WARMUP + 2, n_all - N + 1)
main_hits <- integer(0); spec_hits <- integer(0)
cat(sprintf("Backtest RF walk-forward: %d kỳ (từ #%s tới #%s), ntree=%d\n",
            n_all - start + 1, ids[start], ids[n_all], NTREE))
for (p in start:n_all) {
  pm <- rf_predict(A_main[1:(p - 1), , drop = FALSE], 5, ids[p])
  ps <- rf_predict(A_spec[1:(p - 1), , drop = FALSE], 1, ids[p] + 7L)
  actual_m <- which(A_main[p, ] == 1L)
  actual_s <- which(A_spec[p, ] == 1L)
  main_hits <- c(main_hits, length(intersect(pm, actual_m)))
  spec_hits <- c(spec_hits, as.integer(length(intersect(ps, actual_s)) > 0))
}

nb <- length(main_hits)
avg_main <- mean(main_hits)
sp_rate  <- mean(spec_hits)
dist <- sapply(0:5, function(h) sum(main_hits == h))
exp_main <- 5 * 5 / 35; exp_spec <- 1 / 12

cat("\n================ KẾT QUẢ BACKTEST RANDOM FOREST (R) ================\n")
cat(sprintf("Số kỳ backtest        : %d\n", nb))
cat(sprintf("TB số chính trúng/kỳ  : %.4f   (ngẫu nhiên: %.4f, chênh %+.4f)\n",
            avg_main, exp_main, avg_main - exp_main))
cat(sprintf("Tỉ lệ trúng đặc biệt  : %.4f   (ngẫu nhiên: %.4f, chênh %+.4f)\n",
            sp_rate, exp_spec, sp_rate - exp_spec))
cat(sprintf("Phân bố số chính trúng: 0=%d 1=%d 2=%d 3=%d 4=%d 5=%d\n",
            dist[1], dist[2], dist[3], dist[4], dist[5], dist[6]))
cat(sprintf("Số kỳ trúng >=3 số    : %d\n", sum(main_hits >= 3)))
# t-test đơn giản so mốc ngẫu nhiên
se <- sd(main_hits) / sqrt(nb)
z  <- if (se > 0) (avg_main - exp_main) / se else 0
cat(sprintf("z (số chính vs ngẫu nhiên) = %.2f  → %s\n", z,
            if (abs(z) < 1.96) "KHÔNG khác biệt có ý nghĩa (p>0.05)" else "khác biệt có ý nghĩa"))
cat("Lưu ý: xổ số độc lập — mọi khác biệt ở đây là dao động mẫu, KHÔNG phải lợi thế thật.\n")
