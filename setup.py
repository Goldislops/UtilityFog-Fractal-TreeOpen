#!/usr/bin/env python3
"""
Setup script for UtilityFog-Fractal-TreeOpen
"""

from setuptools import setup, find_packages
import os

# Read version from visualization/__init__.py
version = "0.1.0-rc1"

# Read README
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="utilityfog-fractal-treeopen",
    version=version,
    author="UtilityFog-Fractal-TreeOpen Project",
    author_email="contact@utilityfog.org",
    description="Advanced utility fog simulation with fractal tree structures and comprehensive observability",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Scientific/Engineering :: Visualization",
        "Topic :: System :: Monitoring",
    ],
    python_requires=">=3.8",
    install_requires=[
        "fastapi>=0.68.0",
        "uvicorn>=0.15.0",
        "websockets>=10.0",
        "pydantic>=1.8.0",
        "numpy>=1.21.0",
        "matplotlib>=3.4.0",
        "asyncio-mqtt>=0.11.0",
    ],
    extras_require={
        "dev": [
            "pytest>=6.0",
            "pytest-asyncio>=0.15.0",
            "pytest-cov>=2.12.0",
            "black>=21.0.0",
            "ruff>=0.0.200",
            "mypy>=0.910",
        ],
        "telemetry": [
            "prometheus-client>=0.11.0",
        ],
        "visualization": [
            "rich>=10.0.0",
            "textual>=0.1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "utilityfog-sim=UtilityFog_Agent_Package.agent.main_simulation:main",
            "utilityfog-viz=utilityfog_frontend.cli_viz:main",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["*.json", "*.yaml", "*.yml", "*.md", "*.txt"],
    },
)
