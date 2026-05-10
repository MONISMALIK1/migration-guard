from setuptools import setup, find_packages

setup(
    name="migration-guard",
    version="0.1.0",
    description="Catch dangerous database migrations before they reach production.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Monis Malik",
    url="https://github.com/MONISMALIK1/migration-guard",
    packages=find_packages(exclude=["tests*"]),
    python_requires=">=3.10",
    install_requires=["click>=8.0"],
    extras_require={
        "yaml": ["pyyaml>=6.0"],
        "all":  ["pyyaml>=6.0"],
    },
    entry_points={
        "console_scripts": [
            "migration-guard=migration_guard.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Database",
        "Topic :: Software Development :: Quality Assurance",
        "Topic :: Software Development :: Testing",
    ],
    keywords="database migration safety sql alembic django postgresql devops ci",
)
