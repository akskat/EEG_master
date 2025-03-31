#!/usr/bin/env python3
"""
recording_ui_excel_ole.py

Et Tkinter-basert GUI som:
  - Leser en Excel-fil med EEG-kategorier (30 rader, 8 kolonner).
  - Lar brukeren velge "Recording X" i en Combobox.
  - Viser en sekvens med 30 kategorier (hver 10 sekunder), med nedtelling.
  - Sender markører direkte til BrainVision Recorder via OLE Automation,
    i stedet for å simulere tastetrykk.

Krav:
  pip install pandas openpyxl pywin32
  + BrainVision Recorder installert på Windows
  + Recorder i en modus som aksepterer OLE (typisk Admin mode).
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
import pandas as pd

# OLE/COM
import pythoncom
import win32com.client

# Oppgi stien til Excel-filen (tilpass!)
EXCEL_PATH = "EEG kategori rekkefølge datasett.xlsx"

# Overslag for mapping: Her kan du fortsatt bevare "kortnøkkel-map"
# hvis du vil, men i praksis trenger vi bare "kategori" for SetMarker.
# Du kan likevel beholde dictionaryen til annen bruk:
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
        self.root.title("EEG Category Playback - OLE Edition")
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

        # OLE: Opprett en connection til Recorder
        self.recorder = None
        self.init_recorder()

        # Les Excel-filen
        self.df = pd.read_excel(EXCEL_PATH)
        # Forutsetter at kolonne 0 er "Category" og kolonne 1..8 er "Recording 1..8"
        self.recording_cols = self.df.columns[1:]  # (kolonne 0 er "Category" e.l.)

        # Oppsett av GUI
        main_frame = ttk.Frame(root, padding="20 20 20 20", style="TFrame")
        main_frame.pack(fill="both", expand=True)

        # Topp-seksjon
        top_frame = ttk.Frame(main_frame, style="TFrame")
        top_frame.pack(fill="x", pady=10)
        self.title_label = ttk.Label(top_frame, text="EEG Category Playback (OLE)", style="Header.TLabel")
        self.title_label.pack()

        # Velg Recording
        rec_frame = ttk.Frame(main_frame, style="TFrame")
        rec_frame.pack(pady=10)
        ttk.Label(rec_frame, text="Velg Recording:").pack(side="left", padx=5)
        self.recording_var = tk.StringVar()
        self.recording_combobox = ttk.Combobox(
            rec_frame, textvariable=self.recording_var,
            values=list(self.recording_cols), width=20, state="readonly"
        )
        self.recording_combobox.pack(side="left", padx=5)
        # Sett default til første "Recording X"
        self.recording_combobox.set(self.recording_cols[0])

        # Stor, sentrert gjeldende kategori
        middle_frame = ttk.Frame(main_frame, style="TFrame")
        middle_frame.pack(fill="both", expand=True, pady=30)
        self.current_cat_label = tk.Label(
            middle_frame, text="None", font=("Helvetica", 56, "bold"),
            bg="#E0FFE0", highlightbackground="#A0D0A0", highlightthickness=2
        )
        self.current_cat_label.pack(expand=True, fill="both", padx=100, pady=20)

        # Nedtelling
        self.countdown_label = tk.Label(
            main_frame, text="Countdown: 0 s",
            font=("Helvetica", 22), bg="#FFFFD0",
            highlightbackground="#D0D0A0", highlightthickness=2
        )
        self.countdown_label.pack(pady=10, fill="x", padx=200)

        # Neste kategori
        self.next_cat_label = tk.Label(
            main_frame, text="Next category: None",
            font=("Helvetica", 16), bg="#E0E0FF",
            highlightbackground="#A0A0D0", highlightthickness=2
        )
        self.next_cat_label.pack(pady=10, fill="x", padx=250)

        # Knapper
        button_frame = ttk.Frame(main_frame, style="TFrame")
        button_frame.pack(pady=20)

        self.start_button = tk.Button(
            button_frame, text="Start Recording",
            command=self.start_recording,
            bg="#00CC00", fg="white",
            font=("Helvetica", 14, "bold"),
            padx=20, pady=10
        )
        self.start_button.pack(side="left", padx=15)

        self.stop_button = tk.Button(
            button_frame, text="End Recording",
            command=self.stop_recording,
            bg="#FF0000", fg="white",
            font=("Helvetica", 14, "bold"),
            padx=20, pady=10
        )
        self.stop_button.pack(side="left", padx=15)

    def init_recorder(self):
        """
        Opprett et COM-objekt for Recorder, og klargjør for OLE-kall.
        """
        pythoncom.CoInitialize()  # Nødvendig i enkelte trådkontekster
        try:
            self.recorder = win32com.client.Dispatch("VisionRecorder.Application")
            # Deaktiver "thread blocking mode" for å unngå at calls blokkerer
            self.recorder.DisableThreadBlockingMode = 1
            print("Tilkoblet BrainVision Recorder via OLE.")
        except Exception as e:
            print("Kunne ikke koble til Recorder: ", e)
            self.recorder = None

    def start_recording(self):
        """
        Starter sekvensen av kategorier.
        Kaller også Recorder.Acquisition.StartRecording(...) via OLE.
        """
        if self.is_running:
            return

        if not self.recorder:
            print("Recorder er ikke tilgjengelig via OLE. Avbryter.")
            return

        self.is_running = True
        self.current_index = 0
        self.remaining_time = CATEGORY_DURATION

        # (Valgfritt) Start opptak via OLE -> Oppgi filnavn, kommentar
        try:
            # Du kan endre stien (filnavn) og kommentar:
            self.recorder.Acquisition.StartRecording(
                r"C:\EEG_data\OLE_Recording.eeg",  # For eksempel
                "OLE testopptak"
            )
            print("Startet opptak i Recorder (OLE).")
        except Exception as e:
            print(f"Feil ved StartRecording: {e}")

        # 10 sek forsinkelse før vi går i gang med kategorier
        self.update_current_category("PREPARATION")
        for i in range(DELAY_BEFORE_START, 0, -1):
            self.update_next_category(f"Starting in {i} s...")
            self.update_countdown(i)
            self.root.update()
            time.sleep(1)

        # Bygg en liste av (key, text) fra Excel for valgte Recording
        chosen_col = self.recording_var.get()
        self.categories_seq = self.build_categories(chosen_col)

        # Kjør i egen tråd
        t = threading.Thread(target=self.run_sequence)
        t.daemon = True
        t.start()

    def stop_recording(self):
        """
        Stopper sekvensen og stoppe opptaket i Recorder.
        """
        self.is_running = False
        self.update_current_category("Recording Stopped")
        self.update_next_category("None")
        self.update_countdown(0)

        # Stopp selve opptaket via OLE
        if self.recorder:
            try:
                self.recorder.Acquisition.StopRecording()
                print("Stoppet opptak i Recorder (OLE).")
            except Exception as e:
                print(f"Feil ved StopRecording: {e}")

    def build_categories(self, col_name):
        """
        Leser 30 rader (Category 1..30) for valgte 'Recording X' fra Excel,
        og mapper dem til en liste (shortKey, catText).
        """
        cat_list = []
        for i in range(30):
            cat_text = str(self.df.loc[i, col_name])  # e.g. 'REST', 'MOVE_LEFT', ...
            # Oppslag i SHORTKEY_MAP (om du vil)
            key = SHORTKEY_MAP.get(cat_text, 1)
            cat_list.append((key, cat_text))
        return cat_list

    def run_sequence(self):
        """
        Kjøres i bakgrunnstråd: viser hver kategori i N sekunder,
        og sender markør via OLE.
        """
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

            # I stedet for tastetrykk: SEND MARKØR VIA OLE
            self.send_ole_marker(current_cat)

            # Teller ned i 10 sek
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

    def send_ole_marker(self, category_text):
        """
        Legger inn en marker i Recorder via OLE. Du kan selv definere 'MarkerType'.
        """
        if not self.recorder:
            print("Recorder OLE-objekt ikke tilgjengelig. Marker ikke sendt.")
            return
        try:
            # Du kan velge "Stimulus", "Response", "Comment" etc. for markerType
            self.recorder.Acquisition.SetMarker(category_text, "Stimulus")
            print(f"Sendte OLE-markør: {category_text}")
        except Exception as e:
            print(f"Feil ved SetMarker: {e}")

    # --- Oppdater GUI-elementer ---
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
