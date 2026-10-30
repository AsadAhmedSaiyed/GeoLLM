"""
PRODUCTION SATELLITE CLASSIFIER (HUGGING FACE EUROSAT) - UPGRADED V2
===================================================================
Dataset: 'blanchon/EuroSAT_RGB' (27,000 Real Sentinel-2 satellite image patches)
Classes: 10 Universal Classes (Infrastructure, Agriculture, Water, Urban, Nature)
Algorithm: HistGradientBoosting with Sobel Edge & Contrast Spatial Features
Target Accuracy: 82% - 88%+ (CPU runtime: ~60-90 seconds)
"""

import time
from pathlib import Path
import numpy as np
import pandas as pd
from datasets import load_dataset
from scipy.ndimage import sobel
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.metrics import classification_report, confusion_matrix
import joblib


# =====================================================================
# STEP 1: STREAM & EXTRACT 14 ADVANCED SPATIAL & SPECTRAL FEATURES
# =====================================================================
def load_and_extract_hf_data(max_samples_per_class: int = 1200):
    """
    Downloads/streams real Sentinel-2 satellite patches directly from Hugging Face.
    Extracts 14 physical spectral indices, edge energies, contrast, and spatial disparity.
    """
    print("[HF-HUB] Connecting to Hugging Face Hub: 'blanchon/EuroSAT_RGB'...")
    t0 = time.time()

    dataset = load_dataset("blanchon/EuroSAT_RGB", split="train")
    label_names = dataset.features["label"].names
    
    print(f"[DONE] Found {len(dataset):,} satellite patches across {len(label_names)} classes:")
    for idx, name in enumerate(label_names):
        print(f"   [{idx}] {name}")

    print(f"\n[EXTRACT] Extracting 14 spectral & spatial texture features ({max_samples_per_class} samples/class)...")

    records = []
    class_counts = {i: 0 for i in range(len(label_names))}

    for sample in dataset:
        label = sample["label"]
        if class_counts[label] >= max_samples_per_class:
            continue

        # 64x64 satellite image (RGB from Sentinel-2 B04, B03, B02)
        img = np.array(sample["image"], dtype=np.float32) / 255.0
        r, g, b = img[:, :, 0], img[:, :, 1], img[:, :, 2]
        brightness = (r + g + b) / 3.0

        # 1. Core Spectral Reflectance (Means of center crop to avoid border artifacts)
        h, w = r.shape
        center_r = r[h//4:3*h//4, w//4:3*w//4]
        center_g = g[h//4:3*h//4, w//4:3*w//4]
        center_b = b[h//4:3*h//4, w//4:3*w//4]
        mean_r, mean_g, mean_b = float(np.mean(center_r)), float(np.mean(center_g)), float(np.mean(center_b))

        # 2. Spectral Indices (Physics of green vegetation & roofs)
        eps = 1e-6
        vari = (mean_g - mean_r) / (mean_g + mean_r - mean_b + eps)
        rb_ratio = mean_r / (mean_b + eps)
        ngrdi = (mean_g - mean_r) / (mean_g + mean_r + eps)
        bright_val = float(np.mean(brightness))

        # 3. Channel Textures (Local dispersion)
        texture = float(np.std(brightness))
        r_std = float(np.std(r))
        g_std = float(np.std(g))

        # 4. Sobel Edge Energy (Isolates linear Highways and winding Rivers)
        sx = sobel(brightness, axis=0)
        sy = sobel(brightness, axis=1)
        edge_mag_arr = np.sqrt(sx**2 + sy**2)
        edge_mag = float(np.mean(edge_mag_arr))
        edge_p90 = float(np.percentile(edge_mag_arr, 90))

        # 5. Dynamic Range Contrast (Separates flat crop fields from urban roofs & shadows)
        p10 = float(np.percentile(brightness, 10))
        p90 = float(np.percentile(brightness, 90))
        contrast = p90 - p10

        # 6. Quadrant Spatial Disparity (Diagonal crossings of roads / rivers vs isotropic forests)
        q1 = float(np.mean(brightness[:32, :32]))
        q2 = float(np.mean(brightness[:32, 32:]))
        q3 = float(np.mean(brightness[32:, :32]))
        q4 = float(np.mean(brightness[32:, 32:]))
        quad_disp = float(np.std([q1, q2, q3, q4]))

        records.append({
            "red": mean_r,
            "green": mean_g,
            "blue": mean_b,
            "vari": np.clip(vari, -2.0, 2.0),
            "rb_ratio": np.clip(rb_ratio, 0.0, 10.0),
            "ngrdi": np.clip(ngrdi, -1.0, 1.0),
            "brightness": bright_val,
            "texture": texture,
            "r_std": r_std,
            "g_std": g_std,
            "edge_mag": edge_mag,
            "edge_p90": edge_p90,
            "contrast": contrast,
            "quad_disp": quad_disp,
            "class_id": label
        })
        class_counts[label] += 1

        if all(c >= max_samples_per_class for c in class_counts.values()):
            break

    df = pd.DataFrame(records)
    print(f"[READY] Feature extraction complete in {time.time() - t0:.1f}s: {len(df):,} total samples prepared.")
    return df, label_names


# =====================================================================
# STEP 2: TRAIN PRODUCTION HIST-GRADIENT BOOSTING CLASSIFIER
# =====================================================================
def train_production_model(df: pd.DataFrame, label_names: list[str]):
    """
    Trains an ensemble of 300 Gradient Boosted Trees with early stopping
    and stratified k-fold cross-validation.
    """
    feature_cols = [
        "red", "green", "blue", "vari", "rb_ratio", "ngrdi",
        "brightness", "texture", "r_std", "g_std",
        "edge_mag", "edge_p90", "contrast", "quad_disp"
    ]
    X = df[feature_cols].values
    y = df["class_id"].values

    # Stratified 80/20 Train-Test Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    print("\n" + "="*65)
    print("[TREES] TRAINING UPGRADED HIST-GRADIENT BOOSTED DECISION TREES")
    print("="*65)

    clf = HistGradientBoostingClassifier(
        max_iter=300,            # Max boosting rounds
        learning_rate=0.08,      # Balanced learning rate
        max_leaf_nodes=63,       # Rich multi-class boundary capacity
        min_samples_leaf=20,     # Regularization leaf constraint
        class_weight="balanced", # Equalizes penalty across classes
        early_stopping=True,     # Halts when validation plateau occurs
        validation_fraction=0.15,
        n_iter_no_change=15,
        random_state=42
    )

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(clf, X_train, y_train, cv=cv, scoring="accuracy")
    print(f"[ACCURACY] 5-Fold Cross-Validation Accuracy: {scores.mean()*100:.2f}% (± {scores.std()*100:.2f}%)")

    t_start = time.time()
    clf.fit(X_train, y_train)
    print(f"[SPEED] Model fitted in {time.time() - t_start:.2f}s (stopped at tree iteration {clf.n_iter_})")

    y_pred = clf.predict(X_test)

    print("\n" + "="*65)
    print("[METRICS] UNSEEN SATELLITE TEST SET EVALUATION REPORT")
    print("="*65)
    print(classification_report(y_test, y_pred, target_names=label_names, digits=4))

    return clf, feature_cols


# =====================================================================
# STEP 3: EXPORT PRODUCTION ARTIFACT (.joblib)
# =====================================================================
def export_model_package(clf, label_names, feature_cols, filepath="eurosat_production_model.joblib"):
    """
    Serializes the model, human labels, class hex color palette, and schema.
    """
    palette = {
        0: "#ffd166",  # AnnualCrop (Yellow)
        1: "#1b4332",  # Forest (Deep Green)
        2: "#52b788",  # Herbaceous (Light Green)
        3: "#495057",  # Highway (Dark Asphalt)
        4: "#e63946",  # Industrial (Red)
        5: "#99d98c",  # Pasture (Pasture Green)
        6: "#b5e48c",  # PermanentCrop (Orchard Green)
        7: "#f77f00",  # Residential (Orange)
        8: "#00b4d8",  # River (Cyan)
        9: "#0055ff",  # SeaLake (Deep Blue)
    }

    artifact = {
        "model": clf,
        "classes": {i: name for i, name in enumerate(label_names)},
        "palette": palette,
        "features": feature_cols,
        "source": "European Space Agency Sentinel-2 (EuroSAT)",
        "version": "2.0.0"
    }
    joblib.dump(artifact, filepath)
    print(f"\n[EXPORT] Production model artifact exported to: '{filepath}'")

    # Auto-register into GeoLLM library model registry if directory exists
    geollm_model_dir = Path("lib/geollm_lib/models")
    if geollm_model_dir.is_dir():
        dest = geollm_model_dir / Path(filepath).name
        joblib.dump(artifact, dest)
        print(f"[REGISTER] Auto-registered into GeoLLM: '{dest}'")


# =====================================================================
# STEP 4: AGENT STREAM INFERENCE DEMO
# =====================================================================
def agent_stream_inference(model_path: str, H: int = 512, W: int = 512, chunk_rows: int = 128):
    """
    Demonstrates how the agent loads this model and classifies an arbitrary scene.
    """
    print("\n" + "="*65)
    print(f"[INFERENCE] AGENT INFERENCE: STREAMING {H}x{W} SATELLITE SCENE IN CHUNKS")
    print("="*65)

    artifact = joblib.load(model_path)
    model = artifact["model"]
    classes = artifact["classes"]

    # Simulated scene
    r = np.random.uniform(0.05, 0.40, (H, W)).astype(np.float32)
    g = np.random.uniform(0.05, 0.45, (H, W)).astype(np.float32)
    b = np.random.uniform(0.05, 0.35, (H, W)).astype(np.float32)

    eps = 1e-6
    vari = np.clip((g - r) / (g + r - b + eps), -2.0, 2.0)
    rb_ratio = np.clip(r / (b + eps), 0.0, 10.0)
    ngrdi = np.clip((g - r) / (g + r + eps), -1.0, 1.0)
    brightness = (r + g + b) / 3.0
    texture = np.full((H, W), 0.05, dtype=np.float32)
    r_std = np.full((H, W), 0.03, dtype=np.float32)
    g_std = np.full((H, W), 0.03, dtype=np.float32)
    edge_mag = np.full((H, W), 0.08, dtype=np.float32)
    edge_p90 = np.full((H, W), 0.12, dtype=np.float32)
    contrast = np.full((H, W), 0.20, dtype=np.float32)
    quad_disp = np.full((H, W), 0.02, dtype=np.float32)

    features = np.stack([
        r, g, b, vari, rb_ratio, ngrdi, brightness, texture,
        r_std, g_std, edge_mag, edge_p90, contrast, quad_disp
    ], axis=-1)

    out_classified = np.full((H, W), -1, dtype=np.int16)
    for r_start in range(0, H, chunk_rows):
        r_end = min(r_start + chunk_rows, H)
        slice_flat = features[r_start:r_end, :, :].reshape(-1, features.shape[-1])
        preds = model.predict(slice_flat)
        out_classified[r_start:r_end, :] = preds.reshape(r_end - r_start, W)

    print("Inference completed cleanly! Classified Distribution:")
    u_ids, counts = np.unique(out_classified, return_counts=True)
    total_px = H * W
    for uid, cnt in zip(u_ids, counts):
        pct = (cnt / total_px) * 100
        print(f"  * {classes[uid]:<22}: {pct:5.2f}% ({cnt:,} pixels)")


# =====================================================================
# MAIN RUNNER
# =====================================================================
if __name__ == "__main__":
    # 1. Download & process Hugging Face EuroSAT data (1,200 samples/class = 12,000 samples)
    df_samples, class_names = load_and_extract_hf_data(max_samples_per_class=1200)

    # 2. Train and validate upgraded model
    trained_model, feature_names = train_production_model(df_samples, class_names)

    # 3. Save package
    model_file = "eurosat_production_model.joblib"
    export_model_package(trained_model, class_names, feature_names, filepath=model_file)

    # 4. Demonstrate agent stream inference
    agent_stream_inference(model_file)
