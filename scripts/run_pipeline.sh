#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <csv_file> <exercise_name> <output_html> [db_path]"
  exit 1
fi

csv_file="$1"
exercise_name="$2"
output_html="$3"
db_path="${4:-data/lifts.db}"

python3 -m lifting_data.cli --db "$db_path" init-db
python3 -m lifting_data.cli --db "$db_path" ingest --csv "$csv_file"
python3 -m lifting_data.cli --db "$db_path" plot --exercise "$exercise_name" --output "$output_html"

echo "Pipeline complete: $output_html"
