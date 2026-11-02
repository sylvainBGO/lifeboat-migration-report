"""Small, isolated French rescue UI; native restore GUI is unchanged."""
from __future__ import annotations
import argparse
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from .fs_paths import Path
from . import rescue


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', metavar='JOURNAL')
    parser.add_argument('--log')
    parser.add_argument('--plan')
    parser.add_argument('--resume', metavar='PLAN')
    parser.add_argument('--smoke-test', metavar='RESULT')
    args = parser.parse_args()
    if args.smoke_test:
        # Validate packaged imports and actual Tk availability, without user data.
        root = tk.Tk(); root.withdraw(); root.update(); root.destroy()
        Path(args.smoke_test).write_text(json.dumps({'passed': True, 'planVersion': rescue.VERSION,
                                                    'reserveBytes': rescue.RESERVE}))
        return 0
    if args.prepare or args.resume:
        try:
            output = lambda msg: print(msg, flush=True) if sys.stdout else None
            if args.prepare:
                if not args.log or not args.plan:
                    parser.error('--prepare requires --log and --plan')
                rescue.prepare(Path(args.prepare), Path(args.log), Path(args.plan), output)
            else:
                rescue.execute(Path(args.resume), output)
            return 0
        except Exception as exc:
            if sys.stderr:
                print(str(exc), file=sys.stderr)
            return 2
    run_gui()
    return 0


def run_gui():
    root = tk.Tk()
    root.title('Codex Lifeboat — Reprise specifique 3.4.7')
    root.geometry('1000x690')
    root.minsize(800, 580)
    root.configure(background='#f4f7fa')
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Terminer la restauration interrompue', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='1. Preparer et enregistrer le plan.  2. Charger ce plan pour reprendre, meme apres redemarrage.',
              wraplength=900).pack(anchor='w', pady=(8, 15))
    default = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Codex Lifeboat/recovery-points/20261031-162112'
    journal = tk.StringVar(value=str(default / 'restore-journal.json'))
    log = tk.StringVar()
    plan = tk.StringVar(value=str(default / 'reprise-plan.json'))
    controls = []
    def row(label, value, save=False):
        box = ttk.Frame(frame); box.pack(fill='x', pady=4)
        ttk.Label(box, text=label, width=22).pack(side='left')
        entry = ttk.Entry(box, textvariable=value); entry.pack(side='left', fill='x', expand=True)
        def select():
            chosen = (filedialog.asksaveasfilename(defaultextension='.json') if save else
                      filedialog.askopenfilename())
            if chosen: value.set(chosen)
        button = ttk.Button(box, text='Parcourir', command=select); button.pack(side='left', padx=(8, 0))
        controls.extend((entry, button))
    row('Journal precedent', journal)
    row('Trace de l’erreur (.txt)', log)
    row('Document de reprise', plan, save=True)
    buttons = ttk.Frame(frame); buttons.pack(fill='x', pady=12)
    state = tk.StringVar(value='Preparation possible sous 500 Mo. Le seuil concerne uniquement la restauration.')
    ttk.Label(frame, textvariable=state, wraplength=920).pack(anchor='w', pady=8)
    bar = ttk.Progressbar(frame, mode='indeterminate'); bar.pack(fill='x')
    ttk.Label(frame, text='Activite — les projets termines ne sont ni recopies ni recontroles').pack(anchor='w', pady=(12, 4))
    box = ttk.Frame(frame); box.pack(fill='both', expand=True)
    text = tk.Text(box, background='#142431', foreground='#e9f4fa', wrap='word', state='disabled')
    scrollbar = ttk.Scrollbar(box, command=text.yview)
    text.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y'); text.pack(fill='both', expand=True)
    events = queue.Queue()
    busy = False
    def append(msg):
        text.configure(state='normal'); text.insert('end', msg + '\n'); text.see('end')
        if int(text.index('end-1c').split('.')[0]) > 2000: text.delete('1.0', '501.0')
        text.configure(state='disabled')
    def launch(mode):
        nonlocal busy
        if busy: return
        path = Path(plan.get())
        if not plan.get() or (mode == 'prepare' and (not journal.get() or not log.get())):
            messagebox.showerror('Champs manquants', 'Selectionnez les documents necessaires.'); return
        j, l = Path(journal.get()), Path(log.get())
        busy = True
        for item in controls: item.configure(state='disabled')
        bar.start(15)
        state.set('Preparation du plan...' if mode == 'prepare' else 'Reprise en cours — ne fermez pas cette fenetre.')
        def work():
            try:
                result = (rescue.prepare(j, l, path, lambda m: events.put(('log', m))) if mode == 'prepare'
                          else rescue.execute(path, lambda m: events.put(('log', m))))
                events.put(('done', 'Plan enregistre. Vous pouvez fermer et le recharger plus tard.' if mode == 'prepare'
                            else 'Restauration terminee. Rapport conserve avec le journal.'))
            except Exception as exc:
                events.put(('error', str(exc)))
        threading.Thread(target=work, daemon=False).start()
    def load():
        chosen = filedialog.askopenfilename(filetypes=[('Plan de reprise', '*.json')])
        if chosen:
            plan.set(chosen)
            try:
                data = rescue.backup.read_json(Path(chosen))
                if data.get('format') != 'lifeboat-targeted-rescue': raise ValueError('Ce document n’est pas un plan de reprise.')
                done = sum(t['status'] == 'done' for t in data['tasks'])
                state.set(f'Plan charge : {done}/{len(data["tasks"])} fichiers restants traites. Statut : {data["status"]}.')
            except Exception as exc: messagebox.showerror('Plan', str(exc))
    for title, command in [('Preparer le plan', lambda: launch('prepare')),
                           ('Charger un plan', load), ('Reprendre', lambda: launch('resume'))]:
        button = ttk.Button(buttons, text=title, command=command)
        button.pack(side='left', padx=(0, 10)); controls.append(button)
    def poll():
        nonlocal busy
        try:
            while True:
                kind, message = events.get_nowait(); append(message)
                if kind in ('done', 'error'):
                    busy = False; bar.stop()
                    for item in controls: item.configure(state='normal')
                    state.set(message if kind == 'done' else 'Interruption : ' + message)
                    if kind == 'error': messagebox.showerror('Reprise interrompue — travail conserve', message)
        except queue.Empty: pass
        root.after(100, poll)
    def close():
        if busy:
            messagebox.showinfo('Operation en cours', 'Attendez la fin de la preparation ou un arret propre avant de fermer.')
        else: root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    poll(); root.mainloop()
