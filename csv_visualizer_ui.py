#!/usr/bin/env python3
"""
csv_visualizer_ui.py

Et Tkinter-basert GUI for å:
1) Velge en CSV-fil med EEG-data.
2) Justere parametere: FPS, vindusstørrelse og gain.
3) Velge hvilke kanaler som skal plottes (hver kanal i sitt eget subplot).
4) Starte interaktiv avspilling med Play/Pause og en knapp for å vise annotasjoner.

Kjør:
  python csv_visualizer_ui.py
"""

import tkinter as tk
from tkinter import filedialog, messagebox
import time
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button

class CSVVisualizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CSV Visualizer UI")
        self.csv_file = tk.StringVar(value="")
        self.fps = tk.DoubleVar(value=10.0)
        self.window_size = tk.DoubleVar(value=5.0)
        self.gain = tk.DoubleVar(value=1.0)

        # GUI-layout
        main_frame = tk.Frame(root, padx=10, pady=10)
        main_frame.pack(fill="both", expand=True)

        # CSV-fil valg
        csv_frame = tk.Frame(main_frame)
        csv_frame.pack(pady=5, anchor="w")
        tk.Label(csv_frame, text="CSV-fil:").pack(side="left")
        tk.Entry(csv_frame, textvariable=self.csv_file, width=40).pack(side="left", padx=5)
        tk.Button(csv_frame, text="Velg fil", command=self.browse_csv).pack(side="left")

        # Parameterfelter
        param_frame = tk.Frame(main_frame)
        param_frame.pack(pady=5, anchor="w")
        tk.Label(param_frame, text="FPS:").grid(row=0, column=0, sticky="e", pady=2)
        tk.Entry(param_frame, textvariable=self.fps, width=10).grid(row=0, column=1, sticky="w", padx=5)
        tk.Label(param_frame, text="Vindusstørrelse (s):").grid(row=1, column=0, sticky="e", pady=2)
        tk.Entry(param_frame, textvariable=self.window_size, width=10).grid(row=1, column=1, sticky="w", padx=5)
        tk.Label(param_frame, text="Gain:").grid(row=2, column=0, sticky="e", pady=2)
        tk.Entry(param_frame, textvariable=self.gain, width=10).grid(row=2, column=1, sticky="w", padx=5)

        # Kanalvalg (Listbox med flere valg)
        channel_frame = tk.Frame(main_frame)
        channel_frame.pack(pady=5, anchor="w")
        tk.Label(channel_frame, text="Velg kanaler (hold Ctrl for flere):").pack(anchor="w")
        self.channel_listbox = tk.Listbox(channel_frame, selectmode="extended", width=40, height=10)
        self.channel_listbox.pack(side="left", padx=5, pady=5)
        tk.Button(channel_frame, text="Last kanaler", command=self.load_channels).pack(side="left", padx=5)

        # Start-knapp for avspilling
        tk.Button(main_frame, text="Start avspilling", command=self.start_playback, width=30, pady=5).pack(pady=10)

    def browse_csv(self):
        filename = filedialog.askopenfilename(title="Velg CSV-fil", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if filename:
            self.csv_file.set(filename)

    def load_channels(self):
        csv_path = self.csv_file.get().strip()
        if not csv_path:
            messagebox.showerror("Feil", "Velg en CSV-fil først!")
            return
        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            messagebox.showerror("Feil", f"Kunne ikke laste CSV: {e}")
            return
        channels = [col for col in df.columns if col not in ['time', 'annotation']]
        self.channel_listbox.delete(0, tk.END)
        for ch in channels:
            self.channel_listbox.insert(tk.END, ch)

    def start_playback(self):
        csv_path = self.csv_file.get().strip()
        if not csv_path:
            messagebox.showerror("Feil", "Velg en CSV-fil først!")
            return
        try:
            fps_val = float(self.fps.get())
            win_val = float(self.window_size.get())
            gain_val = float(self.gain.get())
        except ValueError:
            messagebox.showerror("Feil", "FPS, vindusstørrelse og gain må være tall!")
            return

        selected_indices = self.channel_listbox.curselection()
        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            messagebox.showerror("Feil", f"Kunne ikke laste CSV: {e}")
            return

        if 'time' not in df.columns:
            messagebox.showerror("Feil", "CSV-filen mangler 'time'-kolonne!")
            return
        if 'annotation' not in df.columns:
            df['annotation'] = ""
        all_channels = [col for col in df.columns if col not in ['time', 'annotation']]
        if selected_indices:
            channels_to_plot = [self.channel_listbox.get(i) for i in selected_indices]
        else:
            channels_to_plot = all_channels

        visualize_csv(df, channels_to_plot, fps=fps_val, init_window=win_val, init_gain=gain_val)

def visualize_csv(df, channels, fps=10.0, init_window=5.0, init_gain=1.0):
    """
    Åpner et matplotlib-vindu med interaktiv avspilling.
    Hver valgt kanal vises i sitt eget subplot (vertikalt stablet med delt x-akse).
    Inkluderer sliders for tid, vindusstørrelse og gain, samt Play/Pause og en knapp for annotasjoner.
    """
    time_col = df['time'].values
    t_min = time_col[0]
    t_max = time_col[-1]
    
    n_channels = len(channels)
    if n_channels == 0:
        print("Ingen kanaler valgt for plotting.")
        return

    # Opprett subplots: en for hver kanal
    fig, axes = plt.subplots(n_channels, 1, figsize=(10, 2*n_channels), sharex=True)
    if n_channels == 1:
        axes = [axes]
    plt.subplots_adjust(bottom=0.35, top=0.95, hspace=0.5)

    # Opprett sliders:
    ax_slider_time = plt.axes([0.15, 0.27, 0.65, 0.03])
    slider_time = Slider(ax_slider_time, 'Starttid', t_min, max(t_min, t_max - init_window),
                         valinit=t_min, valstep=0.01)
    ax_slider_win = plt.axes([0.15, 0.22, 0.65, 0.03])
    slider_win = Slider(ax_slider_win, 'Vindusstørrelse (s)', 1.0, min(30.0, t_max - t_min),
                        valinit=init_window, valstep=1.0)
    ax_slider_gain = plt.axes([0.15, 0.17, 0.65, 0.03])
    slider_gain = Slider(ax_slider_gain, 'Gain', 0.1, 5.0,
                         valinit=init_gain, valstep=0.1)

    # Play/Pause og Annot-knapper:
    ax_button_play = plt.axes([0.82, 0.27, 0.1, 0.04])
    button_play = Button(ax_button_play, "Play")
    ax_button_pause = plt.axes([0.82, 0.22, 0.1, 0.04])
    button_pause = Button(ax_button_pause, "Pause")
    ax_button_annot = plt.axes([0.82, 0.17, 0.1, 0.04])
    button_annot = Button(ax_button_annot, "Vis Annot.")

    is_playing = [False]
    last_update_time = [time.time()]

    def plot_all(t_start, window_size, gain):
        for i, ch in enumerate(channels):
            axes[i].clear()
            t_end = t_start + window_size
            mask = (time_col >= t_start) & (time_col <= t_end)
            sig = df[ch].values[mask] * gain
            axes[i].plot(time_col[mask], sig, label=ch)
            axes[i].set_ylabel(ch)
            axes[i].legend(loc='upper right', fontsize='x-small')
        axes[-1].set_xlabel("Tid (s)")
        fig.canvas.draw_idle()

    # Initialt plott
    plot_all(t_min, init_window, init_gain)

    def update_sliders(val):
        t_start = slider_time.val
        window_size = slider_win.val
        gain = slider_gain.val
        if t_start + window_size > t_max:
            t_start = t_max - window_size
            slider_time.set_val(t_start)
        plot_all(t_start, window_size, gain)

    slider_time.on_changed(update_sliders)
    slider_win.on_changed(update_sliders)
    slider_gain.on_changed(update_sliders)

    def play_callback(event):
        is_playing[0] = True
        last_update_time[0] = time.time()

    def pause_callback(event):
        is_playing[0] = False

    button_play.on_clicked(play_callback)
    button_pause.on_clicked(pause_callback)

    def show_annotation(event):
        t_start = slider_time.val
        window_size = slider_win.val
        t_end = t_start + window_size
        mask = (time_col >= t_start) & (time_col <= t_end)
        annot_vals = df.loc[mask, 'annotation'].unique()
        annot_vals = [str(a) for a in annot_vals if str(a).strip() != ""]
        for ax in axes:
            if annot_vals:
                ax.set_title(f"Annotasjoner: {', '.join(annot_vals)}", fontsize=9)
            else:
                ax.set_title("Ingen annotasjoner", fontsize=9)
        fig.canvas.draw_idle()

    button_annot.on_clicked(show_annotation)

    def update_playback(frame):
        if is_playing[0]:
            now = time.time()
            elapsed = now - last_update_time[0]
            last_update_time[0] = now
            step = 1.0 / fps
            new_start = slider_time.val + step
            # Sørg for at vi ikke går forbi slutten
            if new_start + slider_win.val > t_max:
                new_start = t_max - slider_win.val
            slider_time.set_val(new_start)

    timer = fig.canvas.new_timer(interval=int(1000 / fps))
    timer.add_callback(update_playback, None)
    timer.start()

    plt.show()

def main():
    root = tk.Tk()
    app = CSVVisualizerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
