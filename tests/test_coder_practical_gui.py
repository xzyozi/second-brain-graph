"""Practical GUI Coder Test Suite for Aider & Ollama Coder Models.

Tests practical, enterprise-grade GUI implementation capabilities with AST validation & isolated git environments:
1. Form Validation & Error Dialog Handling + Async Threading + Progress Bar
2. GUI Data Visualization & Matplotlib/Canvas Component Integration
3. GUI Config Persistence, Binding & File Exception Dialog Handling
"""

import ast
import py_compile
import subprocess
import pytest
from pathlib import Path

# --- Production Scenario 1: Async Order Processing App ---
INITIAL_ORDER_APP_CODE = """import tkinter as tk
from tkinter import ttk, messagebox
import json
import os

class OrderProcessingApp(tk.Tk):
    \"\"\"Production Order Processing GUI Application.\"\"\"
    
    def __init__(self, config_path: str = "config.json"):
        super().__init__()
        self.title("Enterprise Order Management System")
        self.geometry("600x400")
        self.config_path = config_path
        self.orders = []
        
        self._create_widgets()
        
    def _create_widgets(self):
        ttk.Label(self, text="Order ID:").pack(pady=5)
        self.order_id_entry = ttk.Entry(self)
        self.order_id_entry.pack(pady=5)
        
        ttk.Label(self, text="Amount ($):").pack(pady=5)
        self.amount_entry = ttk.Entry(self)
        self.amount_entry.pack(pady=5)
        
        self.submit_btn = ttk.Button(self, text="Process Order", command=self.on_submit)
        self.submit_btn.pack(pady=10)
        
        self.status_label = ttk.Label(self, text="Ready")
        self.status_label.pack(pady=5)

    def on_submit(self):
        order_id = self.order_id_entry.get().strip()
        amount_str = self.amount_entry.get().strip()
        self.status_label.config(text=f"Processed Order {order_id}")
"""

# --- Production Scenario 2: Data Visualization App ---
INITIAL_DASHBOARD_CODE = """import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np

class AnalyticsDashboard(tk.Frame):
    \"\"\"Enterprise Analytics Dashboard Component.\"\"\"
    
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.fig, self.ax = plt.subplots(figsize=(5, 4))
        
        self._setup_ui()
        
    def _setup_ui(self):
        ttk.Label(self, text="Data Analytics Plot").pack(pady=5)
        self.render_btn = ttk.Button(self, text="Generate Plot", command=self.update_plot)
        self.render_btn.pack(pady=5)
        
    def update_plot(self):
        \"\"\"Render sample plot.\"\"\"
        x = np.linspace(0, 10, 100)
        y = np.sin(x)
        self.ax.plot(x, y)
"""

# --- Production Scenario 3: Config Binding & File I/O GUI ---
INITIAL_CONFIG_GUI_CODE = """import tkinter as tk
from tkinter import ttk, messagebox
import json
import os

class SettingsDialog(tk.Toplevel):
    \"\"\"Enterprise Settings Configuration GUI Dialog.\"\"\"
    
    def __init__(self, parent, config_file: str = "settings.json"):
        super().__init__(parent)
        self.title("Application Settings")
        self.config_file = config_file
        
        self.host_entry = ttk.Entry(self)
        self.host_entry.pack(pady=5)
        
        self.port_entry = ttk.Entry(self)
        self.port_entry.pack(pady=5)
        
        self.save_btn = ttk.Button(self, text="Save Settings", command=self.save_config)
        self.save_btn.pack(pady=10)

    def load_config(self):
        pass

    def save_config(self):
        pass
"""


def init_git_repo(repo_dir: Path) -> None:
    """Initialize temporary directory as an isolated git repository for Aider."""
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(repo_dir), check=True, capture_output=True)


def verify_code_syntax_and_get_ast(file_path: Path) -> ast.AST:
    """Verify that generated code is valid Python syntax and return its AST tree."""
    code_text = file_path.read_text(encoding="utf-8")
    tree = ast.parse(code_text, filename=str(file_path))
    py_compile.compile(file_path, doraise=True)
    return tree


def get_ast_identifiers(tree: ast.AST) -> set[str]:
    """Collect all Name and Attribute identifiers from AST nodes."""
    identifiers = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                identifiers.add(alias.name)
                if alias.asname:
                    identifiers.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                identifiers.add(node.module)
            for alias in node.names:
                identifiers.add(alias.name)
    return identifiers


def has_ast_try_statement(tree: ast.AST) -> bool:
    """Check if AST tree contains a try-except block."""
    return any(isinstance(node, ast.Try) for node in ast.walk(tree))


@pytest.mark.integration
def test_coder_practical_gui_async_and_validation(tmp_path):
    """Test 1: Validation, Async Threading, Progress Bar & Error Dialogs."""
    gui_file = tmp_path / "order_app.py"
    gui_file.write_text(INITIAL_ORDER_APP_CODE, encoding="utf-8")
    init_git_repo(tmp_path)
    
    msg_file = tmp_path / "instruction.txt"
    instruction = (
        "Refactor OrderProcessingApp in order_app.py to add production features:\n"
        "1. Input Validation: Validate order_id non-empty and amount positive float. Show messagebox.showerror on invalid.\n"
        "2. Async Threading: Execute order processing in background thread (threading.Thread).\n"
        "3. Progress Bar: Add ttk.Progressbar for progress tracking.\n"
        "4. Error Handling: Catch exceptions during processing and display error dialog."
    )
    msg_file.write_text(instruction, encoding="utf-8")
    
    cmd = [
        "aider", "--model", "ollama/ornith-1.5-9b:latest",
        "--no-auto-commits", "--yes-always", "--no-show-model-warnings",
        "--edit-format", "whole", "--message-file", str(msg_file.resolve()),
        "order_app.py"
    ]
    
    res = subprocess.run(cmd, cwd=str(tmp_path), capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, f"Aider failed: {res.stderr}"
    
    # AST Structural and Syntax Verification
    tree = verify_code_syntax_and_get_ast(gui_file)
    identifiers = get_ast_identifiers(tree)
    
    assert "threading" in identifiers or "Thread" in identifiers, "Missing threading/Thread identifier in AST"
    assert "messagebox" in identifiers or "showerror" in identifiers, "Missing messagebox/showerror in AST"
    assert "Progressbar" in identifiers, "Missing Progressbar identifier in AST"
    assert has_ast_try_statement(tree), "Missing try-except statement in AST"


@pytest.mark.integration
def test_coder_practical_gui_data_visualization(tmp_path):
    """Test 2: Embed Matplotlib FigureCanvasTkAgg and add clear/re-render logic."""
    gui_file = tmp_path / "dashboard.py"
    gui_file.write_text(INITIAL_DASHBOARD_CODE, encoding="utf-8")
    init_git_repo(tmp_path)
    
    msg_file = tmp_path / "instruction.txt"
    instruction = (
        "Refactor AnalyticsDashboard in dashboard.py to:\n"
        "1. Embed FigureCanvasTkAgg into the Frame widget so the plot renders inside Tkinter.\n"
        "2. Clear previous axes (self.ax.clear()) before redrawing new data in update_plot.\n"
        "3. Call canvas.draw() to update the display.\n"
        "4. Add a 'Clear' button that clears the plot and canvas."
    )
    msg_file.write_text(instruction, encoding="utf-8")
    
    cmd = [
        "aider", "--model", "ollama/ornith-1.5-9b:latest",
        "--no-auto-commits", "--yes-always", "--no-show-model-warnings",
        "--edit-format", "whole", "--message-file", str(msg_file.resolve()),
        "dashboard.py"
    ]
    
    res = subprocess.run(cmd, cwd=str(tmp_path), capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, f"Aider failed: {res.stderr}"
    
    # AST Structural and Syntax Verification
    tree = verify_code_syntax_and_get_ast(gui_file)
    identifiers = get_ast_identifiers(tree)
    
    assert "FigureCanvasTkAgg" in identifiers, "Missing FigureCanvasTkAgg identifier in AST"
    assert "clear" in identifiers, "Missing clear method call in AST"
    assert "draw" in identifiers, "Missing draw method call in AST"


@pytest.mark.integration
def test_coder_practical_gui_config_persistence(tmp_path):
    """Test 3: JSON Config Persistence, Binding to Entry fields & Exception Dialogs."""
    gui_file = tmp_path / "settings_gui.py"
    gui_file.write_text(INITIAL_CONFIG_GUI_CODE, encoding="utf-8")
    init_git_repo(tmp_path)
    
    msg_file = tmp_path / "instruction.txt"
    instruction = (
        "Implement load_config and save_config in SettingsDialog in settings_gui.py:\n"
        "1. load_config: Read JSON config_file if exists, insert host/port into Entry widgets. Catch FileNotFoundError or json.JSONDecodeError and show error dialog.\n"
        "2. save_config: Read values from host/port Entry widgets, validate port is integer, write to JSON file. Catch IO/Value errors and show error dialog.\n"
        "3. Automatically call load_config during __init__."
    )
    msg_file.write_text(instruction, encoding="utf-8")
    
    cmd = [
        "aider", "--model", "ollama/ornith-1.5-9b:latest",
        "--no-auto-commits", "--yes-always", "--no-show-model-warnings",
        "--edit-format", "whole", "--message-file", str(msg_file.resolve()),
        "settings_gui.py"
    ]
    
    res = subprocess.run(cmd, cwd=str(tmp_path), capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, f"Aider failed: {res.stderr}"
    
    # AST Structural and Syntax Verification
    tree = verify_code_syntax_and_get_ast(gui_file)
    identifiers = get_ast_identifiers(tree)
    
    assert "dump" in identifiers or "dumps" in identifiers, "Missing json.dump/dumps identifier in AST"
    assert "load" in identifiers or "loads" in identifiers, "Missing json.load/loads identifier in AST"
    assert "messagebox" in identifiers or "showerror" in identifiers, "Missing messagebox/showerror in AST"
    assert has_ast_try_statement(tree), "Missing try-except error handling block in AST"
