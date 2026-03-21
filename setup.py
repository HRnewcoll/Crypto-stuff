from setuptools import setup, find_packages

setup(
    name="crypto-toolkit",
    version="0.1.0",
    description="Comprehensive multi-chain crypto toolkit: wallets, bots, SaaS, AI agents and more",
    author="HRnewcoll",
    packages=find_packages(exclude=["tests*"]),
    python_requires=">=3.10",
    install_requires=[
        line.strip()
        for line in open("requirements.txt")
        if line.strip() and not line.startswith("#")
    ],
    entry_points={
        "console_scripts": [
            "crypto-toolkit=crypto_toolkit.cli:cli",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS-Independent",
    ],
)
