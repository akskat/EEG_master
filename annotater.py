#!/usr/bin/env python3
"""
recording_ui_excel.py

Et Tkinter-basert GUI som leser en Excel-fil med EEG-kategorier (30 rader, 8 kolonner).
Brukeren velger "Recording X" i en Combobox. Programmet lager en sekvens med 30 kategorier
(hver 10 sekunder) og simulerer tastetrykk i BrainVision Recorder (1–9) basert på en
definert mapping.

Funksjonalitet:
  - Leser 'EEG kategori rekkefølge datasett.xlsx' (må tilpasses sti).
  - Velger kolonne 'Recording 1..8' via Combobox.
  - 10 sek forsinkelse før start, slik at man kan bytte til Recorder.
  - Viser stor, sentrert gjeldende kategori, nedtelling, neste kategori.
  - Endrer kategori hvert 10. sekund, simulerer tastetrykk (1–9).
  - Knapp for å stoppe opptaket (uten å lukke programmet).

Krav:
  pip install pandas openpyxl pyautogui
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
import pyautogui
import pandas as pd

# Oppgi stien til Excel-filen (tilpass!)
EXCEL_PATH = "EEG kategori rekkefølge datasett.xlsx"

# Kortnøkkel-mapping (tekst -> tast)
SHORTKEY_MAP = {
    "REST": 1,
    "MOVE_RIGHT": 2,
    "MOVE_LEFT": 3,
    "MOVE_BOTH": 4,
    "IMAGERY_RIGHT": 5,
    "IMAGERY_LEFT": 6,
    "IMAGERY_BOTH": 7,
    "START": 8,
    "END": 9
}

CATEGORY_DURATION = 10  # sekunder per kategori
DELAY_BEFORE_START = 10  # sekunders forsinkelse før første kategori

class RecordingUI:
    def __init__(self, root):
        self.root = root
        self.root.title("EEG Category Playback")
        self.root.geometry("1200x800")
        self.root.configure(bg="#FFFFFF")

        # TTK-stil
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#FFFFFF")
        style.configure("TLabel", font=("Helvetica", 16), background="#FFFFFF")
        style.configure("Header.TLabel", font=("Helvetica", 24, "bold"), background="#FFFFFF")
        style.configure("Big.TLabel", font=("Helvetica", 56, "bold"), background="#E0FFE0")
        style.configure("Medium.TLabel", font=("Helvetica", 22), background="#FFFFD0")
        style.configure("Small.TLabel", font=("Helvetica", 16), background="#E0E0FF")
        style.configure("TButton", font=("Helvetica", 14), padding=10)

        self.is_running = False
        self.current_index = 0
        self.remaining_time = CATEGORY_DURATION

        # Les Excel-filen i forkant
        self.df = pd.read_excel(EXCEL_PATH)
        # Forvent at kolonnen 0 er "Person 1" eller "Category #"
        # og kolonne 1..8 er "Recording 1..8"
        # Indeksering:
        #   rad 0..29 -> Category 1..30
        #   kolonne 0 -> "Person 1" / "Category 1.."
        #   kolonne 1..8 -> "Recording 1..8"

        # Få en liste med mulige Recording-kolonner
        # Forutsetter at 'Recording 1'.. 'Recording 8' er i kolonner 1..8
        self.recording_cols = self.df.columns[1:]  # (Forvent at kolonne 0 er "Category" / "Person 1")

        # Oppsett av GUI
        main_frame = ttk.Frame(root, padding="20 20 20 20", style="TFrame")
        main_frame.pack(fill="both", expand=True)

        # Topp-seksjon
        top_frame = ttk.Frame(main_frame, style="TFrame")
        top_frame.pack(fill="x", pady=10)
        self.title_label = ttk.Label(top_frame, text="EEG Category Playback", style="Header.TLabel")
        self.title_label.pack()

        # Velg Recording
        rec_frame = ttk.Frame(main_frame, style="TFrame")
        rec_frame.pack(pady=10)
        ttk.Label(rec_frame, text="Velg Recording:").pack(side="left", padx=5)
        self.recording_var = tk.StringVar()
        self.recording_combobox = ttk.Combobox(rec_frame, textvariable=self.recording_var,
                                               values=list(self.recording_cols), width=20, state="readonly")
        self.recording_combobox.pack(side="left", padx=5)
        self.recording_combobox.set(self.recording_cols[0])  # default

        # Stor, sentrert gjeldende kategori
        middle_frame = ttk.Frame(main_frame, style="TFrame")
        middle_frame.pack(fill="both", expand=True, pady=30)
        self.current_cat_label = tk.Label(middle_frame, text="None",
                                          font=("Helvetica", 56, "bold"),
                                          bg="#E0FFE0", highlightbackground="#A0D0A0",
                                          highlightthickness=2)
        self.current_cat_label.pack(expand=True, fill="both", padx=100, pady=20)

        # Nedtelling
        self.countdown_label = tk.Label(main_frame, text="Countdown: 0 s",
                                        font=("Helvetica", 22), bg="#FFFFD0",
                                        highlightbackground="#D0D0A0", highlightthickness=2)
        self.countdown_label.pack(pady=10, fill="x", padx=200)

        # Neste kategori
        self.next_cat_label = tk.Label(main_frame, text="Next category: None",
                                       font=("Helvetica", 16), bg="#E0E0FF",
                                       highlightbackground="#A0A0D0", highlightthickness=2)
        self.next_cat_label.pack(pady=10, fill="x", padx=250)

        # Knapper
        button_frame = ttk.Frame(main_frame, style="TFrame")
        button_frame.pack(pady=20)
        self.start_button = tk.Button(button_frame, text="Start Recording",
                                      command=self.start_recording,
                                      bg="#00CC00", fg="white",
                                      font=("Helvetica", 14, "bold"),
                                      padx=20, pady=10)
        self.start_button.pack(side="left", padx=15)

        self.stop_button = tk.Button(button_frame, text="End Recording",
                                     command=self.stop_recording,
                                     bg="#FF0000", fg="white",
                                     font=("Helvetica", 14, "bold"),
                                     padx=20, pady=10)
        self.stop_button.pack(side="left", padx=15)

    def start_recording(self):
        if self.is_running:
            return
        self.is_running = True
        self.current_index = 0
        self.remaining_time = CATEGORY_DURATION

        # 10 sek forsinkelse før start
        self.update_current_category("PREPARATION")
        for i in range(DELAY_BEFORE_START, 0, -1):
            self.update_next_category(f"Starting in {i} s...")
            self.update_countdown(i)
            self.root.update()
            time.sleep(1)

        # Bygg en liste av (shortKey, text) fra Excel for den valgte Recording
        chosen_col = self.recording_var.get()
        self.categories_seq = self.build_categories(chosen_col)

        # Start i en egen tråd
        t = threading.Thread(target=self.run_sequence)
        t.daemon = True
        t.start()

    def build_categories(self, col_name):
        """
        Leser 30 rader (Category 1..30) for valgte 'Recording X' fra Excel,
        og mapper dem til (tast, tekst) basert på SHORTKEY_MAP.
        """
        cat_list = []
        # Forvent at radene 0..29 i self.df tilsvarer Category 1..30
        for i in range(30):
            cat_text = str(self.df.loc[i, col_name])  # f.eks. 'REST', 'MOVE_LEFT', ...
            # Oppslag i SHORTKEY_MAP, fallback = 1 (REST) om ikke finnes
            key = SHORTKEY_MAP.get(cat_text, 1)
            cat_list.append((key, cat_text))
        return cat_list

    def stop_recording(self):
        self.is_running = False
        self.update_current_category("Recording Stopped")
        self.update_next_category("None")
        self.update_countdown(0)

    def run_sequence(self):
        while self.current_index < len(self.categories_seq) and self.is_running:
            key_code, current_cat = self.categories_seq[self.current_index]

            # Oppdater GUI
            self.update_current_category(current_cat)

            # Neste kategori
            if self.current_index + 1 < len(self.categories_seq):
                next_cat = self.categories_seq[self.current_index + 1][1]
            else:
                next_cat = "None"
            self.update_next_category(next_cat)

            # Simuler tastetrykk
            self.simulate_keypress(key_code)

            # 10 sek for denne kategorien
            self.remaining_time = CATEGORY_DURATION
            for _ in range(CATEGORY_DURATION):
                if not self.is_running:
                    break
                self.update_countdown(self.remaining_time)
                time.sleep(1)
                self.remaining_time -= 1

            self.current_index += 1

        self.is_running = False
        self.update_current_category("Completed")
        self.update_next_category("None")
        self.update_countdown(0)

    def simulate_keypress(self, key_code):
        try:
            pyautogui.press(str(key_code))
            print(f"Pressed key: {key_code}")
        except Exception as e:
            print(f"Error during key press: {e}")

    def update_current_category(self, cat):
        self.current_cat_label.config(text=f"{cat}")

    def update_next_category(self, cat):
        self.next_cat_label.config(text=f"Next category: {cat}")

    def update_countdown(self, sec):
        self.countdown_label.config(text=f"Countdown: {sec} s")

def main():
    root = tk.Tk()
    app = RecordingUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
