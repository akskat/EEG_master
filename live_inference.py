#!/usr/bin/env python
# ===============================================================
# live_inference.py – real-time Riemann+SVM inferens via joblib → LSL (“MI_Pred”)
# ===============================================================
import os, sys, time, json, threading
import numpy as np
from datetime import datetime as dt
from scipy.signal import iirnotch, butter, filtfilt
import joblib
from model_utils import CovTransport
from pylsl import StreamInfo, StreamOutlet, StreamInlet, resolve_stream

# ----------------------------------------------------------------
ART_DIR   = os.path.join(os.path.dirname(__file__), "saved_artifacts")
IN_NAME   = "BrainVision RDA"
OUT_NAME  = "MI_Pred"
POLL_S    = 1.0
VERBOSE   = True
# ----------------------------------------------------------------

print(f"⬇  Loading artefacts from {ART_DIR}")
pipe      = joblib.load(os.path.join(ART_DIR, "lda_riemann_pipeline.joblib"))
with open(os.path.join(ART_DIR, "eeg_channels.json")) as f:
    EEG_CHANS = json.load(f)
with open(os.path.join(ART_DIR, "preproc_meta.json")) as f:
    meta = json.load(f)
CLASSES   = np.load(os.path.join(ART_DIR, "label_classes.npy"), allow_pickle=True)

sfreq    = meta["sfreq"]       # 500
win_len  = meta["window_len"]  # 2000
step_len = meta["step_len"]    # 2000 — samme som window_len (ingen overlap)
print(f"   expecting {len(EEG_CHANS)} channels • sfreq={sfreq}Hz • window={win_len} samp • step={step_len} samp")

# design zero‐phase notch @50Hz og Butter‐bandpass 1–40 Hz
b_notch, a_notch = iirnotch(50.0, Q=30.0, fs=sfreq)
b_band,  a_band  = butter(4, [1/(sfreq/2), 40/(sfreq/2)], btype="band")

# q + Enter for å stoppe
def quit_on_q():
    if sys.stdin and sys.stdin.isatty():
        while True:
            if sys.stdin.readline().strip().lower()=="q":
                print("🛑  Quit key pressed"); os._exit(0)
threading.Thread(target=quit_on_q, daemon=True).start()

# vent på EEG‐stream
print(f"\n🔎 waiting for EEG stream '{IN_NAME}' …")
infos = resolve_stream("name", IN_NAME, 1, POLL_S)
if not infos:
    print(f"[EEG-LSL] ⛔ Ingen stream '{IN_NAME}'"); sys.exit(1)
print(f"[EEG-LSL] Connected to '{IN_NAME}'")
inlet = StreamInlet(infos[0], max_chunklen=step_len)

# hent LSL‐kanaler
def stream_labels(info):
    lbl=[]; ch=info.desc().child("channels").child("channel")
    while ch and not ch.empty():
        lbl.append(ch.child_value("label")); ch=ch.next_sibling()
    return lbl

xml_lbl = stream_labels(inlet.info())
print("LSL channels:", xml_lbl)
if all(ch in xml_lbl for ch in EEG_CHANS):
    sel_idx = [xml_lbl.index(ch) for ch in EEG_CHANS]
    print("[EEG-LSL] ✅ Channel mapping OK")
else:
    miss = [ch for ch in EEG_CHANS if ch not in xml_lbl]
    print(f"[EEG-LSL] ⛔ Mangler kanaler: {miss}"); sys.exit(1)

# opprett LSL‐outlet
out_info = StreamInfo(OUT_NAME, "Markers", 1, 0, 'string')
outlet   = StreamOutlet(out_info)

# ringbuffer
buf           = np.zeros((len(EEG_CHANS), win_len), np.float32)
ptr           = 0
total_samples = 0
first_window  = False

print("\n⏳ Streaming – Ctrl-C eller q + Enter for å stoppe\n")
try:
    while True:
        chunk,_ = inlet.pull_chunk(timeout=0.0)
        if not chunk:
            time.sleep(0.002); continue

        data = np.asarray(chunk, dtype=np.float32).T
        data = data[sel_idx,:]
        total_samples += data.shape[1]
        if VERBOSE:
            print(f"\r… received {total_samples:,} samples", end='')

        # fyll buffer til akkurat win_len
        while data.shape[1]:
            take = min(win_len - ptr, data.shape[1])
            buf[:,ptr:ptr+take] = data[:,:take]
            ptr += take
            data = data[:,take:]
            if ptr < win_len:
                continue

            if not first_window:
                print(f"\n🟢 first window ready ({total_samples/sfreq:.2f}s)")
                first_window = True

            # --- identisk preprosess som i notebook ---
            seg = filtfilt(b_notch, a_notch, buf, axis=1)
            seg = filtfilt(b_band,  a_band,  seg, axis=1)
            # ingen CAR (ble ikke brukt i treningen)
            baseline = seg[:,:int(0.5*sfreq)].mean(axis=1, keepdims=True)
            seg = seg - baseline

            # inferens med predict_proba
            X_in  = seg[np.newaxis,...]
            probs = pipe.predict_proba(X_in)[0]
            idx   = np.argmax(probs)
            label = pipe.classes_[idx]

            outlet.push_sample([label])
            ts = dt.now().strftime('%H:%M:%S.%f')[:-3]
            print(f"{ts}  {label:<8}  "
                  f"(p_REST={probs[pipe.classes_.tolist().index('REST')]:.2f}  "
                  f"p_IMAG={probs[pipe.classes_.tolist().index('IMAGERY')]:.2f})")

            # rull buffer og reset ptr
            buf = np.roll(buf, -step_len, axis=1)
            ptr = win_len - step_len

except KeyboardInterrupt:
    print("\n🛑  stopped by user")
