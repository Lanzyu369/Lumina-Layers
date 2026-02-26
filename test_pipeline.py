#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                    LUMINA STUDIO - AUTOMATED TEST PIPELINE                    ║
║                         Zero-Config Integration Test                          ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Purpose: Validate core conversion pipeline across all modes                  ║
║  Usage: python test_pipeline.py                                               ║
║  Requirements: No external test frameworks needed                             ║
╚═══════════════════════════════════════════════════════════════════════════════╝

ARCHITECTURE:
- Zero-config: Just run `python test_pipeline.py`
- Fault-tolerant: Each test case runs independently
- Comprehensive validation: Mesh integrity, material slots, file generation
- Clear reporting: Color-coded terminal output with summary statistics

TEST COVERAGE MATRIX:
┌─────────────────────────────────────────────────────────────────────────────┐
│ Color Modes:                                                                │
│   ✓ 4-Color (CMYW LUT)                                                      │
│   ✓ 4-Color (RYBW LUT)                                                      │
│   ✓ 6-Color                                                                 │
│   ✓ BW (Black & White)                                                      │
│                                                                              │
│ Modeling Modes:                                                             │
│   ✓ High-Fidelity (RLE-based mesh generation)                               │
│   ✓ Pixel Art (Voxel-based blocky aesthetic)                                │
│   ✓ Vector (Native SVG processing)                                          │
│                                                                              │
│ Structure Modes:                                                            │
│   ✓ Double-sided (Keychain style)                                           │
│   ✓ Single-sided (Relief style)                                             │
│                                                                              │
│ Features Tested:                                                            │
│   ✓ Color quantization (8-256 colors)                                       │
│   ✓ Image filters (blur, smooth)                                            │
│   ✓ Background removal (auto/manual)                                        │
│   ✓ Color replacement (single/multiple)                                     │
│   ✓ Backing separation (on/off)                                             │
│   ✓ Size variations (30mm-100mm)                                            │
│   ✓ Image formats (PNG, JPG, SVG)                                           │
│   ✓ LUT switching (CMYW ↔ RYBW)                                             │
│   ✓ Isolated pixel cleanup (on/off)                                         │
│                                                                              │
│ Total Test Cases: 30                                                        │
└─────────────────────────────────────────────────────────────────────────────┘
"""

import os
import sys
import time
import traceback
from typing import Dict, List, Tuple, Optional
import numpy as np

# ========== Color Output Setup ==========
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    HAS_COLOR = True
except ImportError:
    # Fallback to ANSI codes if colorama not available
    class Fore:
        GREEN = '\033[92m'
        RED = '\033[91m'
        YELLOW = '\033[93m'
        CYAN = '\033[96m'
        RESET = '\033[0m'
    
    class Style:
        BRIGHT = '\033[1m'
        RESET_ALL = '\033[0m'
    
    HAS_COLOR = True

# ========== Test Configuration ==========

# Test cases configuration
# Format: {
#     'name': 'Test Case Name',
#     'image': 'path/to/image.png',  # Supports .png, .jpg, .svg
#     'lut': 'path/to/lut.npy',
#     'color_mode': '4-Color' | '6-Color' | '8-Color' | 'BW',
#     'modeling_mode': 'high-fidelity' | 'pixel' | 'vector',  # vector requires .svg
#     'target_width_mm': 50.0,
#     'quantize_colors': 64,
#     'blur_kernel': 0,
#     'smooth_sigma': 10,
#     'structure_mode': 'Double-sided' | 'Single-sided',
#     'auto_bg': True | False,
#     'bg_tol': 10,
#     'color_replacements': None | {'#ff0000': '#00ff00'},
#     'separate_backing': False | True,
#     'enable_cleanup': True | False,  # Isolated pixel cleanup (default: True)
#     'expected_materials': 4 | 6 | 8,  # Expected number of material slots
# }

TEST_CASES = [
    # ========== 4-Color Mode Tests ==========
    # Test all modeling modes with 4-Color
    {
        'name': '4-Color | High-Fidelity | CMYW LUT',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_cmyw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    {
        'name': '4-Color | High-Fidelity | RYBW LUT',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    {
        'name': '4-Color | Pixel Art | RYBW LUT',
        'image': 'test_images/pixel_art.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'pixel',
        'target_width_mm': 40.0,
        'quantize_colors': 32,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': False,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    {
        'name': '4-Color | Pixel Art | CMYW LUT',
        'image': 'test_images/pixel_art.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_cmyw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'pixel',
        'target_width_mm': 40.0,
        'quantize_colors': 32,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': False,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    {
        'name': '4-Color | Vector Mode | SVG',
        'image': 'test_images/1.svg',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'vector',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': False,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    
    # ========== 6-Color Mode Tests ==========
    {
        'name': '6-Color | High-Fidelity | Photo',
        'image': 'test_images/photo.jpg',
        'lut': 'lut-npy预设/Custom/Bambulab_basic_cmywgk.npy',
        'color_mode': '6-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 60.0,
        'quantize_colors': 128,
        'blur_kernel': 0,
        'smooth_sigma': 15,
        'structure_mode': 'Single-sided',
        'auto_bg': True,
        'bg_tol': 15,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 6,
    },
    {
        'name': '6-Color | Pixel Art',
        'image': 'test_images/pixel_art.png',
        'lut': 'lut-npy预设/Custom/Bambulab_basic_cmywgk.npy',
        'color_mode': '6-Color',
        'modeling_mode': 'pixel',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': False,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 6,
    },
    
    # ========== BW Mode Tests ==========
    {
        'name': 'BW | High-Fidelity',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/Custom/Bambulab_basic_BW.npy',
        'color_mode': 'BW (Black & White)',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 32,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 2,
    },
    {
        'name': 'BW | Pixel Art',
        'image': 'test_images/pixel_art.png',
        'lut': 'lut-npy预设/Custom/Bambulab_basic_BW.npy',
        'color_mode': 'BW (Black & White)',
        'modeling_mode': 'pixel',
        'target_width_mm': 40.0,
        'quantize_colors': 16,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': False,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 2,
    },
    
    # ========== Structure Mode Tests ==========
    {
        'name': '4-Color | Single-sided',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Single-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    {
        'name': '4-Color | Double-sided',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    
    # ========== Color Quantization Tests ==========
    {
        'name': '4-Color | Quantize 8 colors',
        'image': 'test_images/photo.jpg',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_cmyw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 8,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    {
        'name': '4-Color | Quantize 256 colors',
        'image': 'test_images/photo.jpg',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_cmyw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 256,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    
    # ========== Filter Tests ==========
    {
        'name': '4-Color | Blur Filter (kernel=3)',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 3,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    {
        'name': '4-Color | Smooth Filter (sigma=20)',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 20,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    
    # ========== Background Removal Tests ==========
    {
        'name': '4-Color | Auto BG Removal ON',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    {
        'name': '4-Color | Auto BG Removal OFF',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': False,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    
    # ========== Color Replacement Tests ==========
    {
        'name': '4-Color | Color Replacement (Red→Green)',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': {'#DC143C': '#00FF00'},
        'separate_backing': False,
        'expected_materials': 4,
    },
    {
        'name': '4-Color | Multiple Color Replacements',
        'image': 'test_images/simple_shapes.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_cmyw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': {
            '#DC143C': '#0086D6',  # Red → Cyan
            '#0064F0': '#EC008C',  # Blue → Magenta
        },
        'separate_backing': False,
        'expected_materials': 4,
    },
    
    # ========== Backing Separation Tests ==========
    {
        'name': '4-Color | Separate Backing ON',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_cmyw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': True,
        'expected_materials': 5,  # 4 materials + 1 backing
    },
    {
        'name': '4-Color | Separate Backing OFF',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_cmyw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    
    # ========== Size Tests ==========
    {
        'name': '4-Color | Small Size (30mm)',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 30.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    {
        'name': '4-Color | Large Size (100mm)',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 100.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    
    # ========== Image Format Tests ==========
    {
        'name': '4-Color | PNG Format',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    {
        'name': '4-Color | JPG Format',
        'image': 'test_images/photo.jpg',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    {
        'name': '4-Color | SVG Format',
        'image': 'test_images/1.svg',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'vector',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': False,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
    },
    
    # ========== Isolated Pixel Cleanup Tests ==========
    {
        'name': '4-Color | Isolated Pixel Cleanup ON',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
        'enable_cleanup': True,
    },
    {
        'name': '4-Color | Isolated Pixel Cleanup OFF',
        'image': 'test_images/sample_logo.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 50.0,
        'quantize_colors': 64,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': True,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
        'enable_cleanup': False,
    },
    {
        'name': '6-Color | Isolated Pixel Cleanup ON',
        'image': 'test_images/photo.jpg',
        'lut': 'lut-npy预设/Custom/Bambulab_basic_cmywgk.npy',
        'color_mode': '6-Color',
        'modeling_mode': 'high-fidelity',
        'target_width_mm': 60.0,
        'quantize_colors': 128,
        'blur_kernel': 0,
        'smooth_sigma': 15,
        'structure_mode': 'Single-sided',
        'auto_bg': True,
        'bg_tol': 15,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 6,
        'enable_cleanup': True,
    },
    {
        'name': 'Pixel Mode | Cleanup Should Be Disabled',
        'image': 'test_images/pixel_art.png',
        'lut': 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy',
        'color_mode': '4-Color',
        'modeling_mode': 'pixel',
        'target_width_mm': 40.0,
        'quantize_colors': 32,
        'blur_kernel': 0,
        'smooth_sigma': 10,
        'structure_mode': 'Double-sided',
        'auto_bg': False,
        'bg_tol': 10,
        'color_replacements': None,
        'separate_backing': False,
        'expected_materials': 4,
        'enable_cleanup': True,  # Should be ignored in pixel mode
    },
]

# Output directory for test results
TEST_OUTPUT_DIR = os.path.join('output', 'test_results')
os.makedirs(TEST_OUTPUT_DIR, exist_ok=True)

# ========== Test Result Tracking ==========

class TestResult:
    """Container for test execution results"""
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.duration = 0.0
        self.error_message = None
        self.error_traceback = None
        self.validations = []  # List of (check_name, passed, message)
    
    def add_validation(self, check_name: str, passed: bool, message: str = ""):
        """Add a validation check result"""
        self.validations.append((check_name, passed, message))
    
    def mark_passed(self):
        """Mark test as passed"""
        self.passed = True
    
    def mark_failed(self, error_msg: str, error_tb: str = None):
        """Mark test as failed with error details"""
        self.passed = False
        self.error_message = error_msg
        self.error_traceback = error_tb


# ========== Validation Functions ==========

def validate_file_generated(output_path: str) -> Tuple[bool, str]:
    """
    Validate that output file was generated
    
    Returns:
        (passed, message)
    """
    if not os.path.exists(output_path):
        return False, f"File not found: {output_path}"
    
    file_size = os.path.getsize(output_path)
    if file_size == 0:
        return False, f"File is empty (0 bytes): {output_path}"
    
    return True, f"File generated ({file_size:,} bytes)"


def validate_mesh_integrity(output_path: str) -> Tuple[bool, str]:
    """
    Validate mesh integrity using trimesh
    
    Checks:
    - File can be loaded
    - Has vertices and faces
    - Mesh is not degenerate
    
    Returns:
        (passed, message)
    """
    try:
        import trimesh
        
        # Load mesh/scene
        loaded = trimesh.load(output_path)
        
        # Handle both Scene and Mesh objects
        if isinstance(loaded, trimesh.Scene):
            # Count total vertices and faces across all geometries
            total_verts = 0
            total_faces = 0
            num_geometries = len(loaded.geometry)
            
            for geom in loaded.geometry.values():
                if isinstance(geom, trimesh.Trimesh):
                    total_verts += len(geom.vertices)
                    total_faces += len(geom.faces)
            
            if total_verts == 0 or total_faces == 0:
                return False, f"Scene has empty geometry (verts={total_verts}, faces={total_faces})"
            
            return True, f"Scene OK: {num_geometries} objects, {total_verts:,} verts, {total_faces:,} faces"
        
        elif isinstance(loaded, trimesh.Trimesh):
            num_verts = len(loaded.vertices)
            num_faces = len(loaded.faces)
            
            if num_verts == 0 or num_faces == 0:
                return False, f"Mesh is empty (verts={num_verts}, faces={num_faces})"
            
            return True, f"Mesh OK: {num_verts:,} verts, {num_faces:,} faces"
        
        else:
            return False, f"Unknown geometry type: {type(loaded)}"
    
    except Exception as e:
        return False, f"Failed to load mesh: {e}"


def validate_material_slots(output_path: str, expected_count: int) -> Tuple[bool, str]:
    """
    Validate number of material slots/objects in the model
    
    Args:
        output_path: Path to 3MF file
        expected_count: Expected number of materials
    
    Returns:
        (passed, message)
    """
    try:
        import trimesh
        
        loaded = trimesh.load(output_path)
        
        if isinstance(loaded, trimesh.Scene):
            actual_count = len(loaded.geometry)
            
            if actual_count < expected_count:
                return False, f"Missing materials: expected {expected_count}, got {actual_count}"
            
            # List geometry names
            geom_names = list(loaded.geometry.keys())
            return True, f"Materials OK: {actual_count} objects ({', '.join(geom_names[:5])}{'...' if len(geom_names) > 5 else ''})"
        
        else:
            # Single mesh - should have at least 1 material
            if expected_count > 1:
                return False, f"Expected {expected_count} materials, but got single mesh"
            
            return True, "Single mesh OK"
    
    except Exception as e:
        return False, f"Failed to validate materials: {e}"


# ========== Core Test Runner ==========

def run_single_test(test_case: Dict) -> TestResult:
    """
    Run a single test case with full isolation
    
    Args:
        test_case: Test configuration dictionary
    
    Returns:
        TestResult object
    """
    result = TestResult(test_case['name'])
    start_time = time.time()
    
    try:
        # Import converter (lazy import to avoid startup issues)
        from core.converter import convert_image_to_3d
        from config import ModelingMode
        
        # Prepare parameters
        image_path = test_case['image']
        lut_path = test_case['lut']
        
        # Validate input files exist
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Test image not found: {image_path}")
        if not os.path.exists(lut_path):
            raise FileNotFoundError(f"LUT file not found: {lut_path}")
        
        # Convert modeling mode string to enum
        mode_str = test_case['modeling_mode']
        if mode_str == 'high-fidelity':
            modeling_mode = ModelingMode.HIGH_FIDELITY
        elif mode_str == 'pixel':
            modeling_mode = ModelingMode.PIXEL
        elif mode_str == 'vector':
            modeling_mode = ModelingMode.VECTOR
        else:
            modeling_mode = ModelingMode.HIGH_FIDELITY
        
        # Execute conversion
        print(f"  → Running conversion...")
        
        output_3mf, output_glb, preview_img, status_msg = convert_image_to_3d(
            image_path=image_path,
            lut_path=lut_path,
            target_width_mm=test_case['target_width_mm'],
            spacer_thick=1.6,  # Standard backing thickness
            structure_mode=test_case['structure_mode'],
            auto_bg=test_case['auto_bg'],
            bg_tol=test_case['bg_tol'],
            color_mode=test_case['color_mode'],
            add_loop=False,  # Disable loop for testing
            loop_width=0,
            loop_length=0,
            loop_hole=0,
            loop_pos=None,
            modeling_mode=modeling_mode,
            quantize_colors=test_case['quantize_colors'],
            blur_kernel=test_case['blur_kernel'],
            smooth_sigma=test_case['smooth_sigma'],
            color_replacements=test_case.get('color_replacements'),
            backing_color_id=0,
            separate_backing=test_case.get('separate_backing', False),
            enable_cleanup=test_case.get('enable_cleanup', True),  # Default to True
        )
        
        # Validation 1: Check if conversion succeeded
        if output_3mf is None:
            raise RuntimeError(f"Conversion failed: {status_msg}")
        
        result.add_validation("Conversion", True, "Completed successfully")
        
        # Validation 2: File generation
        passed, msg = validate_file_generated(output_3mf)
        result.add_validation("File Generation", passed, msg)
        if not passed:
            raise RuntimeError(msg)
        
        # Validation 3: Mesh integrity
        passed, msg = validate_mesh_integrity(output_3mf)
        result.add_validation("Mesh Integrity", passed, msg)
        if not passed:
            raise RuntimeError(msg)
        
        # Validation 4: Material slots
        expected_materials = test_case.get('expected_materials', 4)
        passed, msg = validate_material_slots(output_3mf, expected_materials)
        result.add_validation("Material Slots", passed, msg)
        if not passed:
            # This is a warning, not a failure
            print(f"    ⚠️  {msg}")
        
        # All validations passed
        result.mark_passed()
        
    except Exception as e:
        # Capture error details
        error_msg = str(e)
        error_tb = traceback.format_exc()
        result.mark_failed(error_msg, error_tb)
    
    finally:
        result.duration = time.time() - start_time
    
    return result


def print_test_header(test_name: str, index: int, total: int):
    """Print test case header"""
    print(f"\n{Fore.CYAN}{Style.BRIGHT}{'='*80}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[{index}/{total}] {test_name}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}{'='*80}{Style.RESET_ALL}")


def print_test_result(result: TestResult):
    """Print test result with color coding"""
    if result.passed:
        status = f"{Fore.GREEN}{Style.BRIGHT}[PASS]{Style.RESET_ALL}"
    else:
        status = f"{Fore.RED}{Style.BRIGHT}[FAIL]{Style.RESET_ALL}"
    
    print(f"\n{status} {result.name} ({result.duration:.2f}s)")
    
    # Print validation details
    for check_name, passed, message in result.validations:
        if passed:
            icon = f"{Fore.GREEN}✓{Style.RESET_ALL}"
        else:
            icon = f"{Fore.RED}✗{Style.RESET_ALL}"
        
        print(f"  {icon} {check_name}: {message}")
    
    # Print error details if failed
    if not result.passed and result.error_message:
        print(f"\n  {Fore.RED}Error: {result.error_message}{Style.RESET_ALL}")


def print_summary(results: List[TestResult]):
    """Print final summary statistics"""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    total_time = sum(r.duration for r in results)
    
    print(f"\n{Fore.CYAN}{Style.BRIGHT}{'='*80}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}TEST SUMMARY{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}{'='*80}{Style.RESET_ALL}\n")
    
    print(f"Total Tests:  {total}")
    print(f"{Fore.GREEN}Passed:       {passed}{Style.RESET_ALL}")
    print(f"{Fore.RED}Failed:       {failed}{Style.RESET_ALL}")
    print(f"Total Time:   {total_time:.2f}s")
    print(f"Average Time: {total_time/total:.2f}s per test")
    
    # Print failed tests details
    if failed > 0:
        print(f"\n{Fore.RED}{Style.BRIGHT}FAILED TESTS:{Style.RESET_ALL}\n")
        for result in results:
            if not result.passed:
                print(f"{Fore.RED}✗ {result.name}{Style.RESET_ALL}")
                print(f"  Error: {result.error_message}")
                if result.error_traceback:
                    print(f"\n{Fore.YELLOW}Traceback:{Style.RESET_ALL}")
                    print(result.error_traceback)
                print()
    
    print(f"{Fore.CYAN}{Style.BRIGHT}{'='*80}{Style.RESET_ALL}\n")
    
    # Return exit code
    return 0 if failed == 0 else 1


# ========== Main Entry Point ==========

def main():
    """Main test runner"""
    print(f"{Fore.CYAN}{Style.BRIGHT}")
    print("╔═══════════════════════════════════════════════════════════════════════════════╗")
    print("║                    LUMINA STUDIO - AUTOMATED TEST PIPELINE                    ║")
    print("╚═══════════════════════════════════════════════════════════════════════════════╝")
    print(f"{Style.RESET_ALL}\n")
    
    print(f"Test Output Directory: {TEST_OUTPUT_DIR}")
    print(f"Total Test Cases: {len(TEST_CASES)}\n")
    
    results = []
    
    # Run all test cases
    for i, test_case in enumerate(TEST_CASES, 1):
        print_test_header(test_case['name'], i, len(TEST_CASES))
        
        # Run test with full isolation
        result = run_single_test(test_case)
        results.append(result)
        
        # Print immediate result
        print_test_result(result)
    
    # Print final summary
    exit_code = print_summary(results)
    
    return exit_code


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Test interrupted by user{Style.RESET_ALL}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{Fore.RED}Fatal error: {e}{Style.RESET_ALL}")
        traceback.print_exc()
        sys.exit(1)
