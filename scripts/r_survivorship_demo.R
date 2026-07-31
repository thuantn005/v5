#!/usr/bin/env Rscript
# r_survivorship_demo.R
# --------------------------------------------------------------------------
# BÀI HỌC (học tập): vì sao chọn "vé từng trúng nhiều nhất trong quá khứ"
# (survivorship) KHÔNG giúp trúng ở tương lai.
#
# Cách chứng minh (out-of-sample, chuẩn ML):
#   1. Huấn luyện Random Forest trên toàn lịch sử → xác suất mỗi số → dùng làm
#      TRỌNG SỐ sinh một pool vé có seed (tái lập).
#   2. Chia lịch sử: TRAIN (80% kỳ đầu) và TEST (20% kỳ cuối, "tương lai").
#   3. Chọn TOP vé theo số lần trúng >=3 số trên TRAIN.
#   4. Xem chính những vé "quán quân TRAIN" đó biểu hiện thế nào trên TEST.
#
# Kết quả kỳ vọng: top-TRAIN KHÔNG hơn trung bình pool trên TEST → "giỏi trong
# quá khứ" chỉ là may rủi, không có trí nhớ, không dự báo được tương lai.
#
# Dùng: Rscript scripts/r_survivorship_demo.R --csv data/all.csv [--n 4000]

suppressWarnings(suppressMessages(library(randomForest)))

args <- commandArgs(trailingOnly = TRUE)
get_arg <- function(f, d) { i <- match(f, args); if (!is.na(i) && i < length(args)) args[i+1] else d }
csv_path <- get_arg("--csv", "data/all.csv")
N   <- as.integer(get_arg("--n", "4000"))   # số vé trong pool
W <- 30; WARMUP <- 50; NTREE <- 200

df  <- read.csv(csv_path, colClasses = "character", stringsAsFactors = FALSE)
ids <- suppressWarnings(as.integer(df$draw_id)); ok <- !is.na(ids)
df <- df[ok, ]; ids <- ids[ok]; o <- order(ids); df <- df[o, ]; ids <- ids[o]
n <- nrow(df)

extract <- function(js, key) {
  m <- regmatches(js, regexpr(paste0('"', key, '"[^]]*\\]'), js))
  if (length(m) == 0L) return(integer(0))
  as.integer(regmatches(m, gregexpr("[0-9]+", m))[[1]])
}
# Ma trận thành viên số chính: DrawMat[i,k]=1 nếu số k về ở kỳ i.
DrawMat <- matrix(0L, n, 35)
for (i in seq_len(n)) { v <- extract(df$result_json[i], "numbers"); v <- v[v>=1 & v<=35]; if (length(v)) DrawMat[i, v] <- 1L }

# --- Random Forest: xác suất mỗi số chính (trạng thái cuối) làm trọng số ---
cum <- apply(DrawMat, 2, cumsum)
C0  <- rbind(matrix(0L,1,35), cum[-n,,drop=FALSE])
recent <- C0; if (n>W) recent[(W+1):n,] <- C0[(W+1):n,] - C0[1:(n-W),]
ls <- matrix(0L,n,35)
for (k in 1:35){ last<-0L; for(i in 1:n){ ls[i,k]<-last; if(DrawMat[i,k]==1L) last<-i } }
gap <- (row(C0)-1L) - ls
idx <- (WARMUP+1):n
train_rf <- data.frame(TanSuat=as.vector(C0[idx,]), SoKyChuaVe=as.vector(gap[idx,]),
                       TanSuatGanDay=as.vector(recent[idx,]), KetQua=factor(as.vector(DrawMat[idx,]),levels=c(0,1)))
lsf <- integer(35); for(k in 1:35){ w<-which(DrawMat[,k]==1L); lsf[k]<- if(length(w)) max(w) else 0L }
now_df <- data.frame(TanSuat=cum[n,], SoKyChuaVe=n-lsf, TanSuatGanDay=cum[n,]-(if(n>W) cum[n-W,] else rep(0L,35)))
set.seed(1); rf <- randomForest(KetQua~., data=train_rf, ntree=NTREE)
prob <- predict(rf, now_df, type="prob")[,"1"]; prob <- prob/sum(prob)

# --- Sinh pool N vé (5 số chính) theo trọng số RF, mỗi vé 1 seed ---
TicketMat <- matrix(0L, N, 35)
for (s in 1:N) { set.seed(1000+s); pick <- sample(1:35, 5, prob=prob); TicketMat[s, pick] <- 1L }

# --- Đếm số lần trúng >=3 số trên TRAIN và TEST ---
Tsplit <- floor(n*0.8)
Hits <- TicketMat %*% t(DrawMat)          # N x n : số số chính khớp mỗi (vé,kỳ)
win_train <- rowSums(Hits[, 1:Tsplit] >= 3)
win_test  <- rowSums(Hits[, (Tsplit+1):n] >= 3)
n_test <- n - Tsplit

topk <- 10
top_by_train <- order(win_train, decreasing=TRUE)[1:topk]

cat("================ BÀI HỌC SURVIVORSHIP (Random Forest, R) ================\n")
cat(sprintf("Pool: %d vé (trọng số RF) | TRAIN %d kỳ, TEST %d kỳ\n", N, Tsplit, n_test))
cat(sprintf("\nTrung bình TOÀN POOL — trúng>=3 số:  TRAIN %.3f/vé | TEST %.3f/vé\n",
            mean(win_train), mean(win_test)))
cat(sprintf("Top %d vé 'quán quân TRAIN':\n", topk))
cat(sprintf("   trên TRAIN: %.3f trúng/vé (cao — đã chọn theo đây)\n", mean(win_train[top_by_train])))
cat(sprintf("   trên TEST : %.3f trúng/vé\n", mean(win_test[top_by_train])))
cat(sprintf("   Pool TEST : %.3f trúng/vé (mốc)\n", mean(win_test)))
edge <- mean(win_test[top_by_train]) - mean(win_test)
cat(sprintf("\n>>> Lợi thế của 'quán quân quá khứ' trên tương lai: %+.3f trúng/vé\n", edge))
cat(sprintf(">>> Tương quan (win_train, win_test) = %.3f  (≈0 nghĩa là quá khứ KHÔNG báo trước tương lai)\n",
            cor(win_train, win_test)))
cat("\nKẾT LUẬN: chọn 'vé từng trúng nhiều/từng trúng J1' KHÔNG cho lợi thế nào ở\n")
cat("tương lai — mọi vé vẫn 1/3.895.584 mỗi kỳ. Đó là bản chất, không phải lỗi model.\n")
