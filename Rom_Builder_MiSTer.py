import configparser
import hashlib
import json
import logging
import os
import sys
import re
import shlex
import tkinter as tk
import tkinter.ttk as ttk
import zipfile
from pathlib import Path
from threading import Thread
from tkinter import filedialog
from tkinter import messagebox

import requests


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(SCRIPT_DIR, 'combind_definitions.ini')
MISTER_DEVEL_REPOS_URL='https://api.github.com/users/MiSTer-devel/repos?per_page=100'

DEFINITIONS = None


class RomBuilderError(Exception): 
    def __init__(self, message, type_):
        super().__init__(message)
        self.type = type_


def get_definitions_from_file():
    global DEFAULT_CONFIG
    config = configparser.ConfigParser()
    if Path(DEFAULT_CONFIG).is_file():
        logging.debug("Loading definitions: %s", DEFAULT_CONFIG)
        config.read(DEFAULT_CONFIG)
    logging.info("Avaliable sections: %s", config.sections())
    return config


def get_repo_list():
    repo_list_response = requests.get(MISTER_DEVEL_REPOS_URL)
    for repo in repo_list_response.json():
        if repo['name'].startswith('Arcade-'):
            yield repo


def get_definitions_from_github():
    global DEFINITIONS
    definitions = configparser.ConfigParser()
    for repo in get_repo_list():
        logging.info("Processing %s", repo['name'])
        rom_info = requests.get('{}/raw/master/releases/build_rom.ini'.format(repo['html_url']))
        if rom_info.status_code != requests.codes.ok:
            logging.warning("Repo %s is missing rom info, skipping", repo['name'])
            continue
        section, options = parser_rom_ini(rom_info.text, repo['html_url'])
        definitions[section] = options
    with open(DEFAULT_CONFIG, 'w') as fp:
        definitions.write(fp)
    DEFINITIONS = definitions


def parser_rom_ini(text, html_url=None):
    zip_filename = None
    options = {}
    for line in text.split('\n'):
        if line.strip():
            key, val = line.split('=')
            if key.strip() == "zip":
                zip_filename = val.strip()
            elif key.strip() == "ifiles":
                if html_url is None:
                    files = [f for f in shlex.split(val.strip('()'))]
                else:
                    files = ['{}/raw/master/releases/foo/{}'.format(html_url, f) if f.startswith("../") else f for f in shlex.split(val.strip('()'))]
                options['ifiles'] = " ".join(files)
            else:
                options[key.strip()] = val.strip()
    if html_url is not None:
        options['html_url'] = html_url
    return zip_filename, options

def mame_to_mister(rom_zip, output_rom=None, rom_setting=None):
    global DEFINITIONS

    if rom_setting is None:
        try:
            rom_setting = DEFINITIONS[os.path.basename(rom_zip)]
        except KeyError:
            return "Error", "ROM Definition not found"

    if output_rom is None:
        output_rom = rom_setting['ofile']

    with zipfile.ZipFile(rom_zip) as zip_fp:
        logging.debug("Opening Zip Archive: %s", rom_zip)
        with open(output_rom, 'w+b') as rom_fp:
            md5_sum = hashlib.new('md5')
            logging.debug("Writing output rom: %s", os.path.basename(output_rom))
            for ifile in shlex.split(rom_setting['ifiles']):
                if ifile.startswith(('https://', 'http://')):
                    resp = requests.get(ifile)
                    if not resp.ok:
                        logging.error("Failed to download '%s'", ifile)
                        logging.info("Removing failed rom '%s'",rom_fp.name)
                        os.unlink(rom_fp.name)
                        return "Error", f"Failed to download '{ifile}'"
                    logging.debug("Added '%s' to '%s'", ifile, rom_fp.name)
                    md5_sum.update(resp.content)
                    rom_fp.write(resp.content)
                else:
                    try:
                        with zip_fp.open(ifile) as ifile_fp:
                            chip_content = ifile_fp.read()
                            md5_sum.update(chip_content)
                            logging.debug("Added '%s' to '%s'", ifile, rom_fp.name)
                            rom_fp.write(chip_content)
                    except KeyError as err:
                        logging.error("Missing '%s' in '%s'",
                                      ifile, rom_zip)
                        logging.info("Removing failed rom '%s'",rom_fp.name)
                        os.unlink(rom_fp.name)
                        return "Error", f"Missing '{ifile}' in '{rom_zip}'"
            else:
                if 'ofileMd5sumValid' in rom_setting:
                    if md5_sum.hexdigest() != rom_setting['ofileMd5sumValid']:
                        logging.error("MD5 missmatch for '%s'", os.path.basename(output_rom))
                        return ("Warning", f"MD5 missmatch for '{os.path.basename(output_rom)}'. "
                                            "The ROM may still work but was not tested.")
                    else:
                        logging.info("MD5 verified for '%s'", rom_fp.name)
                        return "Success", f"'{os.path.basename(output_rom)}' created successfully"

class RefreshDefinitionsDialog:
    def __init__(self, master=None, set_count_callback=None):
        self.master = master
        if set_count_callback is None:
            self.set_count = lambda x: None
        else:
            self.set_count = set_count_callback
        self.cancelled = False
        self.thread = None

    def __call__(self):
        if self.thread is not None and self.thread.is_alive():
            return 

        def thread_fn():
            self.do_work()
        self.thread = Thread(target=thread_fn)
        self.cancelled = False
        self.window = tk.Toplevel(self.master)
        self.window.title("Refreshing Definitions")
        self.window.geometry('300x100')
        self.window.resizable(False,False)
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)
        self.window.grab_set()

        self.label = tk.Label(self.window, text="Retriving list of repos from GitHub")
        self.label.pack()
        self.progress = ttk.Progressbar(self.window, mode="indeterminate")
        self.progress.start()
        self.progress.pack(fill=tk.X, padx=5, pady=5)
        cancel = ttk.Button(self.window, text="Cancel", command=self.stop)
        cancel.pack()
        self.thread.start()
    
    def stop(self):
        self.cancelled = True
        logging.info("Thread stop requested")

    def do_work(self):
        global DEFINITIONS
        definitions = configparser.ConfigParser()
        repos = list(get_repo_list())
        self.progress.stop()
        self.progress['mode'] = 'determinate'
        self.progress['value'] = 0
        self.progress['maximum'] = len(repos)+1
        for repo in repos:
            self.progress.step()
            if self.cancelled:
                logging.info("Definition refresh cancelled")
                self.window.destroy()
                return
            self.label['text'] = f"Adding: {repo['name']}"
            logging.info("Processing %s", repo['name'])
            rom_info = requests.get('{}/raw/master/releases/build_rom.ini'.format(repo['html_url']))
            if rom_info.status_code != requests.codes.ok:
                logging.warning("Repo %s is missing rom info, skipping", repo['name'])
                continue
            section, options = parser_rom_ini(rom_info.text, repo['html_url'])
            definitions[section] = options
        with open(DEFAULT_CONFIG, 'w') as fp:
            definitions.write(fp)
        DEFINITIONS = definitions
        self.window.destroy()
        self.set_count(len(DEFINITIONS)-1)

class DefinitionList(tk.Frame):
    def __init__(self, master=None):
        global DEFINITIONS

        super().__init__(master)
        self.master = master
        list_frame = tk.Frame(self)
        self.scrollbar = ttk.Scrollbar(list_frame)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree = ttk.Treeview(list_frame,
                                 columns=('core', 'filename'),
                                 show='headings',
                                 selectmode='browse')
        self.tree.heading('core', text="Core")
        self.tree.heading('filename', text="Default Zip Filename")
        self.tree.pack(fill=tk.X)

        self.tree.config(yscrollcommand=self.scrollbar.set)
        self.scrollbar.config(command=self.tree.yview)

        list_frame.pack()
        #  Definition frame
        def_frame = tk.Frame(self)

        self.rom_label = ttk.Label(def_frame, text="Reading ROM Defintions")
        def set_rom_count(count):
            self.rom_label['text'] = f"ROM Defintions found: {count}"
            self.refresh()
        set_rom_count(len(DEFINITIONS)-1)
        self.rom_label.pack(side=tk.LEFT)

        refresh_dialog = RefreshDefinitionsDialog(master, set_rom_count)
        self.ref_btn = ttk.Button(def_frame, text="Refresh Definitions", command=refresh_dialog)
        self.ref_btn.pack(side=tk.LEFT)

        def_frame.pack(side=tk.BOTTOM)

    def refresh(self):
        global DEFINITIONS
        self.empty()
        for sec in DEFINITIONS.sections():
            repo_name = os.path.basename(DEFINITIONS[sec]['html_url'])
            match = re.match(r'Arcade-(.*)_MiSTer', repo_name)
            self.tree.insert("", tk.END, text=sec, values=(match.group(1), sec,))

    def empty(self):
        self.tree.delete(*self.tree.get_children())

    def selected_item(self):
        curr_item = self.tree.focus()
        if curr_item:
            return self.tree.item(curr_item)['text']
        else:
            return None

class MisterRomBuilder(tk.Frame):
    def __init__(self, master=None):
        global DEFINITIONS
        super().__init__(master)
        self.master = master
        self.master.title("MiSTer ROM Builder")
        self.master.geometry('400x300')
        self.master.resizable(False,False)

        self.def_list = DefinitionList(self.master)
        self.def_list.pack(fill=tk.BOTH)

        sep = ttk.Separator(orient='horizontal')
        sep.pack(side=tk.TOP, fill=tk.X, pady=5)

        self.rom_btn = ttk.Button(self, text="Select ROM to convert", command=self.build_rom)
        self.rom_btn.pack(side=tk.BOTTOM)

        self.pack()

    def build_rom(self):
        global DEFINITIONS
        rom_requested = self.def_list.selected_item()
        rom_zip = filedialog.askopenfilename(
                defaultextension=".zip",
                filetypes=(
                    ("MAME Zip ROM", ".zip"),
                    ("All Files", ".*"),
                    ),
                title="Choose MAME ROM file") 
        if rom_zip == ():  # If dialog wasn't cancelled
            return

        if rom_requested is None:
            rom_requested = os.path.basename(rom_zip)

        rom_setting = DEFINITIONS[rom_requested]
        output_rom = filedialog.asksaveasfilename(
                defaultextension=".rom",
                filetypes=(
                    ("MiSTer ROM", ".rom"),
                    ("All Files", ".*"),
                    ),
                initialfile=rom_setting['ofile'],
                title="Choose output ROM file") 
        if output_rom == ():  # If dialog wasn't cancelled
            return

        level, message = mame_to_mister(rom_zip, output_rom, rom_setting)
        if level == "Error":
            messagebox.showerror("Error", message)
        elif level == "Warning":
            messagebox.showwarning("Warning", message)
        else:
            messagebox.showinfo("Success", message)


def main_gui():
    root = tk.Tk()
    app = MisterRomBuilder(master=root)
    app.mainloop()


def main_cli():
    if sys.argv[1] == '--update-definitions':
        get_definitions_from_github()
    else:
        for rom in sys.argv[1:]:
            level, message = mame_to_mister(rom)
            logging.info("%s -- %s", level, message)

def main():
    global DEFINITIONS
    logging.basicConfig(level=logging.INFO)
    DEFINITIONS = get_definitions_from_file()
    print(sys.argv)
    if len(sys.argv) == 1:
        main_gui()
    else:
        main_cli()

if __name__ == '__main__':
    main()
