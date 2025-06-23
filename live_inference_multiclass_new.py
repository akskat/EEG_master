#!/usr/bin/env python
# ===============================================================
# live_inference_multiclass_new.py – real-time IIR‐filterbank‐multiklasse inferens
# ===============================================================
import os
import sys
import time
import json
import threading
import numpy as np
from datetime import datetime as dt
import joblib

# --- Må importeres for at pipeline unpickler skal finne klassen ---
from old.model_utils import CovTransport
from sklearn.base import TransformerMixin, BaseEstimator
from scipy.signal import iirnotch, butter, filtfilt
from pylsl import StreamInfo, StreamOutlet, StreamInlet, resolve_stream

# ----------------------------------------------------------------
# Definer BandSelector nøyaktig som i treningskoden
class BandSelector(TransformerMixin, BaseEstimator):
    def __init__(self, band_idx): self.band_idx = band_idx
    def fit(self, X, y=None):       return self
    def transform(self, X):
        # X shape: (n_epochs, n_bands, n_ch, n_times)
        return X[:, self.band_idx, :, :]

# Sti til filterbank‐artefakter
ART_DIR  = "./saved_artifacts_multiclass_new"
IN_NAME  = "BrainVision RDA"
OUT_NAME = "MI_Pred"
POLL_S   = 1.0
VERBOSE  = True

# Samme bånd‐definisjon som under trening
bands = {
    'delta': (1,   4),
    'theta': (4,   8),
    'alpha': (8,  12),
    'beta':  (12, 30),
    'gamma': (30,100)
}
# ----------------------------------------------------------------

print(f"⬇  Loading filterbank_multiclass_new artefacts from {ART_DIR}")
pipe = joblib.load(os.path.join(ART_DIR, "filterbank_multiclass_new_pipeline.joblib"))

with open(os.path.join(ART_DIR, "eeg_channels_multiclass_new.json")) as f:
    EEG_CHANS = json.load(f)
with open(os.path.join(ART_DIR, "preproc_meta_multiclass_new.json")) as f:
    meta = json.load(f)
CLASSES = np.load(os.path.join(ART_DIR, "label_classes_multiclass_new.npy"), allow_pickle=True)

sfreq    = meta["sfreq"]
win_len  = meta["window_len"]
step_len = meta["step_len"]
print(f"Expecting {len(EEG_CHANS)} channels • sfreq={sfreq} Hz • "
      f"window={win_len} samp • step={step_len} samp")

# q + Enter for å stoppe
def quit_on_q():
    if sys.stdin and sys.stdin.isatty():
        while True:
            if sys.stdin.readline().strip().lower() == "q":
                print("🛑 Quit key pressed")
                os._exit(0)
threading.Thread(target=quit_on_q, daemon=True).start()

# vent på EEG-stream
print(f"\n🔎 Waiting for EEG stream '{IN_NAME}' …")
infos = resolve_stream("name", IN_NAME, 1, POLL_S)
if not infos:
    print(f"[EEG-LSL] ⛔ Ingen stream '{IN_NAME}'"); sys.exit(1)
print(f"[EEG-LSL] Connected to '{IN_NAME}'")
inlet = StreamInlet(infos[0], max_chunklen=step_len)

# hent LSL-kanaler og sjekk mapping
def stream_labels(info):
    lbl=[]; ch=info.desc().child("channels").child("channel")
    while ch and not ch.empty():
        lbl.append(ch.child_value("label")); ch=ch.next_sibling()
    return lbl

xml_lbl = stream_labels(inlet.info())
if all(ch in xml_lbl for ch in EEG_CHANS):
    sel_idx = [xml_lbl.index(ch) for ch in EEG_CHANS]
    print("[EEG-LSL] ✅ Channel mapping OK")
else:
    miss = [ch for ch in EEG_CHANS if ch not in xml_lbl]
    print(f"[EEG-LSL] ⛔ Mangler kanaler: {miss}"); sys.exit(1)

# opprett LSL‐outlet
outlet = StreamOutlet(StreamInfo(OUT_NAME, "Markers", 1, 0, 'string'))

# ringbuffer
buf   = np.zeros((len(EEG_CHANS), win_len), np.float32)
ptr   = 0
total = 0
first = False

print("\n⏳ Streaming – Ctrl-C eller q + Enter for å stoppe\n")
try:
    while True:
        chunk,_ = inlet.pull_chunk(timeout=0.0)
        if not chunk:
            time.sleep(0.002)
            continue

        data = np.asarray(chunk, dtype=np.float32).T
        data = data[sel_idx,:]
        total += data.shape[1]
        if VERBOSE:
            print(f"\r… received {total:,} samples", end='')

        # fyll buffer
        while data.shape[1]:
            take = min(win_len - ptr, data.shape[1])
            buf[:, ptr:ptr+take] = data[:, :take]
            ptr += take
            data = data[:, take:]
            if ptr < win_len:
                continue

            if not first:
                print(f"\n🟢 first window ready ({total/sfreq:.2f}s)"); first=True

            # --- preprocessing med IIR‐filtre ---
            buf64 = buf.astype(np.float64)

            # 1) Zero-phase notch @50 Hz
            b_notch, a_notch = iirnotch(50.0, Q=30.0, fs=sfreq)
            seg = filtfilt(b_notch, a_notch, buf64, axis=1)

            # 2) Zero-phase bredbånd 1–100 Hz
            b_broad, a_broad = butter(4, [1/(sfreq/2), 100/(sfreq/2)], btype='band')
            seg = filtfilt(b_broad, a_broad, seg, axis=1)

            # 3) baseline‐korreksjon
            baseline = seg[:, :int(0.5*sfreq)].mean(axis=1, keepdims=True)
            seg = seg - baseline

            # 4) bygg filterbank‐array med IIR
            band_segs = []
            for (l,h) in bands.values():
                b_band, a_band = butter(4, [l/(sfreq/2), h/(sfreq/2)], btype='band')
                band_seg = filtfilt(b_band, a_band, seg, axis=1)
                band_segs.append(band_seg)
            X_fb = np.stack(band_segs, axis=0)[np.newaxis, ...]

            # inferens
            probs = pipe.predict_proba(X_fb)[0]
            idx   = np.argmax(probs)
            label = CLASSES[idx]
            outlet.push_sample([label])

            ts = dt.now().strftime('%H:%M:%S.%f')[:-3]
            prob_str = "  ".join(f"p_{c}={probs[i]:.2f}" for i,c in enumerate(CLASSES))
            print(f"{ts}  {label:<8}  ({prob_str})")

            # rull buffer
            buf = np.roll(buf, -step_len, axis=1)
            ptr = win_len - step_len

except KeyboardInterrupt:
    print("\n🛑 Stopped by user")
