#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "${SCRIPT_DIR}/common.sh"
load_project_config

RUN_DIR="data/my_world"
IMAGES_DIR=""
POSES_CSV=""
COLMAP_DIR=""
OUTPUT_DIR=""
CAMERA_MODEL="SIMPLE_PINHOLE"
HORIZONTAL_FOV_DEG="90.0"
FOCAL_PX=""
CX=""
CY=""
MATCHER="sequential"
SEQUENTIAL_OVERLAP=""
WRITE_PLY="true"
OVERWRITE="false"

usage() {
  cat <<'EOF'
Usage: scripts/run_colmap_3dgs_pipeline.sh [options]

Runs the full known-pose COLMAP pipeline for a captured Gazebo screenshot run and
creates a flat Brush/3DGS-style output folder containing images plus COLMAP bins.

Options:
  --run-dir PATH                  Run directory containing screenshots/ (default: data/my_world)
  --images-dir PATH               Captured image directory (default: RUN_DIR/screenshots/images)
  --poses-csv PATH                Pose CSV (default: RUN_DIR/screenshots/poses.csv)
  --colmap-dir PATH               Intermediate COLMAP work dir (default: RUN_DIR/colmap)
  --output-dir PATH               Final flat output dir (default: RUN_DIR/brush_output)
  --camera-model MODEL            COLMAP camera model: SIMPLE_PINHOLE or PINHOLE (default: SIMPLE_PINHOLE)
  --horizontal-fov-deg DEG        Used to derive focal length if --focal-px is omitted (default: 90.0)
  --focal-px PX                   Explicit focal length in pixels
  --cx PX                         Explicit principal point x in pixels
  --cy PX                         Explicit principal point y in pixels
  --matcher sequential|exhaustive Feature matcher to use (default: sequential)
  --sequential-overlap N          Optional SequentialMatching.overlap value
  --no-ply                        Skip writing output/points3D.ply
  --overwrite                     Remove existing COLMAP/output dirs before running
  -h, --help                      Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-dir)
      RUN_DIR="$2"
      shift 2
      ;;
    --images-dir)
      IMAGES_DIR="$2"
      shift 2
      ;;
    --poses-csv)
      POSES_CSV="$2"
      shift 2
      ;;
    --colmap-dir)
      COLMAP_DIR="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --camera-model)
      CAMERA_MODEL="$2"
      shift 2
      ;;
    --horizontal-fov-deg)
      HORIZONTAL_FOV_DEG="$2"
      shift 2
      ;;
    --focal-px)
      FOCAL_PX="$2"
      shift 2
      ;;
    --cx)
      CX="$2"
      shift 2
      ;;
    --cy)
      CY="$2"
      shift 2
      ;;
    --matcher)
      MATCHER="$2"
      shift 2
      ;;
    --sequential-overlap)
      SEQUENTIAL_OVERLAP="$2"
      shift 2
      ;;
    --no-ply)
      WRITE_PLY="false"
      shift
      ;;
    --overwrite)
      OVERWRITE="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

RUN_DIR="$(resolve_project_path "${RUN_DIR}")"
IMAGES_DIR="$(resolve_project_path "${IMAGES_DIR:-${RUN_DIR}/screenshots/images}")"
POSES_CSV="$(resolve_project_path "${POSES_CSV:-${RUN_DIR}/screenshots/poses.csv}")"
COLMAP_DIR="$(resolve_project_path "${COLMAP_DIR:-${RUN_DIR}/colmap}")"
OUTPUT_DIR="$(resolve_project_path "${OUTPUT_DIR:-${RUN_DIR}/brush_output}")"

require_dir "${IMAGES_DIR}" "captured images directory"
require_file "${POSES_CSV}" "poses CSV"

if ! command -v colmap >/dev/null 2>&1; then
  echo "Missing required command: colmap" >&2
  exit 1
fi

if [[ "${CAMERA_MODEL}" != "SIMPLE_PINHOLE" && "${CAMERA_MODEL}" != "PINHOLE" ]]; then
  echo "Unsupported camera model: ${CAMERA_MODEL}" >&2
  exit 1
fi

if [[ "${MATCHER}" != "sequential" && "${MATCHER}" != "exhaustive" ]]; then
  echo "Unsupported matcher: ${MATCHER}" >&2
  exit 1
fi

if [[ "${OVERWRITE}" == "true" ]]; then
  rm -rf "${COLMAP_DIR}" "${OUTPUT_DIR}"
elif [[ -e "${COLMAP_DIR}" || -e "${OUTPUT_DIR}" ]]; then
  echo "COLMAP or output directory already exists. Pass --overwrite to replace them." >&2
  echo "  COLMAP dir: ${COLMAP_DIR}" >&2
  echo "  Output dir: ${OUTPUT_DIR}" >&2
  exit 1
fi

mkdir -p "${COLMAP_DIR}"

FIRST_IMAGE="$(find "${IMAGES_DIR}" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) | sort | head -n 1)"
if [[ -z "${FIRST_IMAGE}" ]]; then
  echo "No PNG/JPEG images found in ${IMAGES_DIR}" >&2
  exit 1
fi

read -r WIDTH HEIGHT DEFAULT_FOCAL DEFAULT_CX DEFAULT_CY < <(
  python3 - "${FIRST_IMAGE}" "${HORIZONTAL_FOV_DEG}" <<'INNER_PY'
import math
import struct
import sys
from pathlib import Path

path = Path(sys.argv[1])
hfov = float(sys.argv[2])
if path.suffix.lower() == ".png":
    with path.open("rb") as f:
        header = f.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise SystemExit(f"Not a PNG: {path}")
    width, height = struct.unpack(">II", header[16:24])
else:
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit("Pillow is required to derive JPEG dimensions") from exc
    width, height = Image.open(path).size
focal = width / (2.0 * math.tan(math.radians(hfov) / 2.0))
print(width, height, focal, width * 0.5, height * 0.5)
INNER_PY
)

FOCAL_PX="${FOCAL_PX:-${DEFAULT_FOCAL}}"
CX="${CX:-${DEFAULT_CX}}"
CY="${CY:-${DEFAULT_CY}}"
CAMERA_PARAMS="${FOCAL_PX},${CX},${CY}"
if [[ "${CAMERA_MODEL}" == "PINHOLE" ]]; then
  CAMERA_PARAMS="${FOCAL_PX},${FOCAL_PX},${CX},${CY}"
fi

DATABASE_PATH="${COLMAP_DIR}/database.db"
SPARSE_KNOWN_DIR="${COLMAP_DIR}/sparse_known"
SPARSE_DIR="${COLMAP_DIR}/sparse/0"

printf 'Images: %s\n' "${IMAGES_DIR}"
printf 'Poses: %s\n' "${POSES_CSV}"
printf 'COLMAP work dir: %s\n' "${COLMAP_DIR}"
printf 'Final 3DGS output: %s\n' "${OUTPUT_DIR}"
printf 'Image size: %sx%s\n' "${WIDTH}" "${HEIGHT}"
printf 'Camera: %s %s\n' "${CAMERA_MODEL}" "${CAMERA_PARAMS}"

colmap feature_extractor \
  --database_path "${DATABASE_PATH}" \
  --image_path "${IMAGES_DIR}" \
  --ImageReader.camera_model "${CAMERA_MODEL}" \
  --ImageReader.single_camera 1 \
  --ImageReader.camera_params "${CAMERA_PARAMS}"

if [[ "${MATCHER}" == "sequential" ]]; then
  matcher_args=(colmap sequential_matcher --database_path "${DATABASE_PATH}")
  if [[ -n "${SEQUENTIAL_OVERLAP}" ]]; then
    matcher_args+=(--SequentialMatching.overlap "${SEQUENTIAL_OVERLAP}")
  fi
  "${matcher_args[@]}"
else
  colmap exhaustive_matcher --database_path "${DATABASE_PATH}"
fi

python3 "${SCRIPT_DIR}/export_colmap_known_poses.py" \
  --poses-csv "${POSES_CSV}" \
  --images-dir "${IMAGES_DIR}" \
  --output-dir "${SPARSE_KNOWN_DIR}" \
  --database-path "${DATABASE_PATH}" \
  --camera-model "${CAMERA_MODEL}" \
  --focal-px "${FOCAL_PX}" \
  --cx "${CX}" \
  --cy "${CY}"

mkdir -p "${SPARSE_DIR}"
colmap point_triangulator \
  --database_path "${DATABASE_PATH}" \
  --image_path "${IMAGES_DIR}" \
  --input_path "${SPARSE_KNOWN_DIR}" \
  --output_path "${SPARSE_DIR}" \
  --clear_points 1 \
  --refine_intrinsics 0 \
  --Mapper.fix_existing_frames 1 \
  --Mapper.ba_refine_focal_length 0 \
  --Mapper.ba_refine_principal_point 0 \
  --Mapper.ba_refine_extra_params 0

colmap model_converter \
  --input_path "${SPARSE_DIR}" \
  --output_path "${SPARSE_DIR}" \
  --output_type BIN

mkdir -p "${OUTPUT_DIR}"
find "${IMAGES_DIR}" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) -exec cp -a {} "${OUTPUT_DIR}/" \;
cp -a "${SPARSE_DIR}/cameras.bin" "${OUTPUT_DIR}/"
cp -a "${SPARSE_DIR}/images.bin" "${OUTPUT_DIR}/"
cp -a "${SPARSE_DIR}/points3D.bin" "${OUTPUT_DIR}/"

if [[ "${WRITE_PLY}" == "true" ]]; then
  colmap model_converter \
    --input_path "${SPARSE_DIR}" \
    --output_path "${OUTPUT_DIR}/points3D.ply" \
    --output_type PLY
fi

printf '\nDone. Brush/3DGS output folder:\n%s\n' "${OUTPUT_DIR}"
