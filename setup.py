"""
Setup script for Azure VM Rightsizer CLI.
"""
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="azure-vm-rightsizer",
    version="1.0.0",
    author="FinOps Team",
    author_email="finops@example.com",
    description="AI-powered Azure VM rightsizing and cost optimization CLI",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/your-org/azure-vm-rightsizer",
    packages=find_packages(),
    py_modules=["main", "config", "azure_client", "ai_analyzer", "analysis_engine"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Systems Administration",
        "Topic :: Utilities",
    ],
    python_requires=">=3.9",
    install_requires=[
        "typer[all]>=0.9.0",
        "rich>=13.7.0",
        "azure-identity>=1.15.0",
        "azure-mgmt-compute>=30.0.0",
        "azure-mgmt-advisor>=9.0.0",
        "azure-mgmt-monitor>=6.0.0",
        "azure-mgmt-resource>=23.0.0",
        "azure-mgmt-costmanagement>=4.0.0",
        "httpx>=0.26.0",
        "pandas>=2.1.0",
        "python-dotenv>=1.0.0",
        "pydantic>=2.5.0",
        "pydantic-settings>=2.1.0",
    ],
    extras_require={
        "ai": ["anthropic>=0.18.0"],
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "ruff>=0.1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "vm-rightsizer=main:main",
        ],
    },
    keywords=[
        "azure",
        "vm",
        "rightsizing",
        "cost-optimization",
        "finops",
        "cloud",
        "cli",
    ],
)
