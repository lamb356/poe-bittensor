from setuptools import setup, find_packages

setup(
    name="poe-subnet",
    version="0.1.0",
    description="Proof of Evaluation Bittensor Subnet",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "bittensor>=7.0.0",
        "numpy>=1.24.0",
    ],
)
