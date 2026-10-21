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
    install_requires=[
        "pyexasol>=0.26",
        "PyYAML>=6.0",
        "python-dotenv>=1.0",
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
