"""Small Windows UI for the same benchmark engine used by the CLI."""
import json
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from benchmark import RunControl, run_suite
from benchmark_report import CACHE_NOTE, DEFENDER_REMINDER


class DefenderAdapter:
    """Only the explicit disable action invokes the shared production helper."""
    def __init__(self, backend=None):
        if backend is None:
            try:
                from codex_transfer import defender_control as backend
            except ImportError:
                backend = None
        self.backend = backend

    def read(self):
        if self.backend is None:
            return {'available': False, 'error': 'Composant Defender indisponible dans ce paquet.'}
        try:
            return self.backend.status()
        except Exception as error:
            return {'available': False, 'error': type(error).__name__}

    def disable_after_confirmation(self, confirmed):
        if not confirmed:
            return {'requested': False, **self.read()}
        if self.backend is None:
            return {'requested': False, **self.read()}
        try:
            return {'requested': True, **self.backend.request_disable()}
        except Exception as error:
            return {'requested': True, 'request_error': type(error).__name__, **self.read()}


class BenchmarkWindow:
    def __init__(self, root, args, defender=None):
        self.root, self.args = root, args
        self.defender = defender or DefenderAdapter()
        self.messages = queue.Queue()
        self.worker = None
        self.control = None
        self.report_path = None
        self.started = None
        self.last_trial_count = 0
        self.last_activity = None
        self.previous_defender = None
        self.defender_busy = False
        self.root.title('Lifeboat — Banc de mesure')
        self.root.geometry('900x800')
        self.root.minsize(780, 740)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.configure('Title.TLabel', font=('Segoe UI', 20, 'bold'))
        style.configure('Subtitle.TLabel', font=('Segoe UI', 10))
        frame = ttk.Frame(root, padding=20)
        frame.grid(sticky='nsew')
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(5, weight=1)
        ttk.Label(frame, text='Mesurer Lifeboat sur ce PC', style='Title.TLabel').grid(sticky='w')
        ttk.Label(frame, text='Des données reproductibles, une comparaison complète et un rapport à partager.',
                  style='Subtitle.TLabel').grid(row=1, sticky='w', pady=(4, 16))

        settings = ttk.LabelFrame(frame, text='Campagne', padding=12)
        settings.grid(row=2, sticky='ew')
        settings.columnconfigure(1, weight=1)
        self.mode = tk.StringVar(value=args.mode)
        self.repeats = tk.IntVar(value=args.repeats or (1 if args.mode == 'quick' else 3))
        choices = ttk.Frame(settings)
        choices.grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Radiobutton(choices, text='Rapide · petits jeux, 1 passage', variable=self.mode,
                        value='quick', command=self.change_mode).pack(side='left', padx=(0, 20))
        ttk.Radiobutton(choices, text='Approfondi · jeux étendus', variable=self.mode,
                        value='thorough', command=self.change_mode).pack(side='left')
        ttk.Label(settings, text='Répétitions').grid(row=1, column=0, sticky='w', pady=8)
        self.repeat_input = ttk.Spinbox(settings, from_=2, to=5, width=5, textvariable=self.repeats)
        self.repeat_input.grid(row=1, column=1, sticky='w', padx=10)
        ttk.Label(settings, text='La durée dépend du disque et du PC.').grid(row=1, column=2, sticky='e')
        ttk.Label(settings, text='Mesures').grid(row=2, column=0, sticky='w')
        labels = {'all': 'Restauration + copies et archives', 'restore': 'Restauration complète',
                  'io': 'Microtests copies et archives'}
        self.focus = tk.StringVar(value=labels[args.focus])
        self.focus_input = ttk.Combobox(settings, textvariable=self.focus, state='readonly',
                                       values=list(labels.values()))
        self.focus_input.grid(row=2, column=1, sticky='ew', padx=10)
        self.focus_values = {value: key for key, value in labels.items()}
        self.include_archives = tk.BooleanVar(value=getattr(args, 'include_archives', False))
        self.archive_input = ttk.Checkbutton(settings, text='Comparer les archives', variable=self.include_archives)
        self.archive_input.grid(row=2, column=2, sticky='e')
        self.focus_input.bind('<<ComboboxSelected>>', lambda event: self.change_focus())
        ttk.Label(settings, text='Rapports').grid(row=3, column=0, sticky='w', pady=8)
        self.directory = tk.StringVar(value=str(Path(args.directory).resolve()))
        ttk.Entry(settings, textvariable=self.directory).grid(row=3, column=1, sticky='ew', padx=10)
        ttk.Button(settings, text='Choisir…', command=self.choose_directory).grid(row=3, column=2)
        ttk.Label(settings, text='Aucun backup personnel n’est lu. L’espace est contrôlé avant génération.\n'
                  'Fermez les applications Codex et ChatGPT pour comparer les restaurations.',
                  wraplength=780).grid(row=4, column=0, columnspan=3, sticky='w', pady=(2, 4))
        ttk.Label(settings, text=CACHE_NOTE, wraplength=780).grid(row=5, column=0, columnspan=3, sticky='w')

        defender_box = ttk.LabelFrame(frame, text='Microsoft Defender', padding=12)
        defender_box.grid(row=3, sticky='ew', pady=12)
        defender_box.columnconfigure(0, weight=1)
        self.defender_status = tk.StringVar(value='Lecture de l’état…')
        ttk.Label(defender_box, textvariable=self.defender_status, wraplength=510).grid(row=0, column=0, sticky='w')
        self.defender_button = ttk.Button(defender_box, text='Désactiver temporairement…', command=self.disable_defender)
        self.defender_button.grid(row=0, column=1, padx=(10, 0))
        ttk.Button(defender_box, text='Ouvrir Sécurité Windows', command=self.open_security).grid(row=1, column=1, pady=(8, 0))
        ttk.Label(defender_box, text='Action volontaire avec validation administrateur Windows.\n'
                  'Aucune désactivation ni réactivation automatique.', wraplength=510).grid(row=1, column=0, sticky='w', pady=(8, 0))

        progress = ttk.Frame(frame)
        progress.grid(row=4, sticky='ew')
        progress.columnconfigure(0, weight=1)
        self.activity = tk.StringVar(value='Prêt. Choisissez le mode puis démarrez la campagne.')
        ttk.Label(progress, textvariable=self.activity, wraplength=800).grid(sticky='w')
        self.progress = ttk.Progressbar(progress, maximum=1, value=0)
        self.progress.grid(row=1, column=0, sticky='ew', pady=8)
        self.elapsed = tk.StringVar(value='')
        ttk.Label(progress, textvariable=self.elapsed).grid(row=2, column=0, sticky='w')
        self.log = tk.Text(frame, height=5, wrap='word', state='disabled', font=('Consolas', 10))
        self.log.grid(row=5, sticky='nsew', pady=10)
        buttons = ttk.Frame(frame)
        buttons.grid(row=6, sticky='ew')
        self.start_button = ttk.Button(buttons, text='Démarrer', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(buttons, text='Arrêter après l’essai en cours', state='disabled', command=self.stop_after_trial)
        self.stop_button.pack(side='left', padx=8)
        self.cancel_button = ttk.Button(buttons, text='Interrompre', state='disabled', command=self.cancel)
        self.cancel_button.pack(side='left')
        self.open_button = ttk.Button(buttons, text='Ouvrir le résumé', state='disabled', command=self.open_summary)
        self.open_button.pack(side='right')
        ttk.Label(frame, text=DEFENDER_REMINDER, wraplength=800).grid(row=7, sticky='w', pady=(12, 0))
        self.change_mode()
        self.change_focus()
        self.refresh_defender()
        root.after(100, self.poll)

    def change_mode(self):
        if self.mode.get() == 'quick':
            self.repeats.set(1)
            self.repeat_input.configure(state='disabled')
        else:
            try:
                value = self.repeats.get()
            except tk.TclError:
                value = 0
            if not 2 <= value <= 5:
                self.repeats.set(3)
            self.repeat_input.configure(state='normal')

    def choose_directory(self):
        path = filedialog.askdirectory(parent=self.root, title='Dossier des rapports et données temporaires')
        if path:
            self.directory.set(path)

    def change_focus(self):
        io_only = self.focus_values[self.focus.get()] == 'io'
        self.archive_input.configure(state='disabled' if io_only else 'normal')
        if io_only:
            self.include_archives.set(False)

    def append_log(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def refresh_defender(self, periodic=False):
        threading.Thread(target=lambda: self.messages.put(('defender', self.defender.read())), daemon=True).start()
        self.root.after(3_600_000, lambda: self.refresh_defender(True))

    def display_defender(self, state):
        enabled = state.get('RealTimeProtectionEnabled') if state.get('available') else None
        if enabled is True:
            self.defender_status.set('Protection en temps réel : active')
        elif enabled is False:
            self.defender_status.set('Protection en temps réel : désactivée — réactivation manuelle à la fin')
        else:
            self.defender_status.set('État de Defender indisponible. Vérifiez-le dans Sécurité Windows.')
        if self.previous_defender is False and enabled is True and self.worker and self.worker.is_alive():
            self.append_log('Defender est redevenu actif. La campagne continue ; aucune nouvelle désactivation automatique.')
        if isinstance(enabled, bool):
            self.previous_defender = enabled

    def disable_defender(self):
        if self.defender_busy:
            return
        confirmed = messagebox.askyesno('Désactiver temporairement Defender ?',
            'Cette action désactive la protection antivirus en temps réel sur tout le PC. '
            'Windows demandera votre validation administrateur.\n\n'
            'Le programme vérifiera l’état réel et ne contournera aucune politique. '
            'Vous devrez réactiver vous-même la protection à la fin, même après une erreur '
            'ou une interruption.\n\nContinuer ?', parent=self.root)
        if not confirmed:
            return
        self.defender_busy = True
        self.defender_button.configure(state='disabled')
        self.defender_status.set('Demande de validation administrateur Windows…')
        threading.Thread(target=lambda: self.messages.put(('defender_request',
            self.defender.disable_after_confirmation(True))), daemon=True).start()

    def open_security(self):
        if os.name == 'nt':
            try:
                os.startfile('windowsdefender://threatsettings')
            except OSError:
                messagebox.showinfo('Sécurité Windows', 'Ouvrez Sécurité Windows → Protection contre les virus et menaces.', parent=self.root)

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            repeats = self.repeats.get()
        except tk.TclError:
            messagebox.showerror('Répétitions', 'Indiquez un nombre de 2 à 5 en mode approfondi.', parent=self.root)
            return
        if (self.mode.get() == 'quick' and repeats != 1) or (self.mode.get() == 'thorough' and not 2 <= repeats <= 5):
            messagebox.showerror('Répétitions', 'Le mode rapide utilise 1 passage ; le mode approfondi en accepte de 2 à 5.', parent=self.root)
            return
        options = dict(directory=self.directory.get(), mode=self.mode.get(), repeats=repeats,
                       focus=self.focus_values[self.focus.get()], baseline_source=self.args.baseline_source,
                       final_source=self.args.final_source, include_archives=self.include_archives.get())
        self.control = RunControl()
        self.report_path = None
        self.started = time.monotonic()
        self.last_trial_count = 0
        self.last_activity = None
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.cancel_button.configure(state='normal')
        self.open_button.configure(state='disabled')
        self.append_log('Nouvelle campagne : ' + ('rapide' if options['mode'] == 'quick' else 'approfondie'))
        def run():
            try:
                report, path = run_suite(**options, control=self.control,
                    observer=lambda value, path: self.messages.put(('report', json.loads(json.dumps(value)), path)))
                self.messages.put(('done', report, path))
            except Exception as error:
                self.messages.put(('error', type(error).__name__ + ': ' + str(error)))
        self.worker = threading.Thread(target=run, daemon=False)
        self.worker.start()

    def stop_after_trial(self):
        if self.control:
            self.control.stop_after_trial.set()
            self.stop_button.configure(state='disabled')
            self.append_log('Arrêt demandé après l’essai courant. Les résultats terminés seront conservés.')

    def cancel(self):
        if self.control:
            self.control.cancel.set()
            self.cancel_button.configure(state='disabled')
            self.append_log('Interruption demandée. Les essais terminés restent dans les rapports.')

    def open_summary(self):
        if self.report_path and os.name == 'nt':
            os.startfile(str(self.report_path.with_suffix('.txt')))

    def finished(self):
        self.start_button.configure(state='normal')
        self.stop_button.configure(state='disabled')
        self.cancel_button.configure(state='disabled')
        self.open_button.configure(state='normal' if self.report_path else 'disabled')
        self.append_log(DEFENDER_REMINDER)

    def poll(self):
        try:
            while True:
                message = self.messages.get_nowait()
                kind = message[0]
                if kind in ('defender', 'defender_request'):
                    state = message[1]
                    self.display_defender(state)
                    if kind == 'defender_request':
                        self.defender_busy = False
                        self.defender_button.configure(state='normal')
                        if state.get('available') and state.get('RealTimeProtectionEnabled') is False:
                            self.append_log('État vérifié : protection en temps réel désactivée. ' + DEFENDER_REMINDER)
                        else:
                            self.append_log('La désactivation n’est pas confirmée. La demande peut avoir été refusée, '
                                'ou bloquée par une politique/protection des paramètres. Effectuez la manipulation '
                                'dans Sécurité Windows si vos droits le permettent ; sinon contactez l’administrateur.')
                elif kind == 'report':
                    report, self.report_path = message[1], Path(message[2])
                    self.progress.configure(maximum=report['planned_trials'], value=len(report['trials']))
                    activity = report.get('current_activity')
                    if activity and activity != self.last_activity:
                        self.activity.set(activity)
                        self.last_activity = activity
                    for trial in report['trials'][self.last_trial_count:]:
                        self.append_log(f"{trial['profile']} / {trial['variant']} : {trial['seconds']:.3f} s, "
                                        + ('vérification OK' if trial.get('valid') else 'ÉCHEC'))
                    self.last_trial_count = len(report['trials'])
                    if report.get('defender_samples'):
                        self.display_defender(report['defender_samples'][-1]['state'])
                elif kind == 'done':
                    report, self.report_path = message[1], Path(message[2])
                    texts = {'complete': 'Campagne terminée.', 'stopped': 'Campagne arrêtée après un essai.',
                             'cancelled': 'Campagne interrompue.', 'failed': 'La campagne a rencontré une erreur.'}
                    self.activity.set(texts[report['status']] + ' JSON et résumé TXT enregistrés.')
                    for error in report.get('errors', []):
                        self.append_log(error)
                    self.append_log('Rapports : ' + str(self.report_path.parent))
                    self.finished()
                elif kind == 'error':
                    self.activity.set('Impossible de terminer la campagne.')
                    self.append_log(message[1])
                    self.finished()
        except queue.Empty:
            pass
        if self.started and self.worker and self.worker.is_alive():
            seconds = int(time.monotonic() - self.started)
            self.elapsed.set(f'Écoulé : {seconds // 60} min {seconds % 60:02d} s · {self.last_trial_count} essais terminés')
        self.root.after(100, self.poll)

    def close(self):
        if self.worker and self.worker.is_alive():
            if messagebox.askyesno('Une campagne est en cours',
                'Arrêter après l’essai en cours ? Les rapports partiels seront conservés. '
                'Vous pourrez fermer la fenêtre après l’arrêt.', parent=self.root):
                self.stop_after_trial()
            return
        if self.defender_busy:
            messagebox.showinfo('Validation Windows en cours', 'Terminez ou annulez la demande administrateur avant de fermer.', parent=self.root)
            return
        if self.previous_defender is False:
            messagebox.showinfo('Microsoft Defender', DEFENDER_REMINDER, parent=self.root)
        self.root.destroy()


def launch(args):
    root = tk.Tk()
    BenchmarkWindow(root, args)
    root.mainloop()
    return 0
