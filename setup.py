#!/usr/bin/env python3
"""
Setup script for WCM (Wayfire Config Manager) Python edition.

Install:
    pip install .

Or run directly:
    python wcm.py
"""

from setuptools import setup

setup(
    name='wcm',
    version='0.1.0',
    description='Wayfire Config Manager — Python/PyQt5 Edition',
    author='Wayfire Contributors',
    license='MIT',
    py_modules=['wcm', 'config_backend', 'metadata'],
    install_requires=[
        'PyQt5',
        'lxml',
    ],
    entry_points={
        'gui_scripts': [
            'wcm = wcm:main',
        ],
    },
    python_requires='>=3.8',
)
