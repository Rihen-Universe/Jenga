#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
from setuptools import setup, find_packages


def get_version():
    """Récupère la version depuis Jenga/__init__.py"""
    init_path = os.path.join(os.path.dirname(__file__), 'Jenga', '__init__.py')
    with open(init_path, 'r', encoding='utf-8') as f:
        content = f.read()
        match = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", content, re.MULTILINE)
        if match:
            return match.group(1)
    return '2.0.1'  # fallback


def get_long_description():
    """Lit le README.md racine pour la description longue"""
    readme_path = os.path.join(os.path.dirname(__file__), 'README.md')
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            return f.read()
    return "Jenga – Cross‑platform build system"


setup(
    name='jenga',
    version=get_version(),
    description='Cross‑platform build system for native applications',
    long_description=get_long_description(),
    long_description_content_type='text/markdown',
    author='Jenga Team (Rihen)',
    author_email='rihen.universe@gmail.com',
    url='https://rihen',
    project_urls={
        'Documentation': 'https://rihen/docs',
        'Source': 'https://github.com/Rihen-Universe/Jenga',
        'Tracker': 'https://github.com/Rihen-Universe/Jenga/issues',
    },
    license='Proprietary',  # À ajuster selon votre licence
    packages=find_packages(exclude=['tests', 'tests.*', 'examples', 'examples.*']),
    include_package_data=True,
    package_data={
        'Jenga': [
            'Unitest/src/Unitest/*.h',
            'Unitest/src/Unitest/*.cpp',
            'Unitest/Entry/*.cpp',
            'Exemples/**/*.h',
            'Exemples/**/*.cpp',
            'py.typed',
        ],
    },
    python_requires='>=3.8',
    install_requires=[
        'watchdog>=2.1.0',
        'requests>=2.28.0',
    ],
    extras_require={
        'watch': ['watchdog>=2.1.0'],
        'docs': ['markdown>=3.4.0', 'pygments>=2.12.0'],
        'all': ['watchdog>=2.1.0', 'markdown>=3.4.0', 'pygments>=2.12.0'],
    },
    entry_points={
        'console_scripts': [
            'jenga = Jenga.Jenga:main',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: Other/Proprietary License',  # À adapter
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: Software Development :: Build Tools',
    ],
    zip_safe=False,
)
