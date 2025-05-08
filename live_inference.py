#!/usr/bin/env python
# ===============================================================
# live_inference.py  –  real-time EEGNet-inferens → LSL (“MI_Pred”)
# ===============================================================
import os, sys, time, json, threading
from datetime import datetime as dt

import numpy  as np
from   scipy.signal import butter, lfilter
import tensorflow as tf
from   pylsl import (StreamInfo, StreamOutlet, StreamInlet,
                     resolve_stream, FOREVER)

# ----------------------------------------------------------------
ART_DIR   = os.path.join(os.path.dirname(__file__), "saved_artifacts")
IN_NAME   = "BrainVision RDA"        # EEG-stream fra RDA-Connector
OUT_NAME  = "MI_Pred"               # etiketter sendes her
POLL_S    = 1.0                     # hvor ofte vi leter etter EEG-stream
VERBOSE   = True
# ----------------------------------------------------------------

print(f"⬇  Loading artefacts from  {ART_DIR}")
model = tf.saved_model.load(os.path.join(ART_DIR, "EEGNet_MI"))

with open(os.path.join(ART_DIR, "eeg_channels.json")) as f:
    EEG_CHANS = json.load(f)

with open(os.path.join(ART_DIR, "preproc_meta.json")) as f:
    meta = json.load(f)
sfreq, win_len, step = meta["sfreq"], meta["window_len"], meta["step_len"]

# etikett-liste
lbl_json = os.path.join(ART_DIR, "label_classes.json")
lbl_npy  = os.path.join(ART_DIR, "label_classes.npy")
if os.path.exists(lbl_json):
    with open(lbl_json) as f: CLASSES = np.array(json.load(f))
else:
    CLASSES = np.load(lbl_npy, allow_pickle=True).astype(str)

print(f"   expecting {len(EEG_CHANS)} channels  •  sfreq={sfreq}  "
      f"window={win_len} samp  step={step}")

# band-pass
b, a = butter(4, [8/(sfreq/2), 30/(sfreq/2)], btype='band')

# ---------- quit-tråd (q + Enter) -------------------------------
def quit_on_q():
    if sys.stdin is None or not sys.stdin.isatty(): return
    while True:
        if sys.stdin.readline().strip().lower() == 'q':
            print("🛑  Quit key pressed"); os._exit(0)
threading.Thread(target=quit_on_q, daemon=True).start()

# ---------- hjelp: hent kanal-etiketter fra LSL-XML -------------
def stream_labels(info):
    lbl = []
    ch  = info.desc().child("channels").child("channel")
    while ch and not ch.empty():
        lbl.append(ch.child_value("label"))
        ch = ch.next_sibling()
    return lbl

# ---------- finn EEG-stream -------------------------------------
print(f"\n🔎 waiting for stream '{IN_NAME}' …")
while True:
    lst = resolve_stream("name", IN_NAME, 1, POLL_S)
    if lst: break

info  = lst[0]
inlet = StreamInlet(info, max_chunklen=step)    # NB riktig klasse!

xml_labels = stream_labels(info)
if xml_labels:
    print("✅ stream labels →", xml_labels[:5], "…")
    sel_idx = [xml_labels.index(ch) for ch in EEG_CHANS]
else:
    print("⚠  no labels – using first", len(EEG_CHANS), "channels")
    sel_idx = list(range(len(EEG_CHANS)))

# ---------- lag marker-outlet -----------------------------------
out_info = StreamInfo(OUT_NAME, "Markers", 1, 0, 'string')
outlet   = StreamOutlet(out_info)

# ---------- ringbuffer & hovedsløyfe ----------------------------
buf  = np.zeros((len(EEG_CHANS), win_len), np.float32)
ptr  = 0
total_samples = 0
first_window  = False

print("\n⏳  Streaming – Ctrl-C eller skriv q + Enter for å stoppe\n")
try:
    while True:
        chunk, _ = inlet.pull_chunk(timeout=0.0)   # non-blocking
        if not chunk:
            time.sleep(0.002)
            continue

        chunk = np.asarray(chunk, dtype=np.float32).T
        chunk = chunk[sel_idx, :]                  # plukk 32 kanaler
        total_samples += chunk.shape[1]

        if VERBOSE:
            print(f"\r… received {total_samples:,} samples", end='')

        while chunk.shape[1]:
            space = win_len - ptr
            take  = min(space, chunk.shape[1])
            buf[:, ptr:ptr+take] = chunk[:, :take]
            ptr  += take
            chunk = chunk[:, take:]

            if ptr < win_len:
                continue          # vindu ikke fylt ennå

            if not first_window:
                print(f"\n🟢 first window ready ({total_samples/sfreq:.2f}s)")
                first_window = True

            # ---------- preprocess ------------------------------
            seg = lfilter(b, a, buf, axis=1)
            seg = (seg - seg.mean(1, keepdims=True)) / (
                   seg.std(1, keepdims=True) + 1e-6)

            # ---------- inferens --------------------------------
            seg_tf = tf.constant(seg[np.newaxis, ..., np.newaxis],
                                 dtype=tf.float32)
            logits = model(seg_tf)
            prob   = tf.nn.softmax(logits)[0].numpy()
            idx    = int(prob.argmax())
            label, conf = CLASSES[idx], prob[idx]*100

            outlet.push_sample([label])
            print(f"{dt.now().strftime('%H:%M:%S.%f')[:-3]}  "
                  f"{label:<12s}  {conf:4.1f}%")

            # ---------- scroll 50 % overlap ----------------------
            buf = np.roll(buf, -step, axis=1)
            ptr = win_len - step
except KeyboardInterrupt:
    print("\n🛑  stopped by user")
