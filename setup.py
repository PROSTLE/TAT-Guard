"""TAT Guard package configuration."""
from setuptools import setup, find_packages

setup(
    name="tat-guard",
    version="0.1.0",
    description="UPI TAT reconciliation and penalty tracking on Exasol",
    author="Harshit Aryan",
    author_email="harshitaryan21@gmail.com",
    url="https://github.com/PROSTLE/TAT-Guard",
    packages=find_packages(exclude=["tests", "tests.*"]),
    python_requires=">=3.10",
    # Lower bounds = versions verified in requirements.txt.
    install_requires=[
        "pyexasol>=2.4.1",
        "PyYAML>=6.0.3",
        "numpy>=2.5.3",
        "pyarrow>=25.0.1",
        "pandas>=3.0.6",
        "mcp>=2.3.0",
    ],
    extras_require={
        "agent": ["google-genai>=2.32"],
        "dev": ["pytest>=8.0"],
    },
    entry_points={
        "console_scripts": [
            "tatguard-ui=ui.server:main",
            "tatguard-generate=generator.generate:main",
            "tatguard-recon=recon.pipeline:main",
        ],
    },
)
