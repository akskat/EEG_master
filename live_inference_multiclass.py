#!/usr/bin/env python
import os, sys, time, json, threading
import numpy as np
from datetime import datetime as dt
from scipy.signal import iirnotch, butter, filtfilt
import joblib
from pylsl import StreamInfo, StreamOutlet, StreamInlet, resolve_stream

# ----------------------------------------------------------------
ART_DIR   = './saved_artifacts_multiclass'
IN_NAME   = "BrainVision RDA"
OUT_NAME  = "MI_Pred"
POLL_S    = 1.0
VERBOSE   = True
# ----------------------------------------------------------------

print(f"⬇  Loading multiclass artefacts from {ART_DIR}")
pipe      = joblib.load(os.path.join(ART_DIR, "multiclass_riemann_pipeline.joblib"))
with open(os.path.join(ART_DIR, "eeg_channels_multiclass.json")) as f:
    EEG_CHANS = json.load(f)
with open(os.path.join(ART_DIR, "preproc_meta_multiclass.json")) as f:
    meta = json.load(f)
CLASSES   = np.load(os.path.join(ART_DIR, "label_classes_multiclass.npy"), allow_pickle=True)

sfreq    = meta["sfreq"]
win_len  = meta["window_len"]
step_len = meta["step_len"]
print(f"   Expecting {len(EEG_CHANS)} channels • sfreq={sfreq}Hz • window={win_len} samp • step={step_len} samp")

# design notch & bandpass
b_notch, a_notch = iirnotch(50.0, Q=30.0, fs=sfreq)
b_band,  a_band  = butter(4, [1/(sfreq/2), 40/(sfreq/2)], btype="band")

# quit on 'q'
def quit_on_q():
    if sys.stdin and sys.stdin.isatty():
        while True:
            if sys.stdin.readline().strip().lower()=="q":
                print("🛑 Quit"); os._exit(0)
threading.Thread(target=quit_on_q, daemon=True).start()

# connect to LSL
infos = resolve_stream("name", IN_NAME, 1, POLL_S)
if not infos:
    print(f"No stream '{IN_NAME}'"); sys.exit(1)
inlet = StreamInlet(infos[0], max_chunklen=step_len)

# channel mapping
def stream_labels(info):
    lbl=[]; ch=info.desc().child("channels").child("channel")
    while ch and not ch.empty():
        lbl.append(ch.child_value("label")); ch=ch.next_sibling()
    return lbl

xml_lbl = stream_labels(inlet.info())
sel_idx = [xml_lbl.index(ch) for ch in EEG_CHANS]
print("[EEG-LSL] Channel mapping OK")

# outlet
outlet = StreamOutlet(StreamInfo(OUT_NAME, "Markers", 1, 0, 'string'))

# buffer
buf = np.zeros((len(EEG_CHANS), win_len), np.float32)
ptr = total = 0
first = False

print("⏳ Streaming – Ctrl-C or q to stop")
try:
    while True:
        chunk,_ = inlet.pull_chunk(timeout=0.0)
        if not chunk:
            time.sleep(0.002); continue

        data = np.asarray(chunk, dtype=np.float32).T
        data = data[sel_idx,:]
        total += data.shape[1]
        if VERBOSE: print(f"\r… received {total} samples", end='')

        while data.shape[1]:
            take = min(win_len - ptr, data.shape[1])
            buf[:,ptr:ptr+take] = data[:,:take]
            ptr += take; data = data[:,take:]
            if ptr < win_len: continue

            if not first:
                print(f"\n🟢 first window ready at {total/sfreq:.2f}s"); first = True

            # preprocessing
            seg = filtfilt(b_notch, a_notch, buf, axis=1)
            seg = filtfilt(b_band,  a_band,  seg, axis=1)
            baseline = seg[:,:int(0.5*sfreq)].mean(1, keepdims=True)
            seg = seg - baseline

            # inference
            X_in  = seg[np.newaxis,...]
            probs = pipe.predict_proba(X_in)[0]
            idx   = np.argmax(probs)
            label = CLASSES[idx]
            outlet.push_sample([label])

            ts = dt.now().strftime('%H:%M:%S.%f')[:-3]
            prob_str = "  ".join(f"p_{c}={probs[i]:.2f}" for i,c in enumerate(CLASSES))
            print(f"{ts}  {label:<8}  ({prob_str})")

            # roll buffer
            buf = np.roll(buf, -step_len, axis=1)
            ptr = win_len - step_len

except KeyboardInterrupt:
    print("\n🛑 stopped by user")
