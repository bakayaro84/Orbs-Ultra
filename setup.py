#!/usr/bin/env python3
"""
Setup script pour créer un package distributable d'Orbs.py
Package ultra-optimisé pour calculs orbitaux industriels
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="orbs-ultra",
    version="2.1.0",  # Version mise à jour avec nouvelles fonctionnalités
    author="Orbs Development Team",
    author_email="dev@orbs-system.com",
    description="Système de calculs orbitaux ultra-optimisé avec cache distribué et vectorisation NumPy",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/your-org/orbs-ultra",
    packages=find_packages(),
    py_modules=["Orbs", "verify_test"],  # Modules explicites
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Science/Research",
        "Intended Audience :: Developers",
        "Topic :: Scientific/Engineering :: Astronomy",
        "Topic :: Scientific/Engineering :: Physics",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=[
        "numpy>=1.20.0",  # Pour la vectorisation matricielle
        "matplotlib>=3.3.0",  # Pour les visualisations et animations
    ],
    extras_require={
        "dev": [
            "pytest>=6.0",
            "pytest-cov>=2.0",
            "black>=21.0",
            "flake8>=3.8",
        ],
        "performance": [
            "numba>=0.50.0",  # Pour optimisation JIT optionnelle
            "scipy>=1.6.0",   # Pour calculs scientifiques avancés
        ],
        "full": [
            "pytest>=6.0",
            "pytest-cov>=2.0",
            "numba>=0.50.0",
            "scipy>=1.6.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "orbs-benchmark=Orbs:main_benchmark",
            "orbs-verify=verify_test:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
