#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import sqlite3
import struct
import sys
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
VIEW_TO_OPTICAL = [
    [0.0, -1.0, 0.0],
    [0.0, 0.0, -1.0],
    [1.0, 0.0, 0.0],
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export a COLMAP text model with known poses from this repo's "
            "capture_gui_camera_survey.py outputs."
        )
    )
    parser.add_argument("--poses-csv", type=Path, required=True, help="Input poses.csv from capture_gui_camera_survey.py")
    parser.add_argument("--images-dir", type=Path, required=True, help="Directory containing captured images")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory to write cameras.txt, images.txt, and points3D.txt")
    parser.add_argument("--database-path", type=Path, help="Optional COLMAP database.db. If set, image IDs match database image IDs")
    parser.add_argument("--camera-model", choices=["SIMPLE_PINHOLE", "PINHOLE"], default="SIMPLE_PINHOLE")
    parser.add_argument("--single-camera", action="store_true", default=True, help="Use one shared camera for all images, enabled by default")
    parser.add_argument("--per-image-camera", dest="single_camera", action="store_false", help="Write one camera entry per image")
    parser.add_argument("--focal-px", type=float, help="Focal length in pixels. Overrides --horizontal-fov-deg")
    parser.add_argument("--horizontal-fov-deg", type=float, default=90.0, help="Horizontal field of view used to derive focal length when --focal-px is omitted")
    parser.add_argument("--cx", type=float, help="Principal point x in pixels. Defaults to image center")
    parser.add_argument("--cy", type=float, help="Principal point y in pixels. Defaults to image center")
    return parser.parse_args()


def read_png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as f:
        header = f.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"Not a valid PNG: {path}")
    return struct.unpack(">II", header[16:24])


def read_jpeg_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as f:
        if f.read(2) != b"\xff\xd8":
            raise ValueError(f"Not a valid JPEG: {path}")
        while True:
            marker_start = f.read(1)
            if marker_start == b"":
                break
            if marker_start != b"\xff":
                continue
            marker = f.read(1)
            while marker == b"\xff":
                marker = f.read(1)
            if marker in {b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6", b"\xc7", b"\xc9", b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"}:
                length = struct.unpack(">H", f.read(2))[0]
                data = f.read(length - 2)
                height, width = struct.unpack(">HH", data[1:5])
                return width, height
            if marker in {b"\xd8", b"\xd9"}:
                continue
            length_data = f.read(2)
            if len(length_data) != 2:
                break
            length = struct.unpack(">H", length_data)[0]
            f.seek(length - 2, 1)
    raise ValueError(f"Could not read JPEG size: {path}")


def image_size(path: Path) -> tuple[int, int]:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return read_png_size(path)
    if suffix in {".jpg", ".jpeg"}:
        return read_jpeg_size(path)
    raise ValueError(f"Unsupported image extension '{path.suffix}' for {path}")


def matmul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [
        [sum(a[row][k] * b[k][col] for k in range(3)) for col in range(3)]
        for row in range(3)
    ]


def transpose(m: list[list[float]]) -> list[list[float]]:
    return [[m[col][row] for col in range(3)] for row in range(3)]


def matvec(m: list[list[float]], v: list[float]) -> list[float]:
    return [sum(m[row][col] * v[col] for col in range(3)) for row in range(3)]


def rotation_matrix_from_rpy(roll: float, pitch: float, yaw: float) -> list[list[float]]:
    cr = math.cos(roll)
    sr = math.sin(roll)
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    cy = math.cos(yaw)
    sy = math.sin(yaw)
    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]


def rotation_matrix_to_quaternion(r: list[list[float]]) -> list[float]:
    trace = r[0][0] + r[1][1] + r[2][2]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        qw = 0.25 * s
        qx = (r[2][1] - r[1][2]) / s
        qy = (r[0][2] - r[2][0]) / s
        qz = (r[1][0] - r[0][1]) / s
    elif r[0][0] > r[1][1] and r[0][0] > r[2][2]:
        s = math.sqrt(1.0 + r[0][0] - r[1][1] - r[2][2]) * 2.0
        qw = (r[2][1] - r[1][2]) / s
        qx = 0.25 * s
        qy = (r[0][1] + r[1][0]) / s
        qz = (r[0][2] + r[2][0]) / s
    elif r[1][1] > r[2][2]:
        s = math.sqrt(1.0 + r[1][1] - r[0][0] - r[2][2]) * 2.0
        qw = (r[0][2] - r[2][0]) / s
        qx = (r[0][1] + r[1][0]) / s
        qy = 0.25 * s
        qz = (r[1][2] + r[2][1]) / s
    else:
        s = math.sqrt(1.0 + r[2][2] - r[0][0] - r[1][1]) * 2.0
        qw = (r[1][0] - r[0][1]) / s
        qx = (r[0][2] + r[2][0]) / s
        qy = (r[1][2] + r[2][1]) / s
        qz = 0.25 * s
    norm = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
    return [qw / norm, qx / norm, qy / norm, qz / norm]


def focal_from_horizontal_fov(width: int, horizontal_fov_deg: float) -> float:
    return width / (2.0 * math.tan(math.radians(horizontal_fov_deg) / 2.0))


def camera_params(model: str, focal_px: float, cx: float, cy: float) -> list[float]:
    if model == "SIMPLE_PINHOLE":
        return [focal_px, cx, cy]
    if model == "PINHOLE":
        return [focal_px, focal_px, cx, cy]
    raise ValueError(f"Unsupported camera model: {model}")


def load_database_image_ids(database_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(database_path)
    try:
        rows = conn.execute("SELECT image_id, name FROM images").fetchall()
    finally:
        conn.close()
    return {name: image_id for image_id, name in rows}


def resolve_image_path(images_dir: Path, poses_csv: Path, image_ref: str) -> tuple[Path, str]:
    ref = Path(image_ref)
    candidates = []
    if ref.is_absolute():
        candidates.append(ref)
    else:
        candidates.append(images_dir / ref.name)
        candidates.append(images_dir / ref)
        candidates.append(poses_csv.parent / ref)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve(), candidate.name
    raise FileNotFoundError(f"Could not resolve image '{image_ref}' under {images_dir}")


def colmap_pose_from_gazebo_row(row: dict[str, str]) -> tuple[list[float], list[float]]:
    center = [float(row["x"]), float(row["y"]), float(row["z"])]
    rot_c2w = rotation_matrix_from_rpy(float(row["roll"]), float(row["pitch"]), float(row["yaw"]))
    rot_w2_view = transpose(rot_c2w)
    rot_w2_optical = matmul(VIEW_TO_OPTICAL, rot_w2_view)
    translation = [-value for value in matvec(rot_w2_optical, center)]
    quaternion = rotation_matrix_to_quaternion(rot_w2_optical)
    return quaternion, translation


def main() -> int:
    args = parse_args()
    poses_csv = args.poses_csv.resolve()
    images_dir = args.images_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not poses_csv.exists():
        print(f"poses.csv does not exist: {poses_csv}", file=sys.stderr)
        return 1
    if not images_dir.exists():
        print(f"images directory does not exist: {images_dir}", file=sys.stderr)
        return 1

    db_image_ids = load_database_image_ids(args.database_path.resolve()) if args.database_path else None
    camera_rows: list[tuple[int, int, int, list[float]]] = []
    image_rows: list[tuple[int, list[float], list[float], int, str]] = []

    with poses_csv.open(newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"No pose rows found in {poses_csv}", file=sys.stderr)
        return 1

    shared_camera_spec: tuple[int, int, int, list[float]] | None = None
    for fallback_image_id, row in enumerate(rows, start=1):
        image_path, image_name = resolve_image_path(images_dir, poses_csv, row["image"])
        if image_path.suffix.lower() not in IMAGE_EXTS:
            print(f"Unsupported image extension for {image_path}", file=sys.stderr)
            return 1
        width, height = image_size(image_path)
        focal_px = args.focal_px if args.focal_px is not None else focal_from_horizontal_fov(width, args.horizontal_fov_deg)
        cx = args.cx if args.cx is not None else width * 0.5
        cy = args.cy if args.cy is not None else height * 0.5
        params = camera_params(args.camera_model, focal_px, cx, cy)

        image_id = fallback_image_id
        if db_image_ids is not None:
            image_id = db_image_ids.get(image_name, -1)
            if image_id < 0:
                print(f"Image '{image_name}' is not present in database '{args.database_path}'", file=sys.stderr)
                return 1

        camera_id = 1 if args.single_camera else image_id
        if args.single_camera:
            if shared_camera_spec is None:
                shared_camera_spec = (1, width, height, params)
                camera_rows.append(shared_camera_spec)
            elif (width, height) != (shared_camera_spec[1], shared_camera_spec[2]):
                print("All images must have the same dimensions when using --single-camera", file=sys.stderr)
                return 1
        else:
            camera_rows.append((camera_id, width, height, params))

        quaternion, translation = colmap_pose_from_gazebo_row(row)
        image_rows.append((image_id, quaternion, translation, camera_id, image_name))

    image_rows.sort(key=lambda row: row[0])
    output_dir.mkdir(parents=True, exist_ok=True)

    with (output_dir / "cameras.txt").open("w", encoding="ascii") as f:
        f.write("# Camera list with one line of data per camera:\n")
        f.write("#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        f.write(f"# Number of cameras: {len(camera_rows)}\n")
        for camera_id, width, height, params in camera_rows:
            param_str = " ".join(f"{value:.17g}" for value in params)
            f.write(f"{camera_id} {args.camera_model} {width} {height} {param_str}\n")

    with (output_dir / "images.txt").open("w", encoding="ascii") as f:
        f.write("# Image list with two lines of data per image:\n")
        f.write("#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
        f.write("#   POINTS2D[] as (X, Y, POINT3D_ID)\n")
        f.write(f"# Number of images: {len(image_rows)}\n")
        for image_id, quaternion, translation, camera_id, image_name in image_rows:
            pose_str = " ".join(f"{value:.17g}" for value in quaternion + translation)
            f.write(f"{image_id} {pose_str} {camera_id} {image_name}\n\n")

    with (output_dir / "points3D.txt").open("w", encoding="ascii") as f:
        f.write("# 3D point list with one line of data per point:\n")
        f.write("#   POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[] as (IMAGE_ID, POINT2D_IDX)\n")
        f.write("# Number of points: 0\n")

    print(f"Wrote COLMAP known-pose text model to {output_dir}")
    print(f"Images referenced by name from {images_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
