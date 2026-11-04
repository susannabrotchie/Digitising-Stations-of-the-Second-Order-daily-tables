# ============================================================
# BATCH dataresqc QC SCRIPT
# ============================================================
#
# Recursively finds .tsv files beneath INPUT_DIR
#
# Variable names determine frequency:
#
# DAILY:
#   tx, tn, rr, sc, sd, fs
#
# SUBDAILY:
#   p, mslp, ta, td, e, rh, w, dd, n
#
# For each file:
#   - identifies variable from filename 
#   - determines daily/subdaily from variable
#   - creates a dedicated output directory (for plots and summaries)
#   - runs climatic outlier QC (using package default IQRs)
#   - creates boxplot PDF (saved into the dedicated output directory)
#   - creates the appropriate daily/subdaily plot
#   - runs appropriate range/repetition/coherence tests
#   - runs WMO gross errors, time consistency, and impossible values
#   - runs duplicate date/time checks
#   - runs paired internal consistency tests
#   - counts non-missing values available to each QC test
#   - securely injects the QC flags into the mirrored SEF files
#
# At the end:
#   - creates qc_summary.csv
#   - prints total values passed to each test
#
# ============================================================

library(dataresqc)

# ============================================================
# 1. DIRECTORIES
# ============================================================

INPUT_DIR <- ""

# Where the QC plots, logs, and summary CSVs will go
OUTPUT_DIR <- ""

# Where the final SEF files (with flags injected) will go, mirroring the INPUT_DIR structure
FLAGGED_DIR <- ""

dir.create(OUTPUT_DIR, recursive = TRUE, showWarnings = FALSE)
dir.create(FLAGGED_DIR, recursive = TRUE, showWarnings = FALSE)


log_file <- file.path(OUTPUT_DIR, "batch_qc_log.txt")
# Create a file connection
log_con <- file(log_file, open = "wt")
# Sink BOTH standard output and standard error (messages/warnings) to the file
sink(log_con, type = "output")
sink(log_con, type = "message")

# ============================================================
# 2. VARIABLES AND FREQUENCIES
# ============================================================

# Variables which contain DAILY data
daily_variables <- c("tx", "tn", "rr", "ss", "tgn")

# Variables which contain SUBDAILY data
subdaily_variables <- c("p", "mslp", "ta", "e", "rh", "w", "dd", "n")

all_variables <- c(daily_variables, subdaily_variables)

# ============================================================
# 3. FIND ALL TSV FILES
# ============================================================

files <- list.files(
  path = INPUT_DIR,
  pattern = "\\.tsv$",
  recursive = TRUE,
  full.names = TRUE,
  ignore.case = TRUE
)

cat("\n")
cat("============================================\n")
cat("BATCH DATARESQC\n")
cat("============================================\n")
cat("Input directory:\n")
cat(INPUT_DIR, "\n")
cat("\nFiles found:", length(files), "\n")
cat("\nQC Output (plots/logs) directory:\n")
cat(OUTPUT_DIR, "\n")
cat("\nFlagged SEF files mirrored directory:\n")
cat(FLAGGED_DIR, "\n")
cat("============================================\n")
cat("\n")

if (length(files) == 0) {
  stop("No .tsv files were found.")
}

# ============================================================
# 4. HELPER FUNCTIONS 
# ============================================================

# Read a TSV and count non-missing observations.
count_nonmissing_variable <- function(file, variable) {
  lines <- tryCatch(readLines(file, warn = FALSE), error = function(e) return(NULL))
  if (is.null(lines) || length(lines) == 0) return(NA_integer_)
  
  header_idx <- grep("^[Yy]ear", trimws(lines))
  if (length(header_idx) > 0) {
    lines <- lines[header_idx[1]:length(lines)]
    dat <- tryCatch(
      read.delim(text = lines, header = TRUE, sep = "\t", stringsAsFactors = FALSE, check.names = FALSE, na.strings = c("", "NA", "NaN", "-999", "-9999")),
      error = function(e) return(NULL)
    )
  } else {
    dat <- tryCatch(
      read.delim(file, header = TRUE, sep = "\t", stringsAsFactors = FALSE, check.names = FALSE, na.strings = c("", "NA", "NaN", "-999", "-9999")),
      error = function(e) return(NULL)
    )
  }
  if (is.null(dat) || nrow(dat) == 0) return(NA_integer_)

  candidate_names <- names(dat)
  val_col <- which(tolower(trimws(candidate_names)) == "value")
  if (length(val_col) > 0) return(sum(!is.na(dat[[val_col[1]]])))

  exact_match <- which(tolower(trimws(candidate_names)) == tolower(variable))
  if (length(exact_match) > 0) return(sum(!is.na(dat[[exact_match[1]]])))

  aliases <- switch(
    variable,
    p=c("p","pres","pressure"), mslp=c("mslp","msl","slp"), ta=c("ta","temp","temperature"),
    tx=c("tx","tmax","t_max"), tn=c("tn","tmin","t_min"), 
    e=c("e"), rh=c("rh","relative_humidity"),
    rr=c("rr","rain","rainfall","precip"),
    td=c("td","dew","dewpoint","dew_point"), w=c("w","wind","windspeed","wind_speed"),
    dd=c("dd","winddir","wind_direction"), n=c("n","cloud","cloudcover","cloud_cover"),
    ss=c("ss"), tgn=c("tgn"),
    character(0)
  )
  alias_match <- which(tolower(trimws(candidate_names)) %in% tolower(aliases))
  if (length(alias_match) > 0) return(sum(!is.na(dat[[alias_match[1]]])))
  return(NA_integer_)
}

add_test_count <- function(counts, variable, test_name, n_values) {
  counts[[length(counts) + 1]] <- data.frame(
    variable = variable, test = test_name, values = n_values, stringsAsFactors = FALSE
  )
  return(counts)
}

# Extracts the 6 required metadata elements from the SEF header:
# station ID, latitude, longitude, altitude, variable code, units
get_sef_meta <- function(file) {
  lines <- tryCatch(readLines(file, warn = FALSE), error = function(e) return(NULL))
  if (is.null(lines)) return(rep(NA_character_, 6))
  
  header_idx <- grep("^[Yy]ear", trimws(lines))
  if (length(header_idx) == 0) return(rep(NA_character_, 6))
  
  meta_lines <- lines[1:(header_idx[1] - 1)]
  
  extract_val <- function(key) {
    idx <- grep(paste0("^", key, "\\b"), meta_lines, ignore.case = TRUE)
    if (length(idx) > 0) {
      parts <- strsplit(meta_lines[idx[1]], "\t")[[1]]
      if (length(parts) >= 2) return(trimws(parts[2]))
    }
    return(NA_character_)
  }
  
  c(
    extract_val("ID"),
    extract_val("Lat"),
    extract_val("Lon"),
    extract_val("Alt"),
    extract_val("Vbl"),
    extract_val("Units")
  )
}

# ============================================================
# CUSTOM ROBUST FLAG INJECTION
# ============================================================
custom_inject_flags <- function(sef_file, qc_file, out_file, frequency) {
  
  # 1. Read Original File safely
  lines <- tryCatch(readLines(sef_file, warn = FALSE), error = function(e) return(NULL))
  if (is.null(lines) || length(lines) == 0) return(FALSE)
  
  header_idx <- grep("^[Yy]ear", trimws(lines))
  if (length(header_idx) == 0) return(FALSE)
  header_idx <- header_idx[1]
  
  meta_lines <- lines[1:(header_idx - 1)]
  
  # Force all classes to character so trailing zeros aren't stripped
  sef_data <- read.delim(text = lines[header_idx:length(lines)], sep = "\t",
                         header = TRUE, stringsAsFactors = FALSE, check.names = FALSE,
                         colClasses = "character")
  
  # Clean column names
  colnames(sef_data) <- trimws(colnames(sef_data))
  
  # 2. Read QC File
  qc_data <- tryCatch(read.delim(qc_file, sep = "\t", header = FALSE,
                                 stringsAsFactors = FALSE, colClasses = "character"),
                      error = function(e) return(NULL))
  
  if (is.null(qc_data) || nrow(qc_data) == 0) {
    file.copy(sef_file, out_file, overwrite = TRUE)
    return(TRUE)
  }
  
  # Helper: Cleans numbers so "0.0" mathematically matches "0"
  clean_num <- function(x) suppressWarnings(as.character(as.numeric(trimws(x))))
  
  # 3. Dynamic Name-based Mapping (Bypasses all Header Name/Spacing Issues)
  s_yr <- clean_num(sef_data$Year)
  s_mo <- clean_num(sef_data$Month)
  s_dy <- clean_num(sef_data$Day)
  s_vl <- clean_num(sef_data$Value)
  
  # The QC .txt file generated by dataresqc has 6 cols for daily, 8 for subdaily
  if (ncol(qc_data) == 6) {
    # QC Daily: Var, Year, Month, Day, Value, Flags
    q_yr <- clean_num(qc_data[[2]])
    q_mo <- clean_num(qc_data[[3]])
    q_dy <- clean_num(qc_data[[4]])
    q_vl <- clean_num(qc_data[[5]])
    qc_data$qc_flags <- qc_data[[6]]
    
    sef_data$join_key <- paste(s_yr, s_mo, s_dy, s_vl, sep="-")
    qc_data$join_key <- paste(q_yr, q_mo, q_dy, q_vl, sep="-")
    
  } else {
    # QC Subdaily: Var, Year, Month, Day, Hour, Minute, Value, Flags
    s_hr <- clean_num(sef_data$Hour)
    s_mn <- clean_num(sef_data$Minute)
    
    q_yr <- clean_num(qc_data[[2]])
    q_mo <- clean_num(qc_data[[3]])
    q_dy <- clean_num(qc_data[[4]])
    q_hr <- clean_num(qc_data[[5]])
    q_mn <- clean_num(qc_data[[6]])
    q_vl <- clean_num(qc_data[[7]])
    qc_data$qc_flags <- qc_data[[8]]
    
    sef_data$join_key <- paste(s_yr, s_mo, s_dy, s_hr, s_mn, s_vl, sep="-")
    qc_data$join_key <- paste(q_yr, q_mo, q_dy, q_hr, q_mn, q_vl, sep="-")
  }
  
  # 4. Handle identical rows AND Aggregate multiple test flags safely
  sef_data$dup_idx <- ave(seq_len(nrow(sef_data)), sef_data$join_key, FUN = seq_along)
  qc_data$dup_idx <- ave(seq_len(nrow(qc_data)), qc_data$join_key, qc_data$qc_flags, FUN = seq_along)
  
  qc_agg <- aggregate(qc_flags ~ join_key + dup_idx, data = qc_data, FUN = function(flags) {
    paste(unique(trimws(flags)), collapse = ";")
  })
  
  sef_data$final_key <- paste(sef_data$join_key, sef_data$dup_idx, sep="-")
  qc_agg$final_key <- paste(qc_agg$join_key, qc_agg$dup_idx, sep="-")
  
  # 5. Merge
  sef_data$orig_id <- seq_len(nrow(sef_data))
  merged <- merge(sef_data, qc_agg[, c("final_key", "qc_flags"), drop = FALSE], by = "final_key", all.x = TRUE)
  merged <- merged[order(merged$orig_id), ]
  
  # 6. Cleanup variables
  merged$final_key <- NULL
  merged$join_key <- NULL
  merged$dup_idx <- NULL
  merged$orig_id <- NULL
  
  # Dynamically find the Meta column (fallback to creating it if it doesn't exist)
  if (!"Meta" %in% colnames(merged)) merged$Meta <- ""
  merged$Meta[is.na(merged$Meta)] <- ""
  merged$qc_flags[is.na(merged$qc_flags)] <- ""
  
  # 7. Inject Flags into the Meta String
  for (i in seq_len(nrow(merged))) {
    if (merged$qc_flags[i] != "") {
      if (merged$Meta[i] == "") {
        merged$Meta[i] <- paste0("qc=", merged$qc_flags[i])
      } else {
        merged$Meta[i] <- paste0(merged$Meta[i], "|qc=", merged$qc_flags[i])
      }
    }
  }
  merged$qc_flags <- NULL
  
  # 8. Write exact SEF format file
  out_con <- file(out_file, "w")
  writeLines(meta_lines, out_con)
  write.table(merged, out_con, sep = "\t", quote = FALSE, row.names = FALSE, na = "NA")
  close(out_con)
  
  return(TRUE)
}

# ============================================================
# 5. FUNCTION TO PROCESS ONE FILE
# ============================================================
process_file <- function(file) {

  filename <- basename(file)
  base_name <- tools::file_path_sans_ext(filename)

  # Replicate Folder Structure
  input_dir_base <- sub("/+$", "", INPUT_DIR)
  file_dir <- dirname(file)
  rel_dir <- sub(input_dir_base, "", file_dir, fixed = TRUE)
  rel_dir <- sub("^/+", "", rel_dir) 
  
  flagged_out_dir <- file.path(FLAGGED_DIR, rel_dir)
  dir.create(flagged_out_dir, recursive = TRUE, showWarnings = FALSE)

  variable <- NA_character_
  for (v in all_variables) {
    pattern <- paste0("_", v, "_[0-9]{8}_[0-9]{8}\\.tsv$")
    if (grepl(pattern, filename, ignore.case = TRUE)) {
      variable <- v
      break
    }
  }

  if (is.na(variable)) {
    cat("WARNING: Could not identify variable from filename:", filename, "\n")
    file.copy(from = file, to = file.path(flagged_out_dir, filename), overwrite = TRUE)
    return(list(
      result = data.frame(file = file, filename = filename, variable = NA_character_, frequency = "unknown", output_directory = NA_character_, status = "SKIPPED_UNKNOWN_VARIABLE", tests = "", message = "Could not identify variable from filename", stringsAsFactors = FALSE),
      counts = data.frame(variable = character(0), test = character(0), values = numeric(0), stringsAsFactors = FALSE)
    ))
  }

  variable <- tolower(variable)
  if (variable %in% daily_variables) { frequency <- "daily" } 
  else if (variable %in% subdaily_variables) { frequency <- "subdaily" } 
  else { frequency <- "unknown" }

  # create hierarchical output directory
  # Extract station name from filename (everything before _variablecode_YYYYMMDD_YYYYMMDD.tsv)
  # safely handles station names with underscores (e.g., BIRR_CASTLE)
  pattern_to_remove <- paste0("_", variable, "_[0-9]{8}_[0-9]{8}\\.tsv$")
  station_name <- sub(pattern_to_remove, "", filename, ignore.case = TRUE)
  
  # Create nested directory: OUTPUT_DIR / Station_Name / File_Base_Name
  output_dir <- file.path(OUTPUT_DIR, station_name, base_name)
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

  result <- "SUCCESS"
  message_text <- ""
  tests <- character(0)
  counts <- list()

  n_available <- count_nonmissing_variable(file, variable)

  # Initialise flag for records with less than 5 years of data
  short_record_outliers <- FALSE

  cat("\n--------------------------------------------\n")
  cat("Processing:", filename, "\n")
  cat("Variable:", variable, "| Frequency:", frequency, "\n")
  cat("Available non-missing values:", n_available, "\n")
  cat("--------------------------------------------\n")

  tryCatch({

    if (frequency == "unknown") {
      result <- "SKIPPED"
      message_text <- paste("Unknown frequency for variable:", variable)
      cat("\nWARNING:", message_text, "\n")
      file.copy(from = file, to = file.path(flagged_out_dir, filename), overwrite = TRUE)

    } else {

      # ======================================================
      # CLIMATIC OUTLIERS
      # ======================================================
      cat("\nRunning climatic outliers...\n")
      
      # Capture the package's console output
      co_out <- capture.output({
        res <- try(climatic_outliers(file, outpath = output_dir), silent = TRUE)
      })
      
      # Print the captured output back to the log file so it's not lost
      if (length(co_out) > 0) cat(paste(co_out, collapse = "\n"), "\n")
      
      # Check if the package printed the specific "Not enough data" message
      if (any(grepl("Not enough data for outliers test (minimum 5 years of non-zero values for daily data)", co_out, ignore.case = TRUE)) || any(grepl("5 years", co_out, ignore.case = TRUE))) {
        short_record_outliers <- TRUE
        cat("  [SKIPPED] climatic_outliers: Not enough data (requires 5+ years).\n")
      } else if (!inherits(res, "try-error")) {
        tests <- c(tests, "climatic_outliers")
        counts <- add_test_count(counts, variable, "climatic_outliers", n_available)
      } else { 
        cat("  [TEST FAILED] climatic_outliers:", attr(res, "condition")$message, "\n") 
      }

      # ======================================================
      # BOXPLOT
      # ======================================================
      cat("Creating boxplot...\n")
      boxplot_file <- file.path(output_dir, paste0(base_name, "_boxplot.pdf"))
      
      bp_out <- capture.output({
        res <- try(climatic_outliers(file, outpath = output_dir, bplot = TRUE, outfile = boxplot_file), silent = TRUE)
      })
      if (length(bp_out) > 0) cat(paste(bp_out, collapse = "\n"), "\n")
      
      if (any(grepl("Not enough data", bp_out, ignore.case = TRUE)) || any(grepl("5 years", bp_out, ignore.case = TRUE))) {
        cat("  [SKIPPED] boxplot: Not enough data (requires 5+ years).\n")
      } else if (!inherits(res, "try-error")) {
        tests <- c(tests, "boxplot")
        counts <- add_test_count(counts, variable, "boxplot", n_available)
      } else { 
        cat("  [TEST FAILED] boxplot:", attr(res, "condition")$message, "\n") 
      }

      if (frequency == "daily") {
        # DAILY PLOT
        cat("Creating daily plot...\n")
        daily_plot_file <- file.path(output_dir, paste0(base_name, "_daily_plot.pdf"))
        res <- try(plot_daily(file, len = 1, outfile = daily_plot_file, startyear = NA, endyear = NA, miss = TRUE, units = NA), silent = TRUE)
        if (!inherits(res, "try-error")) {
          tests <- c(tests, "plot_daily")
          counts <- add_test_count(counts, variable, "plot_daily", n_available)
        } else { cat("  [TEST FAILED] plot_daily:", attr(res, "condition")$message, "\n") }

        # DUPLICATE DATES
        cat("Running duplicate dates test...\n")
        res <- try(duplicate_dates(dailydata = file, meta = NULL, outpath = output_dir), silent = TRUE)
        if (!inherits(res, "try-error")) {
          tests <- c(tests, "duplicate_dates")
          counts <- add_test_count(counts, variable, "duplicate_dates", n_available)
        } else { cat("  [TEST FAILED] duplicate_dates:", attr(res, "condition")$message, "\n") }

        # DAILY REPETITION
        cat("Running daily repetition test...\n")
        res <- try(daily_repetition(dailydata = file, meta = NULL, outpath = output_dir, n = 4), silent = TRUE)
        if (!inherits(res, "try-error")) {
          tests <- c(tests, "daily_repetition")
          counts <- add_test_count(counts, variable, "daily_repetition", n_available)
        } else { cat("  [TEST FAILED] daily_repetition:", attr(res, "condition")$message, "\n") }

        # DAILY OUT-OF-RANGE
        if (variable %in% c("tx", "tn", "rr")) {
          cat("Running daily out-of-range test...\n")
          res <- try(daily_out_of_range(file, meta = NULL, outpath = output_dir, tmax_upper = 45, tmax_lower = -30, tmin_upper = 30, tmin_lower = -40, rr_upper = 200, rr_lower = 0, w_upper = 30, w_lower = 0, dd_upper = 360, dd_lower = 0), silent = TRUE)
          if (!inherits(res, "try-error")) {
            tests <- c(tests, "daily_out_of_range")
            counts <- add_test_count(counts, variable, "daily_out_of_range", n_available)
          } else { cat("  [TEST FAILED] daily_out_of_range:", attr(res, "condition")$message, "\n") }
        }

        # TEMPORAL COHERENCE
        if (variable %in% c("tx", "tn")) {
          cat("Running temporal coherence...\n")
          res <- try(temporal_coherence(file, meta = NULL, outpath = output_dir, temp_jumps = 20, windspeed_jumps = 15), silent = TRUE)
          if (!inherits(res, "try-error")) {
            tests <- c(tests, "temporal_coherence")
            counts <- add_test_count(counts, variable, "temporal_coherence", n_available)
          } else { cat("  [TEST FAILED] temporal_coherence:", attr(res, "condition")$message, "\n") }
        }

      } else if (frequency == "subdaily") {

        # SUBDAILY PLOT
        cat("Creating subdaily plot...\n")
        subdaily_plot_file <- file.path(output_dir, paste0(base_name, "_subdaily_plot.pdf"))
        res <- try(plot_subdaily(file, year = NA, outfile = subdaily_plot_file, fixed = TRUE, units = NA, time_offset = 0), silent = TRUE)
        if (!inherits(res, "try-error")) {
          tests <- c(tests, "plot_subdaily")
          counts <- add_test_count(counts, variable, "plot_subdaily", n_available)
        } else { cat("  [TEST FAILED] plot_subdaily:", attr(res, "condition")$message, "\n") }

        # DUPLICATE TIMES
        cat("Running duplicate times test...\n")
        res <- try(duplicate_times(subdailydata = file, meta = NULL, outpath = output_dir), silent = TRUE)
        if (!inherits(res, "try-error")) {
          tests <- c(tests, "duplicate_times")
          counts <- add_test_count(counts, variable, "duplicate_times", n_available)
        } else { cat("  [TEST FAILED] duplicate_times:", attr(res, "condition")$message, "\n") }

        # SUBDAILY OUT-OF-RANGE
        if (variable %in% c("ta", "w", "dd")) {
          cat("Running subdaily out-of-range test...\n")
          res <- try(subdaily_out_of_range(file, meta = NULL, outpath = output_dir, time_offset = 0, ta_day_upper = 45, ta_day_lower = -35, ta_night_upper = 40, ta_night_lower = -40, rr_upper = 100, rr_lower = 0, w_upper = 50, w_lower = 0, dd_upper = 360, dd_lower = 0), silent = TRUE)
          if (!inherits(res, "try-error")) {
            tests <- c(tests, "subdaily_out_of_range")
            counts <- add_test_count(counts, variable, "subdaily_out_of_range", n_available)
          } else { cat("  [TEST FAILED] subdaily_out_of_range:", attr(res, "condition")$message, "\n") }
        }

        # SUBDAILY REPETITION
        cat("Running subdaily repetition test...\n")
        res <- try(subdaily_repetition(subdailydata = file, meta = NULL, outpath = output_dir, n = 6), silent = TRUE)
        if (!inherits(res, "try-error")) {
          tests <- c(tests, "subdaily_repetition")
          counts <- add_test_count(counts, variable, "subdaily_repetition", n_available)
        } else { cat("  [TEST FAILED] subdaily_repetition:", attr(res, "condition")$message, "\n") }
      }

      # ======================================================
      # Parse SEF Metadata for WMO Tests
      # ======================================================
      sef_meta <- get_sef_meta(file)
      
      # Read the data to pass as a data frame so 'meta' is NOT ignored
      lines_tmp <- tryCatch(readLines(file, warn = FALSE), error = function(e) return(NULL))
      if (!is.null(lines_tmp)) {
        hdr_idx <- grep("^[Yy]ear", trimws(lines_tmp))[1]
        raw_dat <- read.delim(text = lines_tmp[hdr_idx:length(lines_tmp)], sep = "\t", stringsAsFactors = FALSE, check.names = FALSE)
        
        # Format strictly to the 5 or 7 columns the package demands
        if (frequency == "subdaily") {
          series_df <- data.frame(sef_meta[5], raw_dat$Year, raw_dat$Month, raw_dat$Day, raw_dat$Hour, raw_dat$Minute, raw_dat$Value, stringsAsFactors = FALSE)
        } else {
          series_df <- data.frame(sef_meta[5], raw_dat$Year, raw_dat$Month, raw_dat$Day, raw_dat$Value, stringsAsFactors = FALSE)
        }
      } else {
        series_df <- NULL
      }

      # ======================================================
      # WMO GROSS ERRORS
      # ======================================================
      if (variable %in% c("p", "mslp", "ta", "td", "w") && !is.null(series_df)) {
        cat("Running WMO gross errors...\n")
        res <- try(wmo_gross_errors(series = series_df, meta = sef_meta, outpath = output_dir), silent = TRUE)
        if (!inherits(res, "try-error")) {
          tests <- c(tests, "wmo_gross_errors")
          counts <- add_test_count(counts, variable, "wmo_gross_errors", n_available)
        } else { cat("  [TEST FAILED] wmo_gross_errors:", attr(res, "condition")$message, "\n") }
      }

      # ======================================================
      # WMO TIME CONSISTENCY
      # ======================================================
      if (frequency == "subdaily" && variable %in% c("p", "mslp", "ta", "td") && !is.null(series_df)) {
        cat("Running WMO time consistency...\n")
        res <- try(wmo_time_consistency(series = series_df, meta = sef_meta, outpath = output_dir), silent = TRUE)
        if (!inherits(res, "try-error")) {
          tests <- c(tests, "wmo_time_consistency")
          counts <- add_test_count(counts, variable, "wmo_time_consistency", n_available)
        } else { cat("  [TEST FAILED] wmo_time_consistency:", attr(res, "condition")$message, "\n") }
      }

      # IMPOSSIBLE VALUES
      if (variable %in% c("rh", "n")) {
        cat("Running impossible values test...\n")
        res <- try(impossible_values(file, meta = NULL, outpath = output_dir), silent = TRUE)
        if (!inherits(res, "try-error")) {
          tests <- c(tests, "impossible_values")
          counts <- add_test_count(counts, variable, "impossible_values", n_available)
        } else { cat("  [TEST FAILED] impossible_values:", attr(res, "condition")$message, "\n") }
      }
 
      # INTERNAL CONSISTENCY for DAILY DATA
      ic_pairs <- list(c("tx", "tn"))
      for (pair in ic_pairs) {
        v_primary <- pair[1]
        v_secondary <- pair[2]
        
        if (variable == v_primary) {
          search_pattern <- paste0("_", v_primary, "_")
          replace_pattern <- paste0("_", v_secondary, "_")
          paired_file <- sub(search_pattern, replace_pattern, file, ignore.case = TRUE)
          
          if (paired_file != file && file.exists(paired_file)) {
            cat("Running internal consistency (", v_primary, " vs ", v_secondary, ")...\n", sep="")
            test_nm <- paste0("internal_consistency_", v_primary, "_", v_secondary)
            res <- try(internal_consistency(c(file, paired_file), meta = NULL, outpath = output_dir), silent = TRUE)
            if (!inherits(res, "try-error")) {
              tests <- c(tests, test_nm)
              counts <- add_test_count(counts, variable, test_nm, n_available)
            } else { cat("  [TEST FAILED]", test_nm, ":", attr(res, "condition")$message, "\n") }
          }
        }
      }

      # ======================================================
      # LOCATE AND RENAME THE QC TEXT FILE
      # ======================================================
      txt_files <- list.files(output_dir, pattern = "\\.txt$", full.names = TRUE)
      qcfile_path <- file.path(output_dir, paste0("qc_", base_name, ".txt"))
      
      generated_txts <- txt_files[txt_files != qcfile_path]
      if (length(generated_txts) > 0) {
        file.rename(from = generated_txts[1], to = qcfile_path)
        if (length(generated_txts) > 1) {
          file.remove(generated_txts[-1])
        }
      }

      # ======================================================
      # WRITE FLAGS TO FINAL MIRRORED SEF FILE (CUSTOM INJECTION)
      # ======================================================
      if (file.exists(qcfile_path)) {
        cat("\nInjecting flags manually into mirrored directory...\n")
        
        success <- custom_inject_flags(
          sef_file = file,
          qc_file = qcfile_path,
          out_file = file.path(flagged_out_dir, filename),
          frequency = frequency
        )
        
        if(success) {
          tests <- c(tests, "custom_inject_flags")
        } else {
          cat("Failed to manually inject flags! Falling back to unflagged copy.\n")
          file.copy(from = file, to = file.path(flagged_out_dir, filename), overwrite = TRUE)
        }
      } else {
        cat("\nNo QC flag file generated for", filename, "(no tests flagged or file empty).\n")
        cat("Copying unflagged original file to mirrored directory to maintain complete dataset.\n")
        file.copy(from = file, to = file.path(flagged_out_dir, filename), overwrite = TRUE)
      }

    }

  }, error = function(e) {
    # This now ONLY catches truly fatal script errors that aren't caught by the individual test try() blocks
    result <<- "ERROR"
    message_text <<- conditionMessage(e)
    cat("\nFATAL ERROR processing file:\n", filename, "\n", message_text, "\n")
  })

  # Convert counts list to dataframe
  if (length(counts) > 0) {
    counts_df <- do.call(rbind, counts)
  } else {
    counts_df <- data.frame(variable = character(0), test = character(0), values = numeric(0), stringsAsFactors = FALSE)
  }

  return(list(
    result = data.frame(file = file, filename = filename, variable = variable, frequency = frequency, 
    output_directory = output_dir, 
    status = result, 
    short_record = short_record_outliers,
    tests = paste(tests, collapse = "; "), message = message_text, stringsAsFactors = FALSE),
    counts = counts_df
  ))
}

# ============================================================
# 6. PROCESS ALL FILES
# ============================================================

results <- vector("list", length(files))
value_counts <- vector("list", length(files))
start_time <- Sys.time()

for (i in seq_along(files)) {
  cat("\n============================================\n")
  cat("FILE", i, "OF", length(files), "\n")
  cat("============================================\n")

  processed <- process_file(files[i])
  results[[i]] <- processed$result
  value_counts[[i]] <- processed$counts
}

# ============================================================
# 7. COMBINE RESULTS & WRITE SUMMARIES
# ============================================================
summary <- do.call(rbind, results)
all_value_counts <- do.call(rbind, value_counts)

summary_file <- file.path(OUTPUT_DIR, "qc_summary.csv")
value_count_file <- file.path(OUTPUT_DIR, "qc_value_counts.csv")

write.csv(summary, summary_file, row.names = FALSE)
write.csv(all_value_counts, value_count_file, row.names = FALSE)

# ============================================================
# 8. FINAL REPORT
# ============================================================
end_time <- Sys.time()

cat("\n\n============================================\n")
cat("BATCH QC COMPLETE\n")
cat("============================================\n")
cat("Files found: ", nrow(summary), "\n", sep = "")
cat("Successful:  ", sum(summary$status == "SUCCESS"), "\n", sep = "")
cat("Errors:      ", sum(summary$status == "ERROR"), "\n", sep = "")
cat("Skipped:     ", sum(grepl("SKIPPED", summary$status)), "\n", sep = "")
cat("< 5 Yrs Data (Outliers Skipped): ", sum(summary$short_record), "\n", sep = "")

cat("\n============================================\n")
cat("QC VALUE COUNT SUMMARY\n")
cat("============================================\n")

if (nrow(all_value_counts) > 0) {
  overall_test_totals <- aggregate(values ~ test, data = all_value_counts, FUN = function(x) sum(x, na.rm = TRUE), na.action = na.pass)
  overall_test_totals <- overall_test_totals[order(overall_test_totals$test), ]
  cat("\nTOTAL VALUES AVAILABLE TO EACH TEST:\n--------------------------------------------\n")
  for (i in seq_len(nrow(overall_test_totals))) {
    cat(sprintf("%-35s %12s\n", overall_test_totals$test[i], format(overall_test_totals$values[i], big.mark = ",", scientific = FALSE)))
  }

  variable_test_totals <- aggregate(values ~ variable + test, data = all_value_counts, FUN = function(x) sum(x, na.rm = TRUE), na.action = na.pass)
  variable_test_totals <- variable_test_totals[order(variable_test_totals$variable, variable_test_totals$test), ]
  cat("\nVALUES BY VARIABLE AND TEST:\n--------------------------------------------\n")
  current_variable <- ""
  for (i in seq_len(nrow(variable_test_totals))) {
    this_variable <- variable_test_totals$variable[i]
    if (this_variable != current_variable) {
      cat("\n", toupper(this_variable), "\n", sep = "")
      current_variable <- this_variable
    }
    cat(sprintf("  %-33s %12s\n", variable_test_totals$test[i], format(variable_test_totals$values[i], big.mark = ",", scientific = FALSE)))
  }

  total_values_all_tests <- sum(all_value_counts$values, na.rm = TRUE)
  cat("\n--------------------------------------------\n")
  cat("Total values passed across all test applications: ", format(total_values_all_tests, big.mark = ",", scientific = FALSE), "\n", sep = "")
} else {
  cat("\nNo value-count information was recorded.\n")
}

cat("\nSummary written to:\n", summary_file, "\n")
cat("\nValue-count summary written to:\n", value_count_file, "\n")
cat("\nMirrored Flagged Dataset written to:\n", FLAGGED_DIR, "\n")
cat("\nStarted:\n", as.character(start_time), "\n")
cat("\nFinished:\n", as.character(end_time), "\n")
cat("\n============================================\n")
# ============================================================
# END LOGGING TO FILE
# ============================================================
# Close BOTH sinks
sink(type = "message")
sink(type = "output")

# Close the file connection
close(log_con)

# Print one final message directly to the terminal so you know it finished
cat("\nBatch QC processing complete.\nAll terminal output, warnings, and errors have been saved to:\n", log_file, "\n\n")