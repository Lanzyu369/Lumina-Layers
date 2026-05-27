# Local ColorChecker Core

Source: `E:\Work\PythonProject\ColorChecker\colorchecker`

Upstream commit at copy time: `70c3e59`

This directory contains the local core Python package used by Lumina-Layers.
Do not reintroduce the old standalone web UI, iframe bridge, or proxy routes
here. Integration should go through `core/colorchecker_adapter.py`.
